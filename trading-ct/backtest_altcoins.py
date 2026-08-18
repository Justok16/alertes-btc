"""
Rejoue la strategie trading-ct (RSI(14)+MACD normalise(14) + Fear & Greed
crypto global, unanimite, seuils 15/85) sur plusieurs grandes cryptos
liquides, pour voir si l'approche marche aussi ailleurs que sur BTC.

ATTENTION -- biais de survivance : la liste ci-dessous ne contient que des
cryptos encore liquides et cotees aujourd'hui. La grande majorite des
cryptomonnaies lancees depuis 2017 ont perdu presque toute leur valeur ou
ont disparu ; ce script ne dit RIEN sur la probabilite qu'un actif choisi
aujourd'hui reussisse pareil demain. Ce n'est pas une recommandation
d'achat, uniquement un test de robustesse de la strategie sur d'autres
historiques de prix.

Le Fear & Greed Index (Alternative.me) est un indice de marche crypto
GLOBAL, pas par piece : il est partage entre tous les symboles ci-dessous
(c'est deja le comportement du bot en prod pour n'importe quelle crypto
de watchlist.WATCHLIST).
"""

import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from backtest_btc import fetch_fng_history, fetch_full_daily_klines, WINDOW  # noqa: E402
from trading_alert import (  # noqa: E402
    FNG_CRYPTO_BUY, FNG_CRYPTO_SELL, MACD_BUY, MACD_SELL, RSI_BUY, RSI_SELL,
    classify, compute_rsi, macd_score,
)

SYMBOLS = ["BTCUSDT", "ETHUSDT", "BNBUSDT", "XRPUSDT", "LTCUSDT",
           "ADAUSDT", "DOGEUSDT", "SOLUSDT", "LINKUSDT"]


def run_symbol(closes, dates, fng_by_date):
    data_start_idx = next(i for i in range(len(closes)) if i + 1 >= WINDOW and dates[i] in fng_by_date)
    trades = []
    position = None
    prev_state = "neutral"
    buy_signals = sell_signals = 0

    for i in range(data_start_idx, len(closes)):
        date_i = dates[i]
        fng = fng_by_date.get(date_i)
        if fng is None:
            continue
        window_closes = closes[i + 1 - WINDOW:i + 1]
        rsi = compute_rsi(window_closes, 14)
        macd_sc = macd_score(window_closes, 14)
        zones = [
            classify(rsi, RSI_BUY, RSI_SELL),
            classify(macd_sc, MACD_BUY, MACD_SELL),
            classify(fng, FNG_CRYPTO_BUY, FNG_CRYPTO_SELL),
        ]
        combined = "buy" if zones == ["buy"] * 3 else "sell" if zones == ["sell"] * 3 else "neutral"
        price = closes[i]

        if combined != prev_state:
            if combined == "buy" and position is None:
                position = {"entry_price": price}
                buy_signals += 1
            elif combined == "sell" and position is not None:
                trades.append((price - position["entry_price"]) / position["entry_price"] * 100)
                position = None
                sell_signals += 1
            elif combined == "buy":
                buy_signals += 1
            elif combined == "sell":
                sell_signals += 1
        prev_state = combined

    equity = 100.0
    for r in trades:
        equity *= (1 + r / 100)
    if position is not None:
        equity *= (1 + (closes[-1] - position["entry_price"]) / position["entry_price"])

    buy_hold_return = (closes[-1] - closes[data_start_idx]) / closes[data_start_idx] * 100
    wins = sum(1 for r in trades if r > 0)

    return {
        "start_date": dates[data_start_idx], "end_date": dates[-1],
        "buy_signals": buy_signals, "sell_signals": sell_signals,
        "trades": len(trades), "win_rate": (wins / len(trades) * 100) if trades else None,
        "strategy_return": equity - 100, "buy_hold_return": buy_hold_return,
        "still_open": position is not None,
    }


def main():
    print("Telechargement de l'historique Fear & Greed (Alternative.me)...")
    fng_by_date = fetch_fng_history()

    results = []
    for symbol in SYMBOLS:
        print(f"Telechargement + backtest {symbol}...")
        try:
            klines = fetch_full_daily_klines(symbol)
        except Exception as e:
            print(f"  echec pour {symbol}: {e}")
            continue
        if not klines:
            print(f"  aucune donnee pour {symbol}, ignore")
            continue
        dates = [datetime.fromtimestamp(k[0] / 1000, tz=timezone.utc).date() for k in klines]
        closes = [float(k[4]) for k in klines]
        try:
            r = run_symbol(closes, dates, fng_by_date)
        except StopIteration:
            print(f"  pas assez de donnees pour {symbol}, ignore")
            continue
        r["symbol"] = symbol
        results.append(r)

    print("\n" + "=" * 118)
    header = f"{'Symbole':<10} {'Depuis':>10} {'Buy':>4} {'Sell':>5} {'Trades':>7} {'WinRate':>8} " \
             f"{'Strategie':>11} {'BuyHold':>10} {'Ecart':>9} {'Open?':>6}"
    print(header)
    print("-" * 118)
    for r in results:
        wr = f"{r['win_rate']:.0f}%" if r["win_rate"] is not None else "n/a"
        gap = r["strategy_return"] - r["buy_hold_return"]
        print(f"{r['symbol']:<10} {str(r['start_date']):>10} {r['buy_signals']:>4} {r['sell_signals']:>5} "
              f"{r['trades']:>7} {wr:>8} {r['strategy_return']:>+10.1f}% {r['buy_hold_return']:>+9.1f}% "
              f"{gap:>+8.1f}% {'oui' if r['still_open'] else 'non':>6}")
    print("=" * 118)

    beats = [r for r in results if r["strategy_return"] > r["buy_hold_return"]]
    print(f"\nLa strategie bat le buy & hold sur {len(beats)}/{len(results)} cryptos testees : "
          + ", ".join(r["symbol"] for r in beats))


if __name__ == "__main__":
    main()
