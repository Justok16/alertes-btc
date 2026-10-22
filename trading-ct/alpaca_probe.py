"""
Verifie que les actions/ETF US de watchlist.py recoivent bien un historique
Alpaca suffisant pour calculer les 3 indicateurs (RSI, MACD score, score
maison), SANS toucher a l'etat ni envoyer de Telegram. Utile hors seance :
le bot ignore volontairement les actions quand le marche US est ferme, donc
un lancement manuel de trading_alert.py le soir ne prouve rien.

Usage : python alpaca_probe.py [SPY QQQ ...]   (sans argument : toute la
watchlist US). Necessite ALPACA_API_KEY_ID / ALPACA_API_SECRET_KEY.

Ajoute le 22/10/2026 avec le correctif ALPACA_HISTORY_DAYS : avant, Alpaca
ne renvoyait que les bougies du jour courant (parametre `start` par defaut),
le MACD etait toujours None et aucune alerte action/ETF ne pouvait partir.
Le code de sortie vaut 1 si au moins un symbole n'a pas ses 3 indicateurs.
"""

import sys
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).parent))
from trading_alert import (  # noqa: E402
    ALPACA_API_KEY_ID, ALPACA_API_SECRET_KEY, compute_rsi, fetch_alpaca_closes, home_score, macd_score,
)
from watchlist import WATCHLIST  # noqa: E402

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.stderr.reconfigure(encoding="utf-8", errors="replace")


def sonder(session, symbol):
    """Retourne (bougies, dernier cours, rsi, macd, maison) ; bougies=0 si rien recu."""
    closes = fetch_alpaca_closes(session, symbol) or []
    if not closes:
        return 0, None, None, None, None
    return len(closes), closes[-1], compute_rsi(closes, 14), macd_score(closes, 14), home_score(closes)


def main(argv=None, session=None):
    symbols = list(argv if argv is not None else sys.argv[1:])
    if not symbols:
        symbols = [item["symbol"] for item in WATCHLIST if item["asset_class"] != "crypto"]
    if not ALPACA_API_KEY_ID or not ALPACA_API_SECRET_KEY:
        print("ALPACA_API_KEY_ID / ALPACA_API_SECRET_KEY manquants dans l'environnement", file=sys.stderr)
        return 1

    session = session or requests.Session()
    echecs = 0
    print(f"{'Symbole':<8} {'Statut':<7} {'Bougies':>7} {'Dernier cours':>14} {'RSI':>6} {'MACD':>6} {'Maison':>7}")
    print("-" * 62)
    for symbol in symbols:
        n, last, rsi, macd, maison = sonder(session, symbol)
        complet = n > 0 and None not in (rsi, macd, maison)
        statut = "OK" if complet else "KO"
        if not complet:
            echecs += 1
        fmt = lambda v, w: f"{v:>{w}.1f}" if v is not None else f"{'--':>{w}}"  # noqa: E731
        last_txt = f"{last:>14.2f}" if last is not None else f"{'--':>14}"
        print(f"{symbol:<8} {statut:<7} {n:>7} {last_txt} {fmt(rsi, 6)} {fmt(macd, 6)} {fmt(maison, 7)}")

    print("-" * 62)
    if echecs:
        print(f"{echecs} symbole(s) sans les 3 indicateurs : le MACD exige ~50 bougies (cf. ALPACA_HISTORY_DAYS).")
        return 1
    print(f"{len(symbols)} symbole(s) : historique suffisant, les 3 indicateurs sont calculables.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
