"""Garde-fous sur les watchlists : une erreur d'ajout (doublon, format de code
EODHD faux, quota depasse) doit faire echouer la CI plutot que degrader le bot
en silence en production (aucun reseau)."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "trading-ct"))

import eu_watchlist  # noqa: E402
import watchlist  # noqa: E402

# Le tier gratuit EODHD autorise 20 appels API par jour ; le bot Europe en
# consomme un par ETF et par execution quotidienne (cf. eu_watchlist.py).
EODHD_QUOTA_PAR_JOUR = 20
ASSET_CLASSES = {"crypto", "stock", "etf"}


class TestEuWatchlist(unittest.TestCase):
    def test_respecte_le_quota_eodhd(self):
        n = len(eu_watchlist.EU_WATCHLIST)
        self.assertLessEqual(
            n, EODHD_QUOTA_PAR_JOUR,
            f"{n} ETF = {n} appels EODHD/jour : au-dessus du quota gratuit ({EODHD_QUOTA_PAR_JOUR}).")

    def test_symboles_uniques(self):
        symboles = [i["symbol"] for i in eu_watchlist.EU_WATCHLIST]
        self.assertEqual(len(symboles), len(set(symboles)), "symbole EU en double")

    def test_format_des_codes_eodhd(self):
        # <TICKER>.<BOURSE>, ex. XAIX.XETRA, HNSC.LSE, 159995.SHE, BY6.F
        for item in eu_watchlist.EU_WATCHLIST:
            self.assertRegex(item["symbol"], r"^[A-Z0-9]+\.[A-Z]+$", item)
            self.assertTrue(item.get("display"), f"display manquant : {item}")


class TestWatchlistUs(unittest.TestCase):
    def test_symboles_uniques(self):
        symboles = [i["symbol"] for i in watchlist.WATCHLIST]
        self.assertEqual(len(symboles), len(set(symboles)), "symbole US/crypto en double")

    def test_champs_obligatoires(self):
        for item in watchlist.WATCHLIST:
            self.assertTrue(item.get("symbol"), item)
            self.assertTrue(item.get("display"), item)
            self.assertIn(item.get("asset_class"), ASSET_CLASSES, item)

    def test_symboles_alpaca_et_binance(self):
        for item in watchlist.WATCHLIST:
            if item["asset_class"] == "crypto":
                self.assertRegex(item["symbol"], r"^[A-Z0-9]+USDT$", item)   # format Binance
            else:
                self.assertRegex(item["symbol"], r"^[A-Z]{1,5}$", item)      # ticker US (Alpaca)

    def test_regles_de_sortie_personnalisees_coherentes(self):
        for item in watchlist.WATCHLIST:
            rule = item.get("exit_rule")
            if rule:
                target, stop = rule
                self.assertGreater(target, 0, item)
                self.assertGreater(stop, 0, item)


class TestPasDeSymboleCommun(unittest.TestCase):
    def test_un_actif_n_est_pas_suivi_par_les_deux_bots(self):
        us = {i["symbol"] for i in watchlist.WATCHLIST}
        eu = {i["symbol"].split(".")[0] for i in eu_watchlist.EU_WATCHLIST}
        self.assertFalse(us & eu, f"suivis deux fois : {us & eu}")


if __name__ == "__main__":
    unittest.main()
