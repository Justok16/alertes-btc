"""
Bot d'alertes pour les ETF europeens (Xetra) de eu_watchlist.EU_WATCHLIST,
via l'API EODHD (donnees journalieres ajustees splits/dividendes).

Meme logique que trading_alert.py (RSI(14) + MACD normalise(14) + score
maison(14), unanimite, seuils 15/85), mais verification une seule fois par
jour : le tier gratuit EODHD est limite a 20 appels API/jour, incompatible
avec le cron 15 min du reste du bot (4 ETF x plusieurs verifications/jour
depasserait vite le quota). Un ETF est de toute facon un horizon plus
moyen terme qu'un check quotidien suffit a couvrir.

Ceci est un outil de signal technique, PAS un conseil en investissement.
Aucune execution d'ordre n'est faite par ce script.
"""

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from eu_watchlist import EU_WATCHLIST  # noqa: E402
from trading_alert import (  # noqa: E402
    HOME_BUY, HOME_SELL, MACD_BUY, MACD_SELL, RSI_BUY, RSI_SELL,
    classify, compute_rsi, get_with_retry, home_score, macd_score, send_telegram,
)

import json
import os

# Evite les crashs d'encodage sur console Windows (cp1252) quand on affiche des emojis
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.stderr.reconfigure(encoding="utf-8", errors="replace")

STATE_FILE = Path(__file__).parent / "eu_state.json"
EODHD_API_TOKEN = os.environ.get("EODHD_API_TOKEN")
EODHD_EOD_URL = "https://eodhd.com/api/eod/{symbol}"
WINDOW = 100


def fetch_eodhd_closes(symbol, history_days=200):
    if not EODHD_API_TOKEN:
        print(f"[eodhd] cle API manquante, {symbol} ignore", file=sys.stderr)
        return None
    try:
        from_date = (datetime.now(timezone.utc) - timedelta(days=history_days)).strftime("%Y-%m-%d")
        r = get_with_retry(
            EODHD_EOD_URL.format(symbol=symbol),
            params={"api_token": EODHD_API_TOKEN, "fmt": "json", "period": "d", "order": "a", "from": from_date},
        )
        data = r.json()
        # adjusted_close corrige les splits/dividendes (meme raison que
        # adjustment=split cote Alpaca : eviter un faux krach dans les donnees)
        closes = [float(d.get("adjusted_close") or d["close"]) for d in data]
        return closes or None
    except Exception as e:
        print(f"[eodhd] echec pour {symbol}: {e}", file=sys.stderr)
        return None


def load_state():
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    return {}


def save_state(state):
    STATE_FILE.write_text(json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8")


def build_message(result):
    emoji = "🟢 SIGNAL D'ACHAT" if result["combined"] == "buy" else "🔴 SIGNAL DE VENTE"
    lines = [
        f"🇪🇺 <b>Trading CT — ETF Europe</b> — {emoji}",
        f"{result['display']} ({result['symbol']}) — prix actuel : {result['price']}",
        "",
        f"• RSI(14) : {result['rsi']}",
        f"• MACD score (14) : {result['macd_score']}",
        f"• Score maison (14) : {result['home_score']}",
        "",
        "Signal technique automatise, pas un conseil financier. Decision et execution manuelles.",
    ]
    return "\n".join(lines)


def evaluate_symbol(item):
    symbol = item["symbol"]
    closes = fetch_eodhd_closes(symbol)
    if not closes or len(closes) < WINDOW:
        print(f"{symbol}: pas assez de donnees ({len(closes) if closes else 0} bougies)")
        return None
    closes = closes[-WINDOW:]

    rsi_score = compute_rsi(closes, 14)
    rsi_zone = classify(rsi_score, RSI_BUY, RSI_SELL)

    macd_sc = macd_score(closes, 14)
    macd_zone = classify(macd_sc, MACD_BUY, MACD_SELL)

    home_sc = home_score(closes)
    home_zone = classify(home_sc, HOME_BUY, HOME_SELL)

    print(
        f"{symbol}: RSI={rsi_score} ({rsi_zone}) | MACD={macd_sc} ({macd_zone}) | "
        f"Score maison={home_sc} ({home_zone})"
    )

    zones = {rsi_zone, macd_zone, home_zone}
    if zones == {"buy"}:
        combined = "buy"
    elif zones == {"sell"}:
        combined = "sell"
    else:
        combined = "neutral"

    return {
        "symbol": symbol,
        "display": item["display"],
        "combined": combined,
        "price": closes[-1],
        "rsi": rsi_score,
        "macd_score": macd_sc,
        "home_score": home_sc,
    }


def main():
    state = load_state()
    alerte_echouee = False

    for item in EU_WATCHLIST:
        result = evaluate_symbol(item)
        if result is None:
            continue

        symbol = result["symbol"]
        previous = state.get(symbol, {}).get("combined_state", "neutral")

        if result["combined"] in ("buy", "sell") and result["combined"] != previous:
            try:
                send_telegram(build_message(result))
                print(f"Alerte envoyee pour {symbol}: {result['combined']}")
            except Exception as e:
                print(f"[telegram] echec de l'envoi pour {symbol}: {e}", file=sys.stderr)
                alerte_echouee = True
                continue
        else:
            print(f"{symbol}: pas d'alerte (etat={result['combined']}, precedent={previous})")

        state[symbol] = {"combined_state": result["combined"]}

    save_state(state)

    if alerte_echouee:
        sys.exit(1)


if __name__ == "__main__":
    main()
