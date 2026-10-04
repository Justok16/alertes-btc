"""
Actifs non couverts par Alpaca (Europe, Chine continentale...) suivis via
EODHD (necessite EODHD_API_TOKEN). Verifies une fois par jour seulement --
le tier gratuit EODHD est limite a 20 appels API/jour, donc ce fichier est
volontairement tenu court (11 symboles = 11 appels/jour).

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
    # Ajoutes le 03/10/2026 depuis la liste Trade Republic de l'utilisateur ;
    # codes valides avec eodhd_probe.py (cours en EUR, coherents avec l'app).
    # .F = Bourse de Francfort : BY6/4BY/LGI n'existent pas sous .XETRA chez
    # EODHD (404 ou reponse vide), seul AIFS y est disponible.
    {"symbol": "BY6.F", "display": "BYD Company (BY6)"},
    {"symbol": "4BY.F", "display": "BYD Electronic (4BY)"},
    {"symbol": "AIFS.XETRA", "display": "iShares AI Infrastructure UCITS ETF (AIFS)"},
    {"symbol": "LGI.F", "display": "Legal & General Group (LGI)"},
    # Ajoute le 04/10/2026 (ISIN IE00BGV5VN51, cote Xetra en EUR). Code
    # XAIX.XETRA pas encore verifie avec eodhd_probe.py (pas de token dans la
    # session d'ajout) : a lancer pour confirmer le cours.
    {"symbol": "XAIX.XETRA", "display": "Xtrackers Artificial Intelligence & Big Data UCITS ETF 1C (XAIX)"},
]
