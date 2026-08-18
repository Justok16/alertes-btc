"""
Backteste en detail quelques variantes retenues apres le balayage
(backtest_sweep.py) et exporte une courbe d'equity comparable (meme date de
depart pour toutes les variantes + buy & hold) pour visualisation.

Variantes comparees :
  - "Prod actuelle"      : RSI/MACD 15/85, F&G crypto <=10/>=85 (asymetrique),
                            unanimite -- config exacte de trading_alert.py
  - "15/85 uniforme"      : memes seuils 15/85 mais appliques aussi au F&G
                            (au lieu de 10/85), unanimite
  - "20/80 uniforme"      : seuils assouplis, unanimite
  - "15/85 majoritaire"   : seuils stricts mais vote a 2/3 (comme le bot BTC
                            historique) au lieu de l'unanimite
"""

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from backtest_btc import fetch_fng_history, fetch_full_daily_klines, WINDOW  # noqa: E402
from trading_alert import (  # noqa: E402
    FNG_CRYPTO_BUY, FNG_CRYPTO_SELL, MACD_BUY, MACD_SELL, RSI_BUY, RSI_SELL,
    classify, compute_rsi, macd_score,
)

VARIANTS = [
    {"name": "Prod actuelle (10/85 F&G, unanimite)", "rsi": (RSI_BUY, RSI_SELL), "macd": (MACD_BUY, MACD_SELL),
     "fng": (FNG_CRYPTO_BUY, FNG_CRYPTO_SELL), "mode": "unanimous"},
    {"name": "15/85 uniforme, unanimite", "rsi": (15, 85), "macd": (15, 85), "fng": (15, 85), "mode": "unanimous"},
    {"name": "20/80 uniforme, unanimite", "rsi": (20, 80), "macd": (20, 80), "fng": (20, 80), "mode": "unanimous"},
    {"name": "15/85 uniforme, majoritaire (2/3)", "rsi": (15, 85), "macd": (15, 85), "fng": (15, 85), "mode": "majority"},
]


def run_variant_detailed(closes, dates, fng_by_date, variant, data_start_idx):
    signal_log = []
    trades = []
    position = None
    prev_state = "neutral"
    curve = []
    equity_realized = 100.0
    entry_price = None
    equity_at_entry = None
    base_price = closes[data_start_idx]

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

        rsi_zone = classify(rsi, *variant["rsi"])
        macd_zone = classify(macd_sc, *variant["macd"])
        fng_zone = classify(fng, *variant["fng"])
        zones = [rsi_zone, macd_zone, fng_zone]

        if variant["mode"] == "unanimous":
            combined = "buy" if zones == ["buy"] * 3 else "sell" if zones == ["sell"] * 3 else "neutral"
        else:
            buy_votes, sell_votes = zones.count("buy"), zones.count("sell")
            combined = "buy" if buy_votes >= 2 else "sell" if sell_votes >= 2 else "neutral"

        price = closes[i]

        if combined != prev_state:
            signal_log.append({"date": date, "state": combined, "price": price})
            if combined == "buy" and position is None:
                position = {"entry_date": date, "entry_price": price}
                entry_price = price
                equity_at_entry = equity_realized
            elif combined == "sell" and position is not None:
                pct_return = (price - position["entry_price"]) / position["entry_price"] * 100
                trades.append(pct_return)
                equity_realized = equity_at_entry * (price / entry_price)
                position = None
                entry_price = None
        prev_state = combined

        if i >= data_start_idx:
            current_equity = equity_at_entry * (price / entry_price) if entry_price is not None else equity_realized
            curve.append({"date": date.isoformat(), "equity": round(current_equity, 2)})

    if position is not None:
        final_equity = equity_at_entry * (closes[-1] / entry_price)
    else:
        final_equity = equity_realized

    return {
        "name": variant["name"],
        "buy_signals": sum(1 for s in signal_log if s["state"] == "buy"),
        "sell_signals": sum(1 for s in signal_log if s["state"] == "sell"),
        "trades": len(trades),
        "win_rate": (sum(1 for r in trades if r > 0) / len(trades) * 100) if trades else None,
        "final_return": final_equity - 100,
        "still_open": position is not None,
        "curve": curve,
    }


def main():
    print("Telechargement de l'historique BTCUSDT (Binance)...")
    klines = fetch_full_daily_klines()
    dates = [datetime.fromtimestamp(k[0] / 1000, tz=timezone.utc).date() for k in klines]
    closes = [float(k[4]) for k in klines]

    print("Telechargement de l'historique Fear & Greed (Alternative.me)...")
    fng_by_date = fetch_fng_history()

    # Date de depart commune : premier jour ou les 3 indicateurs sont
    # calculables (fenetre de 100 bougies + F&G disponible), independamment
    # des seuils/mode -- pour comparer toutes les variantes sur EXACTEMENT
    # la meme periode.
    data_start_idx = next(i for i in range(len(closes)) if i + 1 >= WINDOW and dates[i] in fng_by_date)
    data_start_date = dates[data_start_idx]
    print(f"Date de depart commune : {data_start_date}")

    results = []
    for variant in VARIANTS:
        print(f"Backtest detaille : {variant['name']}...")
        results.append(run_variant_detailed(closes, dates, fng_by_date, variant, data_start_idx))

    buy_hold_curve = [
        {"date": dates[i].isoformat(), "equity": round(100.0 * closes[i] / closes[data_start_idx], 2)}
        for i in range(data_start_idx, len(closes))
    ]
    buy_hold_return = buy_hold_curve[-1]["equity"] - 100

    print("\n" + "=" * 90)
    for r in results:
        win_rate_str = f"{r['win_rate']:.0f}%" if r["win_rate"] is not None else "n/a"
        print(f"{r['name']:<38} buy={r['buy_signals']:>3} sell={r['sell_signals']:>3} "
              f"trades={r['trades']:>3} winrate={win_rate_str:>5} "
              f"rendement={r['final_return']:>+9.1f}%  {'(position ouverte)' if r['still_open'] else ''}")
    print(f"{'Buy & hold BTC':<38} {'':>28} rendement={buy_hold_return:>+9.1f}%")
    print("=" * 90)

    out_path = Path(__file__).parent / "backtest_compare.json"
    out_path.write_text(json.dumps({
        "data_start_date": data_start_date.isoformat(),
        "variants": results,
        "buy_hold": {"return": buy_hold_return, "curve": buy_hold_curve},
    }, indent=2), encoding="utf-8")
    print(f"\nDonnees ecrites dans {out_path}")


if __name__ == "__main__":
    main()
