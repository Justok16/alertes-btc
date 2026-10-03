"""
Verifie qu'un ou plusieurs codes EODHD (ex. BY6.XETRA) renvoient bien des
donnees, AVANT de les ajouter a eu_watchlist.py : affiche pour chacun la
derniere date, le dernier cours et le nombre de bougies recues, a comparer
au cours affiche dans ton application de courtage pour confirmer que c'est
bien le bon instrument.

Usage : python eodhd_probe.py BY6.XETRA 4BY.XETRA ...
Necessite EODHD_API_TOKEN. Un appel API par code (quota gratuit : 20/jour) ;
les erreurs 4xx (404 code inconnu, 401 cle invalide) ne sont pas retentees,
donc un code faux ne coute qu'un appel.
"""

import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).parent))
from trading_alert import get_with_retry  # noqa: E402

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.stderr.reconfigure(encoding="utf-8", errors="replace")

EODHD_API_TOKEN = os.environ.get("EODHD_API_TOKEN")
EODHD_EOD_URL = "https://eodhd.com/api/eod/{symbol}"


def main():
    symbols = sys.argv[1:]
    if not symbols:
        print("Usage : python eodhd_probe.py CODE.EXCHANGE [CODE.EXCHANGE ...]")
        sys.exit(2)
    if not EODHD_API_TOKEN:
        print("EODHD_API_TOKEN manquant dans l'environnement", file=sys.stderr)
        sys.exit(1)

    from_date = (datetime.now(timezone.utc) - timedelta(days=10)).strftime("%Y-%m-%d")
    session = requests.Session()

    print(f"{'Code':<14} {'Statut':<7} {'Derniere date':<14} {'Dernier cours':>14}  Bougies")
    print("-" * 62)
    for symbol in symbols:
        try:
            r = get_with_retry(
                session,
                EODHD_EOD_URL.format(symbol=symbol),
                params={"api_token": EODHD_API_TOKEN, "fmt": "json", "period": "d", "order": "a", "from": from_date},
            )
            data = r.json()
            if not data:
                print(f"{symbol:<14} {'VIDE':<7} (reponse sans bougie sur les 10 derniers jours)")
                continue
            last = data[-1]
            close = last.get("adjusted_close") or last["close"]
            print(f"{symbol:<14} {'OK':<7} {last['date']:<14} {float(close):>14.4f}  {len(data)}")
        except Exception as e:
            # Le token est dans l'URL de l'exception : on ne l'affiche jamais.
            msg = str(e).split(" for url:")[0]
            print(f"{symbol:<14} {'KO':<7} {msg}")


if __name__ == "__main__":
    main()
