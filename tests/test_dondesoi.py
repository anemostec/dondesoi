import re
import sqlite3

import pytest

from dondesoi import create_app
from dondesoi.db import MIGRATIONS, get_db, init_db
from dondesoi.matching import candidats_pour_offre, tokens


@pytest.fixture
def app(tmp_path):
    app = create_app({
        "TESTING": True,
        "SECRET_KEY": "test",
        "DATABASE": str(tmp_path / "test.sqlite"),
        "UPLOAD_FOLDER": str(tmp_path / "uploads"),
        "MAIL_BACKEND": "memory",
    })
    with app.app_context():
        init_db()
    return app


def csrf(client, path="/connexion"):
    html = client.get(path).get_data(as_text=True)
    return re.search(r'name="_csrf" value="([^"]+)"', html).group(1)


def register(client, email, name, city):
    data = {"_csrf": csrf(client, "/inscription"), "email": email, "password": "motdepasse",
            "display_name": name, "city": city}
    for key in ("gratuite", "double", "argent", "esprit"):
        data[f"engagement_{key}"] = "1"
    return client.post("/inscription", data=data)


def post_annonce(client, kind, category, title, description="", essential=False):
    data = {"_csrf": csrf(client, "/annonces/nouvelle"), "kind": kind, "category": category,
            "title": title, "description": description}
    if essential:
        data["essential"] = "1"
    resp = client.post("/annonces/nouvelle", data=data)
    return int(resp.headers["Location"].rsplit("/", 1)[-1]) if resp.status_code == 302 else resp


def test_tokens_ignore_accents_and_stopwords():
    assert tokens("Je cherche des Vêtements pour l'hiver") == {"vetement", "hiver"}


def test_inscription_exige_les_engagements(app):
    client = app.test_client()
    resp = client.post("/inscription", data={
        "_csrf": csrf(client, "/inscription"), "email": "a@b.fr", "password": "motdepasse",
        "display_name": "A", "city": "Lyon"})
    assert "engagements" in resp.get_data(as_text=True)


def test_post_sans_jeton_refuse(app):
    assert app.test_client().post("/connexion", data={"email": "x"}).status_code == 400


def test_don_argent_refuse(app):
    client = app.test_client()
    register(client, "a@b.fr", "Anne", "Lyon")
    resp = post_annonce(client, "besoin", "autre", "Besoin de 50 euros")
    assert "argent" in resp.get_data(as_text=True)


def test_parcours_complet(app):
    donor, receiver, other = app.test_client(), app.test_client(), app.test_client()
    register(donor, "donor@ex.fr", "Joseph", "Lyon")
    register(receiver, "receiver@ex.fr", "Anne", "Grenoble")
    register(other, "other@ex.fr", "Paul", "Lyon")

    offre = post_annonce(donor, "don", "objet", "Lit bébé en bois", "lit bébé avec matelas")
    besoin = post_annonce(receiver, "besoin", "objet", "Lit pour bébé")
    post_annonce(other, "besoin", "nourriture", "Colis alimentaire")

    # L'identité du donateur n'apparaît pas sur son annonce.
    page = receiver.get(f"/annonces/{offre}").get_data(as_text=True)
    assert "Joseph" not in page

    # Le besoin pertinent est proposé au donateur.
    page = donor.get(f"/annonces/{offre}").get_data(as_text=True)
    assert "Anne" in page and "Lit pour bébé" in page

    data = {"_csrf": csrf(donor, "/tableau-de-bord"), "offre": offre, "receveur": 2,
            "besoin": besoin, "shared_info": "RDV samedi gare", "besoin_comble": "1"}
    resp = donor.post("/dons/preparer", data=data)
    don_url = resp.headers["Location"]

    # Le receveur ne voit que ce que le donateur a partagé.
    page = receiver.get(don_url).get_data(as_text=True)
    assert "RDV samedi gare" in page and "Joseph" not in page
    assert other.get(don_url).status_code == 403

    donor.post(don_url + "/statut", data={"_csrf": csrf(donor, don_url), "action": "realise"})
    donor.post(don_url + "/avis", data={"_csrf": csrf(donor, don_url), "body": "Très reconnaissante."})
    receiver.post(don_url + "/avis", data={"_csrf": csrf(receiver, don_url), "body": "Merci !"})
    with app.app_context():
        avis = get_db().execute("SELECT * FROM avis").fetchone()
        assert avis["body"] == "Très reconnaissante." and avis["reply"] == "Merci !"


def test_premiere_necessite_prioritaire(app):
    with app.app_context():
        db = get_db()
        for i, city in enumerate(["Lyon", "Lyon", "Paris"], start=1):
            db.execute("INSERT INTO users (email, password_hash, display_name, city, "
                       "charter_accepted_at) VALUES (?, 'x', ?, ?, datetime('now'))",
                       (f"u{i}@ex.fr", f"U{i}", city))
        db.executescript("""
            INSERT INTO annonces (user_id, kind, category, title, description, city)
              VALUES (1, 'don', 'service', 'Repas et coup de main', 'repas cuisine', 'Lyon');
            INSERT INTO annonces (user_id, kind, category, title, description, city)
              VALUES (2, 'besoin', 'service', 'Coup de main', 'cuisine', 'Lyon');
            INSERT INTO annonces (user_id, kind, category, title, description, city, essential)
              VALUES (3, 'besoin', 'nourriture', 'Un repas', '', 'Paris', 1);
        """)
        offre = db.execute("SELECT * FROM annonces WHERE id = 1").fetchone()
        candidats = candidats_pour_offre(db, offre)
        assert [c["receiver_id"] for c in candidats] == [3, 2]


def unread(app, user_id):
    with app.app_context():
        return [r["body"] for r in get_db().execute(
            "SELECT body FROM notifications WHERE user_id = ? AND read_at IS NULL", (user_id,))]


def test_messagerie_et_notifications(app):
    donor, receiver, other = app.test_client(), app.test_client(), app.test_client()
    register(donor, "donor@ex.fr", "Joseph", "Lyon")       # id 1
    register(receiver, "receiver@ex.fr", "Anne", "Lyon")   # id 2
    register(other, "other@ex.fr", "Paul", "Lyon")         # id 3

    # Un besoin correspondant à un don existant prévient le donateur, et inversement.
    offre = post_annonce(donor, "don", "objet", "Poussette pliable", "poussette enfant")
    post_annonce(receiver, "besoin", "objet", "Poussette", "poussette pour enfant")
    assert any("Poussette pliable" in b for b in unread(app, 1))
    post_annonce(donor, "don", "objet", "Seconde poussette", "poussette enfant")
    assert any("Seconde poussette" in b for b in unread(app, 2))

    # Signaler son intérêt prévient le donateur.
    other.post(f"/annonces/{offre}/interet", data={"_csrf": csrf(other, f"/annonces/{offre}")})
    assert any("lui serait utile" in b for b in unread(app, 1))

    resp = donor.post("/dons/preparer", data={
        "_csrf": csrf(donor, "/tableau-de-bord"), "offre": offre, "receveur": 2, "shared_info": ""})
    don_url = resp.headers["Location"]
    assert any("vous fait un don" in b for b in unread(app, 2))

    donor.post(don_url + "/messages", data={"_csrf": csrf(donor, don_url), "body": "Bonjour !"})
    receiver.post(don_url + "/messages", data={"_csrf": csrf(receiver, don_url), "body": "Merci"})
    assert other.post(don_url + "/messages", data={"_csrf": csrf(other, "/tableau-de-bord"),
                                                   "body": "intrus"}).status_code == 403

    # Le receveur voit « Le donateur », jamais son nom ; le donateur voit le nom du receveur.
    page = receiver.get(don_url).get_data(as_text=True)
    assert "Le donateur" in page and "Bonjour !" in page and "Joseph" not in page
    assert "Anne" in donor.get(don_url).get_data(as_text=True)

    # Visiter la page marque ses notifications comme lues.
    assert unread(app, 2) and not any(don_url in b for b in unread(app, 2))
    with app.app_context():
        assert get_db().execute("SELECT COUNT(*) FROM notifications WHERE user_id = 2 AND "
                                "link = ? AND read_at IS NULL", (don_url,)).fetchone()[0] == 0

    # Les e-mails ne révèlent pas le donateur, et ne partent pas en double pour la même page.
    outbox = app.extensions["outbox"]
    to_receiver = [m for m in outbox if m["to"] == "receiver@ex.fr"]
    assert to_receiver and all("Joseph" not in m["text"] for m in to_receiver)
    assert len([m for m in outbox if m["to"] == "donor@ex.fr" and "écrit" in m["subject"]]) == 1


def test_email_desactivable(app):
    client = app.test_client()
    register(client, "a@ex.fr", "Anne", "Lyon")
    client.post("/profil", data={"_csrf": csrf(client, "/profil"), "display_name": "Anne",
                                 "city": "Lyon"})
    with app.test_request_context():
        from dondesoi.notifications import notify
        notify(1, "Test", "/")
    assert "outbox" not in app.extensions or not app.extensions["outbox"]


def test_migration_base_existante(tmp_path):
    path = tmp_path / "old.sqlite"
    db = sqlite3.connect(path)
    db.executescript("""
        CREATE TABLE users (id INTEGER PRIMARY KEY, email TEXT, password_hash TEXT,
            display_name TEXT, city TEXT, postal_code TEXT DEFAULT '', bio TEXT DEFAULT '',
            contact TEXT DEFAULT '', charter_accepted_at TEXT, created_at TEXT);
        CREATE TABLE dons (id INTEGER PRIMARY KEY);
    """)
    db.close()
    create_app({"SECRET_KEY": "t", "DATABASE": str(path), "UPLOAD_FOLDER": str(tmp_path)})
    db = sqlite3.connect(path)
    assert db.execute("PRAGMA user_version").fetchone()[0] == len(MIGRATIONS)
    assert "email_notifications" in [r[1] for r in db.execute("PRAGMA table_info(users)")]
    db.execute("SELECT * FROM messages, notifications")


def reset_link(app):
    mail = app.extensions["outbox"][-1]
    return re.search(r"http://localhost(/reinitialiser/\S+)", mail["text"]).group(1)


def login(client, email, password):
    return client.post("/connexion", data={"_csrf": csrf(client), "email": email,
                                           "password": password})


def test_mot_de_passe_oublie(app):
    client = app.test_client()
    register(client, "anne@ex.fr", "Anne", "Lyon")
    client.post("/deconnexion", data={"_csrf": csrf(client, "/")})

    # Adresse inconnue : même message, aucun e-mail.
    resp = client.post("/mot-de-passe-oublie", data={"_csrf": csrf(client), "email": "x@ex.fr"},
                       follow_redirects=True)
    assert "Si un compte existe" in resp.get_data(as_text=True)
    assert not app.extensions.get("outbox")

    client.post("/mot-de-passe-oublie", data={"_csrf": csrf(client), "email": "Anne@ex.fr"})
    link = reset_link(app)

    resp = client.post(link, data={"_csrf": csrf(client, link), "password": "nouveaumdp",
                                   "password2": "different"})
    assert "pas identiques" in resp.get_data(as_text=True)
    client.post(link, data={"_csrf": csrf(client, link), "password": "nouveaumdp",
                            "password2": "nouveaumdp"})

    other = app.test_client()
    assert login(other, "anne@ex.fr", "motdepasse").status_code == 200       # ancien refusé
    assert login(other, "anne@ex.fr", "nouveaumdp").status_code == 302       # nouveau accepté
    # Le lien ne sert qu'une fois.
    assert app.test_client().get(link).headers["Location"].endswith("/mot-de-passe-oublie")


def test_lien_expire(app):
    client = app.test_client()
    register(client, "anne@ex.fr", "Anne", "Lyon")
    client.post("/mot-de-passe-oublie", data={"_csrf": csrf(client), "email": "anne@ex.fr"})
    app.config["PASSWORD_RESET_MAX_AGE"] = -1
    assert app.test_client().get(reset_link(app)).headers["Location"].endswith("/mot-de-passe-oublie")
