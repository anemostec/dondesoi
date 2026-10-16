DROP TABLE IF EXISTS lieux_relais;
DROP TABLE IF EXISTS participations;
DROP TABLE IF EXISTS moderations;
DROP TABLE IF EXISTS signalements;
DROP TABLE IF EXISTS trajet_demandes;
DROP TABLE IF EXISTS codes_postaux;
DROP TABLE IF EXISTS invitations_refusees;
DROP TABLE IF EXISTS invitations;
DROP TABLE IF EXISTS limites;
DROP TABLE IF EXISTS annonce_vecteurs;
DROP TABLE IF EXISTS lieux;
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
    email_notifications INTEGER NOT NULL DEFAULT 1,   -- ancien réglage, remplacé par email_frequence
    -- E-mails de notification : 'immediat', 'hebdo' (récapitulatif) ou 'aucun'.
    email_frequence TEXT NOT NULL DEFAULT 'immediat',
    dernier_recap TEXT,
    -- Présentation et contact masqués après un signalement retenu.
    profil_masque INTEGER NOT NULL DEFAULT 0,
    lat REAL,
    lon REAL,
    -- Qui a invité ce membre (visible seulement de lui et de la personne qui l'a invité).
    invited_by INTEGER REFERENCES users(id) ON DELETE SET NULL,
    -- Nombre de paroles d'Évangile déjà reçues par e-mail (pour ne pas les répéter).
    versets_envoyes INTEGER NOT NULL DEFAULT 0,
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
    postal_code TEXT NOT NULL DEFAULT '',
    essential INTEGER NOT NULL DEFAULT 0,
    -- Don : prêt (l'objet sera rendu) et durée indicative.
    pret INTEGER NOT NULL DEFAULT 0,
    pret_duree TEXT NOT NULL DEFAULT '',
    -- Besoin : nombre de personnes souhaitées pour un coup de main collectif (0 = non).
    mains INTEGER NOT NULL DEFAULT 0,
    -- Publié par le membre pour une personne sans internet (prénom de cette personne).
    pour_proche TEXT NOT NULL DEFAULT '',
    -- Retirée après un signalement retenu.
    masquee INTEGER NOT NULL DEFAULT 0,
    lat REAL,
    lon REAL,
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
    from_cp TEXT NOT NULL DEFAULT '',
    to_cp TEXT NOT NULL DEFAULT '',
    -- Trajet ponctuel : date du trajet. Trajet régulier : date de début.
    date TEXT NOT NULL,
    -- Trajet régulier : jours de la semaine (0 = lundi … 6 = dimanche), ex. « 0,3 ».
    jours TEXT NOT NULL DEFAULT '',
    heure TEXT NOT NULL DEFAULT '',
    date_fin TEXT,
    -- Visible dans les annonces (anonyme, sans l'heure), au choix du voyageur.
    public INTEGER NOT NULL DEFAULT 0,
    note TEXT NOT NULL DEFAULT '',
    from_lat REAL,
    from_lon REAL,
    to_lat REAL,
    to_lon REAL,
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
    -- Date choisie quand le trajet sollicité est régulier.
    transport_date TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    completed_at TEXT,
    -- Prêt : date où le donateur a indiqué que l'objet lui a été rendu.
    rendu_at TEXT
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
    masque INTEGER NOT NULL DEFAULT 0,
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

-- Compteur anti-abus (demandes de mot de passe oublié…), purgé au fil de l'eau.
CREATE TABLE limites (
    cle TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX idx_limites ON limites (cle, created_at);

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

-- Communes de chaque code postal (geo.api.gouv.fr), pour vérifier une ville.
CREATE TABLE codes_postaux (
    cp TEXT PRIMARY KEY,
    communes TEXT NOT NULL,          -- JSON : [{"nom", "lat", "lon", "dep"}]
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- « Ce trajet m'intéresse » : demande d'un membre au voyageur d'un trajet public.
-- Le voyageur reste anonyme ; il choisit ce qu'il partage dans sa réponse.
CREATE TABLE trajet_demandes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    trajet_id INTEGER NOT NULL REFERENCES trajets(id) ON DELETE CASCADE,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    date TEXT NOT NULL,
    message TEXT NOT NULL DEFAULT '',
    statut TEXT NOT NULL DEFAULT 'en_attente' CHECK (statut IN ('en_attente', 'acceptee', 'refusee')),
    reponse TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    reponse_at TEXT,
    UNIQUE (trajet_id, user_id, date)
);

-- Signalement d'un contenu, examiné par trois membres tirés au sort (aucun modérateur attitré).
CREATE TABLE signalements (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    kind TEXT NOT NULL CHECK (kind IN ('annonce', 'message', 'membre', 'grace')),
    objet_id INTEGER NOT NULL,
    auteur_id INTEGER REFERENCES users(id) ON DELETE SET NULL,   -- qui a écrit le contenu
    signale_par INTEGER REFERENCES users(id) ON DELETE SET NULL,
    motif TEXT NOT NULL,
    precision TEXT NOT NULL DEFAULT '',
    statut TEXT NOT NULL DEFAULT 'ouvert' CHECK (statut IN ('ouvert', 'retire', 'maintenu')),
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    decided_at TEXT,
    UNIQUE (kind, objet_id, signale_par)
);
CREATE TABLE moderations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    signalement_id INTEGER NOT NULL REFERENCES signalements(id) ON DELETE CASCADE,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    vote TEXT CHECK (vote IN ('retirer', 'maintenir')),
    voted_at TEXT,
    UNIQUE (signalement_id, user_id)
);

-- « Je participe » à un besoin qui demande plusieurs mains (déménagement, repas…).
CREATE TABLE participations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    annonce_id INTEGER NOT NULL REFERENCES annonces(id) ON DELETE CASCADE,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    message TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE (annonce_id, user_id)
);

-- Lieux relais (paroisse, local associatif, commerce ami) où déposer et retirer des dons.
CREATE TABLE lieux_relais (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    nom TEXT NOT NULL,
    adresse TEXT NOT NULL,
    postal_code TEXT NOT NULL,
    city TEXT NOT NULL,
    lat REAL,
    lon REAL,
    horaires TEXT NOT NULL DEFAULT '',
    description TEXT NOT NULL DEFAULT '',
    propose_par INTEGER REFERENCES users(id) ON DELETE SET NULL,
    masque INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX idx_messages_don ON messages (don_id);
CREATE INDEX idx_notifications_user ON notifications (user_id, read_at);
CREATE INDEX idx_annonces_open ON annonces (kind, status);
CREATE INDEX idx_trajets_date ON trajets (date);

PRAGMA user_version = 10;
