"""
Bot d'alertes trading court/moyen terme (crypto + actions/ETF).

Pour chaque actif de watchlist.WATCHLIST, calcule 3 indicateurs independants
ramenes sur une echelle 0-100 et n'envoie une alerte Telegram QUE si les
3 sont d'accord (unanimite, pas de vote majoritaire) sur le meme sens, ET
que l'etat combine vient de changer par rapport a la derniere execution :

  1. RSI(14)                         : <=15 achat, >=85 vente
  2. MACD histogramme normalise (14) : <=15 achat, >=85 vente
  3. Fear & Greed (14)               : <=15 achat, >=85 vente (seuils alignes
     sur RSI/MACD -- voir backtest_walkforward.py, seule variante validee
     hors-echantillon sur l'historique BTC)
     - crypto  : indice Alternative.me (marche crypto global)
     - actions/ETF : score maison (RSI(14) + position dans le range 14
       bougies), pas d'indice F&G officiel par titre individuel

Ceci est un outil de signal technique, PAS un conseil en investissement.
Aucune execution d'ordre n'est faite par ce script.
"""

import concurrent.futures
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import requests

import memoire_supabase
from watchlist import WATCHLIST

# Evite les crashs d'encodage sur console Windows (cp1252) quand on affiche des emojis
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.stderr.reconfigure(encoding="utf-8", errors="replace")

STATE_FILE = Path(__file__).parent / "state.json"

# Migration du 04/09/2026 (audit externe) : etat persiste dans Supabase
# plutot que commite en Git a chaque cycle (cron 5 min -- jusqu'a 288
# commits/jour) -- cf. memoire_supabase.py pour le detail. Repli automatique
# sur STATE_FILE si ces secrets sont absents (migration progressive, rien
# ne casse tant qu'ils ne sont pas ajoutes).
SUPABASE_URL = os.environ.get("SUPABASE_URL", "")
SUPABASE_SERVICE_ROLE_KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")
ETAT_CLE = "trading_ct_state"

# Seuils demandes : stricts des deux cotes, unanimite requise entre les 3 indicateurs
RSI_BUY, RSI_SELL = 15, 85
MACD_BUY, MACD_SELL = 15, 85
FNG_CRYPTO_BUY, FNG_CRYPTO_SELL = 15, 85
HOME_BUY, HOME_SELL = 15, 85

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")
ALPACA_API_KEY_ID = os.environ.get("ALPACA_API_KEY_ID")
ALPACA_API_SECRET_KEY = os.environ.get("ALPACA_API_SECRET_KEY")

BINANCE_KLINES_URL = "https://data-api.binance.vision/api/v3/klines"
ALPACA_BARS_URL = "https://data.alpaca.markets/v2/stocks/{symbol}/bars"
ALTERNATIVE_FNG_URL = "https://api.alternative.me/fng/?limit=1"

HTTP_TIMEOUT = 15

# Audit du 31/08/2026 : fetch_binance_closes() renvoie None sur echec sans
# jamais impacter le code de sortie -- si Binance est en panne durable
# (endpoint change, rate-limit permanent...), TOUS les symboles crypto de
# WATCHLIST echouent a chaque cycle, silencieusement, et le job GitHub
# Actions reste vert indefiniment (contrairement a une panne Alpaca : les
# actifs "stock"/"etf" sont deja legitimement ignores hors horaires de
# marche US, donc pas de signal fiable a distinguer d'un vrai echec --
# seul le cas crypto, actif en continu, est traite ici pour eviter tout
# faux positif). Cron toutes les 5 min : 12 echecs consecutifs = ~1h de
# panne avant d'alerter, memes principes que btc_alert.py.
SEUIL_ECHECS_CRYPTO_CONSECUTIFS = 12


def get_with_retry(session, url, params=None, headers=None, retries=3, backoff=15):
    """GET avec retry en cas de 429 (rate limit) ou d'erreur reseau transitoire."""
    last_exc = None
    for attempt in range(retries):
        try:
            r = session.get(url, params=params, headers=headers, timeout=HTTP_TIMEOUT)
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


def classify(score, buy_threshold, sell_threshold):
    """Classe un score 0-100 en 'buy', 'sell' ou 'neutral'."""
    if score is None:
        return None
    if score <= buy_threshold:
        return "buy"
    if score >= sell_threshold:
        return "sell"
    return "neutral"


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
    return round(100 - (100 / (1 + rs)), 1)


def ema_series(values, period):
    """Serie EMA (seed = SMA des `period` premieres valeurs)."""
    if len(values) < period:
        return []
    multiplier = 2 / (period + 1)
    ema_values = [sum(values[:period]) / period]
    for value in values[period:]:
        ema_values.append((value - ema_values[-1]) * multiplier + ema_values[-1])
    return ema_values


def compute_macd_histogram(closes):
    """Histogramme MACD (EMA12 - EMA26, signal = EMA9 de cette difference)."""
    ema12 = ema_series(closes, 12)
    ema26 = ema_series(closes, 26)
    if not ema12 or not ema26 or len(ema12) < len(ema26):
        return None
    ema12_aligned = ema12[len(ema12) - len(ema26):]
    macd_line = [a - b for a, b in zip(ema12_aligned, ema26)]

    signal_line = ema_series(macd_line, 9)
    if not signal_line:
        return None
    macd_aligned = macd_line[len(macd_line) - len(signal_line):]
    return [m - s for m, s in zip(macd_aligned, signal_line)]


def macd_score(closes, window=14):
    """Position de l'histogramme MACD courant dans son propre min/max sur `window` bougies."""
    histogram = compute_macd_histogram(closes)
    if not histogram or len(histogram) < window:
        return None
    recent = histogram[-window:]
    lo, hi = min(recent), max(recent)
    if hi == lo:
        return None
    return round((recent[-1] - lo) / (hi - lo) * 100, 1)


def stochastic_score(closes, window=14):
    """Position du prix courant dans son propre min/max sur `window` bougies (0-100)."""
    if len(closes) < window:
        return None
    recent = closes[-window:]
    lo, hi = min(recent), max(recent)
    if hi == lo:
        return None
    return (recent[-1] - lo) / (hi - lo) * 100


def home_score(closes):
    """Score 'Fear & Greed' maison pour actions/ETF : RSI(14) + position dans le range 14."""
    rsi14 = compute_rsi(closes, 14)
    stoch14 = stochastic_score(closes, 14)
    if rsi14 is None or stoch14 is None:
        return None
    return round((rsi14 + stoch14) / 2, 1)


def fetch_binance_closes(session, symbol, interval="15m", limit=100):
    try:
        r = get_with_retry(
            session, BINANCE_KLINES_URL, params={"symbol": symbol, "interval": interval, "limit": limit}
        )
        return [float(k[4]) for k in r.json()]
    except Exception as e:
        print(f"[binance] echec pour {symbol}: {e}", file=sys.stderr)
        return None


def fetch_alpaca_closes(session, symbol, timeframe="15Min", limit=100):
    if not ALPACA_API_KEY_ID or not ALPACA_API_SECRET_KEY:
        print(f"[alpaca] cles API manquantes, {symbol} ignore", file=sys.stderr)
        return None
    try:
        r = get_with_retry(
            session,
            ALPACA_BARS_URL.format(symbol=symbol),
            # adjustment=split : evite qu'un split boursier apparaisse comme
            # un faux krach du prix dans les 100 dernieres bougies
            params={"timeframe": timeframe, "limit": limit, "feed": "iex", "adjustment": "split"},
            headers={"APCA-API-KEY-ID": ALPACA_API_KEY_ID, "APCA-API-SECRET-KEY": ALPACA_API_SECRET_KEY},
        )
        bars = r.json().get("bars", [])
        closes = [float(b["c"]) for b in bars]
        return closes or None
    except Exception as e:
        print(f"[alpaca] echec pour {symbol}: {e}", file=sys.stderr)
        return None


def fetch_crypto_fng(session):
    """Fear & Greed Index crypto global (Alternative.me), partage par tous les symboles crypto."""
    try:
        r = get_with_retry(session, ALTERNATIVE_FNG_URL)
        return int(r.json()["data"][0]["value"])
    except Exception as e:
        print(f"[alternative.me] echec: {e}", file=sys.stderr)
        return None


def is_us_market_open():
    """Horaires du marche US, 09:30-16:00 America/New_York, lun-ven.
    Ne tient pas compte des jours feries US : dans ce cas Alpaca ne renverra
    simplement pas de nouvelle bougie, l'actif sera ignore sans consequence."""
    now = datetime.now(ZoneInfo("America/New_York"))
    if now.weekday() >= 5:
        return False
    market_open = now.replace(hour=9, minute=30, second=0, microsecond=0)
    market_close = now.replace(hour=16, minute=0, second=0, microsecond=0)
    return market_open <= now <= market_close


def load_state():
    # Migration du 04/09/2026 : Supabase d'abord si les secrets sont
    # configures (cf. memoire_supabase.py) -- l'etat porte la detection de
    # transition, une lecture ratee doit donc faire ABANDONNER le cycle
    # (sys.exit) plutot que de repartir silencieusement d'un etat vide, ce
    # qui redeclencherait une alerte deja connue. Repli sur STATE_FILE
    # uniquement si les secrets sont absents (migration pas encore faite).
    if SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY:
        etat = memoire_supabase.charger_etat_supabase(ETAT_CLE, SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY)
        if etat is not None:
            return etat
        print("[state] Supabase injoignable apres retry -- abandon du cycle.", file=sys.stderr)
        sys.exit(1)

    # Audit du 30/08/2026 : un fichier corrompu/tronque faisait planter tout
    # le script avant meme d'atteindre les try/except qui protegent le
    # reste -- repli sur un etat vide plutot qu'un crash (meme correctif
    # que btc_alert.py), au pire un signal deja connu est reenvoye une fois.
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError, ValueError) as e:
            print(f"[state] fichier illisible ({e}) -- repli sur un etat vide.", file=sys.stderr)
            return {}
    return {}


def save_state(state):
    # Migration du 04/09/2026 : Supabase d'abord si configure -- si l'appel
    # reussit, STATE_FILE n'est PLUS ecrit du tout (plus rien a committer,
    # l'etape "Commit updated state" du workflow devient un no-op silencieux
    # sans avoir besoin d'etre modifiee). Repli fichier uniquement si les
    # secrets sont absents OU si l'ecriture Supabase a echoue.
    if SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY:
        if memoire_supabase.sauvegarder_etat_supabase(state, ETAT_CLE, SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY):
            return
        print("[state] Échec d'écriture Supabase -- repli sur STATE_FILE pour ce cycle.", file=sys.stderr)

    # Ecriture ATOMIQUE (fichier temporaire + remplacement) -- un process
    # tue en plein milieu (timeout GitHub Actions) ne peut plus laisser
    # state.json tronque, ce qui ferait planter load_state() au run suivant.
    tmp = STATE_FILE.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, STATE_FILE)


def send_telegram(session, message):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("Secrets Telegram manquants, message non envoye:\n" + message)
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    r = session.post(
        url,
        json={"chat_id": TELEGRAM_CHAT_ID, "text": message, "parse_mode": "HTML"},
        timeout=HTTP_TIMEOUT,
    )
    if not r.ok:
        print(f"[telegram] reponse de l'API: {r.status_code} {r.text}", file=sys.stderr)
    r.raise_for_status()


def build_message(result):
    emoji = "🟢 SIGNAL D'ACHAT" if result["combined"] == "buy" else "🔴 SIGNAL DE VENTE"
    lines = [
        f"⚡ <b>Trading CT</b> — {emoji}",
        f"{result['display']} ({result['symbol']}) — prix actuel : {result['price']}",
        "",
        f"• RSI(14) : {result['rsi']}",
        f"• MACD score (14) : {result['macd_score']}",
        f"• Fear & Greed (14) : {result['fng']}",
        "",
        "Signal technique automatise, pas un conseil financier. Decision et execution manuelles.",
    ]
    return "\n".join(lines)


def evaluate_symbol(session, item, crypto_fng_score):
    symbol = item["symbol"]
    asset_class = item["asset_class"]

    if asset_class == "crypto":
        closes = fetch_binance_closes(session, symbol)
        fng_score = crypto_fng_score
        fng_zone = classify(fng_score, FNG_CRYPTO_BUY, FNG_CRYPTO_SELL)
    else:
        if not is_us_market_open():
            print(f"{symbol}: marche US ferme, verification ignoree")
            return None
        closes = fetch_alpaca_closes(session, symbol)
        fng_score = home_score(closes) if closes else None
        fng_zone = classify(fng_score, HOME_BUY, HOME_SELL)

    if not closes:
        return None

    rsi_score = compute_rsi(closes, 14)
    rsi_zone = classify(rsi_score, RSI_BUY, RSI_SELL)

    macd_sc = macd_score(closes, 14)
    macd_zone = classify(macd_sc, MACD_BUY, MACD_SELL)

    print(
        f"{symbol}: RSI={rsi_score} ({rsi_zone}) | MACD={macd_sc} ({macd_zone}) | "
        f"F&G={fng_score} ({fng_zone})"
    )

    zones = {rsi_zone, macd_zone, fng_zone}
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
        "fng": fng_score,
    }


def main():
    state = load_state()
    # Audit du 03/09/2026 : une seule Session() reutilisee pour tout le run
    # (au lieu d'un requests.get/post independant par appel) garde la
    # connexion TCP/TLS ouverte entre les appels vers un meme hote. Partagee
    # entre les threads ci-dessous : sans risque, on ne mute jamais d'etat
    # dessus (pas de session.headers modifie en cours de route) -- le pool de
    # connexions sous-jacent (urllib3) est lui-meme thread-safe.
    session = requests.Session()
    crypto_fng = fetch_crypto_fng(session)
    print(f"Fear & Greed crypto global: {crypto_fng}")

    alerte_echouee = False
    items_crypto = [i for i in WATCHLIST if i["asset_class"] == "crypto"]
    echecs_crypto = 0

    # Audit du 03/09/2026 : evaluate_symbol() est un pur calcul (fetch HTTP +
    # indicateurs) sans aucun effet de bord -- toute mutation d'etat et tout
    # envoi Telegram n'arrivent qu'apres, sequentiellement, dans la boucle
    # ci-dessous. Le fetch de chaque symbole (jusqu'a 3 tentatives avec
    # backoff dans get_with_retry) est justement l'operation la plus lente
    # et purement I/O-bound (le GIL est relache pendant les appels reseau) :
    # les paralleliser avec des threads divise le temps total par ~len(WATCHLIST)
    # au lieu de le cumuler symbole par symbole -- notable avec un cron
    # toutes les 5 minutes. executor.map() renvoie les resultats dans l'ORDRE
    # DE SOUMISSION (donc l'ordre de WATCHLIST), pas l'ordre de completion :
    # la boucle de traitement ci-dessous (alertes, etat, compteur de pannes)
    # reste donc strictement sequentielle et deterministe, identique a
    # l'ancienne version. Seul l'entrelacement des logs print() de
    # evaluate_symbol() (RSI/MACD/F&G par symbole) peut varier d'un run a
    # l'autre -- purement cosmetique, aucun etat ni alerte n'en depend.
    max_workers = min(len(WATCHLIST), 10) or 1
    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
        results = list(executor.map(lambda item: evaluate_symbol(session, item, crypto_fng), WATCHLIST))

    for item, result in zip(WATCHLIST, results):
        if result is None:
            if item["asset_class"] == "crypto":
                echecs_crypto += 1
            continue

        symbol = result["symbol"]
        previous = state.get(symbol, {}).get("combined_state", "neutral")

        if result["combined"] in ("buy", "sell") and result["combined"] != previous:
            try:
                send_telegram(session, build_message(result))
                print(f"Alerte envoyee pour {symbol}: {result['combined']}")
            except Exception as e:
                # Audit du 30/08/2026 : ce `continue` sautait la mise a jour
                # de l'etat, PRECISEMENT le comportement que le bot BTC a ete
                # corrige pour eviter (cf. btc_alert.py) -- avec un cron
                # toutes les 5 min (contre 1x/jour pour le bot BTC), une
                # panne Telegram meme courte faisait retenter LE MEME signal
                # a chaque run (spam de tentatives + job rouge en boucle sur
                # GitHub Actions) plutot qu'une fois. On aligne desormais sur
                # le bot BTC : l'etat est TOUJOURS mis a jour (le signal
                # "consomme" cette transition une seule fois, meme en cas
                # d'echec Telegram), alerte_echouee fait juste echouer le job
                # pour que l'echec reste visible.
                print(f"[telegram] echec de l'envoi pour {symbol}: {e}", file=sys.stderr)
                alerte_echouee = True
        else:
            print(f"{symbol}: pas d'alerte (etat={result['combined']}, precedent={previous})")

        state[symbol] = {"combined_state": result["combined"]}

    # cf. SEUIL_ECHECS_CRYPTO_CONSECUTIFS plus haut. `_meta` : cle reservee,
    # ne peut jamais collisionner avec un symbole (toujours en majuscules).
    meta = state.setdefault("_meta", {"echecs_crypto_consecutifs": 0, "alerte_panne_crypto_envoyee": False})
    panne_crypto_ce_cycle = bool(items_crypto) and echecs_crypto == len(items_crypto)
    if panne_crypto_ce_cycle:
        meta["echecs_crypto_consecutifs"] = meta.get("echecs_crypto_consecutifs", 0) + 1
    else:
        meta["echecs_crypto_consecutifs"] = 0

    if (meta["echecs_crypto_consecutifs"] >= SEUIL_ECHECS_CRYPTO_CONSECUTIFS
            and not meta.get("alerte_panne_crypto_envoyee")):
        try:
            send_telegram(
                session,
                "⚡ <b>Trading CT</b> — ⚠️ Données crypto (Binance) indisponibles\n"
                f"Échec sur {', '.join(i['symbol'] for i in items_crypto)} depuis "
                f"{meta['echecs_crypto_consecutifs']} cycles d'affilée : plus aucun signal crypto "
                "n'est possible tant que ce n'est pas résolu."
            )
            meta["alerte_panne_crypto_envoyee"] = True
        except Exception as e:
            print(f"[telegram] echec de l'alerte de panne crypto: {e}", file=sys.stderr)
    elif not panne_crypto_ce_cycle and meta.get("alerte_panne_crypto_envoyee"):
        try:
            send_telegram(session, "⚡ <b>Trading CT</b> — ✅ Données crypto de nouveau disponibles.")
        except Exception as e:
            print(f"[telegram] echec du message de retour au vert: {e}", file=sys.stderr)
        meta["alerte_panne_crypto_envoyee"] = False

    save_state(state)

    if alerte_echouee:
        sys.exit(1)


if __name__ == "__main__":
    main()
