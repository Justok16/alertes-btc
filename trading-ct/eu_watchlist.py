"""
Actifs non couverts par Alpaca (Europe, Chine continentale...) suivis via
EODHD (necessite EODHD_API_TOKEN). Verifies une fois par jour seulement --
le tier gratuit EODHD est limite a 20 appels API/jour, donc ce fichier est
volontairement tenu court (6 symboles = 6 appels/jour).

Format des symboles : <TICKER>.<EXCHANGE_CODE> tel qu'attendu par l'API
EODHD, verifie via /api/search/<query> avant tout ajout -- le code de
bourse EODHD ne correspond pas toujours a celui attendu (ex. HNSC n'existe
que sous HNSC.LSE, pas sous un code Xetra ; les A-shares chinoises sont
sous .SHE/.SHG, pas .SZ/.SS). La bourse de Hong Kong (HKEX) ne semble pas
couverte par le plan gratuit -- les equivalents chinois demandes par
l'utilisateur ont ete remplaces par des ETF cotes aux US (SMHC, KTEC dans
watchlist.py, via Alpaca) quand un equivalent existait.
"""

EU_WATCHLIST = [
    {"symbol": "VVSM.XETRA", "display": "VanEck Semiconductor UCITS ETF"},
    {"symbol": "NUKL.XETRA", "display": "VanEck Uranium & Nuclear Technologies UCITS ETF"},
    {"symbol": "SEC0.XETRA", "display": "iShares MSCI Global Semiconductors UCITS ETF"},
    {"symbol": "HNSC.LSE", "display": "HSBC Nasdaq Global Semiconductor UCITS ETF"},
    {"symbol": "159995.SHE", "display": "ChinaAMC CSI Semiconductor Chip ETF"},
    {"symbol": "512480.SHG", "display": "CPIC CSI Fully Semiconductor ETF"},
]
