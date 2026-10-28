# Davz Japan

App perso 100 % foot japonais : J1, J2, J3, Levain Cup et clubs japonais en Ligue des champions AFC.

- `site/` : l'app (une seule page) et ses images
- `worker/` : le petit serveur Cloudflare (direct, détail des matchs, carrières des joueurs)
- `pipeline/` : récupère les données officielles (jleague.jp, YouTube J.League International, guide Davz TV)
- `.github/workflows/update.yml` : mise à jour toutes les 20 minutes et déploiement sur Cloudflare

Adresse : https://davz-japan.odinthor.workers.dev
