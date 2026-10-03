"""Tests de exit_rules.py -- suivi objectif/stop depuis le prix de l'alerte d'achat."""

import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "trading-ct"))

import exit_rules  # noqa: E402

T0 = datetime(2026, 10, 3, 12, 0, tzinfo=timezone.utc)
ENTRY = {"price": 100.0, "ts": T0.isoformat()}


def step(entry, price, new_alert=None, alert_sent=False, days=1.0, target=8.0, stop=5.0):
    return exit_rules.step_position(entry, new_alert, alert_sent, price, T0 + timedelta(days=days), target, stop)


class TestCheckExit(unittest.TestCase):
    def test_objectif_atteint(self):
        kind, change = exit_rules.check_exit(ENTRY, 108.0, T0 + timedelta(days=1), 8, 5)
        self.assertEqual(kind, "target")
        self.assertAlmostEqual(change, 8.0)

    def test_stop_atteint(self):
        kind, change = exit_rules.check_exit(ENTRY, 94.9, T0 + timedelta(days=1), 8, 5)
        self.assertEqual(kind, "stop")
        self.assertLess(change, -5)

    def test_entre_les_deux_rien(self):
        self.assertIsNone(exit_rules.check_exit(ENTRY, 103.0, T0 + timedelta(days=1), 8, 5))

    def test_expiration_apres_max_jours(self):
        kind, _ = exit_rules.check_exit(ENTRY, 101.0, T0 + timedelta(days=exit_rules.EXIT_MAX_DAYS), 8, 5)
        self.assertEqual(kind, "expired")

    def test_objectif_prioritaire_sur_expiration(self):
        kind, _ = exit_rules.check_exit(ENTRY, 120.0, T0 + timedelta(days=60), 8, 5)
        self.assertEqual(kind, "target")

    def test_horodatage_illisible_ne_plante_pas_ni_n_expire(self):
        entry = {"price": 100.0, "ts": "pas-une-date"}
        self.assertIsNone(exit_rules.check_exit(entry, 101.0, T0 + timedelta(days=365), 8, 5))
        self.assertEqual(exit_rules.check_exit(entry, 90.0, T0, 8, 5)[0], "stop")


class TestStepPosition(unittest.TestCase):
    def test_alerte_achat_envoyee_ouvre_le_suivi(self):
        entry, ev = step(None, 100.0, new_alert="buy", alert_sent=True, days=0)
        self.assertIsNone(ev)
        self.assertEqual(entry["price"], 100.0)
        self.assertIn("ts", entry)

    def test_alerte_achat_non_envoyee_n_ouvre_pas_de_suivi(self):
        entry, _ = step(None, 100.0, new_alert="buy", alert_sent=False, days=0)
        self.assertIsNone(entry)

    def test_pas_d_ecrasement_d_un_suivi_ouvert(self):
        entry, _ = step(ENTRY, 97.0, new_alert="buy", alert_sent=True)
        self.assertEqual(entry, ENTRY)

    def test_objectif_ferme_le_suivi_et_signale_une_fois(self):
        entry, ev = step(ENTRY, 109.0)
        self.assertIsNone(entry)
        self.assertEqual(ev[0], "target")
        # cycle suivant : plus rien a signaler
        entry2, ev2 = step(entry, 109.0)
        self.assertIsNone(entry2)
        self.assertIsNone(ev2)

    def test_stop_ferme_le_suivi(self):
        entry, ev = step(ENTRY, 90.0)
        self.assertIsNone(entry)
        self.assertEqual(ev[0], "stop")

    def test_rien_ne_se_passe_entre_objectif_et_stop(self):
        entry, ev = step(ENTRY, 102.0)
        self.assertEqual(entry, ENTRY)
        self.assertIsNone(ev)

    def test_alerte_vente_ferme_le_suivi_sans_message_de_sortie(self):
        entry, ev = step(ENTRY, 112.0, new_alert="sell", alert_sent=True)
        self.assertIsNone(entry)
        self.assertIsNone(ev)

    def test_nouvelle_alerte_achat_apres_sortie_dans_le_meme_cycle(self):
        entry, ev = step(ENTRY, 109.0, new_alert="buy", alert_sent=True)
        self.assertEqual(ev[0], "target")
        self.assertEqual(entry["price"], 109.0)

    def test_entree_corrompue_est_ignoree(self):
        for bad in ({"price": "abc"}, {"price": 0}, {"price": -5}, "texte", 42, {}):
            entry, ev = step(bad, 100.0)
            self.assertIsNone(entry)
            self.assertIsNone(ev)


class TestRegles(unittest.TestCase):
    def test_valeurs_par_defaut_par_classe(self):
        self.assertEqual(exit_rules.exit_rule_for({"asset_class": "crypto"}), (8.0, 5.0))
        self.assertEqual(exit_rules.exit_rule_for({"asset_class": "etf"}), (6.0, 4.0))
        self.assertEqual(exit_rules.exit_rule_for({"asset_class": "stock"}), (6.0, 4.0))

    def test_actif_sans_classe_prend_la_regle_par_defaut(self):
        self.assertEqual(exit_rules.exit_rule_for({"symbol": "VVSM.XETRA"}), exit_rules.DEFAULT_EXIT_RULE)

    def test_surcharge_par_actif(self):
        self.assertEqual(exit_rules.exit_rule_for({"asset_class": "crypto", "exit_rule": (12, 7)}), (12.0, 7.0))

    def test_watchlist_reelle_hut_plus_large_les_autres_par_defaut(self):
        from watchlist import WATCHLIST
        regles = {i["symbol"]: exit_rules.exit_rule_for(i) for i in WATCHLIST}
        self.assertEqual(regles["HUT"], (12.0, 8.0))
        self.assertEqual(regles["NOG"], (6.0, 4.0))
        self.assertEqual(regles["BTCUSDT"], (8.0, 5.0))


class TestMessage(unittest.TestCase):
    def test_messages_contiennent_l_essentiel(self):
        for kind, marqueur in (("target", "OBJECTIF"), ("stop", "STOP"), ("expired", "FIN DU SUIVI")):
            msg = exit_rules.build_exit_message("H", "Bitcoin", "BTCUSDT", kind, ENTRY, 108.0, 8.0, 8.0, 5.0)
            self.assertIn(marqueur, msg)
            self.assertIn("BTCUSDT", msg)
            self.assertIn("2026-10-03", msg)
            self.assertIn("pas un conseil financier".lower(), msg.lower())


if __name__ == "__main__":
    unittest.main()
