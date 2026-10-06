"""
Message quotidien "le bot est vivant" (+ detection de cadence degradee).

Un job a part, independant des bots : il interroge l'API GitHub Actions (lecture
seule) et compte les executions des dernieres 24 h de chaque workflow, puis
envoie un verdict sur Telegram. Raison d'etre : le bot crypto/US tourne grace a
un declencheur EXTERNE (workflow_dispatch toutes les 5 min) ; le cron natif de
GitHub, lui, n'est joue que toutes les ~4 h en pratique. Si le declencheur
externe s'arrete (cle expiree, service coupe...), plus rien n'avertit : le bot
"tourne" encore, mais 50x moins souvent. Ce message quotidien le rend visible.

Ce que le message signale (titre ⚠️ au lieu de 🟢) :
  - moins de WARN_MAIN_BELOW executions crypto/US en 24 h (attendu ~288) ;
  - au moins une execution en echec sur 24 h (avec la cause "GitHub n'a pas
    fourni de runner" distinguee d'un vrai echec du bot : c'est une panne de
    GitHub Actions, le script n'a meme pas demarre) ;
  - derniere execution crypto/US vieille de plus de 30 min ;
  - bot Europe/Chine non execute depuis plus de EU_MAX_AGE_HOURS h (3 j 12 h :
    couvre un week-end) ou derniere execution en echec.
Limite assumee : ce job depend lui-meme du cron GitHub (une execution par
jour, decalee de quelques minutes parfois). Un message qui n'arrive pas un
matin est donc, lui aussi, un signal.

Usage : python heartbeat.py   (GITHUB_TOKEN recommande, TELEGRAM_* pour l'envoi)
"""

import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).parent))
from trading_alert import send_telegram  # noqa: E402

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.stderr.reconfigure(encoding="utf-8", errors="replace")

REPO = os.environ.get("GITHUB_REPOSITORY", "Justok16/alertes-btc")
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
RUNS_URL = "https://api.github.com/repos/{repo}/actions/workflows/{workflow}/runs"

WF_MAIN = "trading-ct-alert.yml"
WF_EU = "trading-ct-eu-alert.yml"
EXPECTED_MAIN_24H = 288          # 1 execution / 5 min
WARN_MAIN_BELOW = 200            # ~70 % : en dessous, la cadence est degradee
MAIN_MAX_AGE = timedelta(minutes=30)
EU_MAX_AGE = timedelta(hours=84)  # vendredi 18:00 -> lundi 18:00 + marge

# Message d'annotation que GitHub ajoute a un job qu'aucun runner n'a pris en
# charge (panne GitHub Actions) : le job reste ~15 min sans aucune etape puis
# est marque en echec.
RUNNER_NOT_ACQUIRED = "not acquired by Runner"
# Autre cause d'echec qui n'a rien a voir avec le code : GitHub refuse de DEMARRER
# les jobs quand un paiement a echoue ou que le plafond de depenses Actions est
# atteint ("The job was not started because recent account payments have failed
# or your spending limit needs to be increased"). Vu le 05/10/2026 de 9 h a 11 h
# UTC (52 executions refusees sur le depot pokedeals) et le 20/08 ici. Seul le
# proprietaire du compte peut le resoudre (Settings > Billing).
BILLING_BLOCKED = ("payments have failed", "spending limit")
MAX_RUNS_INSPECTED = 10          # plafond d'appels API (2 par execution inspectee)

HEADER = "<b>Trading CT</b>"


def _get(session, url, params):
    headers = {"Accept": "application/vnd.github+json"}
    if GITHUB_TOKEN:
        headers["Authorization"] = f"Bearer {GITHUB_TOKEN}"
    r = session.get(url, params=params, headers=headers, timeout=20)
    r.raise_for_status()
    return r.json()


def _parse(ts):
    return datetime.fromisoformat(ts.replace("Z", "+00:00")) if ts else None


def count_failure_causes(session, url, created):
    """Parmi les executions en echec, repere celles qui ne viennent PAS du code :
    {"runner_unacquired": n, "billing_blocked": m} (lecture des annotations des
    jobs). Au plus MAX_RUNS_INSPECTED executions inspectees. Jamais bloquant :
    en cas d'erreur de l'API, renvoie des zeros (l'echec reste un echec ordinaire)."""
    causes = {"runner_unacquired": 0, "billing_blocked": 0}
    try:
        runs = _get(session, url, {"created": created, "status": "failure",
                                   "per_page": MAX_RUNS_INSPECTED}).get("workflow_runs") or []
        for run in runs[:MAX_RUNS_INSPECTED]:
            jobs = _get(session, run["jobs_url"], {}).get("jobs") or []
            messages = [
                a.get("message") or ""
                for job in jobs
                for a in _get(session, f"{job['check_run_url']}/annotations", {})
            ]
            if any(RUNNER_NOT_ACQUIRED in m for m in messages):
                causes["runner_unacquired"] += 1
            elif any(k in m for m in messages for k in BILLING_BLOCKED):
                causes["billing_blocked"] += 1
    except Exception as e:  # noqa: BLE001 - diagnostic annexe, ne doit pas casser le heartbeat
        print(f"[heartbeat] diagnostic des echecs impossible : {e}", file=sys.stderr)
        return {"runner_unacquired": 0, "billing_blocked": 0}
    return causes


def workflow_stats(session, repo, workflow, since):
    """Compteurs sur 24 h + derniere execution d'un workflow (3 appels API, plus
    2 par execution en echec inspectee)."""
    url = RUNS_URL.format(repo=repo, workflow=workflow)
    created = f">={since.strftime('%Y-%m-%dT%H:%M:%SZ')}"
    total = _get(session, url, {"created": created, "per_page": 1})["total_count"]
    failures = _get(session, url, {"created": created, "status": "failure", "per_page": 1})["total_count"]
    causes = count_failure_causes(session, url, created) if failures else {"runner_unacquired": 0,
                                                                          "billing_blocked": 0}
    runs = _get(session, url, {"per_page": 1}).get("workflow_runs") or []
    last = runs[0] if runs else None
    return {
        "total": total,
        "failures": failures,
        "runner_unacquired": causes["runner_unacquired"],
        "billing_blocked": causes["billing_blocked"],
        "last_at": _parse(last["created_at"]) if last else None,
        "last_conclusion": (last.get("conclusion") or last.get("status")) if last else None,
    }


def ago(now, then):
    """"il y a 3 min" / "il y a 2 h" / "il y a 3 j"."""
    if then is None:
        return "jamais"
    secondes = max(0, int((now - then).total_seconds()))
    if secondes < 90:
        return "il y a moins de 2 min"
    if secondes < 3600 * 2:
        return f"il y a {secondes // 60} min"
    if secondes < 86400 * 2:
        return f"il y a {secondes // 3600} h"
    return f"il y a {secondes // 86400} j"


def build_message(main, eu, now, repo=REPO):
    """Renvoie (degrade: bool, message)."""
    alertes = []

    if main["total"] < WARN_MAIN_BELOW:
        alertes.append(
            f"Cadence dégradée : {main['total']} exécutions crypto/US en 24 h (attendu ≈ {EXPECTED_MAIN_24H}). "
            "Le déclencheur externe toutes les 5 min s'est peut-être arrêté ; GitHub seul ne lance le bot "
            "que toutes les ~4 h."
        )
    runner = min(main.get("runner_unacquired", 0), main["failures"])
    if runner:
        alertes.append(
            f"{runner} exécution(s) crypto/US en échec car GitHub n'a pas fourni de runner "
            "(« not acquired by Runner ») : panne de GitHub Actions, pas un bug du bot. "
            "Pendant ce temps, aucune vérification n'a eu lieu. Voir githubstatus.com."
        )
    billing = min(main.get("billing_blocked", 0), main["failures"] - runner)
    if billing:
        alertes.append(
            f"{billing} exécution(s) crypto/US refusée(s) par GitHub : paiement échoué ou plafond de "
            "dépenses Actions atteint (« spending limit »). À régler sans attendre dans GitHub > "
            "Settings > Billing : tant que ce n'est pas fait, le bot peut s'arrêter."
        )
    autres = main["failures"] - runner - billing
    if autres:
        alertes.append(f"{autres} exécution(s) crypto/US en échec sur 24 h.")
    if main["last_at"] is None or now - main["last_at"] > MAIN_MAX_AGE:
        alertes.append(f"Dernière exécution crypto/US : {ago(now, main['last_at'])} (plus de 30 min).")

    if eu["last_at"] is None or now - eu["last_at"] > EU_MAX_AGE:
        alertes.append(f"Bot Europe/Chine non exécuté depuis longtemps (dernière : {ago(now, eu['last_at'])}).")
    elif eu["last_conclusion"] not in ("success", "in_progress", "queued"):
        alertes.append(f"Dernière exécution Europe/Chine en échec ({eu['last_conclusion']}).")

    titre = (f"⚠️ {HEADER} — vérification quotidienne : à regarder"
             if alertes else f"🟢 {HEADER} — le bot est vivant")
    lignes = [
        titre,
        "",
        f"⚡ Crypto + actions US : {main['total']} exécutions sur 24 h (≈ {EXPECTED_MAIN_24H} attendues), "
        f"{main['failures']} en échec. Dernière : {ago(now, main['last_at'])}.",
        f"🇪🇺 Europe/Chine : dernière exécution {ago(now, eu['last_at'])} "
        f"({eu['last_conclusion'] or 'aucune'}).",
    ]
    if alertes:
        lignes += [""] + [f"• {a}" for a in alertes]
    lignes += ["", f"Détails : https://github.com/{repo}/actions"]
    return bool(alertes), "\n".join(lignes)


def main():
    now = datetime.now(timezone.utc)
    session = requests.Session()
    try:
        since = now - timedelta(hours=24)
        stats_main = workflow_stats(session, REPO, WF_MAIN, since)
        stats_eu = workflow_stats(session, REPO, WF_EU, since)
    except Exception as e:
        print(f"[heartbeat] lecture de l'API GitHub impossible : {e}", file=sys.stderr)
        send_telegram(session, f"⚠️ {HEADER} — vérification quotidienne : impossible de lire l'état des "
                               "exécutions (API GitHub indisponible). Le bot lui-même n'est pas forcément en panne.")
        sys.exit(1)

    degrade, message = build_message(stats_main, stats_eu, now)
    print(message)
    send_telegram(session, message)
    print("Verdict :", "DEGRADE" if degrade else "OK")


if __name__ == "__main__":
    main()
