"""Strategie long terme (defaut depuis le 23/10/2026) : bougies journalieres,
alertes d'achat formulees en opportunite ou en rappel de versement (lignes
detenues), aucun signal de vente ni suivi objectif / stop. Aucun reseau."""

import json
import os
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "trading-ct"))

import btc_alert as ba  # noqa: E402
import trading_alert  # noqa: E402
import trading_alert_eu  # noqa: E402
from eu_watchlist import EU_WATCHLIST  # noqa: E402
from watchlist import WATCHLIST  # noqa: E402


def _res(combined, level, price, symbol):
    return {"symbol": symbol, "display": symbol, "combined": combined, "level": level, "price": price,
            "rsi": 10, "macd_score": 10, "fng": 10, "home_score": 10}


class TestReglageParDefaut(unittest.TestCase):
    def test_long_terme_actif_par_defaut_et_reversible(self):
        self.assertTrue(trading_alert.MODE_LONG_TERME)
        self.assertTrue(ba.LONG_TERME)
        # MODE_STRATEGIE=court_terme : retour a l'ancien comportement (lu a l'import)
        with patch.dict(os.environ, {"MODE_STRATEGIE": "court_terme"}):
            mode = os.environ.get("MODE_STRATEGIE", "long_terme").strip().lower() != "court_terme"
        self.assertFalse(mode)

    def test_lignes_detenues(self):
        detenus = {i["symbol"] for i in WATCHLIST + EU_WATCHLIST if i.get("detenu")}
        self.assertEqual(detenus, {"BTCUSDT", "SEC0.XETRA", "VVSM.XETRA"})


class TestMessages(unittest.TestCase):
    def test_ligne_detenue_rappel_de_versement(self):
        msg = trading_alert.build_message(_res("buy", "moderate", 1, "BTCUSDT"), long_terme=True, detenu=True)
        self.assertIn("RAPPEL DE VERSEMENT — BAISSE MARQUÉE", msg)
        self.assertIn("tu détiens déjà", msg)
        self.assertNotIn("SIGNAL D'ACHAT", msg)

    def test_ligne_non_detenue_opportunite(self):
        msg = trading_alert_eu.build_message(_res("buy", "strong", 1, "NUKL.XETRA"), long_terme=True)
        self.assertIn("OPPORTUNITÉ LONG TERME — BAISSE FORTE", msg)
        self.assertIn("plusieurs années", msg)
        up = trading_alert.build_message(_res("buy", "strong", 1, "SPY"), upgrade=True, long_terme=True)
        self.assertIn("BAISSE RENFORCÉE", up)

    def test_mode_court_terme_inchange(self):
        msg = trading_alert.build_message(_res("buy", "strong", 1, "SPY"))
        self.assertIn("SIGNAL D'ACHAT FORT", msg)
        self.assertNotIn("📌", msg)

    def test_btc_alert(self):
        self.assertIn("RAPPEL DE VERSEMENT", ba.build_message("buy", 10, 12, None, long_terme=True))
        self.assertIn("SIGNAL D'ACHAT", ba.build_message("buy", 10, 12, None))


class TestBougiesJournalieres(unittest.TestCase):
    def _reponse(self, payload):
        r = MagicMock()
        r.json.return_value = payload
        return r

    def test_alpaca_journalier_sur_200_jours(self):
        with patch.object(trading_alert, "ALPACA_API_KEY_ID", "k"), \
                patch.object(trading_alert, "ALPACA_API_SECRET_KEY", "s"), \
                patch.object(trading_alert, "MODE_LONG_TERME", True), \
                patch.object(trading_alert, "get_with_retry", return_value=self._reponse({"bars": [{"c": 1}]})) as get:
            trading_alert.fetch_alpaca_closes(MagicMock(), "SPY")
        params = get.call_args.kwargs["params"]
        self.assertEqual(params["timeframe"], "1Day")
        debut = datetime.strptime(params["start"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
        jours = (datetime.now(timezone.utc) - debut).days
        self.assertAlmostEqual(jours, trading_alert.ALPACA_HISTORY_DAYS_DAILY, delta=1)
        # 100 bougies journalieres exigent ~145 jours calendaires (week-ends + feries)
        self.assertGreaterEqual(trading_alert.ALPACA_HISTORY_DAYS_DAILY, 150)

    def test_binance_journalier(self):
        with patch.object(trading_alert, "MODE_LONG_TERME", True), \
                patch.object(trading_alert, "get_with_retry", return_value=self._reponse([[0, 0, 0, 0, "5"]])) as get:
            self.assertEqual(trading_alert.fetch_binance_closes(MagicMock(), "BTCUSDT"), [5.0])
        self.assertEqual(get.call_args.kwargs["params"]["interval"], "1d")
        with patch.object(trading_alert, "MODE_LONG_TERME", False), \
                patch.object(trading_alert, "get_with_retry", return_value=self._reponse([])) as get:
            trading_alert.fetch_binance_closes(MagicMock(), "BTCUSDT")
        self.assertEqual(get.call_args.kwargs["params"]["interval"], "15m")


class _Boucle(unittest.TestCase):
    module = None
    item = None

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.state_file = Path(self.tmp.name) / "state.json"
        self.send = MagicMock()
        patches = [
            patch.object(trading_alert, "MODE_LONG_TERME", True),
            patch.object(self.module, "STATE_FILE", self.state_file),
            patch.object(self.module, "SUPABASE_URL", ""),
            patch.object(self.module, "SUPABASE_SERVICE_ROLE_KEY", ""),
            patch.object(self.module, "send_telegram", self.send),
        ]
        if self.module is trading_alert:
            patches += [patch.object(trading_alert, "WATCHLIST", [self.item]),
                        patch.object(trading_alert, "fetch_crypto_fng", return_value=50)]
        else:
            patches += [patch.object(trading_alert_eu, "EU_WATCHLIST", [self.item]),
                        patch.dict(os.environ, {"FORCER_CYCLE": "1"})]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

    def cycle(self, combined, level, price):
        res = _res(combined, level, price, self.item["symbol"])
        with patch.object(self.module, "evaluate_symbol", return_value=res):
            self.module.main()

    def messages(self):
        return [c.args[1] for c in self.send.call_args_list]

    def etat(self):
        return json.loads(self.state_file.read_text(encoding="utf-8"))[self.item["symbol"]]

    def scenario(self, attendu):
        self.cycle("buy", "moderate", 100.0)
        self.assertEqual(len(self.messages()), 1)
        self.assertIn(attendu, self.messages()[0])
        self.assertNotIn("entry", self.etat())             # aucun suivi objectif / stop ouvert

        self.cycle("neutral", None, 90.0)                  # -10 % : pas de « stop » en long terme
        self.cycle("neutral", None, 120.0)                 # +20 % : pas d'« objectif »
        self.cycle("sell", None, 130.0)                    # zone de vente : aucun message
        self.assertEqual(len(self.messages()), 1)
        self.assertEqual(self.etat()["combined_state"], "sell")   # l'etat suit quand meme

        self.cycle("sell", None, 131.0)                    # vente persistante : toujours rien
        self.cycle("buy", "strong", 95.0)                  # nouvelle baisse : nouveau rappel
        self.assertEqual(len(self.messages()), 2)
        self.assertIn("BAISSE FORTE", self.messages()[1])


class TestBoucleCrypto(_Boucle):
    module = trading_alert
    item = {"symbol": "BTCUSDT", "display": "Bitcoin", "asset_class": "crypto", "detenu": True}

    def test_rappels_sans_vente_ni_sortie(self):
        self.scenario("RAPPEL DE VERSEMENT")


class TestBoucleEurope(_Boucle):
    module = trading_alert_eu
    item = {"symbol": "NUKL.XETRA", "display": "VanEck Uranium"}

    def test_opportunites_sans_vente_ni_sortie(self):
        self.scenario("OPPORTUNITÉ LONG TERME")


class TestBtcAlertLongTerme(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.send = MagicMock()
        self.zone = {"v": "neutral"}
        z = lambda s: (50, self.zone["v"])  # noqa: E731
        for p in (patch.object(ba, "LONG_TERME", True),
                  patch.object(ba, "STATE_FILE", Path(self.tmp.name) / "s.json"),
                  patch.object(ba, "SUPABASE_URL", ""), patch.object(ba, "SUPABASE_SERVICE_ROLE_KEY", ""),
                  patch.object(ba, "send_telegram", self.send),
                  patch.object(ba, "fetch_alternative_fng", z), patch.object(ba, "fetch_coingecko_signal", z),
                  patch.object(ba, "fetch_cmc_fng", z)):
            p.start()
            self.addCleanup(p.stop)

    def test_avidite_extreme_silencieuse_peur_extreme_rappel(self):
        self.zone["v"] = "sell"
        ba.main()
        self.send.assert_not_called()
        self.zone["v"] = "buy"
        ba.main()
        self.assertEqual(self.send.call_count, 1)
        self.assertIn("RAPPEL DE VERSEMENT", self.send.call_args.args[1])


if __name__ == "__main__":
    unittest.main()
