# Trading CT — alertes court/moyen terme (crypto + actions/ETF)

Bot d'alertes techniques multi-actifs, dans le meme esprit que le bot BTC
momentum du dossier parent : verification periodique, alerte Telegram
uniquement au **passage** d'un seuil (pas de spam tant qu'on reste dans la
meme zone).

**Ce n'est pas un conseil en investissement.** Aucun systeme ne "gagne a
tous les coups" a court terme, et ce bot n'execute aucun ordre : il se
contente d'un signal technique, l'achat/vente reste 100% manuel, sur la
plateforme de ton choix.

## Principe

Pour chaque actif de `watchlist.py`, calcul de 3 indicateurs independants
(ramenes sur une echelle 0-100) toutes les ~15 minutes :

| Indicateur | Zone achat | Zone vente | Detail |
|---|---|---|---|
| RSI(14) | <= 15 | >= 85 | RSI classique sur bougies 15 min |
| MACD score (14) | <= 15 | >= 85 | Histogramme MACD normalise sur son min/max des 14 dernieres bougies |
| Fear & Greed (14) | <= 10 (crypto) / <= 15 (actions/ETF) | >= 85 | Indice Alternative.me pour la crypto ; score maison (RSI + position dans le range 14) pour actions/ETF, qui n'ont pas d'indice F&G officiel individuel |

**Une alerte n'est envoyee que si les 3 indicateurs sont d'accord** (unanimite,
pas de vote a 2 sur 3) sur le meme sens, ET que cet etat combine vient de
changer par rapport a la derniere execution. Seuils volontairement stricts :
signaux rares, mais les 3 confirmations doivent converger.

## Watchlist

Voir `watchlist.py`. Liste par defaut volontairement limitee a des actifs
tres liquides (BTC, ETH, SPY, QQQ) — ce sont des **exemples**, pas une
recommandation. Modifie-la librement : chaque entree a un `symbol`
(format Binance pour la crypto, ticker boursier US pour actions/ETF) et un
`asset_class` (`crypto`, `stock` ou `etf`).

## Sources de donnees

- **Crypto** : `data-api.binance.vision` (miroir public Binance, sans cle,
  sans blocage geographique).
- **Actions / ETF** : Alpaca Markets Data API (flux IEX, retard ~15 min sur
  le plan gratuit). Ne verifie ces actifs que pendant les horaires du marche
  US (09:30-16:00 America/New_York, lun-ven).

### Obtenir une cle Alpaca gratuite (a faire toi-meme)

1. Cree un compte gratuit sur https://alpaca.markets (aucune carte bancaire
   necessaire pour les donnees de marche).
2. Dans le dashboard, genere une paire de cles API (mode **paper trading**
   suffit, ce bot ne passe aucun ordre).
3. Ajoute-les comme secrets GitHub (voir plus bas).

## Setup

1. Dans **Settings > Secrets and variables > Actions** de ce repo, ajoute
   (en plus des secrets Telegram deja utilises par le bot BTC) :
   - `ALPACA_API_KEY_ID`
   - `ALPACA_API_SECRET_KEY`
2. Le workflow `trading-ct-alert.yml` tourne automatiquement toutes les 15
   minutes. Tu peux aussi le lancer manuellement via l'onglet
   **Actions > Trading CT Alert > Run workflow**.

## Test en local

```bash
pip install -r requirements.txt
TELEGRAM_BOT_TOKEN=xxx TELEGRAM_CHAT_ID=xxx \
ALPACA_API_KEY_ID=xxx ALPACA_API_SECRET_KEY=xxx \
python trading_alert.py
```

Sans les cles Alpaca, les symboles `stock`/`etf` sont simplement ignores
(la crypto continue de fonctionner sans aucune cle).

## Limites connues

- Ce n'est **pas** du scalping minute par minute : le cron GitHub Actions le
  plus fiable tourne toutes les ~15 minutes, ce qui correspond plutot a du
  swing court/moyen terme (positions de quelques heures a quelques jours).
- Les seuils stricts (15/85, 10/85) rendent les alertes rares par design.
- Ne tient pas compte des jours feries du marche US : dans ce cas Alpaca ne
  renvoie simplement pas de nouvelle bougie, l'actif est ignore sans
  consequence.

## Fichier d'etat

`state.json` retient le dernier etat combine de chaque symbole, commite
automatiquement par le workflow apres chaque execution.
