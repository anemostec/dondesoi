DROP TABLE IF EXISTS actions_grace;
DROP TABLE IF EXISTS prieres;
DROP TABLE IF EXISTS annonce_photos;
DROP TABLE IF EXISTS notifications;
DROP TABLE IF EXISTS messages;
DROP TABLE IF EXISTS avis;
DROP TABLE IF EXISTS dons;
DROP TABLE IF EXISTS trajets;
DROP TABLE IF EXISTS interets;
DROP TABLE IF EXISTS annonces;
DROP TABLE IF EXISTS users;

CREATE TABLE users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    email TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    display_name TEXT NOT NULL,
    city TEXT NOT NULL,
    postal_code TEXT NOT NULL DEFAULT '',
    bio TEXT NOT NULL DEFAULT '',
    -- Coordonnées que le membre accepte de montrer aux donateurs.
    contact TEXT NOT NULL DEFAULT '',
    email_notifications INTEGER NOT NULL DEFAULT 1,
    charter_accepted_at TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Une annonce est soit un don proposé, soit un besoin exprimé.
CREATE TABLE annonces (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    kind TEXT NOT NULL CHECK (kind IN ('don', 'besoin')),
    category TEXT NOT NULL,
    title TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    city TEXT NOT NULL,
    essential INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'ouverte'
        CHECK (status IN ('ouverte', 'attribuee', 'close')),
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Un membre signale qu'un don proposé lui serait utile.
-- Le donateur reste seul à choisir le receveur.
CREATE TABLE interets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    annonce_id INTEGER NOT NULL REFERENCES annonces(id) ON DELETE CASCADE,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    message TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE (annonce_id, user_id)
);

-- Déplacements prévus, pour transporter les dons sans frais d'expédition.
CREATE TABLE trajets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    from_city TEXT NOT NULL,
    to_city TEXT NOT NULL,
    date TEXT NOT NULL,
    note TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE dons (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    offre_id INTEGER NOT NULL REFERENCES annonces(id) ON DELETE CASCADE,
    besoin_id INTEGER REFERENCES annonces(id) ON DELETE SET NULL,
    donor_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    receiver_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    -- Seule information que le receveur verra du donateur.
    shared_info TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'en_cours'
        CHECK (status IN ('en_cours', 'realise', 'annule')),
    trajet_id INTEGER REFERENCES trajets(id) ON DELETE SET NULL,
    transport_status TEXT CHECK (transport_status IN ('demande', 'accepte', 'refuse')),
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    completed_at TEXT
);

-- Avis du donateur sur le receveur, avec droit de réponse.
CREATE TABLE avis (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    don_id INTEGER UNIQUE NOT NULL REFERENCES dons(id) ON DELETE CASCADE,
    author_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    subject_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    body TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    reply TEXT,
    reply_at TEXT
);

-- Messagerie d'un don, entre donateur, receveur et voyageur.
CREATE TABLE messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    don_id INTEGER NOT NULL REFERENCES dons(id) ON DELETE CASCADE,
    author_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    body TEXT NOT NULL DEFAULT '',
    -- Photo jointe, servie seulement aux participants du don.
    photo TEXT,
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

CREATE INDEX idx_messages_don ON messages (don_id);
CREATE INDEX idx_notifications_user ON notifications (user_id, read_at);
CREATE INDEX idx_annonces_open ON annonces (kind, status);
CREATE INDEX idx_trajets_date ON trajets (date);

PRAGMA user_version = 2;
