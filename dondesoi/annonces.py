import os
import re
import uuid

from flask import (Blueprint, abort, current_app, flash, g, redirect, render_template,
                   request, send_from_directory, url_for)

from . import CATEGORY_LABELS, ESSENTIAL_CATEGORIES
from .db import get_db
from .matching import candidats_pour_offre, is_essential, offres_pour_besoin
from .notifications import notify
from .security import login_required

bp = Blueprint("annonces", __name__, url_prefix="/annonces")

# Score à partir duquel on prévient les membres d'une correspondance
# (une catégorie commune seule vaut 3 : il faut au moins un autre indice).
NOTIFY_MIN_SCORE = 4
NOTIFY_MAX = 10

PHOTO_EXTENSIONS = {"jpg", "jpeg", "png", "webp", "gif"}

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


@bp.route("/")
def liste():
    kind = request.args.get("type", "")
    category = request.args.get("categorie", "")
    q = request.args.get("q", "").strip()

    sql = ["SELECT a.*, u.display_name FROM annonces a JOIN users u ON u.id = a.user_id "
           "WHERE a.status = 'ouverte'"]
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

    annonces = get_db().execute(" ".join(sql), params).fetchall()
    return render_template("annonces/liste.html", annonces=annonces, kind=kind,
                           category=category, q=q)


@bp.route("/nouvelle", methods=("GET", "POST"))
@login_required
def nouvelle():
    kind = request.values.get("kind", "don")
    if kind not in ("don", "besoin"):
        kind = "don"
    form = request.form
    if request.method == "POST":
        title = form.get("title", "").strip()
        description = form.get("description", "").strip()
        category = form.get("category", "")
        city = form.get("city", "").strip() or g.user["city"]
        error = None
        if not title:
            error = "Merci de donner un titre à votre annonce."
        elif category not in CATEGORY_LABELS:
            error = "Merci de choisir une catégorie."
        elif MONEY_PATTERN.search(title + " " + description):
            error = ("Le don d'argent entre membres n'est pas permis. Vous pouvez soutenir la "
                     "communauté via la page « Don d'argent ».")

        photo_name = None
        photo = request.files.get("photo")
        if error is None and photo and photo.filename:
            ext = photo.filename.rsplit(".", 1)[-1].lower() if "." in photo.filename else ""
            if ext not in PHOTO_EXTENSIONS:
                error = "Format de photo non accepté (jpg, png, webp, gif)."
            else:
                photo_name = f"{uuid.uuid4().hex}.{ext}"
                photo.save(os.path.join(current_app.config["UPLOAD_FOLDER"], photo_name))

        if error is None:
            essential = kind == "besoin" and (form.get("essential") == "1"
                                              or category in ESSENTIAL_CATEGORIES)
            db = get_db()
            cur = db.execute(
                """INSERT INTO annonces (user_id, kind, category, title, description, city,
                                         essential, photo)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (g.user["id"], kind, category, title, description, city, int(essential), photo_name),
            )
            db.commit()
            notifier_correspondances(db, cur.lastrowid)
            flash("Merci ! Votre don est publié." if kind == "don"
                  else "Votre besoin est publié. Recevoir est aussi une façon de laisser l'autre donner.")
            return redirect(url_for("annonces.detail", annonce_id=cur.lastrowid))
        flash(error, "erreur")
    return render_template("annonces/nouvelle.html", kind=kind, form=form)


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
    ctx = {"annonce": annonce, "auteur": auteur, "is_owner": is_owner}

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
    return render_template("annonces/detail.html", **ctx)


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


@bp.route("/photo/<path:filename>")
def photo(filename):
    return send_from_directory(current_app.config["UPLOAD_FOLDER"], filename)
