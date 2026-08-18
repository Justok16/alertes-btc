"""
Validation hors-echantillon (walk-forward) pour eviter de choisir une
config qui colle par hasard a l'historique BTC complet (surapprentissage).

Principe :
  1. Periode d'ENTRAINEMENT (2018-02-01 -> SPLIT_DATE) : on balaie les
     variantes de seuils/mode et on regarde lesquelles gagnent LA-DESSUS
     uniquement.
  2. Periode de VALIDATION (SPLIT_DATE -> aujourd'hui), jamais vue pendant
     le choix : on rejoue les MEMES variantes (parametres figes, non
     re-optimises) et on regarde si elles tiennent la route.

Chaque periode redemarre "a plat" (aucune position heritee de l'autre
periode) : la question posee est "si je commence a utiliser cette config
maintenant, sans position en cours, comment se comporte-t-elle sur la
periode qui suit ?" -- la question pratique pertinente pour la validation.

Une variante n'est retenue comme credible que si elle bat le buy & hold
A LA FOIS a l'entrainement ET en validation. Gagner seulement a
l'entrainement est le signal classique de surapprentissage.
"""

import sys
from datetime import date, datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from backtest_btc import fetch_fng_history, fetch_full_daily_klines, WINDOW  # noqa: E402
from trading_alert import classify, compute_rsi, macd_score  # noqa: E402

SPLIT_DATE = date(2022, 1, 1)

VARIANTS = [
    {"name": "10/90 uniforme, unanimite", "rsi": (10, 90), "macd": (10, 90), "fng": (10, 90), "mode": "unanimous"},
    {"name": "15/85 uniforme, unanimite", "rsi": (15, 85), "macd": (15, 85), "fng": (15, 85), "mode": "unanimous"},
    {"name": "Prod actuelle (F&G 10/85 asym.), unanimite", "rsi": (15, 85), "macd": (15, 85), "fng": (10, 85), "mode": "unanimous"},
    {"name": "20/80 uniforme, unanimite", "rsi": (20, 80), "macd": (20, 80), "fng": (20, 80), "mode": "unanimous"},
    {"name": "25/75 uniforme, unanimite", "rsi": (25, 75), "macd": (25, 75), "fng": (25, 75), "mode": "unanimous"},
    {"name": "30/70 uniforme, unanimite", "rsi": (30, 70), "macd": (30, 70), "fng": (30, 70), "mode": "unanimous"},
    {"name": "35/65 uniforme, unanimite", "rsi": (35, 65), "macd": (35, 65), "fng": (35, 65), "mode": "unanimous"},
    {"name": "15/85 uniforme, majoritaire (2/3)", "rsi": (15, 85), "macd": (15, 85), "fng": (15, 85), "mode": "majority"},
    {"name": "20/80 uniforme, majoritaire (2/3)", "rsi": (20, 80), "macd": (20, 80), "fng": (20, 80), "mode": "majority"},
]


def run_variant_period(closes, dates, fng_by_date, variant, lo_idx, hi_idx):
    """Rejoue la variante sur l'intervalle d'index [lo_idx, hi_idx) uniquement,
    en repartant a plat (aucune position/etat heritee d'avant lo_idx)."""
    trades = []
    position = None
    prev_state = "neutral"
    buy_signals = sell_signals = 0

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
            if combined == "buy" and position is None:
                position = {"entry_price": price}
                buy_signals += 1
            elif combined == "sell" and position is not None:
                pct_return = (price - position["entry_price"]) / position["entry_price"] * 100
                trades.append(pct_return)
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
        equity *= (1 + (closes[hi_idx - 1] - position["entry_price"]) / position["entry_price"])

    buy_hold_return = (closes[hi_idx - 1] - closes[lo_idx]) / closes[lo_idx] * 100
    wins = sum(1 for r in trades if r > 0)

    return {
        "buy_signals": buy_signals, "sell_signals": sell_signals,
        "trades": len(trades), "win_rate": (wins / len(trades) * 100) if trades else None,
        "return": equity - 100, "buy_hold_return": buy_hold_return,
        "still_open": position is not None,
    }


def main():
    print("Telechargement de l'historique BTCUSDT (Binance)...")
    klines = fetch_full_daily_klines()
    dates = [datetime.fromtimestamp(k[0] / 1000, tz=timezone.utc).date() for k in klines]
    closes = [float(k[4]) for k in klines]

    print("Telechargement de l'historique Fear & Greed (Alternative.me)...")
    fng_by_date = fetch_fng_history()

    data_start_idx = next(i for i in range(len(closes)) if i + 1 >= WINDOW and dates[i] in fng_by_date)
    split_idx = next(i for i in range(len(dates)) if dates[i] >= SPLIT_DATE)
    end_idx = len(dates)

    print(f"\nPeriode entrainement : {dates[data_start_idx]} -> {dates[split_idx - 1]} "
          f"({split_idx - data_start_idx} jours)")
    print(f"Periode validation    : {dates[split_idx]} -> {dates[end_idx - 1]} "
          f"({end_idx - split_idx} jours, jamais vue pendant le choix)\n")

    rows = []
    for variant in VARIANTS:
        train = run_variant_period(closes, dates, fng_by_date, variant, data_start_idx, split_idx)
        valid = run_variant_period(closes, dates, fng_by_date, variant, split_idx, end_idx)
        beats_train = train["return"] > train["buy_hold_return"]
        beats_valid = valid["return"] > valid["buy_hold_return"]
        rows.append({"name": variant["name"], "train": train, "valid": valid,
                     "robust": beats_train and beats_valid})

    def fmt(r):
        wr = f"{r['win_rate']:.0f}%" if r["win_rate"] is not None else "n/a"
        return f"trades={r['trades']:>2} winrate={wr:>4} rendement={r['return']:>+8.1f}% (B&H {r['buy_hold_return']:>+7.1f}%)"

    print("=" * 118)
    print(f"{'Variante':<44} {'ENTRAINEMENT (calibration)':<46} VALIDATION (hors-echantillon)")
    print("-" * 118)
    for row in rows:
        flag = " <-- robuste (bat B&H sur les 2 periodes)" if row["robust"] else ""
        print(f"{row['name']:<44} {fmt(row['train']):<46} {fmt(row['valid'])}{flag}")
    print("=" * 118)

    robust = [r for r in rows if r["robust"]]
    print(f"\n{len(robust)}/{len(rows)} variante(s) battent le buy & hold SUR LES DEUX PERIODES independamment.")
    for r in robust:
        print(f"  - {r['name']}")


if __name__ == "__main__":
    main()
