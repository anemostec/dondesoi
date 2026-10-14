import hashlib

from flask import (Blueprint, abort, current_app, flash, g, redirect, render_template, request,
                   session, url_for)
from itsdangerous import BadSignature, URLSafeTimedSerializer
from werkzeug.security import check_password_hash, generate_password_hash

from .db import get_db
from .geo import VilleInvalide, verifier_ville
from .notifications import prochain_verset, rendre_email, send_email
from .photos import COVER_SQL
from .security import login_required, trop_de_demandes

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
        elif not display_name:
            error = "Merci d'indiquer votre prénom ou un pseudonyme."
        elif not all(form.get(f"engagement_{key}") for key, _ in ENGAGEMENTS):
            error = "Merci de prendre chacun des engagements pour rejoindre Don de soi."
        postal_code = form.get("postal_code", "").strip()
        if error is None:
            try:
                city, lat, lon = verifier_ville(city, postal_code)
            except VilleInvalide as e:
                error = str(e)

        if error is None:
            db = get_db()
            try:
                cur = db.execute(
                    """INSERT INTO users (email, password_hash, display_name, city, postal_code,
                                          lat, lon, charter_accepted_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, datetime('now'))""",
                    (email, generate_password_hash(password), display_name, city, postal_code,
                     lat, lon),
                )
                db.commit()
            except db.IntegrityError:
                error = "Un compte existe déjà avec cette adresse."
            else:
                from .invitations import accepter
                accepter(db, cur.lastrowid)   # relie au membre qui a invité, s'il y en a un
                session.clear()
                session["user_id"] = cur.lastrowid
                flash("Bienvenue dans la famille Don de soi ! Commencez par dire ce que vous "
                      "aimeriez donner, et ce dont vous auriez besoin.")
                return redirect(url_for("main.tableau_de_bord"))
        flash(error, "erreur")
    from .invitations import invitation_en_cours
    invitation = invitation_en_cours()
    if request.method == "GET" and invitation is not None and invitation["email"]:
        form = {"email": invitation["email"]}
    return render_template("auth/inscription.html", engagements=ENGAGEMENTS, form=form,
                           invitation=invitation)


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


def _reset_serializer():
    return URLSafeTimedSerializer(current_app.config["SECRET_KEY"], salt="mot-de-passe-oublie")


def _password_fingerprint(user):
    return hashlib.sha256(user["password_hash"].encode()).hexdigest()[:16]


def make_reset_token(user):
    # Une empreinte du mot de passe actuel est signée avec le lien : dès que
    # le mot de passe change, le lien ne fonctionne plus (usage unique).
    return _reset_serializer().dumps({"id": user["id"], "pw": _password_fingerprint(user)})


def user_from_reset_token(token):
    try:
        data = _reset_serializer().loads(token, max_age=current_app.config["PASSWORD_RESET_MAX_AGE"])
    except BadSignature:  # couvre aussi le lien expiré
        return None
    user = get_db().execute("SELECT * FROM users WHERE id = ?", (data.get("id"),)).fetchone()
    if user is None or _password_fingerprint(user) != data.get("pw"):
        return None
    return user


@bp.route("/mot-de-passe-oublie", methods=("GET", "POST"))
def mot_de_passe_oublie():
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        user = get_db().execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
        # Pas plus de 3 e-mails par adresse et par heure, ni de 10 demandes par connexion :
        # le formulaire ne doit pas servir à inonder la boîte de quelqu'un.
        limite = (trop_de_demandes(f"reset-ip:{request.remote_addr}", 10, 60)
                  or (user is not None and trop_de_demandes(f"reset:{email}", 3, 60)))
        if user is not None and not limite:
            link = url_for("auth.reinitialiser", token=make_reset_token(user), _external=True)
            minutes = current_app.config["PASSWORD_RESET_MAX_AGE"] // 60
            ignorer = ("Si vous n'êtes pas à l'origine de cette demande, ignorez simplement ce "
                       "message : votre mot de passe actuel reste valable.")
            send_email(user["email"], "Don de soi : choisir un nouveau mot de passe",
                       f"Bonjour {user['display_name']},\n\n"
                       f"Pour choisir un nouveau mot de passe, ouvrez ce lien (valable {minutes} minutes,"
                       f" utilisable une seule fois) :\n\n{link}\n\n{ignorer}\n\nDon de soi\n",
                       rendre_email(
                           titre="Choisir un nouveau mot de passe",
                           apercu="Le lien pour choisir un nouveau mot de passe",
                           paragraphes=[f"Bonjour {user['display_name']},",
                                        "Vous avez demandé à choisir un nouveau mot de passe pour "
                                        "votre compte Don de soi."],
                           bouton_texte="Choisir un nouveau mot de passe", bouton_url=link,
                           notes=[f"Ce lien est valable {minutes} minutes et ne sert qu'une fois.",
                                  ignorer],
                           verset=prochain_verset(user["id"])))
        # Même réponse que le compte existe ou non, pour ne pas révéler qui est inscrit.
        flash("Si un compte existe avec cette adresse, un e-mail vient de lui être envoyé avec un "
              "lien pour choisir un nouveau mot de passe.")
        return redirect(url_for("auth.connexion"))
    return render_template("auth/mot_de_passe_oublie.html")


@bp.route("/reinitialiser/<token>", methods=("GET", "POST"))
def reinitialiser(token):
    user = user_from_reset_token(token)
    if user is None:
        flash("Ce lien n'est plus valable (expiré ou déjà utilisé). Vous pouvez en demander un "
              "nouveau.", "erreur")
        return redirect(url_for("auth.mot_de_passe_oublie"))
    if request.method == "POST":
        password = request.form.get("password", "")
        if len(password) < 8:
            flash("Le mot de passe doit contenir au moins 8 caractères.", "erreur")
        elif password != request.form.get("password2", ""):
            flash("Les deux mots de passe ne sont pas identiques.", "erreur")
        else:
            db = get_db()
            db.execute("UPDATE users SET password_hash = ? WHERE id = ?",
                       (generate_password_hash(password), user["id"]))
            db.commit()
            session.clear()
            session["user_id"] = user["id"]
            flash("Votre mot de passe a été changé.")
            return redirect(url_for("main.tableau_de_bord"))
    return render_template("auth/reinitialiser.html")


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
        postal_code = f.get("postal_code", "").strip()
        try:
            if not display_name:
                raise VilleInvalide("Merci d'indiquer votre prénom ou un pseudonyme.")
            city, lat, lon = verifier_ville(city, postal_code)
        except VilleInvalide as e:
            flash(str(e), "erreur")
        else:
            db = get_db()
            db.execute(
                """UPDATE users SET display_name = ?, city = ?, postal_code = ?, bio = ?, contact = ?,
                                    email_notifications = ?, lat = ?, lon = ?
                   WHERE id = ?""",
                (display_name, city, postal_code, f.get("bio", "").strip(),
                 f.get("contact", "").strip(), int(bool(f.get("email_notifications"))),
                 lat, lon, g.user["id"]),
            )
            db.commit()
            flash("Profil mis à jour.")
            return redirect(url_for("auth.profil"))
    return render_template("auth/profil.html")


@bp.route("/profil/supprimer", methods=("GET", "POST"))
@login_required
def supprimer_compte():
    """Chacun est libre de partir (Jn 6,67) : le compte et tout son contenu sont effacés."""
    if request.method == "POST":
        if not check_password_hash(g.user["password_hash"], request.form.get("password", "")):
            flash("Mot de passe incorrect.", "erreur")
        else:
            from .photos import delete_photo
            db = get_db()
            uid = g.user["id"]
            for p in db.execute("SELECT p.filename FROM annonce_photos p JOIN annonces a "
                                "ON a.id = p.annonce_id WHERE a.user_id = ?", (uid,)):
                delete_photo(p["filename"])
            for m in db.execute("SELECT photo FROM messages WHERE author_id = ? AND photo IS NOT NULL",
                                (uid,)):
                delete_photo(m["photo"], "messages")
            for gr in db.execute("SELECT photo FROM actions_grace WHERE author_id = ? "
                                 "AND photo IS NOT NULL", (uid,)):
                delete_photo(gr["photo"], "grace")
            db.execute("DELETE FROM users WHERE id = ?", (uid,))   # le reste suit (ON DELETE CASCADE)
            db.commit()
            session.clear()
            flash("Votre compte et tout ce que vous aviez publié ont été supprimés. Que Dieu vous garde.")
            return redirect(url_for("main.accueil"))
    return render_template("auth/supprimer.html")


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
        f"SELECT a.*, u.display_name, {COVER_SQL} FROM annonces a JOIN users u ON u.id = a.user_id "
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
