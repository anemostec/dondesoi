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
# Il n'y a volontairement pas de catégorie « argent » : le don d'argent
# entre membres n'est pas permis (voir la page « Don d'argent »).
CATEGORIES = [
    ("nourriture", "Nourriture", True),
    ("logement", "Logement / hébergement", True),
    ("vetements", "Vêtements", True),
    ("soins", "Santé / soins", True),
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
        MAX_CONTENT_LENGTH=5 * 1024 * 1024,
        MAIL_BACKEND="console",
        MAIL_FROM="Don de soi <ne-pas-repondre@dondesoi.local>",
        # Lien vers le code source, que l'AGPL demande d'offrir aux utilisateurs.
        SOURCE_URL="",
        TIMEZONE="Europe/Paris",
    )
    # Toute variable d'environnement DONDESOI_XXX remplace la valeur XXX
    # (ex. DONDESOI_MAIL_BACKEND=smtp, DONDESOI_SMTP_HOST=...).
    app.config.from_prefixed_env("DONDESOI")
    if test_config:
        app.config.update(test_config)
    if not app.config.get("SECRET_KEY"):
        app.config["SECRET_KEY"] = _secret_key(app.instance_path)
    os.makedirs(app.config["UPLOAD_FOLDER"], exist_ok=True)

    from . import db, notifications, security
    db.init_app(app)
    security.init_app(app)
    notifications.init_app(app)

    from . import annonces, auth, dons, main, trajets
    app.register_blueprint(main.bp)
    app.register_blueprint(auth.bp)
    app.register_blueprint(annonces.bp)
    app.register_blueprint(dons.bp)
    app.register_blueprint(trajets.bp)
    app.register_blueprint(notifications.bp)

    @app.template_filter("heure")
    def heure(value):
        """Les dates sont stockées en UTC (datetime('now') de SQLite)."""
        utc = datetime.fromisoformat(value).replace(tzinfo=timezone.utc)
        return utc.astimezone(ZoneInfo(app.config["TIMEZONE"])).strftime("%d/%m/%Y %H:%M")

    @app.context_processor
    def inject_constants():
        return {"CATEGORIES": CATEGORIES, "CATEGORY_LABELS": CATEGORY_LABELS,
                "ESSENTIAL_CATEGORIES": ESSENTIAL_CATEGORIES,
                "SOURCE_URL": app.config["SOURCE_URL"]}

    return app
