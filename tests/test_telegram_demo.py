"""Le test complet des alertes (telegram_demo.py) doit lui-meme rester fiable :
il passe sur le code actuel, et il ECHOUE si le comportement d'une alerte casse."""

import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).parent.parent / "trading-ct"))

import exit_rules  # noqa: E402
import telegram_demo  # noqa: E402


class TestTelegramDemo(unittest.TestCase):
    def lancer(self, extra=None):
        envoi = MagicMock()
        with patch.object(telegram_demo, "REAL_SEND", envoi), \
                patch.object(telegram_demo, "PAUSE_ENTRE_MESSAGES", 0), \
                patch("telegram_demo.sys.stdout"):
            code = telegram_demo.main() if extra is None else extra(telegram_demo.main)
        return code, envoi

    def test_tous_les_scenarios_passent_sur_le_code_actuel(self):
        code, envoi = self.lancer()
        self.assertEqual(code, 0)
        self.assertEqual(envoi.call_count, 16)   # 15 scenarios + recapitulatif
        recap = envoi.call_args_list[-1].args[1]
        self.assertIn("15/15", recap)
        self.assertNotIn("❌", recap)

    def test_chaque_message_est_marque_test(self):
        _, envoi = self.lancer()
        for appel in envoi.call_args_list:
            self.assertIn("TEST", appel.args[1])

    def test_detecte_une_regression_de_la_regle_de_sortie(self):
        # Objectif/stop inatteignables : les scenarios "objectif" et "stop" doivent echouer.
        def avec_regle_cassee(main):
            with patch.dict(exit_rules.EXIT_RULES, {"crypto": (500.0, 500.0)}):
                return main()
        code, envoi = self.lancer(avec_regle_cassee)
        self.assertEqual(code, 1)
        recap = envoi.call_args_list[-1].args[1]
        self.assertIn("❌", recap)
        self.assertIn("13/15", recap)

    def test_echec_telegram_rend_le_test_en_erreur(self):
        envoi = MagicMock(side_effect=RuntimeError("telegram down"))
        with patch.object(telegram_demo, "REAL_SEND", envoi), \
                patch.object(telegram_demo, "PAUSE_ENTRE_MESSAGES", 0), \
                patch("telegram_demo.sys.stdout"):
            code = telegram_demo.main()
        self.assertEqual(code, 1)


if __name__ == "__main__":
    unittest.main()
