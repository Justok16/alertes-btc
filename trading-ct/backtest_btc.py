"""
Backtest de la strategie trading-ct (RSI(14) + MACD normalise(14) +
Fear & Greed) sur tout l'historique BTC disponible.

Reutilise les memes fonctions que trading_alert.py (compute_rsi, macd_score,
classify, seuils) pour que le backtest reproduise fidelement le comportement
du bot en production, y compris sa fenetre glissante de 100 bougies (les
indicateurs sont recalcules "a froid" sur les 100 dernieres bougies a
chaque jour, exactement comme le fait le script live a chaque run).

Contrainte de donnees : le Fear & Greed Index (Alternative.me) ne remonte
que jusqu'au 2018-02-01 (date de creation de l'indice) ; le backtest ne peut
donc pas couvrir les tout premiers mois de cotation du BTC sur Binance
(aout-decembre 2017), pour lesquels aucune des 3 sources n'existait.

Strategie simulee : long only, sans effet de levier, sans vente a decouvert.
  - Signal "buy" (transition vers l'etat combine "buy") => ouvre une
    position si aucune n'est en cours.
  - Signal "sell" (transition vers "sell") => cloture la position en cours
    s'il y en a une (sinon ignore, pas de short).
"""

import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).parent))
from trading_alert import (  # noqa: E402
    FNG_CRYPTO_BUY, FNG_CRYPTO_SELL, MACD_BUY, MACD_SELL, RSI_BUY, RSI_SELL,
    classify, compute_rsi, macd_score,
)

BINANCE_KLINES_URL = "https://data-api.binance.vision/api/v3/klines"
ALTERNATIVE_FNG_HISTORY_URL = "https://api.alternative.me/fng/?limit=0&format=json"
WINDOW = 100  # meme fenetre glissante que trading_alert.py (limit=100)
HTTP_TIMEOUT = 15


def get_with_retry(url, params=None, retries=3, backoff=15):
    last_exc = None
    for attempt in range(retries):
        try:
            r = requests.get(url, params=params, timeout=HTTP_TIMEOUT)
            if r.status_code == 429 and attempt < retries - 1:
                time.sleep(backoff * (attempt + 1))
                continue
            r.raise_for_status()
            return r
        except requests.exceptions.RequestException as e:
            last_exc = e
            if attempt < retries - 1:
                time.sleep(backoff * (attempt + 1))
    raise last_exc


def fetch_full_daily_klines(symbol="BTCUSDT"):
    """Recupere tout l'historique de bougies journalieres depuis la cotation."""
    all_klines = []
    start_time = 0
    while True:
        r = get_with_retry(
            BINANCE_KLINES_URL,
            params={"symbol": symbol, "interval": "1d", "limit": 1000, "startTime": start_time},
        )
        batch = r.json()
        if not batch:
            break
        all_klines.extend(batch)
        if len(batch) < 1000:
            break
        start_time = batch[-1][0] + 1
        time.sleep(0.2)
    return all_klines


def fetch_fng_history():
    r = get_with_retry(ALTERNATIVE_FNG_HISTORY_URL)
    entries = r.json()["data"]
    fng_by_date = {}
    for entry in entries:
        date = datetime.fromtimestamp(int(entry["timestamp"]), tz=timezone.utc).date()
        fng_by_date[date] = int(entry["value"])
    return fng_by_date


def run_backtest(closes, dates, fng_by_date):
    """Rejoue la strategie jour par jour, retourne (signal_log, trades)."""
    signal_log = []
    trades = []
    position = None
    prev_state = "neutral"

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

        zones = {
            classify(rsi, RSI_BUY, RSI_SELL),
            classify(macd_sc, MACD_BUY, MACD_SELL),
            classify(fng, FNG_CRYPTO_BUY, FNG_CRYPTO_SELL),
        }
        if zones == {"buy"}:
            combined = "buy"
        elif zones == {"sell"}:
            combined = "sell"
        else:
            combined = "neutral"

        price = closes[i]

        if combined != prev_state:
            signal_log.append({"date": date, "state": combined, "price": price})
            if combined == "buy" and position is None:
                position = {"entry_date": date, "entry_price": price}
            elif combined == "sell" and position is not None:
                pct_return = (price - position["entry_price"]) / position["entry_price"] * 100
                trades.append({
                    "entry_date": position["entry_date"], "entry_price": position["entry_price"],
                    "exit_date": date, "exit_price": price, "pct_return": pct_return,
                })
                position = None
        prev_state = combined

    return signal_log, trades, position


def compute_equity_curve(dates, closes, signal_log, first_valid_date):
    """Courbe d'equity jour par jour : strategie (cash quand hors position)
    vs buy & hold BTC, toutes deux normalisees a 100 au meme point de depart."""
    start_idx = dates.index(first_valid_date)
    base_price = closes[start_idx]
    signals_by_date = {s["date"]: s["state"] for s in signal_log}

    equity_realized = 100.0  # equity fige au moment de la derniere cloture de position
    entry_price = None
    equity_at_entry = None

    curve = []
    for i in range(start_idx, len(dates)):
        date = dates[i]
        price = closes[i]

        state = signals_by_date.get(date)
        if state == "buy" and entry_price is None:
            entry_price = price
            equity_at_entry = equity_realized
        elif state == "sell" and entry_price is not None:
            equity_realized = equity_at_entry * (price / entry_price)
            entry_price = None

        current_equity = equity_at_entry * (price / entry_price) if entry_price is not None else equity_realized
        curve.append({
            "date": date.isoformat(),
            "strategy": round(current_equity, 2),
            "buy_hold": round(100.0 * price / base_price, 2),
        })
    return curve


def main():
    print("Telechargement de l'historique BTCUSDT (Binance)...")
    klines = fetch_full_daily_klines()
    dates = [datetime.fromtimestamp(k[0] / 1000, tz=timezone.utc).date() for k in klines]
    closes = [float(k[4]) for k in klines]
    print(f"{len(closes)} bougies journalieres recuperees ({dates[0]} -> {dates[-1]})")

    print("Telechargement de l'historique Fear & Greed (Alternative.me)...")
    fng_by_date = fetch_fng_history()
    print(f"{len(fng_by_date)} jours de F&G disponibles ({min(fng_by_date)} -> {max(fng_by_date)})")

    signal_log, trades, open_position = run_backtest(closes, dates, fng_by_date)

    first_valid_date = next((s["date"] for s in signal_log), None) or min(fng_by_date)
    print(f"\nPeriode effectivement backtestee : {first_valid_date} -> {dates[-1]}")
    print(f"Signaux emis (changements d'etat) : {len(signal_log)}")
    buy_signals = [s for s in signal_log if s["state"] == "buy"]
    sell_signals = [s for s in signal_log if s["state"] == "sell"]
    print(f"  - dont buy  : {len(buy_signals)}")
    print(f"  - dont sell : {len(sell_signals)}")

    print(f"\nTrades cloture (round-trip long only) : {len(trades)}")
    for t in trades:
        print(f"  {t['entry_date']} @ {t['entry_price']:.2f} -> {t['exit_date']} @ {t['exit_price']:.2f} : "
              f"{t['pct_return']:+.2f}%")

    if open_position:
        last_close = closes[-1]
        unrealized = (last_close - open_position["entry_price"]) / open_position["entry_price"] * 100
        print(f"\nPosition encore ouverte depuis {open_position['entry_date']} "
              f"@ {open_position['entry_price']:.2f} (non realisee : {unrealized:+.2f}% au dernier cours)")

    if trades:
        wins = [t for t in trades if t["pct_return"] > 0]
        win_rate = len(wins) / len(trades) * 100
        avg_return = sum(t["pct_return"] for t in trades) / len(trades)

        equity = 100.0
        for t in trades:
            equity *= (1 + t["pct_return"] / 100)

        # Buy & hold sur exactement la meme periode que le backtest
        start_idx = dates.index(first_valid_date)
        buy_hold_return = (closes[-1] - closes[start_idx]) / closes[start_idx] * 100

        print(f"\nTaux de reussite : {win_rate:.1f}% ({len(wins)}/{len(trades)})")
        print(f"Rendement moyen par trade : {avg_return:+.2f}%")
        print(f"Rendement cumule compose (trades uniquement, 100 -> {equity:.1f}) : {equity - 100:+.2f}%")
        print(f"Buy & hold BTC sur la meme periode : {buy_hold_return:+.2f}%")
    else:
        print("\nAucun trade complet sur la periode : impossible de calculer un rendement.")

    curve = compute_equity_curve(dates, closes, signal_log, first_valid_date)
    out_path = Path(__file__).parent / "backtest_equity_curve.json"
    out_path.write_text(json.dumps({"signals": [
        {"date": s["date"].isoformat(), "state": s["state"], "price": s["price"]} for s in signal_log
    ], "curve": curve}, indent=2), encoding="utf-8")
    print(f"\nCourbe d'equity ecrite dans {out_path}")


if __name__ == "__main__":
    main()
