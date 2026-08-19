"""
Backtest de la strategie trading-ct (RSI(14) + MACD normalise(14) + score
maison(14), unanimite, seuils 15/85) sur les ETF europeens de
eu_watchlist.EU_WATCHLIST, via l'historique journalier complet EODHD.

Necessite EODHD_API_TOKEN (memes cles que le bot en prod). Un seul appel
API par symbole (l'historique complet est renvoye en un coup, pas de
pagination) : 4 symboles = 4 appels, tres loin du quota gratuit de 20/jour.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from eu_watchlist import EU_WATCHLIST  # noqa: E402
from trading_alert import (  # noqa: E402
    HOME_BUY, HOME_SELL, MACD_BUY, MACD_SELL, RSI_BUY, RSI_SELL,
    classify, compute_rsi, get_with_retry, home_score, macd_score,
)
from trading_alert_eu import EODHD_API_TOKEN, EODHD_EOD_URL, WINDOW  # noqa: E402


def fetch_full_eodhd_closes(symbol):
    if not EODHD_API_TOKEN:
        raise RuntimeError("EODHD_API_TOKEN manquant dans l'environnement")
    r = get_with_retry(
        EODHD_EOD_URL.format(symbol=symbol),
        params={"api_token": EODHD_API_TOKEN, "fmt": "json", "period": "d", "order": "a"},
    )
    data = r.json()
    dates = [d["date"] for d in data]
    closes = [float(d.get("adjusted_close") or d["close"]) for d in data]
    return dates, closes


def run_backtest(closes, dates):
    data_start_idx = WINDOW - 1
    if data_start_idx >= len(closes):
        raise ValueError("pas assez de bougies pour calculer les indicateurs")

    trades = []
    position = None
    prev_state = "neutral"
    buy_signals = sell_signals = 0

    for i in range(data_start_idx, len(closes)):
        window_closes = closes[i + 1 - WINDOW:i + 1]
        rsi = compute_rsi(window_closes, 14)
        macd_sc = macd_score(window_closes, 14)
        home_sc = home_score(window_closes)

        zones = [
            classify(rsi, RSI_BUY, RSI_SELL),
            classify(macd_sc, MACD_BUY, MACD_SELL),
            classify(home_sc, HOME_BUY, HOME_SELL),
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
    results = []
    for item in EU_WATCHLIST:
        symbol = item["symbol"]
        print(f"Telechargement + backtest {symbol}...")
        try:
            dates, closes = fetch_full_eodhd_closes(symbol)
        except Exception as e:
            print(f"  echec pour {symbol}: {e}")
            continue
        if not closes:
            print(f"  aucune donnee pour {symbol}, ignore")
            continue
        try:
            r = run_backtest(closes, dates)
        except ValueError as e:
            print(f"  {symbol}: {e}")
            continue
        r["symbol"] = symbol
        r["display"] = item["display"]
        results.append(r)

    print("\n" + "=" * 118)
    header = f"{'Symbole':<12} {'Depuis':>10} {'Buy':>4} {'Sell':>5} {'Trades':>7} {'WinRate':>8} " \
             f"{'Strategie':>11} {'BuyHold':>10} {'Ecart':>9} {'Open?':>6}"
    print(header)
    print("-" * 118)
    for r in results:
        wr = f"{r['win_rate']:.0f}%" if r["win_rate"] is not None else "n/a"
        gap = r["strategy_return"] - r["buy_hold_return"]
        print(f"{r['symbol']:<12} {str(r['start_date']):>10} {r['buy_signals']:>4} {r['sell_signals']:>5} "
              f"{r['trades']:>7} {wr:>8} {r['strategy_return']:>+10.1f}% {r['buy_hold_return']:>+9.1f}% "
              f"{gap:>+8.1f}% {'oui' if r['still_open'] else 'non':>6}")
    print("=" * 118)


if __name__ == "__main__":
    main()
