"""
Walk-forward (entrainement/validation) par symbole, pour plusieurs grandes
cryptos, afin de voir quelle config de seuils/mode "tient la route" pour
CHAQUE actif individuellement -- pas juste sur BTC.

Meme methode que backtest_walkforward.py (voir ce fichier pour le detail du
raisonnement anti-surapprentissage), generalisee a une liste de symboles.
La date de coupure s'adapte a la date de depart reelle des donnees de
chaque symbole (certains n'existent que depuis 2019-2020) : train = premiere
moitie de l'historique disponible, validation = seconde moitie.

Une config n'est retenue comme "robuste" pour un symbole que si :
  - elle bat le buy & hold sur l'entrainement ET la validation, ET
  - il y a au moins MIN_TRADES trades completes sur CHAQUE moitie
    (sinon le resultat n'est pas statistiquement exploitable, meme s'il
    "gagne" par pur hasard sur 1 seul trade).
"""

import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from backtest_btc import fetch_fng_history, fetch_full_daily_klines, WINDOW  # noqa: E402
from trading_alert import classify, compute_rsi, macd_score  # noqa: E402

SYMBOLS = ["BTCUSDT", "ETHUSDT", "BNBUSDT", "XRPUSDT", "LTCUSDT",
           "ADAUSDT", "DOGEUSDT", "SOLUSDT", "LINKUSDT"]

VARIANTS = [
    {"name": "10/90 unanimite", "t": (10, 90), "mode": "unanimous"},
    {"name": "15/85 unanimite", "t": (15, 85), "mode": "unanimous"},
    {"name": "20/80 unanimite", "t": (20, 80), "mode": "unanimous"},
    {"name": "25/75 unanimite", "t": (25, 75), "mode": "unanimous"},
    {"name": "30/70 unanimite", "t": (30, 70), "mode": "unanimous"},
    {"name": "35/65 unanimite", "t": (35, 65), "mode": "unanimous"},
    {"name": "15/85 majoritaire", "t": (15, 85), "mode": "majority"},
    {"name": "20/80 majoritaire", "t": (20, 80), "mode": "majority"},
]
MIN_TRADES = 2


def run_variant_period(closes, dates, fng_by_date, buy_t, sell_t, mode, lo_idx, hi_idx):
    trades = []
    position = None
    prev_state = "neutral"

    for i in range(lo_idx, hi_idx):
        if i + 1 < WINDOW:
            continue
        date_i = dates[i]
        fng = fng_by_date.get(date_i)
        if fng is None:
            continue
        window_closes = closes[i + 1 - WINDOW:i + 1]
        rsi = compute_rsi(window_closes, 14)
        macd_sc = macd_score(window_closes, 14)
        zones = [classify(rsi, buy_t, sell_t), classify(macd_sc, buy_t, sell_t), classify(fng, buy_t, sell_t)]

        if mode == "unanimous":
            combined = "buy" if zones == ["buy"] * 3 else "sell" if zones == ["sell"] * 3 else "neutral"
        else:
            combined = "buy" if zones.count("buy") >= 2 else "sell" if zones.count("sell") >= 2 else "neutral"

        price = closes[i]
        if combined != prev_state:
            if combined == "buy" and position is None:
                position = {"entry_price": price}
            elif combined == "sell" and position is not None:
                trades.append((price - position["entry_price"]) / position["entry_price"] * 100)
                position = None
        prev_state = combined

    equity = 100.0
    for r in trades:
        equity *= (1 + r / 100)
    if position is not None:
        equity *= (1 + (closes[hi_idx - 1] - position["entry_price"]) / position["entry_price"])
    buy_hold_return = (closes[hi_idx - 1] - closes[lo_idx]) / closes[lo_idx] * 100
    return {"trades": len(trades), "return": equity - 100, "buy_hold_return": buy_hold_return}


def analyze_symbol(closes, dates, fng_by_date):
    data_start_idx = next((i for i in range(len(closes)) if i + 1 >= WINDOW and dates[i] in fng_by_date), None)
    if data_start_idx is None:
        return None
    end_idx = len(dates)
    mid_idx = data_start_idx + (end_idx - data_start_idx) // 2

    rows = []
    for v in VARIANTS:
        train = run_variant_period(closes, dates, fng_by_date, *v["t"], v["mode"], data_start_idx, mid_idx)
        valid = run_variant_period(closes, dates, fng_by_date, *v["t"], v["mode"], mid_idx, end_idx)
        robust = (train["return"] > train["buy_hold_return"] and valid["return"] > valid["buy_hold_return"]
                  and train["trades"] >= MIN_TRADES and valid["trades"] >= MIN_TRADES)
        rows.append({"name": v["name"], "train": train, "valid": valid, "robust": robust})

    return {
        "start": dates[data_start_idx], "mid": dates[mid_idx], "end": dates[-1],
        "rows": rows,
    }


def main():
    print("Telechargement de l'historique Fear & Greed (Alternative.me)...")
    fng_by_date = fetch_fng_history()

    print("\n" + "=" * 100)
    for symbol in SYMBOLS:
        print(f"\nTelechargement {symbol}...")
        try:
            klines = fetch_full_daily_klines(symbol)
        except Exception as e:
            print(f"  echec: {e}")
            continue
        dates = [datetime.fromtimestamp(k[0] / 1000, tz=timezone.utc).date() for k in klines]
        closes = [float(k[4]) for k in klines]
        result = analyze_symbol(closes, dates, fng_by_date)
        if result is None:
            print(f"  pas assez de donnees pour {symbol}")
            continue

        print(f"### {symbol}  (train {result['start']}->{result['mid']}, "
              f"validation {result['mid']}->{result['end']})")
        robust = [r for r in result["rows"] for r in [r] if r["robust"]]
        for r in result["rows"]:
            flag = "  <-- ROBUSTE" if r["robust"] else ""
            print(f"  {r['name']:<20} train: trades={r['train']['trades']:>2} "
                  f"rendement={r['train']['return']:>+8.1f}% (B&H {r['train']['buy_hold_return']:>+7.1f}%) | "
                  f"valid: trades={r['valid']['trades']:>2} rendement={r['valid']['return']:>+8.1f}% "
                  f"(B&H {r['valid']['buy_hold_return']:>+7.1f}%){flag}")
        if robust:
            print(f"  => Config(s) robuste(s) pour {symbol} : " + ", ".join(r["name"] for r in robust))
        else:
            print(f"  => AUCUNE config ne bat le buy & hold sur les 2 periodes (avec >= {MIN_TRADES} trades chacune) pour {symbol}")
    print("=" * 100)


if __name__ == "__main__":
    main()
