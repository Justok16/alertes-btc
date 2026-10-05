"""
Liste des actifs surveilles par le bot trading-ct.

Modifie librement cette liste pour ajouter/retirer des actifs. Ce ne sont
QUE des exemples d'actifs tres liquides, PAS une recommandation
d'investissement.

asset_class:
  - "crypto" : symbole au format Binance (ex. BTCUSDT), donnees via
    data-api.binance.vision, pas de cle requise.
  - "stock" ou "etf" : symbole boursier US (ex. AAPL, SPY), donnees via
    Alpaca Data API (necessite ALPACA_API_KEY_ID / ALPACA_API_SECRET_KEY).
"""

WATCHLIST = [
    {"symbol": "BTCUSDT", "display": "Bitcoin", "asset_class": "crypto"},
    {"symbol": "ETHUSDT", "display": "Ethereum", "asset_class": "crypto"},
    {"symbol": "SPY", "display": "S&P 500 ETF", "asset_class": "etf"},
    {"symbol": "QQQ", "display": "Nasdaq 100 ETF", "asset_class": "etf"},
    {"symbol": "SMH", "display": "VanEck Semiconductor ETF", "asset_class": "etf"},
    {"symbol": "SOXX", "display": "iShares Semiconductor ETF", "asset_class": "etf"},
    {"symbol": "XSD", "display": "SPDR S&P Semiconductor ETF (equal-weight)", "asset_class": "etf"},
    {"symbol": "SOXQ", "display": "Invesco PHLX Semiconductor ETF", "asset_class": "etf"},
    {"symbol": "PSI", "display": "Invesco Dynamic Semiconductors ETF", "asset_class": "etf"},
    {"symbol": "SMHC", "display": "VanEck China Semiconductor ETF", "asset_class": "etf"},
    {"symbol": "KTEC", "display": "KraneShares Hang Seng TECH Index ETF", "asset_class": "etf"},
    # Codes allemands de la liste Trade Republic -> ticker US (meme societe) :
    # 4LT1 = Northern Oil & Gas (NYSE: NOG), HUT = Hut 8 (Nasdaq: HUT).
    {"symbol": "NOG", "display": "Northern Oil & Gas (4LT1)", "asset_class": "stock"},
    # HUT : tres volatil (mineur de bitcoin / infrastructure IA) -- la regle
    # par defaut des actions (+6 %/-4 %) serait declenchee par le simple bruit
    # du cours. Niveaux plus larges, de bon sens et NON testes (a ajuster).
    {"symbol": "HUT", "display": "Hut 8 (HUT)", "asset_class": "stock", "exit_rule": (12, 8)},
    # Ajoutees le 05/10/2026 depuis un reel Instagram (Kelvin Bonneau, 30/09/2026) :
    # 7 actions pour jouer les couches de l'IA (refroidissement, compute, energie).
    # Regle de sortie par defaut des actions (+6 % / -4 %), NON testee.
    {"symbol": "SCCO", "display": "Southern Copper (SCCO)", "asset_class": "stock"},
    {"symbol": "MOD", "display": "Modine Manufacturing (MOD)", "asset_class": "stock"},
    {"symbol": "GEV", "display": "GE Vernova (GEV)", "asset_class": "stock"},
    {"symbol": "LITE", "display": "Lumentum (LITE)", "asset_class": "stock"},
    {"symbol": "VRT", "display": "Vertiv (VRT)", "asset_class": "stock"},
    {"symbol": "AMZN", "display": "Amazon (AMZN)", "asset_class": "stock"},
    {"symbol": "MRVL", "display": "Marvell Technology (MRVL)", "asset_class": "stock"},
]
