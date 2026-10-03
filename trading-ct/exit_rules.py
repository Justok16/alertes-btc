"""
Regles de sortie par le prix, partagees par trading_alert.py (crypto + actions
US, toutes les 5 min) et trading_alert_eu.py (Europe/Chine, 1x/jour).

Le bot n'execute rien et ne connait pas les positions reelles de
l'utilisateur : le suivi est donc calcule PAR RAPPORT AU PRIX DE L'ALERTE
D'ACHAT envoyee. Quand une alerte d'achat part, le prix et l'horodatage sont
memorises dans l'etat du symbole ("entry"). Aux cycles suivants, une alerte de
sortie est envoyee une seule fois si :
  - target  : le cours a gagne au moins +target % depuis l'alerte d'achat ;
  - stop    : le cours a perdu au moins -stop % depuis l'alerte d'achat ;
  - expired : EXIT_MAX_DAYS jours se sont ecoules sans que ni l'un ni l'autre
              ne soit touche (fin du suivi, pour ne pas garder une entree
              perimee indefiniment).
Une alerte de VENTE de la strategie ferme aussi le suivi (le signal de sortie
de la strategie remplace la regle de prix).

Valeurs par defaut :
  - crypto +8 % / -5 % : choisies sur l'historique des alertes d'achat BTC/ETH
    en bougies 15 min (365 j) -- objectif atteint avant le stop dans environ
    53-56 % des cas ; des stops plus serres (-3/-4 %) sont touches par le
    simple bruit des bougies. Echantillon d'une seule annee, a prendre comme
    un repere, pas comme une garantie.
  - actions/ETF +6 % / -4 % : valeurs NON testees (pas de backtest dedie),
    plus serrees car ces actifs bougent moins que la crypto.
Surcharge par actif possible dans la watchlist : "exit_rule": (target, stop).

Ceci est un outil de signal technique, PAS un conseil en investissement.
"""

from datetime import datetime

EXIT_RULES = {
    "crypto": (8.0, 5.0),
    "stock": (6.0, 4.0),
    "etf": (6.0, 4.0),
}
DEFAULT_EXIT_RULE = (6.0, 4.0)
EXIT_MAX_DAYS = 30


def exit_rule_for(item):
    """(target %, stop %) d'un element de watchlist."""
    rule = item.get("exit_rule")
    if rule:
        return float(rule[0]), float(rule[1])
    return EXIT_RULES.get(item.get("asset_class"), DEFAULT_EXIT_RULE)


def _entry_valide(entry):
    return (
        isinstance(entry, dict)
        and isinstance(entry.get("price"), (int, float))
        and entry["price"] > 0
    )


def check_exit(entry, price, now, target_pct, stop_pct, max_days=EXIT_MAX_DAYS):
    """None, ou (kind, variation_en_pct) avec kind dans target/stop/expired."""
    change = (price / entry["price"] - 1) * 100
    if change >= target_pct:
        return "target", change
    if change <= -stop_pct:
        return "stop", change
    try:
        age_days = (now - datetime.fromisoformat(entry["ts"])).total_seconds() / 86400
    except (KeyError, ValueError, TypeError):
        age_days = 0  # horodatage illisible : pas d'expiration, objectif/stop restent actifs
    if age_days >= max_days:
        return "expired", change
    return None


def step_position(entry, new_alert, alert_sent, price, now, target_pct, stop_pct):
    """Met a jour le suivi de position d'UN symbole pour ce cycle.

    entry       : dict {"price", "ts"} memorise a la derniere alerte d'achat, ou None
    new_alert   : "buy" / "sell" si une alerte de la strategie a ete tentee ce
                  cycle, sinon None
    alert_sent  : True si l'envoi Telegram de cette alerte a reussi
    Renvoie (entry_apres, exit_event) ; exit_event vaut None ou (kind, change_pct).
    """
    if not _entry_valide(entry):
        entry = None
    exit_event = None

    if new_alert == "sell":
        # Le signal de vente de la strategie remplace la regle de prix.
        return None, None

    if entry is not None:
        exit_event = check_exit(entry, price, now, target_pct, stop_pct)
        if exit_event is not None:
            entry = None

    # Pas d'ecrasement d'un suivi deja ouvert ; on n'ouvre un suivi que si
    # l'utilisateur a bien recu l'alerte d'achat.
    if new_alert == "buy" and alert_sent and entry is None:
        entry = {"price": price, "ts": now.isoformat()}
    return entry, exit_event


def build_exit_message(header, display, symbol, kind, entry, price, change_pct,
                       target_pct, stop_pct, max_days=EXIT_MAX_DAYS):
    depuis = str(entry.get("ts", ""))[:10] or "date inconnue"
    if kind == "target":
        titre = f"🎯 OBJECTIF ATTEINT (+{target_pct:g} %)"
    elif kind == "stop":
        titre = f"🛑 STOP ATTEINT (-{stop_pct:g} %)"
    else:
        titre = f"⏱ FIN DU SUIVI ({max_days} jours)"
    lines = [
        f"{header} — {titre}",
        f"{display} ({symbol})",
        f"Variation depuis l'alerte d'achat du {depuis} : {change_pct:+.1f} % "
        f"({entry['price']} → {price})",
    ]
    if kind == "expired":
        lines.append("Ni l'objectif ni le stop n'ont été touchés : le suivi de cette alerte s'arrête.")
    lines += [
        "",
        "Règle de prix automatique, calculée par rapport au prix de l'alerte d'achat "
        "(pas à ta position réelle). Pas un conseil financier. Décision et exécution manuelles.",
    ]
    return "\n".join(lines)
