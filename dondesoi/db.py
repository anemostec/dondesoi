import sqlite3

import click
from flask import current_app, g


def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(current_app.config["DATABASE"])
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
    return g.db


def close_db(e=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()


# Mises à jour d'une base existante. schema.sql contient toujours le schéma
# complet et fixe user_version au nombre de migrations ; pour faire évoluer
# le schéma, modifier schema.sql ET ajouter ici la migration correspondante.
MIGRATIONS = [
    """
    ALTER TABLE users ADD COLUMN email_notifications INTEGER NOT NULL DEFAULT 1;
    CREATE TABLE messages (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        don_id INTEGER NOT NULL REFERENCES dons(id) ON DELETE CASCADE,
        author_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        body TEXT NOT NULL,
        created_at TEXT NOT NULL DEFAULT (datetime('now'))
    );
    CREATE TABLE notifications (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        body TEXT NOT NULL,
        link TEXT NOT NULL,
        read_at TEXT,
        created_at TEXT NOT NULL DEFAULT (datetime('now'))
    );
    CREATE INDEX idx_messages_don ON messages (don_id);
    CREATE INDEX idx_notifications_user ON notifications (user_id, read_at);
    """,
    # Plusieurs photos par annonce, photos dans les messages, prières, actions de grâce.
    # (L'ancienne colonne annonces.photo est laissée en place mais n'est plus utilisée.)
    """
    ALTER TABLE messages ADD COLUMN photo TEXT;
    -- Photos d'une annonce (6 au plus), dans l'ordre d'affichage.
    CREATE TABLE annonce_photos (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        annonce_id INTEGER NOT NULL REFERENCES annonces(id) ON DELETE CASCADE,
        filename TEXT NOT NULL,
        position INTEGER NOT NULL DEFAULT 0,
        created_at TEXT NOT NULL DEFAULT (datetime('now'))
    );
    
    -- « Je prie pour vous » : un membre porte un besoin dans la prière (Mt 18,19-20).
    CREATE TABLE prieres (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        annonce_id INTEGER NOT NULL REFERENCES annonces(id) ON DELETE CASCADE,
        user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        created_at TEXT NOT NULL DEFAULT (datetime('now')),
        UNIQUE (annonce_id, user_id)
    );
    
    -- Action de grâce du receveur après un don (Lc 17,15). Le mot est toujours
    -- transmis au donateur ; il n'est publié (sans aucun nom) que si le receveur le souhaite.
    CREATE TABLE actions_grace (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        don_id INTEGER UNIQUE NOT NULL REFERENCES dons(id) ON DELETE CASCADE,
        author_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        body TEXT NOT NULL,
        photo TEXT,
        public INTEGER NOT NULL DEFAULT 0,
        created_at TEXT NOT NULL DEFAULT (datetime('now'))
    );
    
    CREATE INDEX idx_annonce_photos ON annonce_photos (annonce_id, position);
    CREATE INDEX idx_actions_grace_public ON actions_grace (public, created_at);
    """,
    # Distance réelle et sens des mots pour la mise en relation.
    """
    ALTER TABLE users ADD COLUMN lat REAL;
    ALTER TABLE users ADD COLUMN lon REAL;
    ALTER TABLE annonces ADD COLUMN lat REAL;
    ALTER TABLE annonces ADD COLUMN lon REAL;
    ALTER TABLE trajets ADD COLUMN from_lat REAL;
    ALTER TABLE trajets ADD COLUMN from_lon REAL;
    ALTER TABLE trajets ADD COLUMN to_lat REAL;
    ALTER TABLE trajets ADD COLUMN to_lon REAL;
    -- Coordonnées des villes déjà cherchées (geo.api.gouv.fr), échecs compris,
    -- pour n'interroger le service qu'une fois par ville.
    CREATE TABLE lieux (
        cle TEXT PRIMARY KEY,
        nom TEXT,
        lat REAL,
        lon REAL,
        updated_at TEXT NOT NULL DEFAULT (datetime('now'))
    );

    -- Représentation du sens d'une annonce (modèle d'embeddings), recalculée
    -- quand l'annonce change.
    CREATE TABLE annonce_vecteurs (
        annonce_id INTEGER PRIMARY KEY REFERENCES annonces(id) ON DELETE CASCADE,
        modele TEXT NOT NULL,
        vecteur BLOB NOT NULL
    );
    """,
    # Limitation des demandes répétées.
    """
    -- Compteur anti-abus (demandes de mot de passe oublié…), purgé au fil de l'eau.
    CREATE TABLE limites (
        cle TEXT NOT NULL,
        created_at TEXT NOT NULL DEFAULT (datetime('now'))
    );
    CREATE INDEX idx_limites ON limites (cle, created_at);
    """,
    # Invitations de nouveaux membres.
    """
    ALTER TABLE users ADD COLUMN invited_by INTEGER REFERENCES users(id) ON DELETE SET NULL;
    -- Invitations : lien personnel à partager (email vide) ou invitation par e-mail.
    -- L'adresse d'une personne invitée qui ne s'inscrit pas est effacée après 30 jours.
    CREATE TABLE invitations (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        inviter_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        token TEXT UNIQUE NOT NULL,
        email TEXT,
        message TEXT NOT NULL DEFAULT '',
        created_at TEXT NOT NULL DEFAULT (datetime('now')),
        accepted_user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
        accepted_at TEXT
    );
    CREATE INDEX idx_invitations_inviter ON invitations (inviter_id);
    CREATE INDEX idx_invitations_email ON invitations (email);

    -- Personnes qui ne veulent plus recevoir d'invitations (empreinte de l'adresse seulement).
    CREATE TABLE invitations_refusees (
        email_hash TEXT PRIMARY KEY,
        created_at TEXT NOT NULL DEFAULT (datetime('now'))
    );
    """,
]


def migrate():
    """Applique les migrations manquantes à une base déjà initialisée."""
    db = get_db()
    if db.execute("SELECT 1 FROM sqlite_master WHERE name = 'users'").fetchone() is None:
        return
    version = db.execute("PRAGMA user_version").fetchone()[0]
    for i in range(version, len(MIGRATIONS)):
        db.executescript(MIGRATIONS[i] + f"\nPRAGMA user_version = {i + 1};")


def init_db():
    db = get_db()
    with current_app.open_resource("schema.sql") as f:
        db.executescript(f.read().decode("utf8"))


@click.command("init-db")
def init_db_command():
    """Crée (ou recrée, en effaçant tout) la base de données."""
    init_db()
    click.echo("Base de données initialisée.")


@click.command("seed-demo")
def seed_demo_command():
    """Remplit la base avec quelques membres et annonces de démonstration."""
    from .seed import seed
    init_db()
    seed(get_db())
    click.echo("Données de démonstration créées (mot de passe : demo1234).")
    localiser(click.echo)


def localiser(echo=print):
    """Complète les coordonnées et les vecteurs de sens qui manquent."""
    from .geo import coords_or_none
    from .sens import get_embedder, vecteurs
    db = get_db()
    n = 0
    for u in db.execute("SELECT * FROM users WHERE lat IS NULL").fetchall():
        lat, lon = coords_or_none(u["city"], u["postal_code"])
        if lat is not None:
            db.execute("UPDATE users SET lat = ?, lon = ? WHERE id = ?", (lat, lon, u["id"]))
            n += 1
    for a in db.execute("SELECT * FROM annonces WHERE lat IS NULL").fetchall():
        lat, lon = coords_or_none(a["city"])
        if lat is not None:
            db.execute("UPDATE annonces SET lat = ?, lon = ? WHERE id = ?", (lat, lon, a["id"]))
            n += 1
    for t in db.execute("SELECT * FROM trajets WHERE from_lat IS NULL OR to_lat IS NULL").fetchall():
        (flat, flon), (tlat, tlon) = coords_or_none(t["from_city"]), coords_or_none(t["to_city"])
        db.execute("UPDATE trajets SET from_lat = ?, from_lon = ?, to_lat = ?, to_lon = ? "
                   "WHERE id = ?", (flat, flon, tlat, tlon, t["id"]))
        n += 1
    db.commit()
    echo(f"{n} lieu(x) localisé(s).")
    if get_embedder() is None:
        echo("Sens des mots indisponible (fastembed absent ou SEMANTIC_MODEL vide).")
    else:
        annonces = db.execute("SELECT * FROM annonces WHERE status = 'ouverte'").fetchall()
        echo(f"Sens calculé pour {len(vecteurs(db, annonces))} annonce(s).")


@click.command("localiser")
def localiser_command():
    """Complète coordonnées (geo.api.gouv.fr) et vecteurs de sens manquants."""
    localiser(click.echo)


def init_app(app):
    app.teardown_appcontext(close_db)
    with app.app_context():
        migrate()
    app.cli.add_command(init_db_command)
    app.cli.add_command(seed_demo_command)
    app.cli.add_command(localiser_command)
