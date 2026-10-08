# Don de soi

Code source : https://github.com/anemostec/dondesoi

Site web chrétien, sans but lucratif et sans publicité, qui met en relation les membres
pour faciliter le don sous toutes ses formes : objets, services, temps, écoute, prière.
L'esprit du projet est décrit dans `../don_de_soi.tex` et sur la page « Charte » du site.

## Comment la charte est appliquée dans le code

| Principe de la charte | Mise en œuvre |
|---|---|
| Chacun est donneur ET receveur | Le tableau de bord invite à publier un don si l'on n'a que des besoins, et inversement ; engagement à l'inscription |
| Don entièrement gratuit, sans argent entre membres | Pas de catégorie « argent » ; les annonces mentionnant somme, virement, PayPal… sont refusées (`annonces.py`) |
| Besoins de première nécessité prioritaires | Catégories essentielles + case « première nécessité » ; toujours en tête des listes et des suggestions (`matching.py`) |
| L'IA met en relation donneurs et receveurs | `matching.py` : score explicable affiché au donateur. Pertinence = même catégorie + mots communs + **sens proche** (modèle open source MiniLM multilingue exécuté sur le serveur, `sens.py`) ; puis **distance réelle** pour départager (`geo.py`), sauf prière, écoute et savoir qui se donnent à distance. Un besoin sans pertinence n'est jamais proposé, même tout proche |
| Le donateur est seul décisionnaire | Les suggestions ne font que proposer ; les membres peuvent signaler leur intérêt, le donateur choisit |
| Le donateur voit le profil et les avis du receveur | Page « Donner à… » (`dons/preparer.html`) |
| Le receveur ne voit que ce que le donateur partage, après le don | L'auteur d'un don n'est jamais affiché ; le receveur ne voit que le champ `shared_info` |
| Messagerie dans la même discrétion | Fil de discussion par don ; le donateur y apparaît comme « le donateur » (`dons.py`) |
| Faciliter les mises en relation | Notifications (cloche + e-mail facultatif) : correspondance don/besoin, intérêt signalé, don reçu, message, transport, avis (`notifications.py`) |
| Photos | Bouton « Prendre une photo » qui ouvre l'appareil du téléphone, plusieurs prises à la suite, réduction dans le téléphone avant envoi (`static/photos.js`) ; site installable sur l'écran d'accueil avec le raccourci « Photographier un objet à donner ». Jusqu'à 6 photos par annonce, ajoutées ou retirées à tout moment ; photos dans les messages (privées) et les actions de grâce. Réencodées : métadonnées et GPS effacés (`photos.py`) |
| Prier les uns pour les autres (Mt 18,19-20) | Bouton « Je prie pour vous » sur chaque besoin, la personne en est prévenue |
| Rendre grâce (Lc 17,15) | Après un don, mot du receveur au donateur, publiable sans aucun nom (page « Actions de grâce ») |
| Ne pas juger, reprendre en frère, pardonner (Mt 7,1 ; 18,15.22) | Avis facultatif, précédé d'une invitation à se parler ; le donateur peut le retirer à tout moment |
| Les œuvres de miséricorde (Mt 25,35-36) | Catégorie « Visite » (personne seule, malade, détenue) ajoutée aux besoins prioritaires |
| Dignité de celui qui demande | Le nom de l'auteur d'un besoin n'est visible que des membres |
| L'Évangile au cœur du site | Passages placés là où ils éclairent le geste, « Parole du jour » (`evangile.py`, Louis Segond 1910, domaine public) |
| Trajets pour éviter les frais d'expédition | `trajets.py` : sont proposés les trajets qui passent à moins de 15 km du donateur puis du receveur, dans le bon sens |
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
| `DONDESOI_SOURCE_URL` | lien vers le code source, affiché en pied de page (exigé par l'AGPL) ; par défaut ce dépôt. Une version modifiée mise en ligne doit pointer vers son propre code |
| `DONDESOI_TIMEZONE` | fuseau d'affichage des heures (défaut `Europe/Paris`) |
| `DONDESOI_GEOCODER` | `api` (défaut : coordonnées des villes via [geo.api.gouv.fr](https://geo.api.gouv.fr), service public ; seuls le nom de ville et le code postal lui sont envoyés, une fois par ville) ou `none` |
| `DONDESOI_SEMANTIC_MODEL` | modèle de sens (défaut `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2`, Apache 2.0) ; vide pour désactiver |
| `DONDESOI_MODEL_CACHE` | dossier du modèle téléchargé (défaut `~/.cache/dondesoi/models`) |
| `DONDESOI_PASSWORD_RESET_MAX_AGE` | durée de validité du lien « mot de passe oublié », en secondes (défaut 3600) |

Les bases existantes sont mises à jour automatiquement au démarrage (`MIGRATIONS` dans `db.py`).
`flask --app dondesoi localiser` complète les coordonnées et les vecteurs de sens manquants
(utile après une mise à jour, ou si geo.api.gouv.fr était injoignable).

## Organisation du code

```
dondesoi/
  __init__.py      création de l'application, catégories
  schema.sql       base de données
  matching.py      mise en relation (receveurs, offres, trajets)
  sens.py          sens des mots (modèle d'embeddings local)
  geo.py           coordonnées des villes, distances, trajets « sur le chemin »
  textes.py        normalisation des textes et des villes
  auth.py          inscription avec engagements, profil, page membre
  annonces.py      dons et besoins
  dons.py          transaction, messagerie, transport, avis
  notifications.py notifications et e-mails
  photos.py        traitement des photos (Pillow)
  evangile.py      passages d'Évangile cités dans le site
  trajets.py       déplacements prévus
  templates/       pages HTML (Jinja)
  static/style.css
tests/
```

## Pistes pour la suite

- Apprentissage des préférences du donateur ; distance par la route plutôt qu'à vol d'oiseau
- Récapitulatif quotidien par e-mail plutôt qu'un e-mail par événement
- Trajets avec étapes, et trajets réguliers
- Suppression de compte, modération, signalement d'un message
- Structure associative et page de transparence pour le don d'argent
- Déploiement (gunicorn + reverse proxy), application mobile

## Don de soi et l'intelligence artificielle

Le code de ce site a été écrit par **Claude**, l'IA d'Anthropic, à la demande et sous la direction
de l'équipe Don de soi. Le projet est très ouvert à l'intelligence artificielle, vue comme un talent
à faire fructifier au service de tous (Mt 25,14-30) : elle propose, l'humain décide ; elle reste
transparente et n'est jamais utilisée pour la publicité ou le profilage. Les contributions faites
avec l'aide d'une IA sont les bienvenues : signalez-le et relisez ce que vous proposez.

## Licence

GNU Affero General Public License v3 (voir `LICENSE`) : toute version du site mise en ligne,
même modifiée, doit offrir son code source à ses utilisateurs.
