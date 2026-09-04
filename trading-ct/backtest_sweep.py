"""
Balaie plusieurs variantes de la strategie trading-ct sur l'historique BTC :
- seuils buy/sell plus ou moins stricts (15/85, 20/80, 25/75, 30/70)
- unanimite (3/3) vs vote majoritaire (2/3) entre RSI(14), MACD normalise(14)
  et Fear & Greed

Reutilise le telechargement de donnees et les indicateurs de backtest_btc.py.
Les 3 indicateurs partagent les memes seuils buy/sell dans ce balayage (pour
rester lisible) ; la prod (trading_alert.py) applique en realite les memes
seuils uniformes 15/85 aux 3 indicateurs (RSI/MACD/F&G) depuis son dernier
changement -- cf. backtest_compare.py/backtest_walkforward.py, qui importent
ces constantes directement plutot que de les recopier en dur ici (correctif
du 04/09/2026 : ce commentaire mentionnait encore une asymetrie F&G 10/85
perimee).
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from backtest_btc import fetch_fng_history, fetch_full_daily_klines, WINDOW  # noqa: E402
from datetime import datetime, timezone  # noqa: E402
from trading_alert import classify, compute_rsi, macd_score  # noqa: E402

THRESHOLD_VARIANTS = [(15, 85), (20, 80), (25, 75), (30, 70)]
MODES = ["unanimous", "majority"]


def run_variant(closes, dates, fng_by_date, buy_t, sell_t, mode):
    signal_log = []
    trades = []
    position = None
    prev_state = "neutral"
    days_in_position = 0
    total_days = 0

    for i in range(len(closes)):
        if i + 1 < WINDOW:
            continue
        date = dates[i]
        fng = fng_by_date.get(date)
        if fng is None:
            continue

        window_closes = closes[i + 1 - WINDOW:i + 1]
        rsi = compute_rsi(window_closes, 14)
        macd_sc = macd_score(window_closes, 14)

        rsi_zone = classify(rsi, buy_t, sell_t)
        macd_zone = classify(macd_sc, buy_t, sell_t)
        fng_zone = classify(fng, buy_t, sell_t)
        zones = [rsi_zone, macd_zone, fng_zone]

        if mode == "unanimous":
            combined = "buy" if zones == ["buy"] * 3 else "sell" if zones == ["sell"] * 3 else "neutral"
        else:  # majority (2 sur 3), meme regle que le bot BTC historique
            buy_votes = zones.count("buy")
            sell_votes = zones.count("sell")
            combined = "buy" if buy_votes >= 2 else "sell" if sell_votes >= 2 else "neutral"

        price = closes[i]
        total_days += 1
        if position is not None:
            days_in_position += 1

        if combined != prev_state:
            signal_log.append({"date": date, "state": combined, "price": price})
            if combined == "buy" and position is None:
                position = {"entry_date": date, "entry_price": price}
            elif combined == "sell" and position is not None:
                pct_return = (price - position["entry_price"]) / position["entry_price"] * 100
                trades.append(pct_return)
                position = None
        prev_state = combined

    first_valid_date = next((s["date"] for s in signal_log), None) or min(fng_by_date)
    start_idx = dates.index(first_valid_date)
    buy_hold_return = (closes[-1] - closes[start_idx]) / closes[start_idx] * 100

    equity = 100.0
    for r in trades:
        equity *= (1 + r / 100)
    if position is not None:
        equity *= (1 + (closes[-1] - position["entry_price"]) / position["entry_price"])

    buy_signals = sum(1 for s in signal_log if s["state"] == "buy")
    sell_signals = sum(1 for s in signal_log if s["state"] == "sell")
    wins = sum(1 for r in trades if r > 0)
    win_rate = (wins / len(trades) * 100) if trades else None
    time_in_market = (days_in_position / total_days * 100) if total_days else 0

    return {
        "buy_t": buy_t, "sell_t": sell_t, "mode": mode,
        "buy_signals": buy_signals, "sell_signals": sell_signals,
        "trades": len(trades), "win_rate": win_rate,
        "strategy_return": equity - 100, "buy_hold_return": buy_hold_return,
        "still_open": position is not None,
        "time_in_market": time_in_market,
        "first_date": first_valid_date,
    }


def main():
    print("Telechargement de l'historique BTCUSDT (Binance)...")
    klines = fetch_full_daily_klines()
    dates = [datetime.fromtimestamp(k[0] / 1000, tz=timezone.utc).date() for k in klines]
    closes = [float(k[4]) for k in klines]

    print("Telechargement de l'historique Fear & Greed (Alternative.me)...")
    fng_by_date = fetch_fng_history()

    results = []
    for buy_t, sell_t in THRESHOLD_VARIANTS:
        for mode in MODES:
            print(f"Backtest seuils {buy_t}/{sell_t} - mode {mode}...")
            results.append(run_variant(closes, dates, fng_by_date, buy_t, sell_t, mode))

    print("\n" + "=" * 100)
    header = f"{'Seuils':>8} {'Mode':>10} {'Buy':>4} {'Sell':>5} {'Trades':>7} {'WinRate':>8} " \
             f"{'StratEquity':>12} {'BuyHold':>10} {'TimeInMkt':>10} {'Open?':>6}"
    print(header)
    print("-" * 100)
    for r in results:
        win_rate_str = f"{r['win_rate']:.0f}%" if r['win_rate'] is not None else "n/a"
        print(
            f"{r['buy_t']:>3}/{r['sell_t']:<3} {r['mode']:>10} {r['buy_signals']:>4} {r['sell_signals']:>5} "
            f"{r['trades']:>7} {win_rate_str:>8} {r['strategy_return']:>+11.1f}% {r['buy_hold_return']:>+9.1f}% "
            f"{r['time_in_market']:>9.1f}% {'oui' if r['still_open'] else 'non':>6}"
        )
    print("=" * 100)


if __name__ == "__main__":
    main()
