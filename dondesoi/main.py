from flask import Blueprint, abort, current_app, g, render_template, send_from_directory

from .db import get_db
from .security import login_required

bp = Blueprint("main", __name__)


@bp.route("/")
def accueil():
    db = get_db()
    stats = {
        "membres": db.execute("SELECT COUNT(*) FROM users").fetchone()[0],
        "dons_ouverts": db.execute(
            "SELECT COUNT(*) FROM annonces WHERE kind='don' AND status='ouverte'").fetchone()[0],
        "besoins_ouverts": db.execute(
            "SELECT COUNT(*) FROM annonces WHERE kind='besoin' AND status='ouverte'").fetchone()[0],
        "dons_realises": db.execute(
            "SELECT COUNT(*) FROM dons WHERE status='realise'").fetchone()[0],
        "prieres": db.execute("SELECT COUNT(*) FROM prieres").fetchone()[0],
    }
    return render_template("pages/accueil.html", stats=stats, graces=actions_grace_publiques(3))


def actions_grace_publiques(limit):
    """Actions de grâce publiées : jamais de nom, seulement la ville du receveur."""
    return get_db().execute(
        """SELECT ag.id, ag.body, ag.photo, ag.created_at, u.city
           FROM actions_grace ag JOIN users u ON u.id = ag.author_id
           WHERE ag.public = 1 ORDER BY ag.created_at DESC LIMIT ?""",
        (limit,),
    ).fetchall()


@bp.route("/actions-de-grace")
def actions_de_grace():
    return render_template("pages/actions_de_grace.html", graces=actions_grace_publiques(200))


@bp.route("/photos/<subdir>/<filename>")
def photo(subdir, filename):
    """Photos des annonces, publiques. Celles des messages et des actions de grâce
    passent par des routes de dons.py qui vérifient qui peut les voir."""
    if subdir != "annonces":
        abort(404)
    return send_from_directory(f"{current_app.config['UPLOAD_FOLDER']}/{subdir}", filename,
                               max_age=7 * 24 * 3600)


@bp.route("/charte")
def charte():
    return render_template("pages/charte.html")


@bp.route("/pour-qui")
def pour_qui():
    return render_template("pages/pour_qui.html")


@bp.route("/fonctionnement")
def fonctionnement():
    return render_template("pages/fonctionnement.html")


@bp.route("/don-argent")
def don_argent():
    return render_template("pages/don_argent.html")


@bp.route("/partenaires")
def partenaires():
    return render_template("pages/partenaires.html")


@bp.route("/confidentialite")
def confidentialite():
    return render_template("pages/confidentialite.html")


@bp.route("/contribuer")
def contribuer():
    return render_template("pages/contribuer.html")


@bp.route("/tableau-de-bord")
@login_required
def tableau_de_bord():
    db = get_db()
    uid = g.user["id"]
    mes_annonces = db.execute(
        """SELECT a.*,
                  (SELECT COUNT(*) FROM interets i WHERE i.annonce_id = a.id) AS nb_interets
           FROM annonces a WHERE a.user_id = ? AND a.status != 'close'
           ORDER BY a.created_at DESC""",
        (uid,),
    ).fetchall()
    dons_donnes = db.execute(
        """SELECT d.*, a.title, u.display_name AS receiver_name
           FROM dons d JOIN annonces a ON a.id = d.offre_id JOIN users u ON u.id = d.receiver_id
           WHERE d.donor_id = ? ORDER BY d.created_at DESC""",
        (uid,),
    ).fetchall()
    dons_recus = db.execute(
        """SELECT d.*, a.title FROM dons d JOIN annonces a ON a.id = d.offre_id
           WHERE d.receiver_id = ? ORDER BY d.created_at DESC""",
        (uid,),
    ).fetchall()
    transports = db.execute(
        """SELECT d.*, a.title, t.from_city, t.to_city, t.date
           FROM dons d JOIN annonces a ON a.id = d.offre_id JOIN trajets t ON t.id = d.trajet_id
           WHERE t.user_id = ? AND d.status = 'en_cours' ORDER BY t.date""",
        (uid,),
    ).fetchall()
    invite_par = db.execute(
        "SELECT u.id, u.display_name FROM users u JOIN users moi ON moi.invited_by = u.id "
        "WHERE moi.id = ?", (uid,),
    ).fetchone()
    a_des_dons = any(a["kind"] == "don" for a in mes_annonces)
    a_des_besoins = any(a["kind"] == "besoin" for a in mes_annonces)
    return render_template(
        "pages/tableau_de_bord.html",
        mes_annonces=mes_annonces, dons_donnes=dons_donnes, dons_recus=dons_recus,
        transports=transports, a_des_dons=a_des_dons, a_des_besoins=a_des_besoins,
        invite_par=invite_par,
    )
