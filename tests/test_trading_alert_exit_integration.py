"""Integration de exit_rules dans la boucle principale de trading_alert.main() :
plusieurs cycles enchaines avec des resultats de strategie simules (aucun
reseau, Telegram mocke, etat dans un fichier temporaire)."""

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).parent.parent / "trading-ct"))

import trading_alert  # noqa: E402

ITEM = {"symbol": "BTCUSDT", "display": "Bitcoin", "asset_class": "crypto"}


def _res(combined, price):
    return {"symbol": "BTCUSDT", "display": "Bitcoin", "combined": combined, "price": price,
            "rsi": 10, "macd_score": 10, "fng": 10}


class TestBoucleAvecSortie(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.state_file = Path(self.tmp.name) / "state.json"
        self.send = MagicMock()
        patches = [
            patch.object(trading_alert, "STATE_FILE", self.state_file),
            patch.object(trading_alert, "SUPABASE_URL", ""),
            patch.object(trading_alert, "SUPABASE_SERVICE_ROLE_KEY", ""),
            patch.object(trading_alert, "WATCHLIST", [ITEM]),
            patch.object(trading_alert, "fetch_crypto_fng", return_value=50),
            patch.object(trading_alert, "send_telegram", self.send),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        self.addCleanup(self.tmp.cleanup)

    def cycle(self, combined, price):
        with patch.object(trading_alert, "evaluate_symbol", return_value=_res(combined, price)):
            trading_alert.main()

    def etat(self):
        return json.loads(self.state_file.read_text(encoding="utf-8"))["BTCUSDT"]

    def messages(self):
        return [c.args[1] for c in self.send.call_args_list]

    def test_achat_puis_objectif_atteint(self):
        self.cycle("buy", 100.0)
        self.assertEqual(self.etat()["entry"]["price"], 100.0)
        self.assertEqual(len(self.messages()), 1)          # alerte d'achat seule

        self.cycle("neutral", 104.0)                       # entre stop et objectif
        self.assertEqual(len(self.messages()), 1)
        self.assertIn("entry", self.etat())

        self.cycle("neutral", 108.5)                       # objectif +8 % touche
        msgs = self.messages()
        self.assertEqual(len(msgs), 2)
        self.assertIn("OBJECTIF ATTEINT", msgs[1])
        self.assertNotIn("entry", self.etat())

        self.cycle("neutral", 130.0)                       # plus de suivi : silence
        self.assertEqual(len(self.messages()), 2)

    def test_achat_puis_stop(self):
        self.cycle("buy", 100.0)
        self.cycle("neutral", 94.0)                        # stop -5 % touche
        msgs = self.messages()
        self.assertEqual(len(msgs), 2)
        self.assertIn("STOP ATTEINT", msgs[1])
        self.assertNotIn("entry", self.etat())

    def test_alerte_de_vente_ferme_le_suivi_sans_double_message(self):
        self.cycle("buy", 100.0)
        self.cycle("sell", 112.0)                          # vente de la strategie (+12 %)
        msgs = self.messages()
        self.assertEqual(len(msgs), 2)                     # achat + vente, pas de message d'objectif
        self.assertNotIn("OBJECTIF", msgs[1])
        self.assertNotIn("entry", self.etat())

    def test_etat_buy_persistant_ne_reouvre_pas_de_suivi_apres_sortie(self):
        self.cycle("buy", 100.0)
        self.cycle("buy", 109.0)                           # toujours en etat buy : pas de nouvelle alerte d'achat
        msgs = self.messages()
        self.assertEqual(len(msgs), 2)                     # achat + objectif
        self.assertIn("OBJECTIF", msgs[1])
        self.assertNotIn("entry", self.etat())

    def test_echec_telegram_sur_la_sortie_ne_la_rejoue_pas_a_chaque_cycle(self):
        self.cycle("buy", 100.0)
        self.send.side_effect = RuntimeError("telegram down")
        with self.assertRaises(SystemExit):                # job rouge pour visibilite
            self.cycle("neutral", 110.0)
        self.assertNotIn("entry", self.etat())             # suivi ferme malgre l'echec
        n = self.send.call_count
        self.send.side_effect = None
        self.cycle("neutral", 111.0)                       # cycle suivant : rien n'est rejoue
        self.assertEqual(self.send.call_count, n)

    def test_echec_telegram_sur_l_achat_n_ouvre_pas_de_suivi(self):
        self.send.side_effect = RuntimeError("telegram down")
        with self.assertRaises(SystemExit):
            self.cycle("buy", 100.0)
        self.assertNotIn("entry", self.etat())


if __name__ == "__main__":
    unittest.main()
