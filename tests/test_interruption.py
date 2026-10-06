"""Alerte d'interruption du bot (trou entre deux cycles) : calcul pur + integration
dans trading_alert.main() (aucun reseau, Telegram mocke, etat dans un fichier temporaire)."""

import json
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).parent.parent / "trading-ct"))

import trading_alert  # noqa: E402

NOW = datetime(2026, 10, 5, 21, 10, tzinfo=timezone.utc)
ITEM = {"symbol": "BTCUSDT", "display": "Bitcoin", "asset_class": "crypto"}


def meta_il_y_a(**kw):
    return {"last_run_at": (NOW - timedelta(**kw)).isoformat()}


class TestInterruptionMessage(unittest.TestCase):
    def test_cadence_normale_pas_d_alerte(self):
        self.assertIsNone(trading_alert.interruption_message(meta_il_y_a(minutes=5), NOW))
        self.assertIsNone(trading_alert.interruption_message(meta_il_y_a(minutes=20), NOW))

    def test_seuil_exclusif(self):
        seuil = trading_alert.INTERRUPTION_SEUIL
        self.assertIsNone(trading_alert.interruption_message({"last_run_at": (NOW - seuil).isoformat()}, NOW))
        self.assertIsNotNone(trading_alert.interruption_message(
            {"last_run_at": (NOW - seuil - timedelta(minutes=1)).isoformat()}, NOW))

    def test_incident_du_05_octobre(self):
        # Dernier cycle 19:25, reprise 21:10 : ~1 h 45 sans runner GitHub
        msg = trading_alert.interruption_message(
            {"last_run_at": datetime(2026, 10, 5, 19, 25, tzinfo=timezone.utc).isoformat()}, NOW)
        self.assertIn("Bot interrompu", msg)
        self.assertIn("05/10 19:25 et 05/10 21:10 UTC", msg)
        self.assertIn("1 h 45", msg)
        self.assertIn("runner non acquis", msg)
        self.assertIn("githubstatus.com", msg)

    def test_duree_en_minutes_sous_90_min(self):
        msg = trading_alert.interruption_message(meta_il_y_a(minutes=45), NOW)
        self.assertIn("≈ 45 min", msg)

    def test_premier_cycle_ou_horodatage_illisible(self):
        self.assertIsNone(trading_alert.interruption_message({}, NOW))
        self.assertIsNone(trading_alert.interruption_message({"last_run_at": "n'importe quoi"}, NOW))
        self.assertIsNone(trading_alert.interruption_message({"last_run_at": None}, NOW))

    def test_cooldown_anti_spam(self):
        meta = meta_il_y_a(hours=4)
        meta["derniere_alerte_interruption"] = (NOW - timedelta(hours=2)).isoformat()
        self.assertIsNone(trading_alert.interruption_message(meta, NOW))
        meta["derniere_alerte_interruption"] = (NOW - timedelta(hours=7)).isoformat()
        self.assertIsNotNone(trading_alert.interruption_message(meta, NOW))

    def test_ne_modifie_pas_meta(self):
        meta = meta_il_y_a(hours=2)
        avant = dict(meta)
        trading_alert.interruption_message(meta, NOW)
        self.assertEqual(meta, avant)


class TestInterruptionDansMain(unittest.TestCase):
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

    def cycle(self):
        neutre = {"symbol": "BTCUSDT", "display": "Bitcoin", "combined": "neutral", "price": 100.0,
                  "rsi": 50, "macd_score": 50, "fng": 50}
        with patch.object(trading_alert, "evaluate_symbol", return_value=neutre):
            trading_alert.main()

    def meta(self):
        return json.loads(self.state_file.read_text(encoding="utf-8"))["_meta"]

    def messages(self):
        return [c.args[1] for c in self.send.call_args_list]

    def ecrire_dernier_cycle(self, **ago):
        self.state_file.write_text(json.dumps({"_meta": {
            "last_run_at": (datetime.now(timezone.utc) - timedelta(**ago)).isoformat()}}), encoding="utf-8")

    def test_premier_cycle_enregistre_l_heure_sans_alerter(self):
        self.cycle()
        self.assertEqual(self.messages(), [])
        self.assertIn("last_run_at", self.meta())

    def test_cycles_rapproches_pas_d_alerte(self):
        self.cycle()
        self.cycle()
        self.assertEqual(self.messages(), [])

    def test_trou_d_une_heure_alerte_une_seule_fois(self):
        self.ecrire_dernier_cycle(minutes=105)
        self.cycle()
        msgs = self.messages()
        self.assertEqual(len(msgs), 1)
        self.assertIn("Bot interrompu", msgs[0])
        self.assertRegex(msgs[0], r"1 h 4[56]")           # 105 min + temps du test
        self.assertIn("derniere_alerte_interruption", self.meta())
        self.cycle()                                   # cycle suivant : plus de trou
        self.assertEqual(len(self.messages()), 1)

    def test_echec_telegram_ne_fait_pas_echouer_le_job(self):
        self.ecrire_dernier_cycle(minutes=105)
        self.send.side_effect = RuntimeError("telegram down")
        self.cycle()                                   # ne leve pas
        self.assertNotIn("derniere_alerte_interruption", self.meta())
        self.assertIn("last_run_at", self.meta())


if __name__ == "__main__":
    unittest.main()
