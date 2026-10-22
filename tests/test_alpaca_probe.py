"""Sonde Alpaca (alpaca_probe.py) : verifie l'historique recu sans etat ni
Telegram. Aucun reseau : fetch_alpaca_closes est remplace."""

import io
import sys
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).parent.parent / "trading-ct"))

import alpaca_probe  # noqa: E402
import trading_alert  # noqa: E402
from watchlist import WATCHLIST  # noqa: E402


def _closes(n):
    # Serie non monotone : evite hi == lo (score None) dans le stochastique/MACD.
    return [100 + (i % 7) - (i % 3) * 0.5 + i * 0.01 for i in range(n)]


CLES = {"ALPACA_API_KEY_ID": "k", "ALPACA_API_SECRET_KEY": "s"}


class TestSonde(unittest.TestCase):
    def _run(self, closes_par_symbole, argv):
        out = io.StringIO()
        with patch.multiple(alpaca_probe, **CLES), \
             patch.object(alpaca_probe, "fetch_alpaca_closes",
                          side_effect=lambda s, sym: closes_par_symbole.get(sym)) as fetch, \
             redirect_stdout(out):
            code = alpaca_probe.main(argv, session=MagicMock())
        return code, out.getvalue(), fetch

    def test_sans_cles_sortie_1_sans_reseau(self):
        session = MagicMock()
        with patch.multiple(alpaca_probe, ALPACA_API_KEY_ID=None, ALPACA_API_SECRET_KEY=None), \
             patch.object(alpaca_probe, "fetch_alpaca_closes") as fetch, redirect_stdout(io.StringIO()):
            self.assertEqual(alpaca_probe.main(["SPY"], session=session), 1)
        fetch.assert_not_called()

    def test_historique_suffisant_les_3_indicateurs_sont_calcules(self):
        code, out, _ = self._run({"SPY": _closes(100)}, ["SPY"])
        self.assertEqual(code, 0)
        ligne = next(l for l in out.splitlines() if l.startswith("SPY"))
        self.assertIn("OK", ligne)
        self.assertNotIn("--", ligne)          # aucun indicateur manquant
        self.assertIn("100", ligne)            # nombre de bougies affiche

    def test_bougies_du_jour_seulement_macd_absent_sortie_1(self):
        # Reproduit le bug d'avant ALPACA_HISTORY_DAYS : ~20 bougies du jour,
        # RSI calculable mais pas le MACD -> la sonde doit le signaler.
        code, out, _ = self._run({"SPY": _closes(20)}, ["SPY"])
        self.assertEqual(code, 1)
        ligne = next(l for l in out.splitlines() if l.startswith("SPY"))
        self.assertIn("KO", ligne)
        self.assertIn("--", ligne)

    def test_symbole_sans_donnees_est_ko(self):
        code, out, _ = self._run({}, ["XXXX"])
        self.assertEqual(code, 1)
        self.assertIn("XXXX     KO", out)

    def test_sans_argument_toute_la_watchlist_us_est_sondee(self):
        us = [i["symbol"] for i in WATCHLIST if i["asset_class"] != "crypto"]
        code, _, fetch = self._run({s: _closes(100) for s in us}, [])
        self.assertEqual(code, 0)
        self.assertEqual([c.args[1] for c in fetch.call_args_list], us)
        self.assertNotIn("BTCUSDT", [c.args[1] for c in fetch.call_args_list])

    def test_utilise_la_vraie_fonction_du_bot(self):
        # La sonde doit tester fetch_alpaca_closes de trading_alert, pas une copie.
        self.assertIs(alpaca_probe.fetch_alpaca_closes, trading_alert.fetch_alpaca_closes)


if __name__ == "__main__":
    unittest.main()
