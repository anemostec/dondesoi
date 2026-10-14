"""Don de soi : mettre en relation et faciliter le don entre les membres.

Application Flask volontairement simple (aucune étape de build, SQLite)
pour que chacun puisse lire le code et contribuer.
"""
import os
import secrets
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from flask import Flask

# Catégories de dons et de besoins. Le troisième champ indique un besoin
# de première nécessité : ces demandes sont mises en relation en priorité.
# Ce sont les œuvres de Mt 25,35-36 : nourrir, accueillir, vêtir, soigner, visiter.
# Il n'y a volontairement pas de catégorie « argent » : le don d'argent
# entre membres n'est pas permis (voir la page « Don d'argent »).
CATEGORIES = [
    ("nourriture", "Nourriture", True),
    ("logement", "Logement / hébergement", True),
    ("vetements", "Vêtements", True),
    ("soins", "Santé / soins", True),
    ("visite", "Visite (personne seule, malade, détenue)", True),
    ("objet", "Objet", False),
    ("service", "Service / coup de main", False),
    ("temps", "Temps / présence", False),
    ("ecoute", "Écoute", False),
    ("priere", "Prière", False),
    ("savoir", "Savoir / formation", False),
    ("transport", "Transport", False),
    ("autre", "Autre", False),
]
CATEGORY_LABELS = {key: label for key, label, _ in CATEGORIES}
ESSENTIAL_CATEGORIES = {key for key, _, essential in CATEGORIES if essential}


def _secret_key(instance_path):
    path = os.path.join(instance_path, "secret_key")
    if not os.path.exists(path):
        with open(path, "w") as f:
            f.write(secrets.token_hex(32))
    with open(path) as f:
        return f.read().strip()


def create_app(test_config=None):
    app = Flask(__name__, instance_relative_config=True)
    os.makedirs(app.instance_path, exist_ok=True)

    app.config.from_mapping(
        DATABASE=os.path.join(app.instance_path, "dondesoi.sqlite"),
        UPLOAD_FOLDER=os.path.join(app.instance_path, "uploads"),
        # Plusieurs photos de téléphone par envoi ; elles sont ensuite réduites.
        MAX_CONTENT_LENGTH=40 * 1024 * 1024,
        MAIL_BACKEND="console",
        MAIL_FROM="Don de soi <ne-pas-repondre@dondesoi.local>",
        # Adresse où arrivent les réponses aux e-mails du site (facultatif).
        MAIL_REPLY_TO="",
        SENDMAIL_PATH="/usr/sbin/sendmail",
        # Lien vers le code source, que l'AGPL demande d'offrir aux utilisateurs.
        SOURCE_URL="https://github.com/anemostec/dondesoi",
        TIMEZONE="Europe/Paris",
        PASSWORD_RESET_MAX_AGE=3600,
        # Adresse de contact affichée sur la page « Confidentialité ».
        CONTACT_EMAIL="",
        # En production derrière un proxy HTTPS (Caddy) : DONDESOI_BEHIND_PROXY=true.
        BEHIND_PROXY=False,
        # Distance réelle : coordonnées des villes via geo.api.gouv.fr (« none » pour désactiver).
        GEOCODER="api",
        GEO_API_URL="https://geo.api.gouv.fr",
        # Sens des mots : modèle d'embeddings open source exécuté sur le serveur
        # (chaîne vide pour désactiver). Téléchargé une fois dans MODEL_CACHE.
        SEMANTIC_MODEL="sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2",
        MODEL_CACHE="~/.cache/dondesoi/models",
    )
    # Toute variable d'environnement DONDESOI_XXX remplace la valeur XXX
    # (ex. DONDESOI_MAIL_BACKEND=smtp, DONDESOI_SMTP_HOST=...).
    app.config.from_prefixed_env("DONDESOI")
    if test_config:
        app.config.update(test_config)
    if app.config["BEHIND_PROXY"]:
        from werkzeug.middleware.proxy_fix import ProxyFix
        app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)
        app.config.update(SESSION_COOKIE_SECURE=True, PREFERRED_URL_SCHEME="https")
    # Flask définit déjà la clé (à None) : setdefault ne suffirait pas.
    app.config["SESSION_COOKIE_SAMESITE"] = app.config.get("SESSION_COOKIE_SAMESITE") or "Lax"
    if not app.config.get("SECRET_KEY"):
        app.config["SECRET_KEY"] = _secret_key(app.instance_path)
    os.makedirs(app.config["UPLOAD_FOLDER"], exist_ok=True)

    from . import db, notifications, security
    db.init_app(app)
    security.init_app(app)
    notifications.init_app(app)

    from . import annonces, auth, dons, invitations, main, trajets
    app.register_blueprint(main.bp)
    app.register_blueprint(auth.bp)
    app.register_blueprint(annonces.bp)
    app.register_blueprint(dons.bp)
    app.register_blueprint(trajets.bp)
    app.register_blueprint(notifications.bp)
    app.register_blueprint(invitations.bp)

    from .calendrier import date_fr
    from .photos import thumb_name
    app.jinja_env.filters["thumb"] = thumb_name
    app.jinja_env.filters["date_fr"] = date_fr

    @app.url_defaults
    def version_statique(endpoint, values):
        """Ajoute ?v=<date de modification> aux fichiers statiques : après une mise à jour,
        les navigateurs rechargent la feuille de style et les scripts au lieu de garder
        l'ancienne version en cache."""
        if endpoint == "static" and "filename" in values and "v" not in values:
            try:
                values["v"] = int(os.stat(os.path.join(app.static_folder, values["filename"])).st_mtime)
            except OSError:
                pass

    @app.template_filter("heure")
    def heure(value):
        """Les dates sont stockées en UTC (datetime('now') de SQLite)."""
        utc = datetime.fromisoformat(value).replace(tzinfo=timezone.utc)
        return utc.astimezone(ZoneInfo(app.config["TIMEZONE"])).strftime("%d/%m/%Y %H:%M")

    from markupsafe import Markup, escape

    from .evangile import parole_du_jour, passage

    def render_passage(p, css="verse"):
        return Markup('<blockquote class="{}"><p>« {} »</p><cite>{}</cite></blockquote>').format(
            css, escape(p["text"]), escape(p["ref"]))

    app.jinja_env.globals["verset"] = lambda key, css="verse": render_passage(passage(key), css)
    app.jinja_env.globals["parole_du_jour"] = lambda: render_passage(parole_du_jour(), "verse verse-jour")

    @app.context_processor
    def inject_constants():
        return {"CATEGORIES": CATEGORIES, "CATEGORY_LABELS": CATEGORY_LABELS,
                "ESSENTIAL_CATEGORIES": ESSENTIAL_CATEGORIES,
                "SOURCE_URL": app.config["SOURCE_URL"],
                "CONTACT_EMAIL": app.config["CONTACT_EMAIL"]}

    return app
