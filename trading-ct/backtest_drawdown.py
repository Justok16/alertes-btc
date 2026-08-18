"""
Question posee : "apres combien de % de baisse en moyenne pourrait-on
declencher une alerte d'achat ?" -- teste une regle beaucoup plus simple
que RSI/MACD/F&G : acheter des qu'un actif chute de X% sous son plus haut
glissant sur 100 bougies, et mesurer le rendement moyen a 90 jours apres
ce declenchement, pour differents X, sur les 9 cryptos deja etudiees.

Chaque "evenement de baisse" ne compte qu'une fois par episode (on ne
recompte pas chaque jour ou le prix reste sous le seuil -- seulement le
jour ou il le FRANCHIT, comme le state-change des autres bots du repo).
"""

import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from backtest_btc import fetch_full_daily_klines  # noqa: E402

SYMBOLS = ["BTCUSDT", "ETHUSDT", "BNBUSDT", "XRPUSDT", "LTCUSDT",
           "ADAUSDT", "DOGEUSDT", "SOLUSDT", "LINKUSDT"]
WINDOW = 100
HORIZON = 90  # jours apres le declenchement, pour mesurer le rendement
THRESHOLDS = [10, 15, 20, 25, 30, 35, 40, 50, 60, 70, 80]
MIN_EVENTS = 3


def rolling_high(closes, i, window=WINDOW):
    lo = max(0, i - window + 1)
    return max(closes[lo:i + 1])


def analyze_threshold(closes, threshold_pct):
    """Renvoie la liste des rendements a HORIZON jours apres chaque
    franchissement du seuil de baisse (evenements distincts uniquement)."""
    returns = []
    triggered = False
    for i in range(WINDOW - 1, len(closes)):
        high = rolling_high(closes, i)
        drawdown = (closes[i] - high) / high * 100  # <= 0

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
    per_asset_best = {}

    print("=" * 100)
    for symbol in SYMBOLS:
        print(f"\nTelechargement {symbol}...")
        try:
            klines = fetch_full_daily_klines(symbol)
        except Exception as e:
            print(f"  echec: {e}")
            continue
        closes = [float(k[4]) for k in klines]
        if len(closes) < WINDOW + HORIZON:
            print(f"  pas assez de donnees pour {symbol}")
            continue

        print(f"### {symbol}")
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
        print(f"Sur {len(per_asset_best)}/{len(SYMBOLS)} actifs avec assez de donnees :")
        for symbol, b in per_asset_best.items():
            print(f"  {symbol:<10} meilleur seuil = -{b['threshold']}%  (rendement moyen a {HORIZON}j = {b['avg']:+.1f}%, n={b['n']})")
        print(f"\nSeuil de baisse moyen (toutes cryptos confondues) : -{avg_threshold:.1f}%")
        print(f"Rendement moyen a {HORIZON}j associe : {avg_return:+.1f}%")
    else:
        print("Aucun actif n'a assez d'evenements pour conclure.")
    print("=" * 100)


if __name__ == "__main__":
    main()
