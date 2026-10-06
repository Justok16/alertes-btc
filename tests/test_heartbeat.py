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

    def test_echecs_runner_non_acquis_distingues_d_un_bug(self):
        main = main_stats(failures=7)
        main["runner_unacquired"] = 7
        degrade, msg = heartbeat.build_message(main, eu_stats(), NOW)
        self.assertTrue(degrade)
        self.assertIn("7 exécution(s) crypto/US en échec car GitHub n'a pas fourni de runner", msg)
        self.assertIn("panne de GitHub Actions", msg)
        self.assertIn("githubstatus.com", msg)
        # Tous les echecs s'expliquent par la panne : pas de ligne "echec ordinaire" en plus
        self.assertNotIn("en échec sur 24 h.", msg)

    def test_echecs_mixtes_runner_et_autres(self):
        main = main_stats(failures=5)
        main["runner_unacquired"] = 2
        _, msg = heartbeat.build_message(main, eu_stats(), NOW)
        self.assertIn("2 exécution(s) crypto/US en échec car GitHub n'a pas fourni de runner", msg)
        self.assertIn("3 exécution(s) crypto/US en échec sur 24 h.", msg)

    def test_echecs_factures_paiement_ou_plafond_de_depenses(self):
        main = main_stats(failures=52)
        main["billing_blocked"] = 52
        degrade, msg = heartbeat.build_message(main, eu_stats(), NOW)
        self.assertTrue(degrade)
        self.assertIn("52 exécution(s) crypto/US refusée(s) par GitHub : paiement échoué ou plafond", msg)
        self.assertIn("Settings > Billing", msg)
        self.assertNotIn("en échec sur 24 h.", msg)
        self.assertNotIn("runner", msg)

    def test_echecs_trois_causes_melangees(self):
        main = main_stats(failures=10)
        main["runner_unacquired"] = 3
        main["billing_blocked"] = 4
        _, msg = heartbeat.build_message(main, eu_stats(), NOW)
        self.assertIn("3 exécution(s) crypto/US en échec car GitHub n'a pas fourni de runner", msg)
        self.assertIn("4 exécution(s) crypto/US refusée(s) par GitHub", msg)
        self.assertIn("3 exécution(s) crypto/US en échec sur 24 h.", msg)

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
    def test_workflow_stats_appels_et_filtres(self):
        session = MagicMock()
        session.get.side_effect = [
            _reponse({"total_count": 290}),
            _reponse({"total_count": 2}),
            _reponse({"workflow_runs": []}),  # diagnostic des echecs (aucun run detaille ici)
            _reponse({"workflow_runs": [{"created_at": "2026-10-05T06:14:03Z", "conclusion": "success",
                                         "status": "completed"}]}),
        ]
        stats = heartbeat.workflow_stats(session, "o/r", "wf.yml", NOW - timedelta(hours=24))
        self.assertEqual(stats["total"], 290)
        self.assertEqual(stats["failures"], 2)
        self.assertEqual(stats["last_at"], datetime(2026, 10, 5, 6, 14, 3, tzinfo=timezone.utc))
        self.assertEqual(stats["last_conclusion"], "success")
        appels = session.get.call_args_list
        self.assertEqual(len(appels), 4)
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


class TestRunnerNonAcquis(unittest.TestCase):
    URL = "https://api.github.com/repos/o/r/actions/workflows/wf.yml/runs"

    def _run(self, i):
        return {"id": i, "jobs_url": f"https://api.github.com/repos/o/r/actions/runs/{i}/jobs"}

    def _job(self, i):
        return {"jobs": [{"id": i, "check_run_url": f"https://api.github.com/repos/o/r/check-runs/{i}"}]}

    def test_compte_les_runs_dont_le_runner_n_a_pas_ete_acquis(self):
        session = MagicMock()
        session.get.side_effect = [
            _reponse({"workflow_runs": [self._run(1), self._run(2)]}),
            _reponse(self._job(11)),
            _reponse([{"message": "The job was not acquired by Runner of type hosted even after multiple attempts"},
                      {"message": "The ubuntu-latest label will migrate to Ubuntu 26"}]),
            _reponse(self._job(22)),
            _reponse([{"message": "Process completed with exit code 1."}]),  # vrai echec du bot
        ]
        self.assertEqual(heartbeat.count_failure_causes(session, self.URL, ">=2026-10-04T00:00:00Z")["runner_unacquired"], 1)
        self.assertEqual(session.get.call_args_list[0].kwargs["params"]["status"], "failure")
        self.assertTrue(session.get.call_args_list[2].args[0].endswith("/check-runs/11/annotations"))

    def test_distingue_runner_paiement_et_vrai_echec(self):
        session = MagicMock()
        session.get.side_effect = [
            _reponse({"workflow_runs": [self._run(1), self._run(2), self._run(3), self._run(4)]}),
            _reponse(self._job(11)),
            _reponse([{"message": "The job was not acquired by Runner of type hosted even after multiple attempts"}]),
            _reponse(self._job(22)),
            _reponse([{"message": "The job was not started because recent account payments have failed or "
                                  "your spending limit needs to be increased."}]),
            _reponse(self._job(33)),
            _reponse([{"message": "The job was not started because your spending limit needs to be increased"}]),
            _reponse(self._job(44)),
            _reponse([{"message": "Process completed with exit code 1."}]),
        ]
        self.assertEqual(heartbeat.count_failure_causes(session, self.URL, ">=x"),
                         {"runner_unacquired": 1, "billing_blocked": 2})

    def test_annotation_sans_message_ne_plante_pas(self):
        session = MagicMock()
        session.get.side_effect = [_reponse({"workflow_runs": [self._run(1)]}), _reponse(self._job(11)),
                                   _reponse([{"message": None}, {}])]
        self.assertEqual(heartbeat.count_failure_causes(session, self.URL, ">=x"),
                         {"runner_unacquired": 0, "billing_blocked": 0})

    def test_erreur_api_n_est_pas_bloquante(self):
        session = MagicMock()
        session.get.side_effect = RuntimeError("boom")
        self.assertEqual(heartbeat.count_failure_causes(session, self.URL, ">=x"),
                         {"runner_unacquired": 0, "billing_blocked": 0})

    def test_plafond_de_runs_inspectes(self):
        session = MagicMock()
        runs = [self._run(i) for i in range(heartbeat.MAX_RUNS_INSPECTED + 5)]
        session.get.side_effect = [_reponse({"workflow_runs": runs})] + [
            r for _ in range(heartbeat.MAX_RUNS_INSPECTED) for r in (_reponse({"jobs": []}),)]
        heartbeat.count_failure_causes(session, self.URL, ">=x")
        self.assertEqual(session.get.call_count, 1 + heartbeat.MAX_RUNS_INSPECTED)

    def test_workflow_stats_n_inspecte_rien_sans_echec(self):
        session = MagicMock()
        session.get.side_effect = [_reponse({"total_count": 288}), _reponse({"total_count": 0}),
                                   _reponse({"workflow_runs": []})]
        stats = heartbeat.workflow_stats(session, "o/r", "wf.yml", NOW)
        self.assertEqual(stats["runner_unacquired"], 0)
        self.assertEqual(session.get.call_count, 3)

    def test_workflow_stats_expose_le_compteur(self):
        session = MagicMock()
        session.get.side_effect = [
            _reponse({"total_count": 291}), _reponse({"total_count": 1}),
            _reponse({"workflow_runs": [self._run(1)]}), _reponse(self._job(11)),
            _reponse([{"message": "The job was not acquired by Runner of type hosted"}]),
            _reponse({"workflow_runs": []}),
        ]
        stats = heartbeat.workflow_stats(session, "o/r", "wf.yml", NOW)
        self.assertEqual((stats["failures"], stats["runner_unacquired"]), (1, 1))


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
