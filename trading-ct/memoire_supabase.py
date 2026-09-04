"""
Persistance d'etat via Supabase -- remplace le JSON commite en Git a chaque
cycle (state.json/eu_state.json). Ajoute le 04/09/2026 suite a un audit
externe convergent (Gemini/ChatGPT/DeepSeek) signalant ce commit-par-cycle
comme anti-pattern structurel : jusqu'a 288 commits/jour rien que pour
trading-ct-alert.yml (cron 5 min), qui pollue l'historique Git sans raison
architecturale -- Git n'est pas une base de donnees. Meme chantier deja
mene avec succes sur le depot pokedeals (scraper/memoire_supabase.py,
migration "memoire hors de Git" du 24/08/2026), reutilise ici a l'identique
pour le meme projet Supabase (deja provisionne pour pokedeals-saas, aucun
nouveau service a payer/maintenir).

Reutilise le meme projet Supabase que pokedeals-saas (table dediee
`alertes_btc_memoire`, DISTINCTE de `scraper_memoire` -- cle namespace
different, aucun lien avec les donnees utilisateur du dashboard Pokemon) :

    create table alertes_btc_memoire (
      cle text primary key,
      donnees jsonb not null default '{}'::jsonb,
      maj_le timestamptz not null default now()
    );
    alter table alertes_btc_memoire enable row level security;
    -- Aucune policy anon/authenticated : accessible uniquement via
    -- service_role, jamais expose cote client.

Secrets requis (NOUVEAUX pour ce depot, a ajouter dans Settings > Secrets
and variables > Actions) : SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY.

PAS "optionnel et non bloquant" (contrairement aux ponts Supabase du depot
pokedeals qui touchent des fonctionnalites annexes) : cet etat porte la
detection de TRANSITION (achat/vente/neutre) qui evite de spammer la meme
alerte a chaque cycle -- une lecture ratee qui renverrait silencieusement
{} ferait perdre l'etat connu et pourrait re-declencher une alerte pour un
signal deja notifie. charger_etat_supabase() distingue donc explicitement :
  - dict (potentiellement vide {}) : lecture reussie, {} = vraiment aucun
    etat pour cette cle (premiere execution).
  - None : Supabase injoignable/erreur meme apres retry -- l'appelant DOIT
    abandonner le cycle plutot que de continuer avec un etat vide (meme
    principe que memoire_supabase.py cote pokedeals).

Migration PROGRESSIVE et retro-compatible : si SUPABASE_URL/
SUPABASE_SERVICE_ROLE_KEY sont absents (secrets pas encore ajoutes), chaque
bot continue de fonctionner exactement comme avant (repli sur le fichier
JSON local + commit Git par le workflow) -- rien ne casse tant que les
secrets ne sont pas configures. Une fois les secrets ajoutes, l'ecriture
locale s'arrete d'elle-meme (plus rien a committer), et les etapes "Commit
updated state" des workflows deviennent des no-op silencieux sans avoir
besoin d'etre modifiees.
"""
from __future__ import annotations

import logging
import time
from datetime import datetime, timezone

import requests

log = logging.getLogger("alertes_btc.memoire_supabase")

TIMEOUT = 20
TENTATIVES = 3
BACKOFF_SECONDES = 5


def _requete_avec_retry(methode, url, **kwargs):
    """Retry minimal (3 tentatives, backoff fixe) sur erreur reseau/5xx --
    memes garanties que get_with_retry() de chaque bot, mais autonome ici
    pour ne pas creer de dependance croisee entre ce module et les scripts
    qui l'utilisent (pas de session partagee requise)."""
    derniere_erreur = None
    for tentative in range(1, TENTATIVES + 1):
        try:
            r = methode(url, timeout=TIMEOUT, **kwargs)
            if r.status_code >= 500:
                r.raise_for_status()
            return r
        except requests.RequestException as e:
            derniere_erreur = e
            if tentative < TENTATIVES:
                time.sleep(BACKOFF_SECONDES)
    raise derniere_erreur


def charger_etat_supabase(cle: str, supabase_url: str, service_role_key: str) -> dict | None:
    """Retourne l'etat associe a `cle`, {} si la cle n'existe pas encore
    (premiere execution), ou None si Supabase est injoignable/en erreur
    apres retry -- l'appelant doit alors ABANDONNER le cycle plutot que de
    continuer avec un etat vide (cf. docstring du module)."""
    if not supabase_url or not service_role_key:
        return None
    try:
        r = _requete_avec_retry(
            requests.get,
            f"{supabase_url.rstrip('/')}/rest/v1/alertes_btc_memoire",
            params={"select": "donnees", "cle": f"eq.{cle}"},
            headers={"apikey": service_role_key, "Authorization": f"Bearer {service_role_key}"},
        )
        r.raise_for_status()
        lignes = r.json()
        return lignes[0]["donnees"] if lignes else {}
    except (requests.RequestException, ValueError, KeyError, IndexError) as e:
        log.error("[memoire_supabase] Lecture de '%s' échouée : %s", cle, e)
        return None


def sauvegarder_etat_supabase(etat: dict, cle: str, supabase_url: str, service_role_key: str) -> bool:
    """Ecrit (upsert) l'etat complet sous `cle`. Retourne False en cas
    d'echec (reseau, erreur API) -- l'appelant doit alors le signaler
    clairement (l'etat de ce cycle est perdu)."""
    if not supabase_url or not service_role_key:
        return False
    try:
        r = _requete_avec_retry(
            requests.post,
            f"{supabase_url.rstrip('/')}/rest/v1/alertes_btc_memoire",
            params={"on_conflict": "cle"},
            json={
                "cle": cle,
                "donnees": etat,
                "maj_le": datetime.now(timezone.utc).isoformat(),
            },
            headers={
                "apikey": service_role_key,
                "Authorization": f"Bearer {service_role_key}",
                "Content-Type": "application/json",
                "Prefer": "resolution=merge-duplicates",
            },
        )
        r.raise_for_status()
        return True
    except requests.RequestException as e:
        log.error("[memoire_supabase] Écriture de '%s' échouée : %s", cle, e)
        return False
