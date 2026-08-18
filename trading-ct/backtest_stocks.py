"""
Backtest de la strategie trading-ct (RSI(14) + MACD normalise(14) +
score maison(14), unanimite, seuils 15/85) sur des actions/ETF via
l'historique journalier Alpaca.

Necessite ALPACA_API_KEY_ID / ALPACA_API_SECRET_KEY dans l'environnement
(les memes que ceux utilises par trading_alert.py en prod). Comme ce script
lit potentiellement des annees de donnees, il est plus simple de le lancer
en local avec tes cles, ou via un declenchement manuel du workflow GitHub
dedie (trading-ct-backtest.yml) qui lit les secrets du repo sans jamais les
exposer.

Contrairement au F&G crypto (indice de marche global), le "score maison"
est calcule PAR symbole (RSI + position dans le range 14 bougies) : pas de
donnee partagee entre actifs a telecharger separement.
"""

import os
import sys
import time
from datetime import date, datetime, timezone
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).parent))
from trading_alert import (  # noqa: E402
    HOME_BUY, HOME_SELL, MACD_BUY, MACD_SELL, RSI_BUY, RSI_SELL,
    classify, compute_rsi, home_score, macd_score,
)

ALPACA_API_KEY_ID = os.environ.get("ALPACA_API_KEY_ID")
ALPACA_API_SECRET_KEY = os.environ.get("ALPACA_API_SECRET_KEY")
ALPACA_BARS_URL = "https://data.alpaca.markets/v2/stocks/{symbol}/bars"
WINDOW = 100
HTTP_TIMEOUT = 15

SYMBOLS = ["SPY", "QQQ"]
HISTORY_START = "2016-01-01"  # aussi loin que possible ; l'API renverra moins si indisponible


def get_with_retry(url, params=None, headers=None, retries=3, backoff=15):
    last_exc = None
    for attempt in range(retries):
        try:
            r = requests.get(url, params=params, headers=headers, timeout=HTTP_TIMEOUT)
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


def fetch_full_daily_bars(symbol):
    if not ALPACA_API_KEY_ID or not ALPACA_API_SECRET_KEY:
        raise RuntimeError("ALPACA_API_KEY_ID / ALPACA_API_SECRET_KEY manquants dans l'environnement")

    headers = {"APCA-API-KEY-ID": ALPACA_API_KEY_ID, "APCA-API-SECRET-KEY": ALPACA_API_SECRET_KEY}
    all_bars = []
    page_token = None
    while True:
        params = {"timeframe": "1Day", "start": HISTORY_START, "limit": 10000, "feed": "iex"}
        if page_token:
            params["page_token"] = page_token
        r = get_with_retry(ALPACA_BARS_URL.format(symbol=symbol), params=params, headers=headers)
        data = r.json()
        all_bars.extend(data.get("bars", []))
        page_token = data.get("next_page_token")
        if not page_token:
            break
        time.sleep(0.2)
    return all_bars


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
    symbols = sys.argv[1:] or SYMBOLS
    results = []
    for symbol in symbols:
        print(f"Telechargement + backtest {symbol}...")
        try:
            bars = fetch_full_daily_bars(symbol)
        except Exception as e:
            print(f"  echec pour {symbol}: {e}")
            continue
        if not bars:
            print(f"  aucune donnee pour {symbol}, ignore")
            continue
        dates = [datetime.fromisoformat(b["t"].replace("Z", "+00:00")).date() for b in bars]
        closes = [float(b["c"]) for b in bars]
        try:
            r = run_backtest(closes, dates)
        except ValueError as e:
            print(f"  {symbol}: {e}")
            continue
        r["symbol"] = symbol
        results.append(r)

    print("\n" + "=" * 118)
    header = f"{'Symbole':<8} {'Depuis':>10} {'Buy':>4} {'Sell':>5} {'Trades':>7} {'WinRate':>8} " \
             f"{'Strategie':>11} {'BuyHold':>10} {'Ecart':>9} {'Open?':>6}"
    print(header)
    print("-" * 118)
    for r in results:
        wr = f"{r['win_rate']:.0f}%" if r["win_rate"] is not None else "n/a"
        gap = r["strategy_return"] - r["buy_hold_return"]
        print(f"{r['symbol']:<8} {str(r['start_date']):>10} {r['buy_signals']:>4} {r['sell_signals']:>5} "
              f"{r['trades']:>7} {wr:>8} {r['strategy_return']:>+10.1f}% {r['buy_hold_return']:>+9.1f}% "
              f"{gap:>+8.1f}% {'oui' if r['still_open'] else 'non':>6}")
    print("=" * 118)


if __name__ == "__main__":
    main()
