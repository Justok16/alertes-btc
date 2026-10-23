# Trading CT — alertes long terme sur les baisses (crypto + actions/ETF)

Bot d'alertes techniques multi-actifs, dans le meme esprit que le bot BTC
momentum du dossier parent : verification periodique, alerte Telegram
uniquement au **passage** d'un seuil (pas de spam tant qu'on reste dans la
meme zone).

**Ce n'est pas un conseil en investissement.** Aucun systeme ne "gagne a
tous les coups" a court terme, et ce bot n'execute aucun ordre : il se
contente d'un signal technique, l'achat/vente reste 100% manuel, sur la
plateforme de ton choix.

## Strategie long terme (par defaut depuis le 23/10/2026)

Le bot est regle pour un investisseur **long terme qui achete sur les
baisses marquees**. Concretement :

- **Bougies journalieres** pour tous les actifs (actions/ETF US et crypto
  passent de 15 min a 1 jour ; l'Europe etait deja en journalier). Une alerte
  ne part que si les 3 indicateurs journaliers sont a 20 ou moins en meme
  temps : une vraie baisse de plusieurs jours, pas un creux de quelques heures.
- **Les alertes d'achat changent de nom** :
  - « 💶 RAPPEL DE VERSEMENT » pour une ligne que tu detiens deja
    (`"detenu": True` dans `watchlist.py` / `eu_watchlist.py` : BTC, SEC0 et
    VVSM depuis le 22/10/2026) -- un versement supplementaire, en plus du
    plan programme, se fait la a meilleur prix ;
  - « 💶 OPPORTUNITÉ LONG TERME » pour les autres actifs suivis.
  Les niveaux restent BAISSE MARQUÉE (<= 20), BAISSE FORTE (<= 15) et
  BAISSE RENFORCÉE (passage de marquee a forte).
- **Plus aucun signal de vente, ni objectif / stop** (les sections « Regles
  de sortie » ci-dessous ne s'appliquent qu'au mode court terme) : vendre sur
  une variation de quelques pour cent va a l'encontre d'un placement de
  plusieurs annees. Meme chose pour `btc_alert.py` (zone d'avidite extreme
  silencieuse, zone de peur extreme = rappel de versement).
- Quand tu achetes une nouvelle ligne, ajoute `"detenu": True` a son entree
  dans la watchlist (ou demande-le) pour recevoir des rappels de versement.

Retour a l'ancien comportement court terme (15 min, ventes, objectif / stop) :
variable d'environnement `MODE_STRATEGIE=court_terme` dans les workflows.
La demo `telegram_demo.py` rejoue toujours les scenarios court terme (elle
verifie la mecanique d'envoi), le mode long terme est couvert par
`tests/test_long_terme.py`.

## Principe (mode court terme historique)

Pour chaque actif de `watchlist.py`, calcul de 3 indicateurs independants
(ramenes sur une echelle 0-100) toutes les ~5 minutes, sur des bougies
15 min (le pas de verification est plus fin que la bougie elle-meme, pour
detecter le changement d'etat au plus tot apres la cloture d'une bougie) :

| Indicateur | Zone achat | Zone vente | Detail |
|---|---|---|---|
| RSI(14) | <= 15 | >= 85 | RSI classique sur bougies 15 min |
| MACD score (14) | <= 15 | >= 85 | Histogramme MACD normalise sur son min/max des 14 dernieres bougies |
| Fear & Greed (14) | <= 15 | >= 85 | Indice Alternative.me pour la crypto ; score maison (RSI + position dans le range 14) pour actions/ETF, qui n'ont pas d'indice F&G officiel individuel |

Seuil F&G crypto aligne sur RSI/MACD (15/85, au lieu de 10/85 a l'origine)
suite a un backtest sur l'historique BTC complet + validation hors-echantillon
(voir `backtest_walkforward.py`) : c'est la seule variante testee qui bat le
buy & hold sur deux periodes independantes (2018-2021 et 2022-2026).

**Une alerte n'est envoyee que si les 3 indicateurs sont d'accord** (unanimite,
pas de vote a 2 sur 3) sur le meme sens, ET que cet etat combine vient de
changer par rapport a la derniere execution. Les 3 confirmations doivent
converger.

### Deux niveaux pour l'achat (depuis le 03/10/2026)

- **Signal d'achat FORT** : les 3 indicateurs a **15 ou moins** (la regle
  d'origine, inchangee, rare).
- **Signal d'achat MODERE** : les 3 indicateurs a **20 ou moins** sans que les
  3 soient a 15 ou moins. Mesure sur BTC/ETH en bougies 15 min (365 j) : ~4x
  plus d'alertes (une a deux par semaine et par crypto au lieu d'une a deux
  par mois), avantage environ divise par 2 mais encore au-dessus de la
  reference ; a 25/75 et en vote 2 sur 3 l'avantage disparait, d'ou le
  plafond a 20. Echantillon d'une seule annee (dont 91 jours en "peur
  extreme"), a prendre comme un repere. Non mesure sur actions/ETF.
- Si un signal modere devient fort, une alerte **"RENFORCE -> FORT"** est
  envoyee (une seule fois par episode, meme si le signal oscille ensuite
  autour de 15). Une redescente fort -> modere ne declenche rien.
- La **vente** n'est PAS assouplie (85 inchange) : aucune donnee ne le
  justifie, et la sortie est couverte par les regles ci-dessous.

## Regles de sortie (objectif / stop)

Les signaux de VENTE de la strategie sont tres rares (sur crypto, le Fear &
Greed >= 85 ne s'est produit aucun jour sur l'annee ecoulee). Le bot ajoute
donc une regle de sortie par le prix, **calculee par rapport au prix de
l'alerte d'achat** (le bot n'execute rien et ne connait pas tes positions) :

- apres une alerte d'achat, le prix et la date sont memorises (`entry` dans
  l'etat du symbole) ;
- une alerte de sortie part **une seule fois** quand le cours gagne
  `+objectif %` ou perd `-stop %` depuis ce prix ;
- sans l'un ni l'autre apres 30 jours, un message annonce la fin du suivi ;
- une alerte de vente de la strategie ferme aussi le suivi.

Valeurs par defaut (`exit_rules.py`) : crypto **+8 % / -5 %** (choisies sur
l'historique des alertes BTC/ETH en 15 min : objectif atteint avant le stop
dans ~53-56 % des cas, sur une seule annee -- un repere, pas une garantie) ;
actions/ETF **+6 % / -4 %** (non testees). Surcharge possible par actif en
ajoutant `"exit_rule": (objectif, stop)` dans `watchlist.py` /
`eu_watchlist.py`. Le suivi est evalue sur chaque cycle (5 min pour
crypto/US, 1x/jour pour l'Europe/Chine, sur le cours de cloture).

## Watchlist

Voir `watchlist.py`. Liste par defaut volontairement limitee a des actifs
tres liquides (BTC, ETH, SPY, QQQ) — ce sont des **exemples**, pas une
recommandation. Modifie-la librement : chaque entree a un `symbol`
(format Binance pour la crypto, ticker boursier US pour actions/ETF) et un
`asset_class` (`crypto`, `stock` ou `etf`).

## Sources de donnees

- **Crypto** : `data-api.binance.vision` (miroir public Binance, sans cle,
  sans blocage geographique).
- **Actions / ETF US** : Alpaca Markets Data API, flux consolide SIP (toutes
  les bourses US) retarde de 15 min, la seule forme du SIP servie par le plan
  gratuit (`ALPACA_FEED=iex` pour le flux IEX temps reel, deconseille : les
  titres peu echanges sur IEX comme SMHC ou KTEC n'y ont presque pas de
  bougies et des indicateurs faux). Ne verifie ces actifs que pendant les
  horaires du marche US (09:30-16:00 America/New_York, lun-ven).
- **ETF europeens** (Xetra, LSE, Francfort) : EODHD (`eu_watchlist.py` /
  `trading_alert_eu.py`, workflow separe `trading-ct-eu-alert.yml`). Alpaca
  ne couvre pas ces marches, d'ou une source distincte. Le tier
  gratuit EODHD est limite a **20 appels API/jour** : ce bot ne verifie ces
  actifs qu'**une fois par cloture Xetra** (17h30 a Francfort, jours ouvres ;
  un second declenchement le meme jour ou le week-end s'arrete avant tout
  appel EODHD, `FORCER_CYCLE=1` / case "forcer" du workflow pour passer
  outre), pas toutes les 5 min comme le reste -- et meme sans cette limite de quota, verifier
  plus souvent ne servirait a rien : ce sont des cours de cloture (EOD), qui
  ne changent qu'une fois par jour.

### Obtenir une cle Alpaca gratuite (a faire toi-meme)

1. Cree un compte gratuit sur https://alpaca.markets (aucune carte bancaire
   necessaire pour les donnees de marche).
2. Dans le dashboard, genere une paire de cles API (mode **paper trading**
   suffit, ce bot ne passe aucun ordre).
3. Ajoute-les comme secrets GitHub (voir plus bas).

### Obtenir une cle EODHD gratuite (a faire toi-meme)

1. Cree un compte gratuit sur https://eodhd.com (aucune carte bancaire
   necessaire).
2. Recupere ton `api_token` depuis le dashboard.
3. Ajoute-le comme secret GitHub `EODHD_API_TOKEN` (voir plus bas).

## Setup

1. Dans **Settings > Secrets and variables > Actions** de ce repo, ajoute
   (en plus des secrets Telegram deja utilises par le bot BTC) :
   - `ALPACA_API_KEY_ID`
   - `ALPACA_API_SECRET_KEY`
   - `EODHD_API_TOKEN`
2. Le workflow `trading-ct-alert.yml` (crypto + actions/ETF US) tourne
   automatiquement toutes les 5 minutes. Le workflow
   `trading-ct-eu-alert.yml` (Europe + Chine) tourne une fois par jour.
   Les deux peuvent aussi etre lances manuellement via l'onglet
   **Actions > ... > Run workflow**.

## Test en local

```bash
pip install -r requirements.txt
TELEGRAM_BOT_TOKEN=xxx TELEGRAM_CHAT_ID=xxx \
ALPACA_API_KEY_ID=xxx ALPACA_API_SECRET_KEY=xxx \
python trading_alert.py
```

Sans les cles Alpaca, les symboles `stock`/`etf` sont simplement ignores
(la crypto continue de fonctionner sans aucune cle).

## Bilan quotidien « le bot est vivant » (`heartbeat.py`)

Workflow **Trading CT Heartbeat**, une fois par jour a 06:17 UTC (08:17 a
Paris en ete). Job independant des bots : il lit (lecture seule) l'API GitHub
Actions et envoie sur Telegram le nombre d'executions des dernieres 24 h.
- 🟢 **« le bot est vivant »** : cadence normale (~288 executions crypto/US en
  24 h), aucun echec, derniere execution recente, bot Europe/Chine execute.
- ⚠️ **« a regarder »** : moins de 200 executions en 24 h (le declencheur
  externe toutes les 5 min s'est probablement arrete -- GitHub seul ne lance
  le bot que toutes les ~4 h), une execution en echec, derniere execution de
  plus de 30 min, ou bot Europe/Chine non execute depuis plus de 3 j 12 h.
- Si l'API GitHub est illisible, un message le dit et le job passe au rouge.
Limite : ce job depend lui-meme du cron GitHub ; un matin sans message est
donc aussi un signal. Test manuel possible a tout moment (Run workflow).

## Alerte d'interruption du bot

Si GitHub ne fournit aucun runner (« not acquired by Runner », panne du
05/10/2026 : ~1 h 45 sans cycle) ou si le déclencheur externe s'arrête, aucun
workflow ne peut prévenir *pendant* la panne. Le bot compare donc l'heure de
son cycle à celle du précédent (`_meta.last_run_at`) et envoie une alerte
Telegram **dès la reprise** si le trou dépasse 30 min (cadence normale : 5 min),
avec la durée du trou. Au plus une alerte par 6 h (si seul le cron GitHub, ~4 h,
tourne, chaque cycle verrait un trou). Le message de 6 h 17 UTC précise ensuite
la cause (échecs « runner non acquis » comptés à part).

## Être alerté PENDANT une panne (healthchecks.io, optionnel)

Quand GitHub ne fournit aucun runner (« not acquired by Runner »), qu'un
paiement échoue ou que le déclencheur externe s'arrête, **aucun workflow ne peut
tourner, donc aucun workflow ne peut prévenir**. L'alerte d'interruption du bot
n'arrive qu'à la reprise. Pour être prévenu *pendant* la panne, un service
externe surveille les signes de vie du bot (« dead man's switch ») :

1. Créer un compte gratuit sur [healthchecks.io](https://healthchecks.io) et un
   check : *Period* = 5 minutes, *Grace time* = 15 minutes.
2. Dans ses *Integrations*, brancher Telegram (ou l'e-mail) : c'est lui qui
   enverra l'alerte « le bot ne répond plus » environ 20 min après le dernier cycle.
3. Copier l'URL de ping du check et l'ajouter comme secret GitHub
   **`HEALTHCHECK_URL`** (Settings > Secrets and variables > Actions).

Le bot appelle cette URL à la fin de chaque cycle (délai maximum 5 s, jamais
bloquant). Secret absent : aucun appel, comportement inchangé.

## Test complet des alertes (`telegram_demo.py`)

Workflow **Trading CT Backtest (actions/ETF)** -> script `telegram_demo.py`.
Il rejoue 15 scenarios dans les VRAIES boucles des deux bots (achat modere,
renforce -> fort, achat fort, objectif, stop, fin de suivi, vente, pannes de
donnees et retours au vert, cote crypto et cote ETF Europe, plus les deux
bilans quotidiens), envoie chaque message sur Telegram marque "TEST n/15", verifie le contenu de chacun et
envoie un recapitulatif ; le job devient rouge si un scenario echoue.
L'etat reel (fichiers / Supabase) n'est jamais lu ni modifie, aucune donnee
de marche n'est appelee, prix et scores sont fictifs. Le test lui-meme est
couvert par `tests/test_telegram_demo.py` (il doit echouer si une alerte casse).

## Sonde Alpaca (`alpaca_probe.py`)

Workflow **Trading CT Backtest (actions/ETF)** -> script `alpaca_probe.py`
(champ *symbols* vide = toute la watchlist US). Pour chaque action/ETF, affiche
le nombre de bougies 15 min recues d'Alpaca, le dernier cours et les 3
indicateurs (RSI, MACD score, score maison) ; le job devient rouge si un
symbole n'a pas ses 3 indicateurs. Ne lit ni n'ecrit l'etat, n'envoie rien
sur Telegram, fonctionne marche ferme : c'est le moyen de verifier le
correctif du 22/10/2026 (historique de 10 jours, cf. `ALPACA_HISTORY_DAYS`)
sans attendre la prochaine seance. Avant ce correctif, Alpaca ne renvoyait
que les bougies du jour et le MACD restait vide, donc aucune alerte
action/ETF ne pouvait partir. Option `--feed iex|sip` (en tete du champ
*symbols*) pour comparer les deux flux ; c'est cette sonde qui a montre le
22/10/2026 que le flux IEX laissait SMHC et KTEC sans MACD et faussait les
indicateurs des titres peu echanges, d'ou le passage du bot au flux SIP.

## Limites connues

- En strategie long terme (defaut), les bougies sont journalieres : le
  cycle de 5 min ne fait que detecter plus tot le passage du seuil pendant
  la seance, sur la bougie du jour en cours. En mode court terme, les
  bougies 15 min correspondent a du swing de quelques heures a quelques jours.
- Les seuils stricts (15/85 fort, 20 modere a l'achat) rendent les alertes
  peu frequentes ; sur crypto, la vente est quasi impossible (Fear & Greed
  >= 85 : aucun jour sur l'annee ecoulee) -- d'ou les regles de sortie.
- Ne tient pas compte des jours feries du marche US : dans ce cas Alpaca ne
  renvoie simplement pas de nouvelle bougie, l'actif est ignore sans
  consequence.

## Fichier d'etat

`state.json` (crypto + actions/ETF US) et `eu_state.json` (ETF europeens)
retiennent le dernier etat combine de chaque symbole, commites
automatiquement par leur workflow respectif apres chaque execution.
