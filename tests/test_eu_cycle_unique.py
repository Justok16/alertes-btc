"""Bot Europe : un seul cycle par cloture Xetra (quota EODHD de 20 appels/jour,
double declenchement externe + cron GitHub, week-ends). Aucun reseau."""

import json
import os
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).parent.parent / "trading-ct"))

import trading_alert_eu as eu  # noqa: E402

BERLIN = ZoneInfo("Europe/Berlin")


def berlin(y, m, d, h, mi=0):
    return datetime(y, m, d, h, mi, tzinfo=BERLIN)


class TestDerniereCloture(unittest.TestCase):
    def test_apres_la_cloture_du_jour(self):
        # Jeudi 15/10/2026 18:05 Berlin (= 16:05 UTC, heure d'ete) -> cloture du jour
        self.assertEqual(eu.derniere_cloture_xetra(berlin(2026, 10, 15, 18, 5)), berlin(2026, 10, 15, 17, 30))

    def test_avant_la_cloture_du_jour(self):
        # Jeudi 29/10/2026 17:05 Berlin (= 16:05 UTC, heure d'hiver) -> cloture de la VEILLE
        self.assertEqual(eu.derniere_cloture_xetra(berlin(2026, 10, 29, 17, 5)), berlin(2026, 10, 28, 17, 30))

    def test_week_end_renvoie_le_vendredi(self):
        self.assertEqual(eu.derniere_cloture_xetra(berlin(2026, 10, 17, 18, 5)), berlin(2026, 10, 16, 17, 30))  # samedi
        self.assertEqual(eu.derniere_cloture_xetra(berlin(2026, 10, 18, 12, 0)), berlin(2026, 10, 16, 17, 30))  # dimanche
        self.assertEqual(eu.derniere_cloture_xetra(berlin(2026, 10, 19, 9, 0)), berlin(2026, 10, 16, 17, 30))   # lundi matin

    def test_accepte_un_instant_utc(self):
        now_utc = datetime(2026, 10, 15, 16, 5, tzinfo=timezone.utc)
        self.assertEqual(eu.derniere_cloture_xetra(now_utc), berlin(2026, 10, 15, 17, 30))


class TestCycleDejaFait(unittest.TestCase):
    NOW = berlin(2026, 10, 15, 23, 22)   # cron GitHub de 18h UTC parti en retard

    def setUp(self):
        os.environ.pop("FORCER_CYCLE", None)

    def test_premier_cycle_ou_horodatage_illisible(self):
        self.assertFalse(eu.cycle_deja_fait({}, self.NOW))
        self.assertFalse(eu.cycle_deja_fait({"last_run_at": "n'importe quoi"}, self.NOW))
        self.assertFalse(eu.cycle_deja_fait({"last_run_at": None}, self.NOW))
        self.assertFalse(eu.cycle_deja_fait({"last_run_at": "2026-10-15T16:05:00"}, self.NOW))  # naif

    def test_second_passage_du_jour_ignore(self):
        meta = {"last_run_at": berlin(2026, 10, 15, 18, 5).isoformat()}
        self.assertTrue(eu.cycle_deja_fait(meta, self.NOW))

    def test_passage_de_la_veille_ne_bloque_pas(self):
        meta = {"last_run_at": berlin(2026, 10, 14, 23, 22).isoformat()}
        self.assertFalse(eu.cycle_deja_fait(meta, berlin(2026, 10, 15, 18, 5)))

    def test_hiver_le_passage_avant_cloture_est_ignore_puis_le_soir_passe(self):
        # 29/10 (heure d'hiver) : 17:05 Berlin est AVANT la cloture ; la veille au soir a deja evalue la veille
        meta = {"last_run_at": berlin(2026, 10, 28, 23, 22).isoformat()}
        self.assertTrue(eu.cycle_deja_fait(meta, berlin(2026, 10, 29, 17, 5)))
        self.assertFalse(eu.cycle_deja_fait(meta, berlin(2026, 10, 29, 22, 0)))

    def test_week_end_ignore_apres_le_passage_du_vendredi(self):
        meta = {"last_run_at": berlin(2026, 10, 16, 18, 5).isoformat()}
        self.assertTrue(eu.cycle_deja_fait(meta, berlin(2026, 10, 17, 18, 5)))
        self.assertTrue(eu.cycle_deja_fait(meta, berlin(2026, 10, 18, 18, 5)))
        self.assertFalse(eu.cycle_deja_fait(meta, berlin(2026, 10, 19, 18, 5)))   # lundi apres cloture

    def test_forcer_cycle(self):
        meta = {"last_run_at": berlin(2026, 10, 15, 18, 5).isoformat()}
        for v in ("1", "true", "oui"):
            with patch.dict(os.environ, {"FORCER_CYCLE": v}):
                self.assertFalse(eu.cycle_deja_fait(meta, self.NOW), v)
        for v in ("", "0", "false"):
            with patch.dict(os.environ, {"FORCER_CYCLE": v}):
                self.assertTrue(eu.cycle_deja_fait(meta, self.NOW), repr(v))


class TestDansMain(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.state_file = Path(self.tmp.name) / "eu_state.json"
        self.evaluate = MagicMock(return_value={
            "symbol": "VVSM.XETRA", "display": "VanEck", "combined": "neutral", "level": None,
            "price": 10.0, "rsi": 50, "macd_score": 50, "home_score": 50})
        self.send = MagicMock()
        for p in (patch.object(eu, "STATE_FILE", self.state_file),
                  patch.object(eu, "SUPABASE_URL", ""),
                  patch.object(eu, "SUPABASE_SERVICE_ROLE_KEY", ""),
                  patch.object(eu, "EU_WATCHLIST", [{"symbol": "VVSM.XETRA", "display": "VanEck"}]),
                  patch.object(eu, "evaluate_symbol", self.evaluate),
                  patch.object(eu, "send_telegram", self.send),
                  patch.dict(os.environ, {"FORCER_CYCLE": ""})):
            p.start()
            self.addCleanup(p.stop)

    def meta(self):
        return json.loads(self.state_file.read_text(encoding="utf-8")).get("_meta", {})

    def test_premier_cycle_evalue_et_horodate(self):
        eu.main()
        self.evaluate.assert_called_once()
        self.assertIn("last_run_at", self.meta())

    def test_second_cycle_apres_la_meme_cloture_n_appelle_pas_eodhd(self):
        eu.main()
        self.evaluate.reset_mock()
        eu.main()
        self.evaluate.assert_not_called()

    def test_cycle_entierement_en_echec_n_est_pas_horodate(self):
        self.evaluate.return_value = None
        eu.main()
        self.assertNotIn("last_run_at", self.meta())
        self.evaluate.reset_mock()
        eu.main()                                   # retente : pas bloque par le garde-fou
        self.evaluate.assert_called_once()

    def test_forcer_cycle_passe_outre(self):
        eu.main()
        self.evaluate.reset_mock()
        with patch.dict(os.environ, {"FORCER_CYCLE": "1"}):
            eu.main()
        self.evaluate.assert_called_once()


if __name__ == "__main__":
    unittest.main()
