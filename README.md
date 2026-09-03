# Alertes BTC

Projet perso : deux bots Telegram indépendants qui envoient une alerte
**uniquement au passage d'un seuil** (jamais de spam tant qu'on reste dans
la même zone). Aucun serveur, aucune base de données — tout tourne sur des
cron **GitHub Actions**, et l'état persiste dans des fichiers JSON commités
automatiquement dans le dépôt après chaque exécution.

## `btc_alert.py` — alerte Bitcoin Fear & Greed (1x/jour)

Vérifie chaque jour si le Bitcoin entre en zone de peur ou d'avidité
extrême, à partir de 3 sources indépendantes ramenées sur une échelle
0-100 :

1. **Alternative.me Fear & Greed Index** (officiel, gratuit) — source obligatoire
2. **Score maison CoinGecko** : distance à l'ATH + RSI hebdomadaire (14 semaines) — source obligatoire
3. **CoinMarketCap Fear & Greed** (endpoint non officiel, best-effort) — bonus

Seuils : score `<= 20` → signal d'achat (peur extrême) ; score `>= 80` →
signal de vente (avidité extrême). Une alerte n'est envoyée que si **au
moins 2 sources sur 3** confirment le même sens au même moment, et que
l'état combiné vient de changer par rapport à la veille.

## `trading-ct/` — alertes court/moyen terme multi-actifs

Bot séparé, dans le même esprit, qui surveille une watchlist de crypto,
actions et ETF US (`watchlist.py` : BTC, ETH, SPY, QQQ, plusieurs ETF
semi-conducteurs) toutes les 5 minutes pendant les horaires de marché, plus
une watchlist d'ETF européens (`eu_watchlist.py`, Xetra/LSE) et A-shares
chinoises, vérifiée une fois par jour.

Pour chaque actif, 3 indicateurs indépendants (RSI(14), histogramme MACD
normalisé(14), Fear & Greed(14)) doivent être **unanimement** d'accord
(seuils stricts 15/85) pour déclencher une alerte — pas de vote majoritaire
comme pour le bot BTC. Voir **[`trading-ct/README.md`](trading-ct/README.md)**
pour le détail des indicateurs, des sources de données et des watchlists.

Ce n'est **pas un conseil en investissement** : aucun ordre n'est exécuté,
uniquement un signal technique.

## Fiabilité

Les deux bots partagent les mêmes garde-fous, ajoutés au fil des audits
successifs du code :

- **Écriture d'état atomique** : le JSON d'état est écrit dans un fichier
  temporaire puis renommé (`os.replace`), pour qu'un process tué en plein
  run (timeout GitHub Actions) ne laisse jamais un fichier d'état tronqué.
- **Retry sur le push d'état** : chaque workflow retente jusqu'à 3 fois
  (`git pull --rebase` + `push`) si un autre push (autre workflow, commit
  manuel) est arrivé entre-temps, au lieu de faire échouer tout le run pour
  un simple conflit de course.
- **Détection de panne source (circuit breaker)** : si les sources de
  données obligatoires échouent plusieurs cycles d'affilée (3 jours pour le
  bot BTC, 12 cycles ≈ 1h pour la crypto de trading-ct, 3 jours pour les ETF
  EU), une alerte de panne est envoyée **une seule fois**, avec un message
  de retour au vert dès que les sources refonctionnent — plutôt que de
  rester silencieusement bloqué (job GitHub Actions vert, mais plus aucune
  alerte possible) ou de spammer à chaque cycle.
- **Session HTTP réutilisée** et **retry avec backoff** sur les erreurs
  429/réseau transitoires sur tous les appels API.
- **Fetch parallélisé** (`ThreadPoolExecutor`) par symbole dans
  `trading_alert.py`, pour que le cron de 5 minutes ne soit pas ralenti par
  le nombre d'actifs surveillés.
- **CI légère** (`.github/workflows/ci.yml`) : pyflakes sur chaque push/PR
  (imports inutilisés, erreurs de syntaxe), pas de suite de tests.

## Déploiement

Pas de serveur : tout tourne via 3 workflows GitHub Actions indépendants,
chacun aussi déclenchable manuellement (**Actions > ... > Run workflow**) :

| Workflow | Fréquence | Script |
|---|---|---|
| `btc-alert.yml` | tous les jours à 08h00 UTC | `btc_alert.py` |
| `trading-ct-alert.yml` | toutes les 5 minutes | `trading-ct/trading_alert.py` |
| `trading-ct-eu-alert.yml` | tous les jours ouvrés à 18h00 UTC | `trading-ct/trading_alert_eu.py` |

## Secrets nécessaires

Dans **Settings > Secrets and variables > Actions** du dépôt :

| Secret | Utilisé par | Obtention |
|---|---|---|
| `TELEGRAM_BOT_TOKEN` | les 3 bots | token du bot Telegram |
| `TELEGRAM_CHAT_ID` | les 3 bots | ID du chat/canal destinataire |
| `ALPACA_API_KEY_ID` / `ALPACA_API_SECRET_KEY` | `trading_alert.py` (actions/ETF US) | compte gratuit sur alpaca.markets, clés en mode paper trading |
| `EODHD_API_TOKEN` | `trading_alert_eu.py` (ETF Europe/Chine) | compte gratuit sur eodhd.com |

Sans les clés Alpaca ou EODHD, les actifs concernés sont simplement ignorés
(la crypto continue de fonctionner sans aucune clé). Sans les secrets
Telegram, les messages sont affichés dans le terminal au lieu d'être
envoyés.

## Test en local

```bash
# Bot BTC
pip install -r requirements.txt
TELEGRAM_BOT_TOKEN=xxx TELEGRAM_CHAT_ID=xxx python btc_alert.py

# Bot trading-ct
cd trading-ct
pip install -r requirements.txt
TELEGRAM_BOT_TOKEN=xxx TELEGRAM_CHAT_ID=xxx \
ALPACA_API_KEY_ID=xxx ALPACA_API_SECRET_KEY=xxx \
python trading_alert.py
```

## Structure du dépôt

```
.
├── .github/workflows/     # cron des 3 bots + CI (pyflakes)
├── btc_alert.py           # bot BTC (racine)
├── requirements.txt
├── state.json              # état du bot BTC, commité par le workflow
└── trading-ct/
    ├── trading_alert.py     # bot crypto + actions/ETF US (5 min)
    ├── trading_alert_eu.py  # bot ETF Europe/Chine (1x/jour)
    ├── watchlist.py         # actifs crypto/US surveillés
    ├── eu_watchlist.py       # actifs Europe/Chine surveillés
    ├── state.json / eu_state.json  # état, commités par leurs workflows
    ├── backtest_*.py         # scripts de backtest (hors production)
    └── README.md             # détail des indicateurs et sources
```
