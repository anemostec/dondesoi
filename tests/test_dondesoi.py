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
    app.extensions["communes_cp"] = fake_communes
    with app.app_context():
        init_db()
    return app


# Coordonnées réelles approximatives, pour tester sans réseau.
VILLES = {
    "lyon": (45.758, 4.835), "villeurbanne": (45.767, 4.880), "grenoble": (45.188, 5.724),
    "paris": (48.857, 2.352), "valence": (44.933, 4.892), "marseille": (43.296, 5.370),
}


CODES_POSTAUX = {"lyon": "69001", "villeurbanne": "69100", "grenoble": "38000",
                 "paris": "75001", "valence": "26000", "marseille": "13001"}


def fake_communes(cp):
    """Faux geo.api.gouv.fr : communes d'un code postal (deux Chenereilles pour les tests)."""
    if cp == "42560":
        return [{"nom": "Chenereilles", "lat": 45.48, "lon": 4.09, "dep": "Loire"},
                {"nom": "Marols", "lat": 45.48, "lon": 4.04, "dep": "Loire"}]
    if cp == "43190":
        return [{"nom": "Chenereilles", "lat": 45.11, "lon": 4.24, "dep": "Haute-Loire"}]
    return [{"nom": v.capitalize(), "lat": VILLES[v][0], "lon": VILLES[v][1], "dep": ""}
            for v, c in CODES_POSTAUX.items() if c == cp]


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
            "display_name": name, "city": city, "postal_code": CODES_POSTAUX.get(city.lower(), "")}
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
                                 "city": "Lyon", "postal_code": "69001"})
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
    # Les coordonnées viennent de la liste des communes du code postal (une seule question au
    # service, gardée en cache), sans recherche par nom.
    assert app.extensions["geocoder"].calls == []
    with app.app_context():
        assert get_db().execute("SELECT COUNT(*) FROM codes_postaux").fetchone()[0] == 1


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
        assert len(found) == 1 and found[0]["trajet"]["to_city"] == "Marseille"
        assert "de chez vous" in found[0]["explication"]
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


def test_envoi_par_sendmail(app, tmp_path):
    """Le mode « sendmail » passe le message complet au programme d'envoi local."""
    capture = tmp_path / "mail.eml"
    fake = tmp_path / "sendmail"
    fake.write_text(f"#!/bin/sh\ncat > {capture}\n")
    fake.chmod(0o755)
    app.config.update(MAIL_BACKEND="sendmail", SENDMAIL_PATH=str(fake),
                      MAIL_FROM="Don de soi <ne-pas-repondre@exemple.org>",
                      MAIL_REPLY_TO="contact@exemple.org")
    with app.test_request_context():
        from dondesoi.notifications import send_email
        send_email("anne@ex.fr", "Bonjour", "Un message accentué : prière.", "<p>Bonjour</p>")
    mail = capture.read_text()
    assert "To: anne@ex.fr" in mail and "Reply-To: contact@exemple.org" in mail
    assert "multipart/alternative" in mail and "text/html" in mail and "text/plain" in mail
    assert "ne-pas-repondre@exemple.org" in mail


# --- Invitations ---------------------------------------------------------------------

def invitation_link(app, to):
    mail = [m for m in app.extensions["outbox"] if m["to"] == to][-1]
    return mail, re.search(r"http://localhost(/rejoindre/\S+)", mail["text"]).group(1)


def test_invitation_par_email_et_invite_par(app):
    philippe = app.test_client()
    register(philippe, "philippe@ex.fr", "Philippe", "Lyon")
    philippe.post("/inviter", data={"_csrf": csrf(philippe, "/inviter"),
                                    "email": "Nathanael@Ex.fr", "message": "Viens voir !"})
    mail, link = invitation_link(app, "nathanael@ex.fr")
    assert "Philippe vous invite" in mail["subject"] and "Viens voir !" in mail["text"]
    assert "philippe@ex.fr" not in mail["text"]          # l'adresse de l'invitant n'est pas révélée

    nathanael = app.test_client()
    page = nathanael.get(link).get_data(as_text=True)
    assert "Philippe vous invite" in page and "Jn 1,46" in page
    assert 'value="nathanael@ex.fr"' in nathanael.get("/inscription").get_data(as_text=True)
    register(nathanael, "nathanael@ex.fr", "Nathanaël", "Lyon")

    with app.app_context():
        db = get_db()
        assert db.execute("SELECT invited_by FROM users WHERE email = 'nathanael@ex.fr'").fetchone()[0] == 1
        assert db.execute("SELECT COUNT(*) FROM invitations WHERE email IS NOT NULL").fetchone()[0] == 0
    assert any("a rejoint la famille" in b for b in unread(app, 1))
    assert "Nathanaël" in philippe.get("/inviter").get_data(as_text=True)
    assert "à l'invitation de" in nathanael.get("/tableau-de-bord").get_data(as_text=True)
    # Le lien ne sert qu'une fois.
    assert app.test_client().get(link).status_code == 302


def test_lien_personnel(app):
    philippe, a, b = app.test_client(), app.test_client(), app.test_client()
    register(philippe, "philippe@ex.fr", "Philippe", "Lyon")
    page = philippe.get("/inviter").get_data(as_text=True)
    link = re.search(r'id="lien" value="http://localhost(/rejoindre/[^"]+)"', page).group(1)
    for client, email in ((a, "a@ex.fr"), (b, "b@ex.fr")):   # réutilisable
        assert client.get(link).status_code == 200
        register(client, email, email[0].upper(), "Lyon")
    with app.app_context():
        assert get_db().execute("SELECT COUNT(*) FROM users WHERE invited_by = 1").fetchone()[0] == 2
    assert link in philippe.get("/inviter").get_data(as_text=True)    # toujours le même lien


def test_garde_fous_invitations(app):
    philippe = app.test_client()
    register(philippe, "philippe@ex.fr", "Philippe", "Lyon")
    send = lambda email: philippe.post("/inviter", data={"_csrf": csrf(philippe, "/inviter"),
                                                         "email": email})
    send("philippe@ex.fr")                 # déjà membre : rien n'est envoyé
    send("x@ex.fr"); send("x@ex.fr")       # une seule invitation par adresse
    assert [m["to"] for m in app.extensions["outbox"]] == ["x@ex.fr"]

    # Refus : plus aucune invitation, adresse effacée.
    _, link = invitation_link(app, "x@ex.fr")
    token = link.rsplit("/", 1)[1]
    visitor = app.test_client()
    visitor.post(f"/invitation/{token}/refuser",
                 data={"_csrf": csrf(visitor, f"/invitation/{token}/refuser")})
    with app.app_context():
        assert get_db().execute("SELECT COUNT(*) FROM invitations WHERE email = 'x@ex.fr'").fetchone()[0] == 0
    send("x@ex.fr")
    assert len(app.extensions["outbox"]) == 1

    # Pas plus de 10 par jour.
    for i in range(12):
        send(f"ami{i}@ex.fr")
    # Chaque tentative compte (même sans envoi, pour qu'on ne puisse pas sonder qui est
    # inscrit) : 4 tentatives déjà faites, donc 6 envois de plus, 10 tentatives en tout.
    assert len(app.extensions["outbox"]) == 1 + 6


def test_invitations_effacees_apres_30_jours(app):
    philippe = app.test_client()
    register(philippe, "philippe@ex.fr", "Philippe", "Lyon")
    philippe.post("/inviter", data={"_csrf": csrf(philippe, "/inviter"), "email": "y@ex.fr"})
    with app.app_context():
        db = get_db()
        db.execute("UPDATE invitations SET created_at = datetime('now', '-31 days') WHERE email IS NOT NULL")
        db.commit()
    philippe.get("/inviter")
    with app.app_context():
        assert get_db().execute("SELECT COUNT(*) FROM invitations WHERE email = 'y@ex.fr'").fetchone()[0] == 0



def test_emails_html(app):
    philippe = app.test_client()
    register(philippe, "philippe@ex.fr", "Philippe", "Lyon")
    philippe.post("/inviter", data={"_csrf": csrf(philippe, "/inviter"), "email": "n@ex.fr",
                                    "message": "<script>alert(1)</script> Viens !"})
    mail = app.extensions["outbox"][-1]
    html = mail["html"]
    assert "#a4472d" in html and "Don de soi" in html                     # charte du site
    assert "Découvrir Don de soi" in html and "/rejoindre/" in html      # bouton
    assert "Jn 1,46" in html and "Ne plus jamais recevoir" in html
    assert "<script>" not in html and "&lt;script&gt;" in html             # texte des membres échappé
    assert "/static/email/croix.png" in html

    # Notification et mot de passe oublié ont aussi leur version HTML.
    with app.test_request_context():
        from dondesoi.notifications import notify
        notify(1, "Un membre prie pour vous.", "/annonces/1")
    assert "Voir sur Don de soi" in app.extensions["outbox"][-1]["html"]
    philippe.post("/mot-de-passe-oublie", data={"_csrf": csrf(philippe), "email": "philippe@ex.fr"})
    assert "Choisir un nouveau mot de passe" in app.extensions["outbox"][-1]["html"]


def test_une_parole_differente_par_email(app):
    from dondesoi.evangile import PASSAGES, POUR_EMAILS
    assert set(POUR_EMAILS) <= set(PASSAGES)
    client = app.test_client()
    register(client, "anne@ex.fr", "Anne", "Lyon")
    from dondesoi.notifications import notify
    refs = []
    with app.test_request_context():
        for i in range(len(POUR_EMAILS) + 1):
            notify(1, f"Notification {i}", f"/page/{i}")   # une page par e-mail (pas de regroupement)
            refs.append(re.search(r"font-size:12px;color:#6e6359;\">([^<]+)</p>",
                                  app.extensions["outbox"][-1]["html"]).group(1))
    n = len(POUR_EMAILS)
    assert len(set(refs[:n])) == n          # toutes différentes sur un cycle complet
    assert refs[n] == refs[0]               # puis le cycle recommence
    # Un autre membre reçoit les paroles dans un autre ordre.
    other = app.test_client()
    register(other, "paul@ex.fr", "Paul", "Lyon")
    with app.test_request_context():
        others = []
        for i in range(5):
            notify(2, f"N{i}", f"/autre/{i}")
            others.append(re.search(r"font-size:12px;color:#6e6359;\">([^<]+)</p>",
                                    app.extensions["outbox"][-1]["html"]).group(1))
    assert others != refs[:5]



# --- Trajets réguliers ----------------------------------------------------------------

def test_calendrier_trajet_regulier():
    from datetime import date
    from dondesoi.calendrier import description, occurrences
    t = {"date": "2026-10-01", "jours": "0,3", "heure": "07:30", "date_fin": "2026-10-20"}
    # Le 13/10/2026 est un mardi : prochains lundis et jeudis jusqu'au 20/10.
    assert occurrences(t, depuis=date(2026, 10, 13)) == [date(2026, 10, 15), date(2026, 10, 19)]
    assert description(t).startswith("tous les lundis et jeudis à 7 h 30")
    semaine = {"date": "2026-10-01", "jours": "0,1,2,3,4", "heure": "", "date_fin": None}
    assert description(semaine).startswith("du lundi au vendredi")
    ponctuel = {"date": "2026-10-21", "jours": "", "heure": "09:00", "date_fin": None}
    assert description(ponctuel) == "le mer. 21 oct. à 9 h"


def test_trajet_regulier_avec_retour_et_transport(app):
    from datetime import date, timedelta
    donor, receiver, paul = app.test_client(), app.test_client(), app.test_client()
    register(donor, "donor@ex.fr", "Joseph", "Lyon")          # 1
    register(receiver, "receiver@ex.fr", "Anne", "Valence")    # 2
    register(paul, "paul@ex.fr", "Paul", "Villeurbanne")       # 3

    # Paul fait Villeurbanne → Marseille tous les lundis et jeudis à 7 h 30, retour à 18 h.
    page = paul.post("/trajets/", data={
        "_csrf": csrf(paul, "/trajets/"), "from_city": "Villeurbanne", "from_cp": "69100",
        "to_city": "Marseille", "to_cp": "13001",
        "frequence": "regulier", "jours": ["0", "3"], "heure": "07:30",
        "retour": "1", "heure_retour": "18:00"}, follow_redirects=True).get_data(as_text=True)
    assert "avec son retour" in page and "tous les lundis et jeudis à 7 h 30" in page
    assert "à 18 h" in page
    with app.app_context():
        assert get_db().execute("SELECT COUNT(*) FROM trajets WHERE jours = '0,3'").fetchone()[0] == 2

    # Un don de Lyon vers Valence : le trajet régulier est proposé, avec ses prochaines dates.
    offre = post_annonce(donor, "don", "objet", "Table", "table en bois")
    don_url = donor.post("/dons/preparer", data={"_csrf": csrf(donor, "/tableau-de-bord"),
                         "offre": offre, "receveur": 2, "shared_info": ""}).headers["Location"]
    page = donor.get(don_url).get_data(as_text=True)
    assert "Régulier" in page and 'name="transport_date"' in page
    choix = re.findall(r'<option value="(\d{4}-\d\d-\d\d)">', page)
    assert choix and all(date.fromisoformat(d).weekday() in (0, 3) for d in choix)

    with app.app_context():
        trajet_id = get_db().execute("SELECT id FROM trajets WHERE from_city = 'Villeurbanne'").fetchone()[0]
    # Une date qui n'est pas un jour du trajet est refusée.
    mardi = date.today() + timedelta(days=(1 - date.today().weekday()) % 7 or 7)
    bad = donor.post(don_url + "/transport", data={"_csrf": csrf(donor, don_url), "action": "demander",
                     "trajet_id": trajet_id, "transport_date": mardi.isoformat()})
    assert bad.status_code == 400
    donor.post(don_url + "/transport", data={"_csrf": csrf(donor, don_url), "action": "demander",
               "trajet_id": trajet_id, "transport_date": choix[1]})
    with app.app_context():
        assert get_db().execute("SELECT transport_date FROM dons").fetchone()[0] == choix[1]
    assert any("à 7 h 30" in b for b in unread(app, 3))
    assert "à 07:30" in paul.get("/tableau-de-bord").get_data(as_text=True)


def test_trajet_regulier_termine_disparait(app):
    paul = app.test_client()
    register(paul, "paul@ex.fr", "Paul", "Lyon")
    with app.app_context():
        db = get_db()
        db.execute("INSERT INTO trajets (user_id, from_city, to_city, date, jours, date_fin) "
                   "VALUES (1, 'Lyon', 'Paris', '2020-01-01', '0', '2020-06-01')")
        db.commit()
    assert "Paris" not in paul.get("/trajets/").get_data(as_text=True)



# --- Ville vérifiée par le code postal --------------------------------------------------

def test_ville_verifiee_par_code_postal(app):
    client = app.test_client()
    data = {"_csrf": csrf(client, "/inscription"), "email": "c@ex.fr", "password": "motdepasse",
            "display_name": "Claire", **{f"engagement_{k}": "1" for k in
                                         ("gratuite", "double", "argent", "esprit")}}
    # Mauvaise paire : le site indique les communes du code postal.
    page = client.post("/inscription", data={**data, "city": "Tence", "postal_code": "42560"})
    texte = page.get_data(as_text=True)
    assert "n&#39;a pas le code postal 42560" in texte and "Chenereilles, Marols" in texte
    # Deux Chenereilles : le code postal fait la différence.
    client.post("/inscription", data={**data, "city": "chenereilles", "postal_code": "43190"})
    with app.app_context():
        u = get_db().execute("SELECT city, postal_code, lat FROM users").fetchone()
    assert (u["city"], u["postal_code"], u["lat"]) == ("Chenereilles", "43190", 45.11)

    # Le point d'accès utilisé par le formulaire.
    assert client.get("/communes/42560").get_json()["communes"][0]["dep"] == "Loire"
    assert client.get("/communes/00000").get_json()["communes"] == []


def test_ville_annonce_et_trajet(app):
    client = app.test_client()
    register(client, "a@ex.fr", "Anne", "Lyon")
    # Annonce dans la ville du membre : rien à saisir.
    ok = post_annonce(client, "don", "objet", "Table")
    assert isinstance(ok, int)
    # Annonce ailleurs : le code postal est vérifié.
    page = client.post("/annonces/nouvelle", data={
        "_csrf": csrf(client, "/annonces/nouvelle"), "kind": "don", "category": "objet",
        "title": "Chaise", "city": "Grenoble", "postal_code": "69001"}).get_data(as_text=True)
    assert "n&#39;a pas le code postal" in page
    # Trajet sans code postal d'arrivée : refusé.
    page = client.post("/trajets/", data={
        "_csrf": csrf(client, "/trajets/"), "from_city": "Lyon", "from_cp": "69001",
        "to_city": "Grenoble", "to_cp": "", "frequence": "ponctuel", "date": "2099-01-01"},
        follow_redirects=True).get_data(as_text=True)
    assert "code postal à 5 chiffres" in page


# --- Trajets dans les annonces et recherche -------------------------------------------

def ajouter_trajet(client, depart, arrivee, public=True, **extra):
    data = {"_csrf": csrf(client, "/trajets/"), "from_city": depart,
            "from_cp": CODES_POSTAUX[depart.lower()], "to_city": arrivee,
            "to_cp": CODES_POSTAUX[arrivee.lower()], "frequence": "regulier",
            "jours": ["0", "3"], "heure": "07:30", **extra}
    if public:
        data["public"] = "1"
    return client.post("/trajets/", data=data)


def test_recherche_de_trajets(app):
    paul, anne, visiteur = app.test_client(), app.test_client(), app.test_client()
    register(paul, "paul@ex.fr", "Paul", "Villeurbanne")   # 1
    register(anne, "anne@ex.fr", "Anne", "Lyon")           # 2
    ajouter_trajet(paul, "Villeurbanne", "Marseille")             # public
    ajouter_trajet(paul, "Villeurbanne", "Paris", public=False)   # privé

    # Recherche le long de la route : Lyon → Valence est sur Villeurbanne → Marseille.
    url = "/trajets/recherche?from_cp=69001&from_city=Lyon&to_cp=26000&to_city=Valence"
    page = anne.get(url).get_data(as_text=True)
    assert "Un membre fait Villeurbanne → Marseille" in page
    assert "Paul" not in page and "7 h 30" not in page and "07:30" not in page   # anonyme, sans l'heure
    assert "→ Paris" not in anne.get("/trajets/recherche?to_cp=75001&to_city=Paris").get_data(as_text=True)
    # Mauvais sens : Valence → Lyon ne correspond pas.
    sens_inverse = "/trajets/recherche?from_cp=26000&from_city=Valence&to_cp=69001&to_city=Lyon"
    assert "Villeurbanne → Marseille" not in anne.get(sens_inverse).get_data(as_text=True)
    # Filtre par date : un mardi ne correspond pas à un trajet du lundi et du jeudi.
    from datetime import date, timedelta
    mardi = date.today() + timedelta(days=(1 - date.today().weekday()) % 7 or 7)
    assert "Marseille" not in anne.get(f"/trajets/recherche?date={mardi}").get_data(as_text=True)
    # Encart dans les annonces, et réservé aux membres.
    assert "Trajets qui passent près de chez vous" in anne.get("/annonces/").get_data(as_text=True)
    assert visiteur.get("/trajets/recherche").status_code == 302
    assert "Marseille" not in visiteur.get("/annonces/").get_data(as_text=True)

    # Demande, puis réponse du voyageur.
    with app.app_context():
        trajet_id = get_db().execute("SELECT id FROM trajets WHERE to_city = 'Marseille'").fetchone()[0]
    jour = re.search(r'<option value="(\d{4}-\d\d-\d\d)">', anne.get(url).get_data(as_text=True)).group(1)
    anne.post(f"/trajets/{trajet_id}/demande", data={"_csrf": csrf(anne, url), "date": jour,
                                                     "message": "Un carton de livres pour Valence"})
    assert any("Anne aimerait faire porter" in b for b in unread(app, 1))
    page = paul.get("/trajets/").get_data(as_text=True)
    assert "Un carton de livres pour Valence" in page
    with app.app_context():
        demande_id = get_db().execute("SELECT id FROM trajet_demandes").fetchone()[0]
    paul.post(f"/trajets/demandes/{demande_id}/reponse", data={
        "_csrf": csrf(paul, "/trajets/"), "statut": "acceptee", "reponse": "Paul, 06 00 00 00 00"})
    assert any("Le voyageur accepte" in b for b in unread(app, 2))
    page = anne.get("/trajets/").get_data(as_text=True)
    assert "le voyageur accepte" in page and "Paul, 06 00 00 00 00" in page
    # Seul le voyageur peut répondre.
    assert anne.post(f"/trajets/demandes/{demande_id}/reponse", data={
        "_csrf": csrf(anne, "/trajets/"), "statut": "refusee"}).status_code == 403


def test_visibilite_trajet(app):
    paul, anne = app.test_client(), app.test_client()
    register(paul, "paul@ex.fr", "Paul", "Villeurbanne")
    register(anne, "anne@ex.fr", "Anne", "Lyon")
    ajouter_trajet(paul, "Villeurbanne", "Grenoble", public=False)
    with app.app_context():
        trajet_id = get_db().execute("SELECT id FROM trajets").fetchone()[0]
    assert "Grenoble" not in anne.get("/trajets/recherche").get_data(as_text=True)
    paul.post(f"/trajets/{trajet_id}/visibilite", data={"_csrf": csrf(paul, "/trajets/")})
    assert "Villeurbanne → Grenoble" in anne.get("/trajets/recherche").get_data(as_text=True)
    assert anne.post(f"/trajets/{trajet_id}/visibilite",
                     data={"_csrf": csrf(anne, "/trajets/")}).status_code == 403


def test_mentions_legales_et_interdits(app):
    client = app.test_client()
    page = client.get("/mentions-legales").get_data(as_text=True)
    assert "ALWAYSDATA" in page and "492 893 490" in page and "non professionnel" in page
    register(client, "a@ex.fr", "Anne", "Lyon")
    resp = post_annonce(client, "don", "objet", "Boîte de médicaments")
    assert "ne se donnent pas" in resp.get_data(as_text=True)
    assert isinstance(post_annonce(client, "don", "objet", "Armoire en chêne"), int)   # pas « arme »


# --- Signalement et modération collégiale ----------------------------------------------

def test_moderation_collegiale(app):
    clients = {}
    for i, nom in enumerate(["Anne", "Paul", "Marie", "Luc", "Jean"], start=1):
        clients[i] = app.test_client()
        register(clients[i], f"m{i}@ex.fr", nom, "Lyon")
    annonce = post_annonce(clients[1], "don", "objet", "Vélo", "contactez-moi en privé")
    url = f"/annonces/{annonce}"
    # On ne peut pas signaler son propre contenu.
    assert clients[1].post("/signaler", data={"_csrf": csrf(clients[1], url), "kind": "annonce",
                           "objet_id": annonce, "motif": "argent"}).status_code == 400
    clients[2].post("/signaler", data={"_csrf": csrf(clients[2], url), "kind": "annonce",
                    "objet_id": annonce, "motif": "argent", "retour": url})
    with app.app_context():
        jures = [r[0] for r in get_db().execute("SELECT user_id FROM moderations")]
    assert len(jures) == 3 and 1 not in jures and 2 not in jures      # ni l'auteur ni le signaleur
    for j in jures:
        assert any("tiré au sort" in b for b in unread(app, j))
    # Deux votes « retirer » sur trois : l'annonce disparaît pour les autres.
    for j in jures[:2]:
        page = clients[j].get("/moderation").get_data(as_text=True)
        assert "contactez-moi en privé" in page
        mid = re.search(r"/moderation/(\d+)/vote", page).group(1)
        clients[j].post(f"/moderation/{mid}/vote", data={"_csrf": csrf(clients[j], "/moderation"),
                                                         "vote": "retirer"})
    assert clients[2].get(url).status_code == 404
    assert "Vélo" not in clients[2].get("/annonces/").get_data(as_text=True)
    assert "a été retirée" in clients[1].get(url).get_data(as_text=True)   # l'auteur la voit encore
    assert any("retiré" in b for b in unread(app, 1))
    # Un juré ne peut voter que pour lui-même.
    with app.app_context():
        autre = get_db().execute("SELECT id FROM moderations WHERE user_id = ?", (jures[2],)).fetchone()[0]
    assert clients[jures[0]].post(f"/moderation/{autre}/vote", data={
        "_csrf": csrf(clients[jures[0]], "/moderation"), "vote": "maintenir"}).status_code == 403


def test_signalement_sans_jures_masque_par_precaution(app):
    anne, paul = app.test_client(), app.test_client()
    register(anne, "a@ex.fr", "Anne", "Lyon")
    register(paul, "p@ex.fr", "Paul", "Lyon")
    annonce = post_annonce(anne, "don", "objet", "Table")
    paul.post("/signaler", data={"_csrf": csrf(paul, f"/annonces/{annonce}"), "kind": "annonce",
              "objet_id": annonce, "motif": "charte"})
    assert paul.get(f"/annonces/{annonce}").status_code == 404
