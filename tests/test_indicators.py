"""Indicateurs du bot (RSI, EMA, MACD, score maison) et recuperation des cours :
le coeur des signaux d'alerte, jusqu'ici sans test. Valeurs calculees a la main
sur des series simples ; aucun reseau (sessions et API mockees)."""

import sys
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).parent.parent / "trading-ct"))

import trading_alert as ta  # noqa: E402

NY = ZoneInfo("America/New_York")


def serie(depart, deltas):
    closes = [depart]
    for d in deltas:
        closes.append(closes[-1] + d)
    return closes


class TestRsi(unittest.TestCase):
    def test_historique_trop_court(self):
        self.assertIsNone(ta.compute_rsi([100] * 14))           # il faut period + 1 cours

    def test_que_des_hausses_vaut_100(self):
        self.assertEqual(ta.compute_rsi(serie(100, [1] * 14)), 100.0)

    def test_que_des_baisses_vaut_0(self):
        self.assertEqual(ta.compute_rsi(serie(100, [-1] * 14)), 0.0)

    def test_valeur_connue(self):
        # 7 hausses de 2 et 7 baisses de 1 : gain moyen 1, perte moyenne 0.5, RS = 2
        self.assertEqual(ta.compute_rsi(serie(100, [2, -1] * 7)), 66.7)

    def test_ne_regarde_que_les_14_derniers_ecarts(self):
        ancien_krach = serie(100, [-50] + [2, -1] * 7)
        self.assertEqual(ta.compute_rsi(ancien_krach), 66.7)


class TestEma(unittest.TestCase):
    def test_trop_court(self):
        self.assertEqual(ta.ema_series([1, 2], 3), [])

    def test_valeurs_connues(self):
        # seed = moyenne(1,2,3) = 2 ; multiplicateur 2/(3+1) = 0.5
        self.assertEqual(ta.ema_series([1, 2, 3, 4, 5], 3), [2.0, 3.0, 4.0])


class TestMacd(unittest.TestCase):
    def test_longueur_minimale(self):
        # EMA26 a besoin de 26 cours, la ligne de signal de 9 points MACD : 34 cours
        self.assertIsNone(ta.compute_macd_histogram([100.0] * 33))
        self.assertEqual(len(ta.compute_macd_histogram([100.0] * 34)), 1)
        self.assertEqual(len(ta.compute_macd_histogram([100.0] * 60)), 27)

    def test_cours_constants_histogramme_nul(self):
        self.assertTrue(all(v == 0 for v in ta.compute_macd_histogram([100.0] * 60)))

    def test_score_none_si_histogramme_plat_ou_trop_court(self):
        self.assertIsNone(ta.macd_score([100.0] * 60))           # hi == lo
        self.assertIsNone(ta.macd_score([100.0] * 45 + [110.0]))  # histogramme de 13 points < 14

    def test_score_100_sur_une_hausse_brutale_et_0_sur_une_baisse(self):
        self.assertEqual(ta.macd_score([100.0] * 59 + [110.0]), 100.0)
        self.assertEqual(ta.macd_score([100.0] * 59 + [90.0]), 0.0)


class TestScoreMaison(unittest.TestCase):
    def test_stochastique(self):
        self.assertIsNone(ta.stochastic_score([1] * 13))
        self.assertIsNone(ta.stochastic_score([5] * 14))           # range nul
        self.assertEqual(ta.stochastic_score([0, 10] + [5] * 12), 50.0)
        self.assertEqual(ta.stochastic_score(list(range(14))), 100.0)

    def test_home_score_extremes(self):
        self.assertEqual(ta.home_score(serie(100, [1] * 20)), 100.0)
        self.assertEqual(ta.home_score(serie(100, [-1] * 20)), 0.0)

    def test_home_score_none_si_cours_plats(self):
        self.assertIsNone(ta.home_score([100.0] * 20))             # stochastique indefini


def _reponse(payload):
    r = MagicMock()
    r.json.return_value = payload
    return r


class TestRecuperationDesCours(unittest.TestCase):
    def test_binance_lit_le_cours_de_cloture(self):
        bougies = [[0, "1", "2", "0.5", "101.5", "9"], [0, "1", "2", "0.5", "102", "9"]]
        with patch.object(ta, "get_with_retry", return_value=_reponse(bougies)) as get:
            self.assertEqual(ta.fetch_binance_closes(MagicMock(), "BTCUSDT"), [101.5, 102.0])
        self.assertEqual(get.call_args.kwargs["params"]["symbol"], "BTCUSDT")

    def test_binance_erreur_renvoie_none(self):
        with patch.object(ta, "get_with_retry", side_effect=RuntimeError("down")):
            self.assertIsNone(ta.fetch_binance_closes(MagicMock(), "BTCUSDT"))

    def test_alpaca_sans_cles_ignore_l_actif(self):
        with patch.object(ta, "ALPACA_API_KEY_ID", None), patch.object(ta, "get_with_retry") as get:
            self.assertIsNone(ta.fetch_alpaca_closes(MagicMock(), "SPY"))
        get.assert_not_called()

    def test_alpaca_cours_ajustes_des_splits(self):
        with patch.object(ta, "ALPACA_API_KEY_ID", "k"), patch.object(ta, "ALPACA_API_SECRET_KEY", "s"), \
                patch.object(ta, "get_with_retry", return_value=_reponse({"bars": [{"c": 10}, {"c": 11.5}]})) as get:
            self.assertEqual(ta.fetch_alpaca_closes(MagicMock(), "SPY"), [10.0, 11.5])
        self.assertEqual(get.call_args.kwargs["params"]["adjustment"], "split")
        self.assertEqual(get.call_args.kwargs["headers"]["APCA-API-KEY-ID"], "k")

    def test_alpaca_sans_bougie_ou_en_erreur(self):
        with patch.object(ta, "ALPACA_API_KEY_ID", "k"), patch.object(ta, "ALPACA_API_SECRET_KEY", "s"):
            with patch.object(ta, "get_with_retry", return_value=_reponse({"bars": []})):
                self.assertIsNone(ta.fetch_alpaca_closes(MagicMock(), "SPY"))
            with patch.object(ta, "get_with_retry", side_effect=RuntimeError("429")):
                self.assertIsNone(ta.fetch_alpaca_closes(MagicMock(), "SPY"))

    def test_fear_and_greed_crypto(self):
        with patch.object(ta, "get_with_retry", return_value=_reponse({"data": [{"value": "23"}]})):
            self.assertEqual(ta.fetch_crypto_fng(MagicMock()), 23)
        with patch.object(ta, "get_with_retry", side_effect=RuntimeError("down")):
            self.assertIsNone(ta.fetch_crypto_fng(MagicMock()))


class TestHorairesMarcheUs(unittest.TestCase):
    def ouvert_a(self, *args):
        with patch.object(ta, "datetime") as dt:
            dt.now.return_value = datetime(*args, tzinfo=NY)
            return ta.is_us_market_open()

    def test_bornes(self):
        self.assertFalse(self.ouvert_a(2026, 10, 5, 9, 29))   # lundi, avant l'ouverture
        self.assertTrue(self.ouvert_a(2026, 10, 5, 9, 30))
        self.assertTrue(self.ouvert_a(2026, 10, 5, 16, 0))
        self.assertFalse(self.ouvert_a(2026, 10, 5, 16, 1))

    def test_week_end_ferme(self):
        self.assertFalse(self.ouvert_a(2026, 10, 3, 12, 0))   # samedi
        self.assertFalse(self.ouvert_a(2026, 10, 4, 12, 0))   # dimanche


if __name__ == "__main__":
    unittest.main()
