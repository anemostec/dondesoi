from flask import (Blueprint, abort, flash, g, redirect, render_template, request,
                   session, url_for)
from werkzeug.security import check_password_hash, generate_password_hash

from .db import get_db
from .security import login_required

bp = Blueprint("auth", __name__)

# Engagements demandés à l'inscription : ils reprennent l'esprit de la charte.
ENGAGEMENTS = [
    ("gratuite", "Je donne sans rien attendre en retour : le don reste entièrement et toujours gratuit."),
    ("double", "Je m'inscris pour donner ET pour recevoir, selon mes moyens et mes besoins."),
    ("argent", "Je ne demande ni ne propose d'argent à un autre membre."),
    ("esprit", "Je me reconnais dans l'esprit de Don de soi, inspiré de l'exemple de vie de Jésus-Christ, "
               "et je respecte la liberté de conscience de chacun."),
]


@bp.route("/inscription", methods=("GET", "POST"))
def inscription():
    form = request.form
    if request.method == "POST":
        email = form.get("email", "").strip().lower()
        password = form.get("password", "")
        display_name = form.get("display_name", "").strip()
        city = form.get("city", "").strip()
        error = None
        if not email or "@" not in email:
            error = "Adresse e-mail invalide."
        elif len(password) < 8:
            error = "Le mot de passe doit contenir au moins 8 caractères."
        elif not display_name or not city:
            error = "Le prénom (ou pseudonyme) et la ville sont nécessaires."
        elif not all(form.get(f"engagement_{key}") for key, _ in ENGAGEMENTS):
            error = "Merci de prendre chacun des engagements pour rejoindre Don de soi."

        if error is None:
            db = get_db()
            try:
                cur = db.execute(
                    """INSERT INTO users (email, password_hash, display_name, city, postal_code,
                                          charter_accepted_at)
                       VALUES (?, ?, ?, ?, ?, datetime('now'))""",
                    (email, generate_password_hash(password), display_name, city,
                     form.get("postal_code", "").strip()),
                )
                db.commit()
            except db.IntegrityError:
                error = "Un compte existe déjà avec cette adresse."
            else:
                session.clear()
                session["user_id"] = cur.lastrowid
                flash("Bienvenue dans la famille Don de soi ! Commencez par dire ce que vous "
                      "aimeriez donner, et ce dont vous auriez besoin.")
                return redirect(url_for("main.tableau_de_bord"))
        flash(error, "erreur")
    return render_template("auth/inscription.html", engagements=ENGAGEMENTS, form=form)


@bp.route("/connexion", methods=("GET", "POST"))
def connexion():
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        user = get_db().execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
        if user is None or not check_password_hash(user["password_hash"], request.form.get("password", "")):
            flash("Adresse ou mot de passe incorrect.", "erreur")
        else:
            session.clear()
            session["user_id"] = user["id"]
            target = request.args.get("next", "")
            if not target.startswith("/") or target.startswith("//"):
                target = url_for("main.tableau_de_bord")
            return redirect(target)
    return render_template("auth/connexion.html")


@bp.route("/deconnexion", methods=("POST",))
def deconnexion():
    session.clear()
    return redirect(url_for("main.accueil"))


@bp.route("/profil", methods=("GET", "POST"))
@login_required
def profil():
    if request.method == "POST":
        f = request.form
        display_name, city = f.get("display_name", "").strip(), f.get("city", "").strip()
        if not display_name or not city:
            flash("Le prénom (ou pseudonyme) et la ville sont nécessaires.", "erreur")
        else:
            db = get_db()
            db.execute(
                """UPDATE users SET display_name = ?, city = ?, postal_code = ?, bio = ?, contact = ?,
                                    email_notifications = ?
                   WHERE id = ?""",
                (display_name, city, f.get("postal_code", "").strip(), f.get("bio", "").strip(),
                 f.get("contact", "").strip(), int(bool(f.get("email_notifications"))),
                 g.user["id"]),
            )
            db.commit()
            flash("Profil mis à jour.")
            return redirect(url_for("auth.profil"))
    return render_template("auth/profil.html")


@bp.route("/membre/<int:user_id>")
@login_required
def membre(user_id):
    """Profil public d'un membre : ce qu'il a publié, ses besoins, les avis reçus.

    Les dons qu'il propose n'y figurent pas : le don se fait dans la discrétion.
    """
    db = get_db()
    membre = db.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    if membre is None:
        abort(404)
    besoins = db.execute(
        "SELECT a.*, u.display_name FROM annonces a JOIN users u ON u.id = a.user_id "
        "WHERE a.user_id = ? AND a.kind = 'besoin' AND a.status = 'ouverte' "
        "ORDER BY a.created_at DESC", (user_id,),
    ).fetchall()
    avis = db.execute(
        "SELECT * FROM avis WHERE subject_id = ? ORDER BY created_at DESC", (user_id,),
    ).fetchall()
    nb_recus = db.execute(
        "SELECT COUNT(*) FROM dons WHERE receiver_id = ? AND status != 'annule'", (user_id,),
    ).fetchone()[0]
    return render_template("auth/membre.html", membre=membre, besoins=besoins, avis=avis,
                           nb_recus=nb_recus)
