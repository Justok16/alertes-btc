"""Niveaux de signal d'achat (fort 15 / modere 20) : logique pure, messages et
integration dans les boucles principales des deux bots (aucun reseau)."""

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).parent.parent / "trading-ct"))

import trading_alert  # noqa: E402
import trading_alert_eu  # noqa: E402
from trading_alert import combine_signal, is_upgrade  # noqa: E402


class TestCombineSignal(unittest.TestCase):
    def test_fort_si_les_trois_zones_achat(self):
        self.assertEqual(combine_signal(("buy",) * 3, (10, 12, 14)), ("buy", "strong"))

    def test_vente_toujours_stricte(self):
        self.assertEqual(combine_signal(("sell",) * 3, (90, 88, 86)), ("sell", "strong"))
        # 3 scores >= 80 mais pas >= 85 : aucun assouplissement cote vente
        self.assertEqual(combine_signal(("neutral",) * 3, (82, 83, 84)), ("neutral", None))

    def test_modere_si_les_trois_scores_a_20_ou_moins(self):
        self.assertEqual(combine_signal(("buy", "neutral", "neutral"), (14, 19, 20)), ("buy", "moderate"))

    def test_pas_modere_si_un_score_depasse_20(self):
        self.assertEqual(combine_signal(("buy", "buy", "neutral"), (10, 12, 20.1)), ("neutral", None))

    def test_score_manquant_empeche_le_modere(self):
        self.assertEqual(combine_signal(("buy", "buy", None), (10, 12, None)), ("neutral", None))

    def test_zones_mixtes_achat_vente_restent_neutres(self):
        self.assertEqual(combine_signal(("buy", "sell", "buy"), (10, 90, 10)), ("neutral", None))


class TestUpgradeEtMessages(unittest.TestCase):
    def test_upgrade_seulement_de_modere_vers_fort(self):
        fort = {"combined": "buy", "level": "strong"}
        modere = {"combined": "buy", "level": "moderate"}
        self.assertTrue(is_upgrade("buy", "moderate", fort))
        self.assertFalse(is_upgrade("buy", "strong", fort))
        self.assertFalse(is_upgrade("buy", "strong", modere))      # descente : silence
        self.assertFalse(is_upgrade("buy", None, fort))            # etat historique sans niveau
        self.assertFalse(is_upgrade("neutral", None, fort))        # c'est une nouvelle alerte, pas un upgrade

    def test_episode_level_garde_le_plus_haut_niveau(self):
        fort = {"combined": "buy", "level": "strong"}
        modere = {"combined": "buy", "level": "moderate"}
        neutre = {"combined": "neutral", "level": None}
        self.assertEqual(trading_alert.episode_level("buy", "strong", modere), "strong")
        self.assertEqual(trading_alert.episode_level("buy", "moderate", fort), "strong")
        self.assertEqual(trading_alert.episode_level("buy", "moderate", modere), "moderate")
        self.assertEqual(trading_alert.episode_level("buy", "strong", neutre), None)       # episode termine
        self.assertEqual(trading_alert.episode_level("neutral", None, modere), "moderate")  # nouvel episode

    def _res(self, level, combined="buy"):
        return {"symbol": "BTCUSDT", "display": "Bitcoin", "combined": combined, "level": level,
                "price": 100.0, "rsi": 12, "macd_score": 13, "fng": 14}

    def test_titres(self):
        self.assertIn("MODÉRÉ", trading_alert.build_message(self._res("moderate")))
        self.assertIn("FORT", trading_alert.build_message(self._res("strong")))
        self.assertIn("RENFORCÉ", trading_alert.build_message(self._res("strong"), upgrade=True))
        vente = trading_alert.build_message(self._res("strong", combined="sell"))
        self.assertIn("VENTE", vente)
        self.assertNotIn("MODÉRÉ", vente)

    def test_message_modere_explique_les_seuils(self):
        msg = trading_alert.build_message(self._res("moderate"))
        self.assertIn("20 ou moins", msg)
        self.assertIn("15 ou moins", msg)

    def test_message_europe_utilise_les_memes_titres(self):
        res = {"symbol": "VVSM.XETRA", "display": "VanEck", "combined": "buy", "level": "moderate",
               "price": 100.0, "rsi": 12, "macd_score": 13, "home_score": 14}
        msg = trading_alert_eu.build_message(res)
        self.assertIn("ETF Europe", msg)
        self.assertIn("MODÉRÉ", msg)


def _res(combined, level, price, symbol="BTCUSDT"):
    return {"symbol": symbol, "display": "Bitcoin", "combined": combined, "level": level, "price": price,
            "rsi": 10, "macd_score": 10, "fng": 10, "home_score": 10}


class _BaseIntegration(unittest.TestCase):
    module = None
    symbol = "BTCUSDT"

    def _extra_patches(self):
        return []

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.state_file = Path(self.tmp.name) / "state.json"
        self.send = MagicMock()
        patches = [
            patch.object(self.module, "STATE_FILE", self.state_file),
            patch.object(self.module, "SUPABASE_URL", ""),
            patch.object(self.module, "SUPABASE_SERVICE_ROLE_KEY", ""),
            patch.object(self.module, "send_telegram", self.send),
        ] + self._extra_patches()
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        self.addCleanup(self.tmp.cleanup)

    def cycle(self, combined, level, price):
        with patch.object(self.module, "evaluate_symbol", return_value=_res(combined, level, price, self.symbol)):
            self.module.main()

    def etat(self):
        return json.loads(self.state_file.read_text(encoding="utf-8"))[self.symbol]

    def messages(self):
        return [c.args[1] for c in self.send.call_args_list]

    # --- scenarios communs aux deux bots ---
    def scenario_modere_puis_fort(self):
        self.cycle("buy", "moderate", 100.0)
        msgs = self.messages()
        self.assertEqual(len(msgs), 1)
        self.assertIn("MODÉRÉ", msgs[0])
        self.assertEqual(self.etat()["level"], "moderate")
        self.assertEqual(self.etat()["entry"]["price"], 100.0)     # le suivi s'ouvre des l'alerte moderee

        self.cycle("buy", "moderate", 101.0)                       # rien de nouveau : silence
        self.assertEqual(len(self.messages()), 1)

        self.cycle("buy", "strong", 99.0)                          # devient fort : alerte "renforce"
        msgs = self.messages()
        self.assertEqual(len(msgs), 2)
        self.assertIn("RENFORCÉ", msgs[1])
        self.assertEqual(self.etat()["level"], "strong")
        self.assertEqual(self.etat()["entry"]["price"], 100.0)     # prix de suivi inchange

        self.cycle("buy", "moderate", 99.0)                        # redescend a modere : silence
        self.assertEqual(len(self.messages()), 2)
        self.assertEqual(self.etat()["level"], "strong")           # on garde le plus haut niveau de l'episode
        self.cycle("buy", "strong", 99.0)                          # oscillation : pas de 2e "renforce"
        self.assertEqual(len(self.messages()), 2)

    def scenario_fort_direct_puis_modere_silencieux(self):
        self.cycle("buy", "strong", 100.0)
        self.assertIn("FORT", self.messages()[0])
        self.cycle("buy", "moderate", 100.0)
        self.cycle("buy", "strong", 100.0)                         # strong -> moderate -> strong : pas d'upgrade
        self.assertEqual(len(self.messages()), 1)

    def scenario_retour_neutre_puis_nouveau_modere_realerte(self):
        self.cycle("buy", "moderate", 100.0)
        self.cycle("neutral", None, 101.0)
        self.assertNotIn("level", self.etat())
        self.cycle("buy", "moderate", 100.5)
        self.assertEqual(len(self.messages()), 2)                  # deux alertes modérées distinctes


class TestIntegrationBotCrypto(_BaseIntegration):
    module = trading_alert

    def _extra_patches(self):
        return [
            patch.object(trading_alert, "WATCHLIST", [{"symbol": "BTCUSDT", "display": "Bitcoin", "asset_class": "crypto"}]),
            patch.object(trading_alert, "fetch_crypto_fng", return_value=50),
        ]

    def test_modere_puis_fort(self):
        self.scenario_modere_puis_fort()

    def test_fort_direct(self):
        self.scenario_fort_direct_puis_modere_silencieux()

    def test_retour_neutre(self):
        self.scenario_retour_neutre_puis_nouveau_modere_realerte()

    def test_etat_historique_sans_niveau_ne_declenche_pas_d_upgrade(self):
        self.state_file.write_text(json.dumps({"BTCUSDT": {"combined_state": "buy"}}), encoding="utf-8")
        self.cycle("buy", "strong", 100.0)
        self.assertEqual(len(self.messages()), 0)
        self.assertEqual(self.etat()["level"], "strong")


class TestIntegrationBotEurope(_BaseIntegration):
    module = trading_alert_eu
    symbol = "VVSM.XETRA"

    def _extra_patches(self):
        return [patch.object(trading_alert_eu, "EU_WATCHLIST", [{"symbol": "VVSM.XETRA", "display": "VanEck"}])]

    def test_modere_puis_fort(self):
        self.scenario_modere_puis_fort()

    def test_fort_direct(self):
        self.scenario_fort_direct_puis_modere_silencieux()

    def test_retour_neutre(self):
        self.scenario_retour_neutre_puis_nouveau_modere_realerte()

    def test_alerte_moderee_puis_objectif_europe(self):
        self.cycle("buy", "moderate", 100.0)
        self.cycle("neutral", None, 106.5)                         # ETF : objectif +6 %
        msgs = self.messages()
        self.assertEqual(len(msgs), 2)
        self.assertIn("OBJECTIF ATTEINT", msgs[1])
        self.assertNotIn("entry", self.etat())


if __name__ == "__main__":
    unittest.main()
