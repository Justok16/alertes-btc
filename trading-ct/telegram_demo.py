"""
Test complet de TOUTES les alertes du bot, de bout en bout.

Contrairement a un simple envoi d'exemples, chaque scenario passe par la VRAIE
boucle principale (trading_alert.main() / trading_alert_eu.main()) avec des
resultats de strategie simules : decision d'alerte, niveaux fort/modere,
"renforce", objectif/stop/fin de suivi, ventes, pannes de donnees et retours
au vert ; plus les deux bilans quotidiens (bot vivant / cadence degradee, via
heartbeat.build_message). Les messages produits sont envoyes sur ton Telegram, chacun marque
"TEST n/N", et chaque scenario est VERIFIE (un message attendu, avec le bon
contenu). Un recapitulatif final est envoye ; le script sort en erreur (job
rouge) si un scenario echoue ou si un envoi Telegram echoue.

Garanties : l'etat des bots est redirige vers des fichiers temporaires
(STATE_FILE) avec Supabase desactive -- ton vrai etat n'est jamais lu ni
ecrit ; aucune donnee de marche n'est appelee ; prix/scores fictifs.
Sans TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID, les messages sont seulement
affiches (la verification des scenarios reste faite).

Usage : python telegram_demo.py
"""

import json
import sys
import tempfile
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import requests

sys.path.insert(0, str(Path(__file__).parent))
import heartbeat  # noqa: E402
import trading_alert  # noqa: E402
import trading_alert_eu  # noqa: E402

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.stderr.reconfigure(encoding="utf-8", errors="replace")

REAL_SEND = trading_alert.send_telegram  # capture AVANT tout patch
PAUSE_ENTRE_MESSAGES = 1.5  # secondes : evite le rate-limit Telegram, garde l'ordre d'arrivee

BTC = {"symbol": "BTCUSDT", "display": "Bitcoin", "asset_class": "crypto"}
ETF = {"symbol": "VVSM.XETRA", "display": "VanEck Semiconductor UCITS ETF"}


def crypto_result(combined, level, price, rsi, macd, fng):
    return {"symbol": "BTCUSDT", "display": "Bitcoin", "combined": combined, "level": level,
            "price": price, "rsi": rsi, "macd_score": macd, "fng": fng}


def eu_result(combined, level, price, rsi, macd, home):
    return {"symbol": "VVSM.XETRA", "display": ETF["display"], "combined": combined, "level": level,
            "price": price, "rsi": rsi, "macd_score": macd, "home_score": home}


def ancien_horodatage(jours):
    return (datetime.now(timezone.utc) - timedelta(days=jours)).isoformat()


def bilan(total, failures, minutes):
    """Message du bilan quotidien (heartbeat.build_message) pour des statistiques fictives."""
    now = datetime.now(timezone.utc)
    main = {"total": total, "failures": failures, "last_at": now - timedelta(minutes=minutes),
            "last_conclusion": "success"}
    eu = {"total": 1, "failures": 0, "last_at": now - timedelta(hours=14), "last_conclusion": "success"}
    return heartbeat.build_message(main, eu, now)[1]


def scenarios():
    """(label, module, etat_a_injecter|None, resultat_evaluate|None, marqueurs_attendus)

    module = None : message direct (bilan quotidien), `resultat_evaluate` est alors le texte."""
    c, e = trading_alert, trading_alert_eu
    seuil_c = c.SEUIL_ECHECS_CRYPTO_CONSECUTIFS
    seuil_e = e.SEUIL_ECHECS_CONSECUTIFS
    return [
        ("achat MODÉRÉ (crypto)", c, None,
         crypto_result("buy", "moderate", 61000.0, 17.8, 19.2, 16.0), ["ACHAT MODÉRÉ", "20 ou moins"]),
        ("passage MODÉRÉ → FORT (renforcé)", c, None,
         crypto_result("buy", "strong", 60500.0, 12.1, 13.5, 14.0), ["RENFORCÉ → FORT"]),
        ("objectif atteint (+8 %)", c, None,
         crypto_result("neutral", None, 66500.0, 52.0, 48.0, 55.0), ["OBJECTIF ATTEINT"]),
        ("achat FORT (crypto)", c, None,
         crypto_result("buy", "strong", 61000.0, 11.4, 12.9, 13.0), ["ACHAT FORT", "15 ou moins"]),
        ("stop atteint (-5 %)", c, None,
         crypto_result("neutral", None, 57800.0, 40.0, 35.0, 42.0), ["STOP ATTEINT"]),
        ("vente (crypto)", c, None,
         crypto_result("sell", "strong", 63000.0, 91.0, 88.0, 90.0), ["SIGNAL DE VENTE"]),
        ("fin du suivi après 30 jours", c,
         {"BTCUSDT": {"combined_state": "neutral", "entry": {"price": 61000.0, "ts": ancien_horodatage(31)}}},
         crypto_result("neutral", None, 62000.0, 55.0, 50.0, 52.0), ["FIN DU SUIVI"]),
        ("panne des données crypto (Binance)", c,
         {"_meta": {"echecs_crypto_consecutifs": seuil_c - 1, "alerte_panne_crypto_envoyee": False}},
         None, ["Données crypto (Binance) indisponibles"]),
        ("retour au vert des données crypto", c, None,
         crypto_result("neutral", None, 62000.0, 55.0, 50.0, 52.0), ["Données crypto de nouveau disponibles"]),
        ("achat MODÉRÉ (ETF Europe)", e, None,
         eu_result("buy", "moderate", 98.42, 18.4, 14.9, 17.6), ["ETF Europe", "ACHAT MODÉRÉ"]),
        ("vente (ETF Europe)", e, None,
         eu_result("sell", "strong", 112.8, 90.2, 87.5, 91.0), ["ETF Europe", "SIGNAL DE VENTE"]),
        ("panne des données EODHD", e,
         {"_meta": {"echecs_consecutifs": seuil_e - 1, "alerte_panne_envoyee": False}},
         None, ["Données EODHD indisponibles"]),
        ("retour au vert des données EODHD", e, None,
         eu_result("neutral", None, 99.0, 55.0, 50.0, 52.0), ["Données EODHD de nouveau disponibles"]),
        # Bilans quotidiens : messages directs (module None), via la vraie fonction de heartbeat.py
        ("bilan quotidien : bot vivant", None, None,
         bilan(total=288, failures=0, minutes=3), ["le bot est vivant", "288 exécutions"]),
        ("bilan quotidien : cadence dégradée", None, None,
         bilan(total=6, failures=1, minutes=190), ["à regarder", "Cadence dégradée", "en échec"]),
    ]


def merge_state(state_file, patch_state):
    etat = json.loads(state_file.read_text(encoding="utf-8")) if state_file.exists() else {}
    for cle, valeur in patch_state.items():
        if cle == "_meta":
            etat.setdefault("_meta", {}).update(valeur)
        else:
            etat[cle] = valeur
    state_file.write_text(json.dumps(etat), encoding="utf-8")


def main():
    plan = scenarios()
    total = len(plan)
    tmp = tempfile.TemporaryDirectory()
    state_files = {trading_alert: Path(tmp.name) / "crypto_state.json",
                   trading_alert_eu: Path(tmp.name) / "eu_state.json"}
    verdicts = []
    envoyes = []

    def forward(banniere):
        def _send(session, message):
            envoyes.append(message)
            REAL_SEND(session, banniere + message)
            time.sleep(PAUSE_ENTRE_MESSAGES)
        return _send

    for i, (label, module, etat, resultat, marqueurs) in enumerate(plan, start=1):
        envoyes.clear()
        banniere = (f"🧪 <b>TEST {i}/{total} — {label}</b>\n"
                    "Message d'exemple, ce n'est pas un vrai signal.\n\n")
        print(f"--- TEST {i}/{total} : {label} ---")

        if module is None:
            # Message direct (bilan quotidien) : `resultat` est le texte deja construit.
            try:
                forward(banniere)(requests.Session(), resultat)
                sortie_erreur = False
            except Exception:
                sortie_erreur = True
        else:
            if etat:
                merge_state(state_files[module], etat)

            watchlist_patch = (patch.object(module, "WATCHLIST", [BTC]) if module is trading_alert
                               else patch.object(module, "EU_WATCHLIST", [ETF]))
            with watchlist_patch, \
                    patch.object(module, "STATE_FILE", state_files[module]), \
                    patch.object(module, "SUPABASE_URL", ""), \
                    patch.object(module, "SUPABASE_SERVICE_ROLE_KEY", ""), \
                    patch.object(module, "send_telegram", forward(banniere)), \
                    patch.object(module, "evaluate_symbol", return_value=resultat), \
                    patch.object(trading_alert, "fetch_crypto_fng", return_value=50):
                try:
                    module.main()
                    sortie_erreur = False
                except SystemExit as ex:
                    sortie_erreur = bool(ex.code)

        probleme = None
        if sortie_erreur:
            probleme = "envoi Telegram échoué"
        elif len(envoyes) != 1:
            probleme = f"{len(envoyes)} message(s) au lieu de 1"
        else:
            manquants = [m for m in marqueurs if m not in envoyes[0]]
            if manquants:
                probleme = f"contenu inattendu (manque : {', '.join(manquants)})"
        verdicts.append((label, probleme))
        print(f"    -> {'OK' if probleme is None else 'ECHEC : ' + probleme}")

    tmp.cleanup()
    ok = sum(1 for _, p in verdicts if p is None)
    lignes = [f"🧪 <b>TEST COMPLET — {ok}/{total} scénarios OK</b>"]
    for label, probleme in verdicts:
        lignes.append(("✅ " if probleme is None else "❌ ") + label + ("" if probleme is None else f" — {probleme}"))
    lignes += ["", "Aucun état réel n'a été lu ni modifié ; prix et scores fictifs."]
    try:
        REAL_SEND(requests.Session(), "\n".join(lignes))
    except Exception as ex:  # le recapitulatif ne doit pas masquer le verdict
        print(f"[telegram] echec du recapitulatif : {ex}", file=sys.stderr)
    print(f"{ok}/{total} scenarios OK")
    return 0 if ok == total else 1


if __name__ == "__main__":
    sys.exit(main())
