# Alertes BTC

Bot qui verifie une fois par jour si le Bitcoin entre dans une zone de peur
ou d'avidite extreme, et envoie une alerte Telegram uniquement au moment
du passage du seuil (pas de spam tant qu'on reste dans la meme zone).

## Sources

1. **Alternative.me Fear & Greed Index** (officiel, gratuit, source principale)
2. **Score maison CoinGecko** : distance a l'ATH + RSI hebdomadaire (14 semaines)
3. **CoinMarketCap Fear & Greed** (endpoint non officiel, best-effort, bonus)

Une alerte n'est envoyee que si **au moins 2 sources sur 3** confirment le
meme sens (achat ou vente) au meme moment.

Seuils : score <= 20 => signal d'achat (peur extreme) ; score >= 80 =>
signal de vente (avidite extreme). Modifiable dans `btc_alert.py`
(`BUY_THRESHOLD` / `SELL_THRESHOLD`).

## Setup

1. Push ce dossier dans un repo GitHub (public ou prive, peu importe pour
   GitHub Actions gratuit).
2. Dans **Settings > Secrets and variables > Actions**, ajoute :
   - `TELEGRAM_BOT_TOKEN` : le token du bot (reutilise celui de PokeDeals)
   - `TELEGRAM_CHAT_ID` : l'ID du chat/canal qui recevra les alertes
3. Le workflow tourne automatiquement tous les jours a 08h00 UTC.
   Tu peux aussi le lancer manuellement via l'onglet **Actions > BTC
   Momentum Alert > Run workflow** pour tester.

## Test en local

```bash
pip install -r requirements.txt
TELEGRAM_BOT_TOKEN=xxx TELEGRAM_CHAT_ID=xxx python btc_alert.py
```

Sans les variables d'environnement, le script affiche le message dans le
terminal au lieu de l'envoyer sur Telegram.

## Fichier d'etat

`state.json` retient la derniere zone connue de chaque source et l'etat
combine. Il est commite automatiquement par le workflow apres chaque
execution : c'est ce qui permet de ne pas re-alerter tant qu'on reste
dans la meme zone.
