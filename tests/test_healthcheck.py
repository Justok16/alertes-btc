"""Signal de vie vers un service externe (healthchecks.io) : desactive sans URL,
jamais bloquant, appele a chaque cycle (aucun reseau)."""

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).parent.parent / "trading-ct"))

import trading_alert  # noqa: E402

URL = "https://hc-ping.com/abc-123"


class TestPing(unittest.TestCase):
    def test_desactive_sans_url(self):
        session = MagicMock()
        with patch.object(trading_alert, "HEALTHCHECK_URL", ""):
            self.assertFalse(trading_alert.ping_healthcheck(session))
        session.get.assert_not_called()

    def test_ping_avec_url_et_timeout_court(self):
        session = MagicMock()
        with patch.object(trading_alert, "HEALTHCHECK_URL", URL):
            self.assertTrue(trading_alert.ping_healthcheck(session))
        session.get.assert_called_once_with(URL, timeout=trading_alert.HEALTHCHECK_TIMEOUT)
        self.assertLessEqual(trading_alert.HEALTHCHECK_TIMEOUT, 10)

    def test_erreur_reseau_n_est_pas_bloquante(self):
        session = MagicMock()
        session.get.side_effect = RuntimeError("timeout")
        with patch.object(trading_alert, "HEALTHCHECK_URL", URL):
            self.assertFalse(trading_alert.ping_healthcheck(session))   # ne leve pas

    def test_reponse_http_en_erreur_n_est_pas_bloquante(self):
        session = MagicMock()
        session.get.return_value.raise_for_status.side_effect = RuntimeError("502")
        with patch.object(trading_alert, "HEALTHCHECK_URL", URL):
            self.assertFalse(trading_alert.ping_healthcheck(session))


class TestPingDansMain(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.state_file = Path(self.tmp.name) / "state.json"
        self.ping = MagicMock()
        item = {"symbol": "BTCUSDT", "display": "Bitcoin", "asset_class": "crypto"}
        neutre = {"symbol": "BTCUSDT", "display": "Bitcoin", "combined": "neutral", "price": 100.0,
                  "rsi": 50, "macd_score": 50, "fng": 50}
        for p in (patch.object(trading_alert, "STATE_FILE", self.state_file),
                  patch.object(trading_alert, "SUPABASE_URL", ""),
                  patch.object(trading_alert, "SUPABASE_SERVICE_ROLE_KEY", ""),
                  patch.object(trading_alert, "WATCHLIST", [item]),
                  patch.object(trading_alert, "fetch_crypto_fng", return_value=50),
                  patch.object(trading_alert, "evaluate_symbol", return_value=neutre),
                  patch.object(trading_alert, "send_telegram", MagicMock()),
                  patch.object(trading_alert, "ping_healthcheck", self.ping)):
            p.start()
            self.addCleanup(p.stop)

    def test_un_ping_par_cycle_apres_l_ecriture_de_l_etat(self):
        trading_alert.main()
        self.ping.assert_called_once()
        self.assertTrue(self.state_file.exists())          # etat ecrit avant le ping
        json.loads(self.state_file.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
