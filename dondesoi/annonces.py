import re

from flask import Blueprint, abort, flash, g, redirect, render_template, request, url_for

from . import CATEGORY_LABELS, ESSENTIAL_CATEGORIES
from .db import get_db
from .geo import VilleInvalide, coords_or_none, distance_rows, verifier_ville
from .matching import candidats_pour_offre, is_essential, offres_pour_besoin
from .notifications import notify
from .photos import (COVER_SQL, MAX_PHOTOS_PAR_ANNONCE, PhotoInvalide, delete_photo,
                     save_photos)
from .security import login_required
from .sens import oublier
from .textes import normalize_city

bp = Blueprint("annonces", __name__, url_prefix="/annonces")

# Score à partir duquel on prévient les membres d'une correspondance
# (une catégorie commune seule vaut 3 : il faut au moins un autre indice).
NOTIFY_MIN_SCORE = 4
NOTIFY_MAX = 10

# Le don d'argent entre membres n'est pas permis (charte, « Don d'argent »).
MONEY_PATTERN = re.compile(
    r"(\d+\s?(€|eur\b|euros?\b))|\b(virement|paypal|lydia|western union|argent liquide|"
    r"chèque|cheque|espèces|especes|iban)\b",
    re.IGNORECASE,
)


def get_annonce(annonce_id):
    annonce = get_db().execute("SELECT * FROM annonces WHERE id = ?", (annonce_id,)).fetchone()
    if annonce is None:
        abort(404)
    return annonce


def get_photos(annonce_id):
    return get_db().execute(
        "SELECT * FROM annonce_photos WHERE annonce_id = ? ORDER BY position, id", (annonce_id,),
    ).fetchall()


def add_photos(db, annonce_id, filenames):
    start = db.execute("SELECT COALESCE(MAX(position), -1) + 1 FROM annonce_photos "
                       "WHERE annonce_id = ?", (annonce_id,)).fetchone()[0]
    db.executemany(
        "INSERT INTO annonce_photos (annonce_id, filename, position) VALUES (?, ?, ?)",
        [(annonce_id, name, start + i) for i, name in enumerate(filenames)],
    )


def validate_form(form):
    """Vérifie les champs communs à la création et à la modification."""
    title = form.get("title", "").strip()
    if not title:
        return "Merci de donner un titre à votre annonce."
    if form.get("category", "") not in CATEGORY_LABELS:
        return "Merci de choisir une catégorie."
    if MONEY_PATTERN.search(title + " " + form.get("description", "")):
        return ("Le don d'argent entre membres n'est pas permis. Vous pouvez soutenir la "
                "communauté via la page « Don d'argent ».")
    return None


def annonce_lieu(form):
    """(ville, code postal, lat, lon) de l'annonce : ceux du membre par défaut, sinon la ville
    saisie, vérifiée par son code postal. Lève VilleInvalide."""
    city, cp = form.get("city", "").strip(), form.get("postal_code", "").strip()
    u = g.user
    if not city and not cp or (normalize_city(city) == normalize_city(u["city"])
                               and cp in ("", u["postal_code"])):
        if u["lat"] is None:
            return (u["city"], u["postal_code"], *coords_or_none(u["city"], u["postal_code"]))
        return u["city"], u["postal_code"], u["lat"], u["lon"]
    nom, lat, lon = verifier_ville(city, cp)
    return nom, cp, lat, lon


# Rayons proposés dans la liste des annonces, en km.
RAYONS = (5, 15, 30, 100)


def essential_from_form(kind, form):
    return int(kind == "besoin" and (form.get("essential") == "1"
                                     or form.get("category") in ESSENTIAL_CATEGORIES))


@bp.route("/")
def liste():
    kind = request.args.get("type", "")
    category = request.args.get("categorie", "")
    q = request.args.get("q", "").strip()
    if kind == "trajet":
        return redirect(url_for("trajets.recherche"))

    sql = [f"SELECT a.*, u.display_name, {COVER_SQL}, "
           "(SELECT COUNT(*) FROM prieres p WHERE p.annonce_id = a.id) AS nb_prieres "
           "FROM annonces a JOIN users u ON u.id = a.user_id WHERE a.status = 'ouverte'"]
    params = []
    if kind in ("don", "besoin"):
        sql.append("AND a.kind = ?")
        params.append(kind)
    if category in CATEGORY_LABELS:
        sql.append("AND a.category = ?")
        params.append(category)
    if q:
        sql.append("AND (a.title LIKE ? OR a.description LIKE ? OR a.city LIKE ?)")
        params += [f"%{q}%"] * 3
    # Les besoins de première nécessité en premier.
    sql.append("ORDER BY (a.kind = 'besoin' AND (a.essential OR a.category IN (%s))) DESC, "
               "a.created_at DESC" % ",".join("?" * len(ESSENTIAL_CATEGORIES)))
    params += sorted(ESSENTIAL_CATEGORIES)

    rows = get_db().execute(" ".join(sql), params).fetchall()

    # Distance depuis chez le membre connecté, et filtre « dans un rayon de ».
    rayon = request.args.get("rayon", type=int)
    localise = g.user is not None and g.user["lat"] is not None
    annonces = []
    for row in rows:
        a = dict(row)
        a["distance"] = distance_rows(g.user, row) if localise else None
        if rayon and localise and (a["distance"] is None or a["distance"] > rayon):
            continue
        annonces.append(a)
    # Trajets publics qui passent près de chez le membre (visibles des membres seulement).
    trajets = []
    if g.user is not None and not kind and not category and not q:
        from .matching import rechercher_trajets
        u = g.user
        trajets = rechercher_trajets(get_db(), u["id"], (u["city"], u["lat"], u["lon"]), limite=3)
    return render_template("annonces/liste.html", annonces=annonces, kind=kind,
                           category=category, q=q, rayon=rayon, rayons=RAYONS,
                           localise=localise, trajets=trajets)


@bp.route("/nouvelle", methods=("GET", "POST"))
@login_required
def nouvelle():
    kind = request.values.get("kind", "don")
    if kind not in ("don", "besoin"):
        kind = "don"
    form = request.form
    if request.method == "POST":
        error = validate_form(form)
        filenames = []
        if error is None:
            try:
                city, cp, lat, lon = annonce_lieu(form)
            except VilleInvalide as e:
                error = str(e)
        if error is None:
            try:
                filenames = save_photos(request.files.getlist("photos"))
            except PhotoInvalide as e:
                error = str(e)

        if error is None:
            db = get_db()
            cur = db.execute(
                """INSERT INTO annonces (user_id, kind, category, title, description, city,
                                         postal_code, essential, lat, lon)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (g.user["id"], kind, form["category"], form["title"].strip(),
                 form.get("description", "").strip(), city, cp, essential_from_form(kind, form),
                 lat, lon),
            )
            add_photos(db, cur.lastrowid, filenames)
            db.commit()
            notifier_correspondances(db, cur.lastrowid)
            flash("Merci ! Votre don est publié." if kind == "don"
                  else "Votre besoin est publié. Recevoir est aussi une façon de laisser l'autre donner.")
            return redirect(url_for("annonces.detail", annonce_id=cur.lastrowid))
        flash(error, "erreur")
    return render_template("annonces/nouvelle.html", kind=kind, form=form, annonce=None,
                           photos=[], max_photos=MAX_PHOTOS_PAR_ANNONCE)


@bp.route("/<int:annonce_id>/modifier", methods=("GET", "POST"))
@login_required
def modifier(annonce_id):
    annonce = get_annonce(annonce_id)
    if annonce["user_id"] != g.user["id"]:
        abort(403)
    if annonce["status"] == "close":
        flash("Une annonce clôturée ne peut plus être modifiée.", "erreur")
        return redirect(url_for("annonces.detail", annonce_id=annonce_id))
    photos = get_photos(annonce_id)
    form = request.form if request.method == "POST" else annonce

    if request.method == "POST":
        error = validate_form(form)
        to_delete = {int(i) for i in request.form.getlist("supprimer_photo") if i.isdigit()}
        remaining = len([p for p in photos if p["id"] not in to_delete])
        filenames = []
        if error is None:
            try:
                city, cp, lat, lon = annonce_lieu(form)
            except VilleInvalide as e:
                error = str(e)
        if error is None:
            try:
                filenames = save_photos(request.files.getlist("photos"),
                                        limit=MAX_PHOTOS_PAR_ANNONCE - remaining)
            except PhotoInvalide as e:
                error = str(e) if remaining == 0 else (
                    f"{e} Cette annonce a déjà {remaining} photo(s) sur {MAX_PHOTOS_PAR_ANNONCE}.")
        if error is None:
            db = get_db()
            db.execute(
                """UPDATE annonces SET title = ?, description = ?, category = ?, city = ?,
                                       postal_code = ?, essential = ?, lat = ?, lon = ? WHERE id = ?""",
                (form["title"].strip(), form.get("description", "").strip(), form["category"],
                 city, cp, essential_from_form(annonce["kind"], form), lat, lon, annonce_id),
            )
            oublier(db, annonce_id)   # le texte a pu changer : le sens sera recalculé
            for p in photos:
                if p["id"] in to_delete:
                    db.execute("DELETE FROM annonce_photos WHERE id = ?", (p["id"],))
                    delete_photo(p["filename"])
            add_photos(db, annonce_id, filenames)
            db.commit()
            flash("Annonce mise à jour.")
            return redirect(url_for("annonces.detail", annonce_id=annonce_id))
        flash(error, "erreur")
    return render_template("annonces/nouvelle.html", kind=annonce["kind"], form=form,
                           annonce=annonce, photos=photos, max_photos=MAX_PHOTOS_PAR_ANNONCE)


def notifier_correspondances(db, annonce_id):
    """Prévient les membres dont une annonce correspond à celle qui vient d'être publiée."""
    annonce = get_annonce(annonce_id)
    link = url_for("annonces.detail", annonce_id=annonce_id)
    if annonce["kind"] == "don":
        for c in candidats_pour_offre(db, annonce)[:NOTIFY_MAX]:
            if c["besoin"] is not None and c["score"] >= NOTIFY_MIN_SCORE:
                notify(c["receiver_id"],
                       f"Un don pourrait répondre à votre besoin « {c['besoin']['title']} » : "
                       f"« {annonce['title']} ».", link)
    else:
        essential = " de première nécessité" if is_essential(annonce) else ""
        for s in offres_pour_besoin(db, annonce, limit=NOTIFY_MAX):
            if s["score"] >= NOTIFY_MIN_SCORE:
                notify(s["offre"]["user_id"],
                       f"Un nouveau besoin{essential} pourrait correspondre à votre don "
                       f"« {s['offre']['title']} ».",
                       url_for("annonces.detail", annonce_id=s["offre"]["id"]))


@bp.route("/<int:annonce_id>")
def detail(annonce_id):
    db = get_db()
    annonce = get_annonce(annonce_id)
    auteur = db.execute("SELECT * FROM users WHERE id = ?", (annonce["user_id"],)).fetchone()
    is_owner = g.user is not None and g.user["id"] == annonce["user_id"]
    ctx = {"annonce": annonce, "auteur": auteur, "is_owner": is_owner,
           "distance": distance_rows(g.user, annonce) if g.user is not None and not is_owner else None,
           "photos": get_photos(annonce_id),
           "nb_prieres": db.execute("SELECT COUNT(*) FROM prieres WHERE annonce_id = ?",
                                    (annonce_id,)).fetchone()[0]}

    if annonce["kind"] == "don" and is_owner and annonce["status"] == "ouverte":
        ctx["candidats"] = candidats_pour_offre(db, annonce)
    elif annonce["kind"] == "besoin" and is_owner and annonce["status"] == "ouverte":
        ctx["suggestions"] = offres_pour_besoin(db, annonce)
    elif annonce["kind"] == "don" and g.user is not None:
        ctx["mon_interet"] = db.execute(
            "SELECT * FROM interets WHERE annonce_id = ? AND user_id = ?",
            (annonce_id, g.user["id"]),
        ).fetchone()
    elif annonce["kind"] == "besoin" and g.user is not None:
        # Un donateur peut répondre à ce besoin avec l'un de ses dons ouverts.
        ctx["mes_offres"] = db.execute(
            "SELECT * FROM annonces WHERE user_id = ? AND kind = 'don' AND status = 'ouverte'",
            (g.user["id"],),
        ).fetchall()
        ctx["je_prie"] = db.execute(
            "SELECT 1 FROM prieres WHERE annonce_id = ? AND user_id = ?",
            (annonce_id, g.user["id"]),
        ).fetchone() is not None
    return render_template("annonces/detail.html", **ctx)


@bp.route("/<int:annonce_id>/priere", methods=("POST",))
@login_required
def priere(annonce_id):
    """« Je prie pour vous » : porter le besoin d'un autre membre dans la prière."""
    annonce = get_annonce(annonce_id)
    if annonce["kind"] != "besoin" or annonce["user_id"] == g.user["id"]:
        abort(400)
    db = get_db()
    if request.form.get("retirer"):
        db.execute("DELETE FROM prieres WHERE annonce_id = ? AND user_id = ?",
                   (annonce_id, g.user["id"]))
        db.commit()
    else:
        cur = db.execute("INSERT OR IGNORE INTO prieres (annonce_id, user_id) VALUES (?, ?)",
                         (annonce_id, g.user["id"]))
        db.commit()
        if cur.rowcount:
            notify(annonce["user_id"],
                   f"Un membre porte votre besoin « {annonce['title']} » dans la prière.",
                   url_for("annonces.detail", annonce_id=annonce_id))
            flash("Merci de porter cette intention dans votre prière.")
    return redirect(url_for("annonces.detail", annonce_id=annonce_id))


@bp.route("/<int:annonce_id>/interet", methods=("POST",))
@login_required
def interet(annonce_id):
    annonce = get_annonce(annonce_id)
    if annonce["kind"] != "don" or annonce["user_id"] == g.user["id"] or annonce["status"] != "ouverte":
        abort(400)
    db = get_db()
    if request.form.get("retirer"):
        db.execute("DELETE FROM interets WHERE annonce_id = ? AND user_id = ?",
                   (annonce_id, g.user["id"]))
        flash("Votre signalement est retiré.")
    else:
        db.execute(
            "INSERT OR REPLACE INTO interets (annonce_id, user_id, message) VALUES (?, ?, ?)",
            (annonce_id, g.user["id"], request.form.get("message", "").strip()),
        )
        db.commit()
        notify(annonce["user_id"],
               f"Un membre signale que votre don « {annonce['title']} » lui serait utile.",
               url_for("annonces.detail", annonce_id=annonce_id))
        flash("Le donateur sait que ce don vous serait utile. Il reste libre de son choix.")
    db.commit()
    return redirect(url_for("annonces.detail", annonce_id=annonce_id))


@bp.route("/<int:annonce_id>/cloturer", methods=("POST",))
@login_required
def cloturer(annonce_id):
    annonce = get_annonce(annonce_id)
    if annonce["user_id"] != g.user["id"]:
        abort(403)
    db = get_db()
    db.execute("UPDATE annonces SET status = 'close' WHERE id = ?", (annonce_id,))
    db.commit()
    flash("Annonce clôturée.")
    return redirect(url_for("main.tableau_de_bord"))
