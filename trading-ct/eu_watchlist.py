"""
ETF europeens (Xetra/Deutsche Boerse) suivis via EODHD (necessite
EODHD_API_TOKEN). Verifies une fois par jour seulement -- le tier gratuit
EODHD est limite a 20 appels API/jour, donc ce fichier est volontairement
tenu court (4 symboles = 4 appels/jour).

Format des symboles : <TICKER>.<EXCHANGE_CODE> tel qu'attendu par l'API
EODHD (ex. VVSM.XETRA, HNSC.DE) -- verifie manuellement par l'utilisateur.
"""

EU_WATCHLIST = [
    {"symbol": "VVSM.XETRA", "display": "VanEck Semiconductor UCITS ETF"},
    {"symbol": "NUKL.XETRA", "display": "VanEck Uranium & Nuclear Technologies UCITS ETF"},
    {"symbol": "SEC0.XETRA", "display": "iShares MSCI Global Semiconductors UCITS ETF"},
    {"symbol": "HNSC.DE", "display": "HSBC Nasdaq Global Semiconductor UCITS ETF"},
]
