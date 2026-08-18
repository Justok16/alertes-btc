"""
Meme analyse que backtest_drawdown.py (seuil de baisse simple sous un plus
haut glissant sur 100 bougies, rendement moyen a 90 jours apres
declenchement) mais appliquee aux actions/ETF via l'historique Alpaca.

Necessite ALPACA_API_KEY_ID / ALPACA_API_SECRET_KEY (memes cles que le bot
en prod). A lancer via le workflow GitHub dedie ou en local avec les cles
dans l'environnement.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from backtest_stocks import fetch_full_daily_bars  # noqa: E402

SYMBOLS = ["SPY", "QQQ", "AAPL", "MSFT", "GOOGL", "AMZN", "NVDA", "TSLA", "META", "JPM", "XOM", "COIN"]
WINDOW = 100
HORIZON = 90
THRESHOLDS = [5, 10, 15, 20, 25, 30, 35, 40, 50, 60]
MIN_EVENTS = 3


def rolling_high(closes, i, window=WINDOW):
    lo = max(0, i - window + 1)
    return max(closes[lo:i + 1])


def analyze_threshold(closes, threshold_pct):
    returns = []
    triggered = False
    for i in range(WINDOW - 1, len(closes)):
        high = rolling_high(closes, i)
        drawdown = (closes[i] - high) / high * 100

        if drawdown <= -threshold_pct:
            if not triggered:
                triggered = True
                exit_idx = i + HORIZON
                if exit_idx < len(closes):
                    fwd_return = (closes[exit_idx] - closes[i]) / closes[i] * 100
                    returns.append(fwd_return)
        else:
            triggered = False
    return returns


def main():
    symbols = sys.argv[1:] or SYMBOLS
    per_asset_best = {}

    print("=" * 100)
    for symbol in symbols:
        print(f"\nTelechargement {symbol}...")
        try:
            bars = fetch_full_daily_bars(symbol)
        except Exception as e:
            print(f"  echec: {e}")
            continue
        closes = [float(b["c"]) for b in bars]
        if len(closes) < WINDOW + HORIZON:
            print(f"  pas assez de donnees pour {symbol} ({len(closes)} bougies)")
            continue

        print(f"### {symbol}  ({len(closes)} bougies)")
        best = None
        for t in THRESHOLDS:
            rets = analyze_threshold(closes, t)
            if not rets:
                continue
            avg = sum(rets) / len(rets)
            win_rate = sum(1 for r in rets if r > 0) / len(rets) * 100
            flag = ""
            if len(rets) >= MIN_EVENTS and (best is None or avg > best["avg"]):
                best = {"threshold": t, "avg": avg, "win_rate": win_rate, "n": len(rets)}
                flag = "  <-- meilleur (>= {} evenements)".format(MIN_EVENTS)
            print(f"  -{t:>2}% : {len(rets):>3} evenement(s), rendement moyen a {HORIZON}j = {avg:>+7.1f}%, "
                  f"win rate = {win_rate:>5.1f}%{flag}")

        if best:
            per_asset_best[symbol] = best
            print(f"  => Meilleur seuil pour {symbol} : -{best['threshold']}% "
                  f"({best['n']} evenements, rendement moyen {best['avg']:+.1f}%)")
        else:
            print(f"  => Pas assez d'evenements ({MIN_EVENTS}+ requis) pour {symbol}, quel que soit le seuil")

    print("\n" + "=" * 100)
    if per_asset_best:
        avg_threshold = sum(b["threshold"] for b in per_asset_best.values()) / len(per_asset_best)
        avg_return = sum(b["avg"] for b in per_asset_best.values()) / len(per_asset_best)
        print(f"Sur {len(per_asset_best)}/{len(symbols)} actifs avec assez de donnees :")
        for symbol, b in per_asset_best.items():
            print(f"  {symbol:<8} meilleur seuil = -{b['threshold']}%  (rendement moyen a {HORIZON}j = {b['avg']:+.1f}%, n={b['n']})")
        print(f"\nSeuil de baisse moyen (tous actifs confondus) : -{avg_threshold:.1f}%")
        print(f"Rendement moyen a {HORIZON}j associe : {avg_return:+.1f}%")
    else:
        print("Aucun actif n'a assez d'evenements pour conclure.")
    print("=" * 100)


if __name__ == "__main__":
    main()
