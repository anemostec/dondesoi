import io
import re
import sqlite3

import pytest
from PIL import Image

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
        "GEOCODER": "none",
        "SEMANTIC_MODEL": "",
    })
    app.extensions["geocoder"] = FakeGeocoder()
    with app.app_context():
        init_db()
    return app


# Coordonnées réelles approximatives, pour tester sans réseau.
VILLES = {
    "lyon": (45.758, 4.835), "villeurbanne": (45.767, 4.880), "grenoble": (45.188, 5.724),
    "paris": (48.857, 2.352), "valence": (44.933, 4.892), "marseille": (43.296, 5.370),
}


class FakeGeocoder:
    def __init__(self):
        self.calls = []

    def __call__(self, city, postal_code):
        self.calls.append(city)
        key = city.lower()
        return (city, *VILLES[key]) if key in VILLES else None


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
        CREATE TABLE annonces (id INTEGER PRIMARY KEY);
        CREATE TABLE trajets (id INTEGER PRIMARY KEY);
    """)
    db.close()
    create_app({"SECRET_KEY": "t", "DATABASE": str(path), "UPLOAD_FOLDER": str(tmp_path)})
    db = sqlite3.connect(path)
    assert db.execute("PRAGMA user_version").fetchone()[0] == len(MIGRATIONS)
    assert "email_notifications" in [r[1] for r in db.execute("PRAGMA table_info(users)")]
    db.execute("SELECT * FROM messages, notifications, annonce_photos, prieres, lieux, "
               "annonce_vecteurs")
    assert "lat" in [r[1] for r in db.execute("PRAGMA table_info(annonces)")]


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


def image_file(name="photo.jpg", size=(2400, 1800), with_exif=True):
    img = Image.new("RGB", size, "tomato")
    buf = io.BytesIO()
    exif = Image.Exif()
    if with_exif:
        exif[0x010F] = "Telephone-Espion"   # Make
        exif[0x8825] = {1: "N", 2: (45.0, 45.0, 0.0)}   # GPSInfo
    img.save(buf, "JPEG", exif=exif)
    buf.seek(0)
    return (buf, name)


def first_photo_path(app, subdir="annonces"):
    with app.app_context():
        name = get_db().execute("SELECT filename FROM annonce_photos ORDER BY id").fetchone()[0]
    return f"{app.config['UPLOAD_FOLDER']}/{subdir}/{name}"


def test_photos_annonce(app):
    client = app.test_client()
    register(client, "anne@ex.fr", "Anne", "Lyon")
    resp = client.post("/annonces/nouvelle", data={
        "_csrf": csrf(client, "/annonces/nouvelle"), "kind": "don", "category": "objet",
        "title": "Vélo", "photos": [image_file("a.jpg"), image_file("b.png")]})
    annonce_id = int(resp.headers["Location"].rsplit("/", 1)[-1])

    # Réduite, réencodée, sans métadonnées (ni marque d'appareil, ni GPS).
    with Image.open(first_photo_path(app)) as img:
        assert max(img.size) == 1600
        assert not img.getexif()
    page = client.get(f"/annonces/{annonce_id}").get_data(as_text=True)
    assert page.count('alt="Photo ') == 2

    # Modifier : supprimer une photo, en ajouter deux.
    with app.app_context():
        first_id = get_db().execute("SELECT id FROM annonce_photos ORDER BY id").fetchone()[0]
    url = f"/annonces/{annonce_id}/modifier"
    client.post(url, data={"_csrf": csrf(client, url), "title": "Vélo enfant", "category": "objet",
                           "supprimer_photo": str(first_id),
                           "photos": [image_file("c.jpg"), image_file("d.jpg")]})
    with app.app_context():
        assert get_db().execute("SELECT COUNT(*) FROM annonce_photos").fetchone()[0] == 3
        assert get_db().execute("SELECT title FROM annonces").fetchone()[0] == "Vélo enfant"

    # Pas plus de 6 photos.
    resp = client.post(url, data={"_csrf": csrf(client, url), "title": "Vélo", "category": "objet",
                                  "photos": [image_file(f"{i}.jpg") for i in range(4)]})
    assert "6 photos" in resp.get_data(as_text=True) or "photo" in resp.get_data(as_text=True)
    with app.app_context():
        assert get_db().execute("SELECT COUNT(*) FROM annonce_photos").fetchone()[0] == 3

    # Un faux fichier image est refusé.
    resp = client.post("/annonces/nouvelle", data={
        "_csrf": csrf(client, "/annonces/nouvelle"), "kind": "don", "category": "objet",
        "title": "Piège", "photos": [(io.BytesIO(b"<script>alert(1)</script>"), "x.jpg")]})
    assert "pas une image" in resp.get_data(as_text=True)

    # Seul l'auteur peut modifier.
    other = app.test_client()
    register(other, "paul@ex.fr", "Paul", "Lyon")
    assert other.get(url).status_code == 403


def setup_don(app):
    donor, receiver, other = app.test_client(), app.test_client(), app.test_client()
    register(donor, "donor@ex.fr", "Joseph", "Lyon")       # id 1
    register(receiver, "receiver@ex.fr", "Anne", "Lyon")   # id 2
    register(other, "other@ex.fr", "Paul", "Lyon")         # id 3
    offre = post_annonce(donor, "don", "objet", "Table", "table en bois")
    resp = donor.post("/dons/preparer", data={
        "_csrf": csrf(donor, "/tableau-de-bord"), "offre": offre, "receveur": 2, "shared_info": ""})
    return donor, receiver, other, resp.headers["Location"]


def test_photo_message_privee(app):
    donor, receiver, other, don_url = setup_don(app)
    donor.post(don_url + "/messages", data={"_csrf": csrf(donor, don_url), "body": "",
                                            "photo": image_file()})
    with app.app_context():
        msg = get_db().execute("SELECT * FROM messages").fetchone()
    assert msg["photo"]
    photo_url = f"{don_url}/messages/{msg['id']}/photo"
    assert receiver.get(photo_url).status_code == 200
    assert other.get(photo_url).status_code == 403
    assert app.test_client().get(photo_url).status_code == 302   # non connecté


def test_action_de_grace_et_pardon(app):
    donor, receiver, other, don_url = setup_don(app)
    donor.post(don_url + "/statut", data={"_csrf": csrf(donor, don_url), "action": "realise"})

    receiver.post(don_url + "/grace", data={"_csrf": csrf(receiver, don_url),
                                            "body": "Merci Seigneur pour cette table !",
                                            "public": "1", "photo": image_file()})
    assert any("rend grâce" in b for b in unread(app, 1))
    page = app.test_client().get("/actions-de-grace").get_data(as_text=True)
    assert "Merci Seigneur" in page and "Anne" not in page and "Joseph" not in page
    with app.app_context():
        grace_id = get_db().execute("SELECT id FROM actions_grace").fetchone()[0]
    assert app.test_client().get(f"/dons/grace/{grace_id}/photo").status_code == 200

    # Dépubliée : disparaît de la page publique, photo réservée au donateur et au receveur.
    receiver.post(don_url + "/grace/depublier", data={"_csrf": csrf(receiver, don_url)})
    assert "Merci Seigneur" not in app.test_client().get("/actions-de-grace").get_data(as_text=True)
    assert app.test_client().get(f"/dons/grace/{grace_id}/photo").status_code == 404
    assert donor.get(f"/dons/grace/{grace_id}/photo").status_code == 200

    # Avis puis pardon : le donateur peut le retirer.
    donor.post(don_url + "/avis", data={"_csrf": csrf(donor, don_url), "body": "Retard au RDV."})
    donor.post(don_url + "/avis/retirer", data={"_csrf": csrf(donor, don_url)})
    with app.app_context():
        assert get_db().execute("SELECT COUNT(*) FROM avis").fetchone()[0] == 0
    assert receiver.post(don_url + "/avis/retirer",
                         data={"_csrf": csrf(receiver, don_url)}).status_code == 403


def test_priere_et_dignite(app):
    anne, paul = app.test_client(), app.test_client()
    register(anne, "anne@ex.fr", "Anne", "Lyon")
    register(paul, "paul@ex.fr", "Paul", "Lyon")
    besoin = post_annonce(anne, "besoin", "nourriture", "Colis alimentaire")

    url = f"/annonces/{besoin}/priere"
    paul.post(url, data={"_csrf": csrf(paul, f"/annonces/{besoin}")})
    paul.post(url, data={"_csrf": csrf(paul, f"/annonces/{besoin}")})   # pas de doublon
    assert sum("prière" in b for b in unread(app, 1)) == 1
    assert "1 membre porte" in anne.get(f"/annonces/{besoin}").get_data(as_text=True)
    assert anne.post(url, data={"_csrf": csrf(anne, f"/annonces/{besoin}")}).status_code == 400

    # Le nom de la personne dans le besoin n'est pas montré aux visiteurs non inscrits.
    visitor = app.test_client()
    assert "Anne" not in visitor.get(f"/annonces/{besoin}").get_data(as_text=True)
    assert "Anne" not in visitor.get("/annonces/").get_data(as_text=True)


def test_versets_affiches(app):
    page = app.test_client().get("/charte").get_data(as_text=True)
    assert "Mt 6,3-4" in page and "Louis Segond" in page
    assert "Parole du jour" in app.test_client().get("/").get_data(as_text=True)


def test_photo_depuis_le_telephone(app):
    client = app.test_client()
    register(client, "anne@ex.fr", "Anne", "Lyon")
    page = client.get("/annonces/nouvelle?kind=don&categorie=objet").get_data(as_text=True)
    # Bouton qui ouvre directement l'appareil photo, catégorie « Objet » présélectionnée.
    assert 'capture="environment"' in page
    assert '<option value="objet" selected>' in page
    # Sans JavaScript, les deux champs (appareil photo et galerie) sont envoyés ensemble.
    resp = client.post("/annonces/nouvelle", data={
        "_csrf": csrf(client, "/annonces/nouvelle"), "kind": "don", "category": "objet",
        "title": "Chaise", "photos": [image_file("camera.jpg"), image_file("galerie.jpg")]})
    assert resp.status_code == 302
    with app.app_context():
        assert get_db().execute("SELECT COUNT(*) FROM annonce_photos").fetchone()[0] == 2
    for path in ("/static/photos.js", "/static/manifest.webmanifest", "/static/icons/icon-192.png"):
        assert client.get(path).status_code == 200



# --- Distance réelle et sens des mots ------------------------------------------------

def test_geocodage_mis_en_cache(app):
    client = app.test_client()
    register(client, "a@ex.fr", "Anne", "Villeurbanne")
    post_annonce(client, "don", "objet", "Table")              # même ville que le membre
    post_annonce(client, "don", "objet", "Chaise", "")          # idem
    with app.app_context():
        user = get_db().execute("SELECT lat, lon FROM users").fetchone()
        assert user["lat"] == pytest.approx(45.767)
        assert get_db().execute("SELECT COUNT(*) FROM annonces WHERE lat IS NOT NULL").fetchone()[0] == 2
    assert app.extensions["geocoder"].calls == ["Villeurbanne"]   # une seule question au service


def test_api_geo_gouv(app, monkeypatch):
    """Lecture de la réponse de geo.api.gouv.fr : on garde la commune au bon nom."""
    import json as _json
    from dondesoi import geo
    payload = [{"nom": "Saint-Genis-Laval", "centre": {"coordinates": [4.79, 45.69]}},
               {"nom": "Lyon", "centre": {"coordinates": [4.835, 45.758]}}]

    class Resp(io.BytesIO):
        def __enter__(self): return self
        def __exit__(self, *a): pass
    seen = {}
    def fake_urlopen(req, timeout):
        seen["url"] = req.full_url
        return Resp(_json.dumps(payload).encode())
    monkeypatch.setattr(geo.urllib.request, "urlopen", fake_urlopen)
    with app.app_context():
        assert geo._api_geocode("Lyon", "") == ("Lyon", 45.758, 4.835)
    assert seen["url"].startswith("https://geo.api.gouv.fr/communes?nom=Lyon")


def make_users_and_annonces(app, rows):
    """rows : (ville, kind, category, title, description). Retourne les ids d'annonces."""
    from dondesoi.geo import coords_or_none
    ids = []
    with app.app_context():
        db = get_db()
        for i, (city, kind, cat, title, desc) in enumerate(rows):
            lat, lon = coords_or_none(city)
            uid = db.execute("INSERT INTO users (email, password_hash, display_name, city, lat, lon, "
                             "charter_accepted_at) VALUES (?, 'x', ?, ?, ?, ?, datetime('now'))",
                             (f"u{i}@ex.fr", f"U{i}", city, lat, lon)).lastrowid
            ids.append(db.execute("INSERT INTO annonces (user_id, kind, category, title, description, "
                                  "city, lat, lon) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                                  (uid, kind, cat, title, desc, city, lat, lon)).lastrowid)
        db.commit()
    return ids


def candidats(app, offre_id):
    with app.app_context():
        db = get_db()
        offre = db.execute("SELECT * FROM annonces WHERE id = ?", (offre_id,)).fetchone()
        return candidats_pour_offre(db, offre)


def test_distance_departage(app):
    offre, paris, villeurbanne, voisin = make_users_and_annonces(app, [
        ("Lyon", "don", "objet", "Table en bois", ""),
        ("Paris", "besoin", "objet", "Table", ""),
        ("Villeurbanne", "besoin", "objet", "Table", ""),
        ("Villeurbanne", "besoin", "savoir", "Cours de guitare", ""),   # proche mais sans rapport
    ])
    c = candidats(app, offre)
    assert [x["besoin"]["id"] for x in c] == [villeurbanne, paris]   # le voisin sans rapport est exclu
    assert "à 4 km" in c[0]["reasons"] and "à 392 km" in c[1]["reasons"]


def test_distance_ignoree_pour_ce_qui_se_donne_a_distance(app):
    offre, besoin = make_users_and_annonces(app, [
        ("Lyon", "don", "priere", "Je prie pour vos intentions", ""),
        ("Marseille", "besoin", "priere", "Priez pour ma mère malade", ""),
    ])
    c = candidats(app, offre)
    assert len(c) == 1 and not any("km" in r for r in c[0]["reasons"])


class FakeEmbedder:
    """Vecteurs à 3 dimensions : (enfant, meuble, autre)."""
    name = "fake"
    GROUPES = {"landau": 0, "poussette": 0, "bureau": 1, "table": 1}

    def embed(self, texts):
        import numpy as np
        out = []
        for t in texts:
            v = np.array([0.0, 0.0, 0.2], dtype="float32")
            for mot, axe in self.GROUPES.items():
                if mot in t.lower():
                    v[axe] = 1.0
            out.append(v / np.linalg.norm(v))
        return out


def test_sens_des_mots(app):
    app.extensions["embedder"] = FakeEmbedder()
    offre, poussette, bureau = make_users_and_annonces(app, [
        ("Lyon", "don", "autre", "Landau", "très bon état"),
        ("Lyon", "besoin", "objet", "Poussette", "pour notre fille"),
        ("Lyon", "besoin", "objet", "Bureau", "pour étudier"),
    ])
    c = candidats(app, offre)
    # Aucun mot ni catégorie en commun : seul le sens rapproche landau et poussette.
    assert [x["besoin"]["id"] for x in c] == [poussette]
    assert "sens très proche" in c[0]["reasons"]
    with app.app_context():   # les vecteurs sont gardés en base
        assert get_db().execute("SELECT COUNT(*) FROM annonce_vecteurs").fetchone()[0] == 3


def test_trajet_sur_le_chemin(app):
    from datetime import date, timedelta
    from dondesoi.geo import coords_or_none
    from dondesoi.matching import trajets_pour_don
    demain = (date.today() + timedelta(days=1)).isoformat()
    with app.app_context():
        db = get_db()
        def user(city):
            lat, lon = coords_or_none(city)
            uid = db.execute("INSERT INTO users (email, password_hash, display_name, city, lat, lon, "
                             "charter_accepted_at) VALUES (?, 'x', ?, ?, ?, ?, datetime('now'))",
                             (f"{city}@ex.fr", city, city, lat, lon)).lastrowid
            return db.execute("SELECT * FROM users WHERE id = ?", (uid,)).fetchone()
        def trajet(owner, a, b):
            (fa, fo), (ta, to) = coords_or_none(a), coords_or_none(b)
            db.execute("INSERT INTO trajets (user_id, from_city, to_city, date, from_lat, from_lon, "
                       "to_lat, to_lon) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                       (owner["id"], a, b, demain, fa, fo, ta, to))
        lyon, valence, paris, voyageur = user("Lyon"), user("Valence"), user("Paris"), user("Grenoble")
        trajet(voyageur, "Villeurbanne", "Marseille")   # passe par Lyon puis Valence
        trajet(voyageur, "Marseille", "Lyon")           # mauvais sens
        found = trajets_pour_don(db, lyon, valence)
        assert len(found) == 1 and found[0][0]["to_city"] == "Marseille"
        assert "de chez vous" in found[0][1]
        assert trajets_pour_don(db, lyon, paris) == []   # Paris n'est pas sur la route


def test_filtre_rayon(app):
    client = app.test_client()
    register(client, "a@ex.fr", "Anne", "Lyon")
    make_users_and_annonces(app, [
        ("Villeurbanne", "don", "objet", "Table proche", ""),
        ("Grenoble", "don", "objet", "Table lointaine", ""),
    ])
    page = client.get("/annonces/?rayon=15").get_data(as_text=True)
    assert "Table proche" in page and "Table lointaine" not in page
    assert "à 4 km" in page


# --- Mise en ligne -------------------------------------------------------------------

def test_limite_mot_de_passe_oublie(app):
    client = app.test_client()
    register(client, "anne@ex.fr", "Anne", "Lyon")
    for _ in range(5):
        client.post("/mot-de-passe-oublie", data={"_csrf": csrf(client), "email": "anne@ex.fr"})
    assert len(app.extensions["outbox"]) == 3     # pas plus de 3 e-mails par heure


def test_supprimer_son_compte(app):
    donor, receiver, other, don_url = setup_don(app)
    receiver.post(don_url + "/messages", data={"_csrf": csrf(receiver, don_url), "body": "Merci",
                                               "photo": image_file()})
    resp = receiver.post("/profil/supprimer", data={"_csrf": csrf(receiver, "/profil"),
                                                    "password": "mauvais"})
    assert "incorrect" in resp.get_data(as_text=True)
    receiver.post("/profil/supprimer", data={"_csrf": csrf(receiver, "/profil"),
                                             "password": "motdepasse"})
    with app.app_context():
        db = get_db()
        assert db.execute("SELECT COUNT(*) FROM users WHERE email = 'receiver@ex.fr'").fetchone()[0] == 0
        assert db.execute("SELECT COUNT(*) FROM dons").fetchone()[0] == 0
        assert db.execute("SELECT COUNT(*) FROM messages").fetchone()[0] == 0
    import os
    assert os.listdir(f"{app.config['UPLOAD_FOLDER']}/messages") == []   # photo effacée du disque
    assert login(app.test_client(), "receiver@ex.fr", "motdepasse").status_code == 200


def test_derriere_un_proxy(tmp_path):
    app = create_app({"SECRET_KEY": "t", "DATABASE": str(tmp_path / "p.sqlite"),
                      "UPLOAD_FOLDER": str(tmp_path), "BEHIND_PROXY": True, "GEOCODER": "none",
                      "SEMANTIC_MODEL": "", "MAIL_BACKEND": "memory"})
    with app.app_context():
        init_db()
    client = app.test_client()
    resp = client.get("/connexion", headers={"X-Forwarded-Proto": "https",
                                            "X-Forwarded-Host": "dondesoi.example.org"})
    assert app.config["SESSION_COOKIE_SECURE"] is True
    assert "Secure" in resp.headers.get("Set-Cookie", "")
    assert client.get("/confidentialite").status_code == 200
