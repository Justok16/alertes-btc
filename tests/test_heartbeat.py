"""heartbeat.py : verdict quotidien "bot vivant" / "cadence degradee" (aucun reseau)."""

import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).parent.parent / "trading-ct"))

import heartbeat  # noqa: E402

NOW = datetime(2026, 10, 5, 6, 17, tzinfo=timezone.utc)


def main_stats(total=288, failures=0, minutes=3, conclusion="success"):
    return {"total": total, "failures": failures, "last_at": NOW - timedelta(minutes=minutes),
            "last_conclusion": conclusion}


def eu_stats(hours=12, conclusion="success"):
    return {"total": 1, "failures": 0, "last_at": NOW - timedelta(hours=hours), "last_conclusion": conclusion}


class TestVerdict(unittest.TestCase):
    def test_tout_va_bien(self):
        degrade, msg = heartbeat.build_message(main_stats(), eu_stats(), NOW)
        self.assertFalse(degrade)
        self.assertIn("le bot est vivant", msg)
        self.assertIn("288 exécutions sur 24 h", msg)
        self.assertNotIn("⚠️", msg)
        self.assertIn("github.com/Justok16/alertes-btc/actions", msg)

    def test_cadence_degradee_si_le_declencheur_externe_s_arrete(self):
        # Seul le cron natif de GitHub continue : ~6 executions par jour
        degrade, msg = heartbeat.build_message(main_stats(total=6), eu_stats(), NOW)
        self.assertTrue(degrade)
        self.assertIn("Cadence dégradée", msg)
        self.assertIn("6 exécutions", msg)
        self.assertIn("déclencheur externe", msg)
        self.assertIn("à regarder", msg)

    def test_seuil_de_cadence(self):
        self.assertTrue(heartbeat.build_message(main_stats(total=heartbeat.WARN_MAIN_BELOW - 1), eu_stats(), NOW)[0])
        self.assertFalse(heartbeat.build_message(main_stats(total=heartbeat.WARN_MAIN_BELOW), eu_stats(), NOW)[0])

    def test_executions_en_echec(self):
        degrade, msg = heartbeat.build_message(main_stats(failures=3), eu_stats(), NOW)
        self.assertTrue(degrade)
        self.assertIn("3 exécution(s) crypto/US en échec", msg)

    def test_derniere_execution_trop_ancienne(self):
        degrade, msg = heartbeat.build_message(main_stats(minutes=45), eu_stats(), NOW)
        self.assertTrue(degrade)
        self.assertIn("plus de 30 min", msg)

    def test_aucune_execution_connue(self):
        vide = {"total": 0, "failures": 0, "last_at": None, "last_conclusion": None}
        degrade, msg = heartbeat.build_message(vide, vide, NOW)
        self.assertTrue(degrade)
        self.assertIn("jamais", msg)

    def test_europe_tolere_le_week_end(self):
        # vendredi 18:00 -> lundi 06:17 = 60 h : normal
        self.assertFalse(heartbeat.build_message(main_stats(), eu_stats(hours=60), NOW)[0])

    def test_europe_non_execute_depuis_trop_longtemps(self):
        degrade, msg = heartbeat.build_message(main_stats(), eu_stats(hours=100), NOW)
        self.assertTrue(degrade)
        self.assertIn("Europe/Chine non exécuté", msg)

    def test_europe_derniere_execution_en_echec(self):
        degrade, msg = heartbeat.build_message(main_stats(), eu_stats(conclusion="failure"), NOW)
        self.assertTrue(degrade)
        self.assertIn("Europe/Chine en échec", msg)

    def test_europe_en_cours_n_est_pas_une_alerte(self):
        self.assertFalse(heartbeat.build_message(main_stats(), eu_stats(conclusion="in_progress"), NOW)[0])


class TestAgo(unittest.TestCase):
    def test_formats(self):
        a = lambda **kw: heartbeat.ago(NOW, NOW - timedelta(**kw))  # noqa: E731
        self.assertEqual(a(seconds=30), "il y a moins de 2 min")
        self.assertEqual(a(minutes=12), "il y a 12 min")
        self.assertEqual(a(hours=3), "il y a 3 h")
        self.assertEqual(a(days=3), "il y a 3 j")
        self.assertEqual(heartbeat.ago(NOW, None), "jamais")


def _reponse(payload):
    r = MagicMock()
    r.json.return_value = payload
    r.raise_for_status.return_value = None
    return r


class TestApi(unittest.TestCase):
    def test_workflow_stats_trois_appels_et_filtres(self):
        session = MagicMock()
        session.get.side_effect = [
            _reponse({"total_count": 290}),
            _reponse({"total_count": 2}),
            _reponse({"workflow_runs": [{"created_at": "2026-10-05T06:14:03Z", "conclusion": "success",
                                         "status": "completed"}]}),
        ]
        stats = heartbeat.workflow_stats(session, "o/r", "wf.yml", NOW - timedelta(hours=24))
        self.assertEqual(stats["total"], 290)
        self.assertEqual(stats["failures"], 2)
        self.assertEqual(stats["last_at"], datetime(2026, 10, 5, 6, 14, 3, tzinfo=timezone.utc))
        self.assertEqual(stats["last_conclusion"], "success")
        appels = session.get.call_args_list
        self.assertEqual(len(appels), 3)
        self.assertIn("/repos/o/r/actions/workflows/wf.yml/runs", appels[0].args[0])
        self.assertEqual(appels[0].kwargs["params"]["created"], ">=2026-10-04T06:17:00Z")
        self.assertEqual(appels[1].kwargs["params"]["status"], "failure")

    def test_workflow_jamais_execute(self):
        session = MagicMock()
        session.get.side_effect = [_reponse({"total_count": 0}), _reponse({"total_count": 0}),
                                   _reponse({"workflow_runs": []})]
        stats = heartbeat.workflow_stats(session, "o/r", "wf.yml", NOW)
        self.assertIsNone(stats["last_at"])
        self.assertIsNone(stats["last_conclusion"])


class TestMain(unittest.TestCase):
    def test_envoie_le_verdict(self):
        send = MagicMock()
        with patch.object(heartbeat, "workflow_stats", side_effect=[main_stats(), eu_stats()]), \
                patch.object(heartbeat, "send_telegram", send), \
                patch.object(heartbeat, "datetime") as dt:
            dt.now.return_value = NOW
            dt.fromisoformat = datetime.fromisoformat
            heartbeat.main()
        send.assert_called_once()
        self.assertIn("le bot est vivant", send.call_args.args[1])

    def test_api_github_indisponible_previent_et_echoue(self):
        send = MagicMock()
        with patch.object(heartbeat, "workflow_stats", side_effect=RuntimeError("boom")), \
                patch.object(heartbeat, "send_telegram", send):
            with self.assertRaises(SystemExit) as ctx:
                heartbeat.main()
        self.assertEqual(ctx.exception.code, 1)
        self.assertIn("impossible de lire", send.call_args.args[1])


if __name__ == "__main__":
    unittest.main()
