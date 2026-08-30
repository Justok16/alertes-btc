"""
Bot d'alerte Bitcoin : detecte les moments de peur/avidite extreme
et envoie une notification Telegram uniquement au PASSAGE du seuil.

Sources (2 obligatoires + 1 bonus non bloquant) :
  1. Alternative.me Fear & Greed Index (officiel, gratuit, stable)
  2. CoinGecko "maison" : distance a l'ATH + RSI hebdomadaire
  3. CoinMarketCap Fear & Greed (endpoint keyless non officiel, best-effort)

Une alerte n'est envoyee que si :
  - au moins 2 sources actives sont d'accord sur le meme sens (achat ou vente)
  - ET l'etat combine vient de CHANGER par rapport a la derniere execution
    (pas de repetition tant qu'on reste dans la meme zone)
"""

import json
import os
import sys
import time
from pathlib import Path

import requests

# Evite les crashs d'encodage sur console Windows (cp1252) quand on affiche des emojis
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.stderr.reconfigure(encoding="utf-8", errors="replace")

STATE_FILE = Path(__file__).parent / "state.json"

# Seuils Fear & Greed (0-100). <= BUY_THRESHOLD => peur extreme => achat
# >= SELL_THRESHOLD => avidite extreme => vente. Meme rigueur des deux cotes.
BUY_THRESHOLD = 20
SELL_THRESHOLD = 80

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

HTTP_TIMEOUT = 15


def get_with_retry(url, params=None, headers=None, retries=3, backoff=20):
    """GET avec retry en cas de 429 (rate limit), frequent sur les API publiques
    gratuites partagees par IP. En usage 1x/jour, quelques secondes d'attente
    suffisent generalement a passer le pic de trafic partage."""
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


def classify(score):
    """Classe un score 0-100 en 'buy', 'sell' ou 'neutral'."""
    if score is None:
        return None
    if score <= BUY_THRESHOLD:
        return "buy"
    if score >= SELL_THRESHOLD:
        return "sell"
    return "neutral"


def fetch_alternative_fng():
    """Source obligatoire 1 : Alternative.me Fear & Greed Index."""
    try:
        r = get_with_retry("https://api.alternative.me/fng/?limit=1")
        data = r.json()["data"][0]
        score = int(data["value"])
        return score, classify(score)
    except Exception as e:
        print(f"[alternative.me] echec: {e}", file=sys.stderr)
        return None, None


def fetch_cmc_fng():
    """Source bonus (non bloquante) : CoinMarketCap F&G, endpoint keyless."""
    try:
        r = get_with_retry(
            "https://pro-api.coinmarketcap.com/public-api/v3/fear-and-greed/latest",
            headers={"Accept": "application/json"},
            retries=1,
        )
        score = int(r.json()["data"]["value"])
        return score, classify(score)
    except Exception as e:
        print(f"[coinmarketcap] indisponible (normal si l'endpoint change): {e}", file=sys.stderr)
        return None, None


def compute_rsi(closes, period=14):
    """RSI classique (moyenne simple) sur une liste de cours de cloture."""
    if len(closes) < period + 1:
        return None
    deltas = [closes[i] - closes[i - 1] for i in range(1, len(closes))]
    gains = [d if d > 0 else 0 for d in deltas]
    losses = [-d if d < 0 else 0 for d in deltas]

    avg_gain = sum(gains[-period:]) / period
    avg_loss = sum(losses[-period:]) / period

    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def weekly_closes_from_daily(daily_prices):
    """Reechantillonne des cours journaliers [ [ts_ms, price], ... ] en cloture hebdo."""
    weekly = []
    for i in range(0, len(daily_prices), 7):
        week_chunk = daily_prices[i:i + 7]
        if week_chunk:
            weekly.append(week_chunk[-1][1])
    return weekly


def fetch_coingecko_signal():
    """Source obligatoire 2 : calcul maison via CoinGecko (gratuit, sans cle)."""
    try:
        r = get_with_retry(
            "https://api.coingecko.com/api/v3/coins/bitcoin",
            params={
                "localization": "false",
                "tickers": "false",
                "market_data": "true",
                "community_data": "false",
                "developer_data": "false",
            },
        )
        market_data = r.json()["market_data"]
        current_price = market_data["current_price"]["usd"]
        ath = market_data["ath"]["usd"]
        ath_distance_pct = (current_price - ath) / ath * 100  # negatif si sous l'ATH

        r2 = get_with_retry(
            "https://api.coingecko.com/api/v3/coins/bitcoin/market_chart",
            # CoinGecko limite l'historique gratuit sans cle API a 365 jours
            params={"vs_currency": "usd", "days": "365"},
        )
        daily_prices = r2.json()["prices"]
        weekly_closes = weekly_closes_from_daily(daily_prices)
        rsi_weekly = compute_rsi(weekly_closes, period=14)

        if rsi_weekly is None:
            print("[coingecko] pas assez de donnees pour le RSI hebdo", file=sys.stderr)
            return None, None

        # Composante ATH : -80% ou pire => 0 (peur extreme), 0% (a l'ATH) => 100 (avidite extreme)
        ath_component = max(0, min(100, 100 + (ath_distance_pct / 80) * 100))
        # RSI est deja sur une echelle 0-100 comparable au F&G Index
        rsi_component = rsi_weekly

        score = (ath_component + rsi_component) / 2
        return round(score, 1), classify(score)
    except Exception as e:
        print(f"[coingecko] echec: {e}", file=sys.stderr)
        return None, None


_ETAT_PAR_DEFAUT = {"alternative_zone": "neutral", "coingecko_zone": "neutral",
                    "cmc_zone": "neutral", "combined_state": "neutral"}


def load_state():
    # Audit du 30/08/2026 : un fichier corrompu/tronque (ex. process tue en
    # plein ecriture, cf. save_state ci-dessous avant son propre correctif)
    # faisait planter tout le script avant meme d'atteindre les try/except
    # qui protegent le reste -- repli sur l'etat neutre par defaut plutot
    # qu'un crash, au pire une alerte deja connue est reenvoyee une fois.
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError, ValueError) as e:
            print(f"[state] fichier illisible ({e}) -- repli sur l'etat neutre par defaut.", file=sys.stderr)
            return dict(_ETAT_PAR_DEFAUT)
    return dict(_ETAT_PAR_DEFAUT)


def save_state(state):
    # Ecriture ATOMIQUE (fichier temporaire + remplacement) -- un process
    # tue en plein milieu (timeout GitHub Actions) ne peut plus laisser
    # state.json tronque, ce qui ferait planter load_state() au run suivant.
    tmp = STATE_FILE.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, STATE_FILE)


def send_telegram(message):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("Secrets Telegram manquants, message non envoye:\n" + message)
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    r = requests.post(
        url,
        json={"chat_id": TELEGRAM_CHAT_ID, "text": message, "parse_mode": "HTML"},
        timeout=HTTP_TIMEOUT,
    )
    if not r.ok:
        print(f"[telegram] reponse de l'API: {r.status_code} {r.text}", file=sys.stderr)
    r.raise_for_status()


def build_message(direction, score_alt, score_cg, score_cmc):
    emoji = "🟢 SIGNAL D'ACHAT" if direction == "buy" else "🔴 SIGNAL DE VENTE"
    zone = "peur extreme" if direction == "buy" else "avidite extreme"
    lines = [f"🟠 <b>BTC Alert</b> — {emoji}", f"Le marche Bitcoin entre en zone de {zone}.", ""]
    if score_alt is not None:
        lines.append(f"• Alternative.me F&G : {score_alt}/100")
    if score_cg is not None:
        lines.append(f"• Score maison (ATH + RSI hebdo) : {score_cg}/100")
    if score_cmc is not None:
        lines.append(f"• CoinMarketCap F&G : {score_cmc}/100")
    return "\n".join(lines)


def main():
    state = load_state()

    score_alt, zone_alt = fetch_alternative_fng()
    score_cg, zone_cg = fetch_coingecko_signal()
    score_cmc, zone_cmc = fetch_cmc_fng()

    print(f"Alternative.me: score={score_alt} zone={zone_alt}")
    print(f"CoinGecko maison: score={score_cg} zone={zone_cg}")
    print(f"CoinMarketCap (bonus): score={score_cmc} zone={zone_cmc}")

    zones = [z for z in (zone_alt, zone_cg, zone_cmc) if z is not None]

    buy_votes = zones.count("buy")
    sell_votes = zones.count("sell")

    if buy_votes >= 2:
        combined_state = "buy"
    elif sell_votes >= 2:
        combined_state = "sell"
    else:
        combined_state = "neutral"

    previous_combined = state.get("combined_state", "neutral")

    # L'envoi Telegram est entoure d'un try/except : si Telegram echoue
    # (token invalide, timeout, erreur temporaire de leur API...), l'etat du
    # jour doit quand meme etre sauvegarde plus bas. Sans ce garde-fou, un
    # echec d'envoi empechait save_state() de s'executer (exception non
    # rattrapee qui arretait tout le script avant), et le lendemain le
    # script retentait d'envoyer la MEME alerte en boucle jusqu'a ce que
    # Telegram remarche, potentiellement avec un signal devenu perime
    # entre-temps.
    alerte_echouee = False
    if combined_state in ("buy", "sell") and combined_state != previous_combined:
        message = build_message(combined_state, score_alt, score_cg, score_cmc)
        try:
            send_telegram(message)
            print("Alerte envoyee:", combined_state)
        except Exception as e:
            print(f"[telegram] echec de l'envoi: {e}", file=sys.stderr)
            alerte_echouee = True
    else:
        print("Pas d'alerte (etat inchange ou pas assez de sources d'accord).")

    state["alternative_zone"] = zone_alt or state.get("alternative_zone", "neutral")
    state["coingecko_zone"] = zone_cg or state.get("coingecko_zone", "neutral")
    state["cmc_zone"] = zone_cmc or state.get("cmc_zone", "neutral")
    state["combined_state"] = combined_state
    save_state(state)

    if alerte_echouee:
        # Etat bien sauvegarde (ci-dessus) malgre l'echec -- on fait quand
        # meme echouer le job GitHub Actions pour que l'echec reste visible
        # dans l'onglet Actions plutot que de passer inaperçu.
        sys.exit(1)


if __name__ == "__main__":
    main()
