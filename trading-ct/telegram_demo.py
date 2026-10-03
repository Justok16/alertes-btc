"""
Envoie sur Telegram des EXEMPLES de chaque type d'alerte du bot, construits
avec les vraies fonctions de formatage (trading_alert.build_message,
trading_alert_eu.build_message, exit_rules.build_exit_message) : le rendu est
exactement celui d'une vraie alerte. Chaque message est marque "MESSAGE DE
TEST" pour ne jamais etre pris pour un vrai signal.

Aucun etat n'est lu ni ecrit (ni fichier, ni Supabase), aucune donnee de
marche n'est appelee : les prix et scores ci-dessous sont fictifs.
Sans TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID, les messages sont seulement
affiches (comme le fait send_telegram).

Usage : python telegram_demo.py
"""

import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).parent))
import exit_rules  # noqa: E402
import trading_alert  # noqa: E402
import trading_alert_eu  # noqa: E402

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.stderr.reconfigure(encoding="utf-8", errors="replace")

TEST_BANNER = "🧪 <b>MESSAGE DE TEST</b> — exemple de format, ce n'est pas un vrai signal\n\n"
HEADER_US = "⚡ <b>Trading CT</b>"
HEADER_EU = "🇪🇺 <b>Trading CT — ETF Europe</b>"


def exemples():
    crypto = {"symbol": "BTCUSDT", "display": "Bitcoin", "price": 61234.5,
              "rsi": 17.8, "macd_score": 19.2, "fng": 16.0}
    europe = {"symbol": "VVSM.XETRA", "display": "VanEck Semiconductor UCITS ETF", "price": 98.42,
              "rsi": 18.4, "macd_score": 14.9, "home_score": 17.6}

    entry = {"price": 61234.5, "ts": (datetime.now(timezone.utc) - timedelta(days=3)).isoformat()}
    cible, stop = exit_rules.exit_rule_for({"asset_class": "crypto"})

    def sortie(kind, price):
        change = (price / entry["price"] - 1) * 100
        return exit_rules.build_exit_message(
            HEADER_US, "Bitcoin", "BTCUSDT", kind, entry, price, change, cible, stop)

    return [
        ("1/6 achat MODÉRÉ (crypto)",
         trading_alert.build_message({**crypto, "combined": "buy", "level": "moderate"})),
        ("2/6 renforcé → FORT",
         trading_alert.build_message({**crypto, "combined": "buy", "level": "strong",
                                      "rsi": 12.1, "macd_score": 13.5, "fng": 14.0}, upgrade=True)),
        ("3/6 objectif atteint", sortie("target", round(entry["price"] * 1.082, 1))),
        ("4/6 stop atteint", sortie("stop", round(entry["price"] * 0.948, 1))),
        ("5/6 fin du suivi (30 jours)", sortie("expired", round(entry["price"] * 1.021, 1))),
        ("6/6 achat MODÉRÉ (ETF Europe)",
         trading_alert_eu.build_message({**europe, "combined": "buy", "level": "moderate"})),
    ]


def main():
    session = requests.Session()
    messages = exemples()
    for i, (titre, message) in enumerate(messages):
        print(f"--- {titre} ---")
        trading_alert.send_telegram(session, TEST_BANNER + message)
        if i < len(messages) - 1:
            time.sleep(1.5)  # evite le rate-limit Telegram et garde l'ordre d'arrivee
    print(f"{len(messages)} messages de test traites.")


if __name__ == "__main__":
    main()
