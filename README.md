# Don de soi

Site web chrétien, sans but lucratif et sans publicité, qui met en relation les membres
pour faciliter le don sous toutes ses formes : objets, services, temps, écoute, prière.
L'esprit du projet est décrit dans `../don_de_soi.tex` et sur la page « Charte » du site.

## Comment la charte est appliquée dans le code

| Principe de la charte | Mise en œuvre |
|---|---|
| Chacun est donneur ET receveur | Le tableau de bord invite à publier un don si l'on n'a que des besoins, et inversement ; engagement à l'inscription |
| Don entièrement gratuit, sans argent entre membres | Pas de catégorie « argent » ; les annonces mentionnant somme, virement, PayPal… sont refusées (`annonces.py`) |
| Besoins de première nécessité prioritaires | Catégories essentielles + case « première nécessité » ; toujours en tête des listes et des suggestions (`matching.py`) |
| L'IA met en relation donneurs et receveurs | `matching.py` : score explicable (catégorie, mots communs, ville), raisons affichées au donateur |
| Le donateur est seul décisionnaire | Les suggestions ne font que proposer ; les membres peuvent signaler leur intérêt, le donateur choisit |
| Le donateur voit le profil et les avis du receveur | Page « Donner à… » (`dons/preparer.html`) |
| Le receveur ne voit que ce que le donateur partage, après le don | L'auteur d'un don n'est jamais affiché ; le receveur ne voit que le champ `shared_info` |
| Messagerie dans la même discrétion | Fil de discussion par don ; le donateur y apparaît comme « le donateur » (`dons.py`) |
| Faciliter les mises en relation | Notifications (cloche + e-mail facultatif) : correspondance don/besoin, intérêt signalé, don reçu, message, transport, avis (`notifications.py`) |
| Trajets pour éviter les frais d'expédition | `trajets.py` + proposition des voyageurs de la ville du donateur vers celle du receveur |
| Avis après le don, droit de réponse, sans blocage | Table `avis` ; visibles sur le profil du receveur ; ils n'empêchent jamais un don |
| Pas de prosélytisme, liberté de partir | Pages « Charte » et « À qui s'adresse Don de soi » |
| Pas de publicité, partenaires gratuits seulement | Page « Partenaires » |
| Open source, développement partagé | Ce dépôt ; Python/Flask + SQLite, sans étape de build |

## Lancer le site en local

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/flask --app dondesoi seed-demo      # ou init-db pour une base vide
.venv/bin/flask --app dondesoi run --debug
```

Puis ouvrir http://localhost:5000. Comptes de démo : `marie@exemple.org`, `joseph@exemple.org`,
`anne@exemple.org`, `paul@exemple.org`, mot de passe `demo1234`.

Tests : `.venv/bin/pip install pytest && .venv/bin/python -m pytest tests`

## Configuration

Toute variable d'environnement `DONDESOI_XXX` remplace le réglage `XXX` :

| Variable | Rôle |
|---|---|
| `DONDESOI_SECRET_KEY` | clé de session (sinon générée dans `instance/secret_key`) |
| `DONDESOI_MAIL_BACKEND` | `console` (défaut : e-mails affichés dans le terminal) ou `smtp` |
| `DONDESOI_SMTP_HOST`, `DONDESOI_SMTP_PORT`, `DONDESOI_SMTP_USER`, `DONDESOI_SMTP_PASSWORD` | serveur d'envoi (STARTTLS) |
| `DONDESOI_MAIL_FROM` | expéditeur des e-mails |
| `DONDESOI_SOURCE_URL` | lien vers le dépôt public, affiché en pied de page (exigé par l'AGPL) |
| `DONDESOI_TIMEZONE` | fuseau d'affichage des heures (défaut `Europe/Paris`) |
| `DONDESOI_PASSWORD_RESET_MAX_AGE` | durée de validité du lien « mot de passe oublié », en secondes (défaut 3600) |

Les bases existantes sont mises à jour automatiquement au démarrage (`MIGRATIONS` dans `db.py`).

## Organisation du code

```
dondesoi/
  __init__.py      création de l'application, catégories
  schema.sql       base de données
  matching.py      mise en relation (receveurs, offres, trajets)
  auth.py          inscription avec engagements, profil, page membre
  annonces.py      dons et besoins
  dons.py          transaction, messagerie, transport, avis
  notifications.py notifications et e-mails
  trajets.py       déplacements prévus
  templates/       pages HTML (Jinja)
  static/style.css
tests/
```

## Pistes pour la suite

- Mise en relation sémantique (modèle d'embeddings open source), distance géographique réelle,
  apprentissage des préférences du donateur
- Récapitulatif quotidien par e-mail plutôt qu'un e-mail par événement
- Trajets avec étapes, et trajets réguliers
- Suppression de compte, modération, signalement d'un message
- Structure associative et page de transparence pour le don d'argent
- Déploiement (gunicorn + reverse proxy), application mobile

## Licence

GNU Affero General Public License v3 (voir `LICENSE`) : toute version du site mise en ligne,
même modifiée, doit offrir son code source à ses utilisateurs.
