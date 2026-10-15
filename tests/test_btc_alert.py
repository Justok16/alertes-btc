"""btc_alert.py (bot Bitcoin Fear & Greed) : jusqu'ici aucun test. Calculs purs
+ boucle principale avec sources et Telegram simules (aucun reseau)."""

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).parent.parent))

import btc_alert as ba  # noqa: E402


class TestCalculs(unittest.TestCase):
    def test_classify_seuils(self):
        self.assertEqual(ba.classify(20), "buy")
        self.assertEqual(ba.classify(21), "neutral")
        self.assertEqual(ba.classify(79), "neutral")
        self.assertEqual(ba.classify(80), "sell")
        self.assertIsNone(ba.classify(None))

    def test_rsi(self):
        self.assertIsNone(ba.compute_rsi([1] * 14))
        self.assertEqual(ba.compute_rsi([100 + i for i in range(15)]), 100.0)
        self.assertEqual(ba.compute_rsi([100 - i for i in range(15)]), 0.0)
        closes = [100]
        for d in [2, -1] * 7:
            closes.append(closes[-1] + d)
        self.assertAlmostEqual(ba.compute_rsi(closes), 66.6667, places=3)   # RS = 1 / 0.5

    def test_cloture_hebdo_depuis_journalier(self):
        daily = [[i, float(i)] for i in range(16)]            # 16 jours -> 3 semaines (7, 7, 2)
        self.assertEqual(ba.weekly_closes_from_daily(daily), [6.0, 13.0, 15.0])
        self.assertEqual(ba.weekly_closes_from_daily([]), [])

    def test_message(self):
        msg = ba.build_message("buy", 12, 18.5, None)
        self.assertIn("SIGNAL D'ACHAT", msg)
        self.assertIn("peur extreme", msg)
        self.assertIn("Alternative.me F&G : 12/100", msg)
        self.assertIn("Score maison (ATH + RSI hebdo) : 18.5/100", msg)
        self.assertNotIn("CoinMarketCap", msg)                  # source bonus absente
        self.assertIn("SIGNAL DE VENTE", ba.build_message("sell", 85, 90, 88))


def _reponse(payload):
    r = MagicMock()
    r.json.return_value = payload
    return r


class TestSources(unittest.TestCase):
    def test_alternative_me(self):
        with patch.object(ba, "get_with_retry", return_value=_reponse({"data": [{"value": "15"}]})):
            self.assertEqual(ba.fetch_alternative_fng(MagicMock()), (15, "buy"))
        with patch.object(ba, "get_with_retry", side_effect=RuntimeError("down")):
            self.assertEqual(ba.fetch_alternative_fng(MagicMock()), (None, None))

    def test_coinmarketcap_bonus_non_bloquant(self):
        with patch.object(ba, "get_with_retry", return_value=_reponse({"data": {"value": 85}})):
            self.assertEqual(ba.fetch_cmc_fng(MagicMock()), (85, "sell"))
        with patch.object(ba, "get_with_retry", side_effect=RuntimeError("404")):
            self.assertEqual(ba.fetch_cmc_fng(MagicMock()), (None, None))

    def test_coingecko_score_maison(self):
        # Prix a -40 % de l'ATH (composante ATH = 50) et cours hebdo plats en hausse (RSI 100)
        coin = {"market_data": {"current_price": {"usd": 60.0}, "ath": {"usd": 100.0}}}
        chart = {"prices": [[i, 100.0 + i] for i in range(7 * 16)]}
        with patch.object(ba, "get_with_retry", side_effect=[_reponse(coin), _reponse(chart)]):
            score, zone = ba.fetch_coingecko_signal(MagicMock())
        self.assertEqual((score, zone), (75.0, "neutral"))

    def test_coingecko_historique_trop_court(self):
        coin = {"market_data": {"current_price": {"usd": 60.0}, "ath": {"usd": 100.0}}}
        chart = {"prices": [[i, 100.0] for i in range(20)]}       # < 15 semaines
        with patch.object(ba, "get_with_retry", side_effect=[_reponse(coin), _reponse(chart)]):
            self.assertEqual(ba.fetch_coingecko_signal(MagicMock()), (None, None))


class TestBoucle(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.state_file = Path(self.tmp.name) / "state.json"
        self.send = MagicMock()
        self.sources = {"alt": (50, "neutral"), "cg": (50, "neutral"), "cmc": (50, "neutral")}
        for p in (patch.object(ba, "STATE_FILE", self.state_file),
                  patch.object(ba, "SUPABASE_URL", ""),
                  patch.object(ba, "SUPABASE_SERVICE_ROLE_KEY", ""),
                  patch.object(ba, "send_telegram", self.send),
                  patch.object(ba, "fetch_alternative_fng", lambda s: self.sources["alt"]),
                  patch.object(ba, "fetch_coingecko_signal", lambda s: self.sources["cg"]),
                  patch.object(ba, "fetch_cmc_fng", lambda s: self.sources["cmc"])):
            p.start()
            self.addCleanup(p.stop)

    def etat(self):
        return json.loads(self.state_file.read_text(encoding="utf-8"))

    def messages(self):
        return [c.args[1] for c in self.send.call_args_list]

    def test_deux_sources_sur_trois_declenchent_une_fois(self):
        self.sources.update(alt=(10, "buy"), cg=(15, "buy"))
        ba.main()
        self.assertEqual(len(self.messages()), 1)
        self.assertIn("SIGNAL D'ACHAT", self.messages()[0])
        self.assertEqual(self.etat()["combined_state"], "buy")
        ba.main()                                               # meme zone le lendemain : silence
        self.assertEqual(len(self.messages()), 1)

    def test_une_seule_source_ne_suffit_pas(self):
        self.sources.update(alt=(10, "buy"))
        ba.main()
        self.assertEqual(self.messages(), [])
        self.assertEqual(self.etat()["combined_state"], "neutral")

    def test_retour_en_zone_neutre_puis_vente(self):
        self.sources.update(alt=(10, "buy"), cg=(15, "buy"))
        ba.main()
        self.sources.update(alt=(50, "neutral"), cg=(50, "neutral"))
        ba.main()                                               # neutre : pas de message
        self.sources.update(alt=(90, "sell"), cmc=(85, "sell"))
        ba.main()
        self.assertEqual(len(self.messages()), 2)
        self.assertIn("SIGNAL DE VENTE", self.messages()[1])

    def test_echec_telegram_sauvegarde_quand_meme_l_etat_et_fait_echouer_le_job(self):
        self.sources.update(alt=(10, "buy"), cg=(15, "buy"))
        self.send.side_effect = RuntimeError("telegram down")
        with self.assertRaises(SystemExit) as ctx:
            ba.main()
        self.assertEqual(ctx.exception.code, 1)
        self.assertEqual(self.etat()["combined_state"], "buy")  # pas de renvoi en boucle le lendemain

    def test_panne_des_sources_obligatoires_alerte_une_fois_puis_retour_au_vert(self):
        self.sources.update(alt=(None, None), cg=(None, None), cmc=(10, "buy"))
        for _ in range(ba.SEUIL_ECHECS_SOURCES_CONSECUTIFS):
            ba.main()
        msgs = self.messages()
        self.assertEqual(len(msgs), 1)
        self.assertIn("Sources de données en panne", msgs[0])
        ba.main()                                               # toujours en panne : pas de doublon
        self.assertEqual(len(self.messages()), 1)
        self.sources.update(alt=(50, "neutral"), cg=(50, "neutral"))
        ba.main()
        self.assertIn("de nouveau opérationnelles", self.messages()[1])
        self.assertEqual(self.etat()["echecs_sources_consecutifs"], 0)

    def test_fichier_d_etat_corrompu_repart_de_l_etat_neutre(self):
        self.state_file.write_text("{pas du json", encoding="utf-8")
        ba.main()                                               # ne plante pas
        self.assertEqual(self.etat()["combined_state"], "neutral")


if __name__ == "__main__":
    unittest.main()
