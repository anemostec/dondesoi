"""Transactions : le donateur choisit un receveur, partage ce qu'il veut, puis donne.

Règles de la charte appliquées ici :
- le donateur est seul décisionnaire du choix du receveur ;
- il voit le profil et les avis du receveur potentiel ;
- le receveur ne voit du donateur que ce que celui-ci choisit de partager,
  et seulement une fois le don engagé ;
- après le don, le donateur peut laisser un avis, auquel le receveur peut répondre ;
- la messagerie du don garde la même discrétion : le donateur y apparaît
  comme « le donateur », jamais sous son nom ;
- le receveur peut rendre grâce (Lc 17,15) : son mot va au donateur et,
  s'il le souhaite, est publié sans aucun nom ;
- le donateur peut retirer son avis à tout moment : c'est le pardon (Mt 18,22).
"""
import os

from flask import (Blueprint, abort, current_app, flash, g, redirect, render_template, request,
                   send_from_directory, url_for)

from .db import get_db
from .calendrier import date_fr, heure_fr, occurrences
from .matching import meme_endroit, trajets_pour_don
from .notifications import notify
from .photos import COVER_SQL, PhotoInvalide, save_photo, thumb_name
from .security import login_required

bp = Blueprint("dons", __name__, url_prefix="/dons")


def get_don(don_id):
    db = get_db()
    don = db.execute(
        f"""SELECT d.*, a.title, a.description, a.category, a.city AS offre_city, {COVER_SQL}
            FROM dons d JOIN annonces a ON a.id = d.offre_id WHERE d.id = ?""",
        (don_id,),
    ).fetchone()
    if don is None:
        abort(404)
    return don


def get_trajet(don):
    if not don["trajet_id"]:
        return None
    return get_db().execute(
        "SELECT t.*, u.display_name, u.contact FROM trajets t JOIN users u ON u.id = t.user_id "
        "WHERE t.id = ?", (don["trajet_id"],),
    ).fetchone()


def participants(don, trajet):
    """Membres qui peuvent lire et écrire dans la messagerie du don."""
    ids = {don["donor_id"], don["receiver_id"]}
    if trajet is not None and don["transport_status"] in ("demande", "accepte"):
        ids.add(trajet["user_id"])
    return ids


def author_label(author_id, viewer_id, don, receiver_name, trajet):
    if author_id == viewer_id:
        return "Vous"
    if author_id == don["donor_id"]:
        return "Le donateur"
    if author_id == don["receiver_id"]:
        return receiver_name if viewer_id == don["donor_id"] else "Le receveur"
    return f"{trajet['display_name']} (voyageur)" if trajet else "Voyageur"


@bp.route("/preparer", methods=("GET", "POST"))
@login_required
def preparer():
    db = get_db()
    offre_id = request.values.get("offre", type=int)
    receiver_id = request.values.get("receveur", type=int)
    besoin_id = request.values.get("besoin", type=int)

    offre = db.execute("SELECT * FROM annonces WHERE id = ?", (offre_id,)).fetchone()
    receiver = db.execute("SELECT * FROM users WHERE id = ?", (receiver_id,)).fetchone()
    if (offre is None or receiver is None or offre["kind"] != "don"
            or offre["user_id"] != g.user["id"] or receiver["id"] == g.user["id"]):
        abort(400)
    if offre["status"] != "ouverte":
        flash("Ce don a déjà été attribué.", "erreur")
        return redirect(url_for("annonces.detail", annonce_id=offre_id))
    besoin = None
    if besoin_id:
        besoin = db.execute(
            "SELECT * FROM annonces WHERE id = ? AND user_id = ? AND kind = 'besoin'",
            (besoin_id, receiver_id),
        ).fetchone()

    if request.method == "POST":
        cur = db.execute(
            """INSERT INTO dons (offre_id, besoin_id, donor_id, receiver_id, shared_info)
               VALUES (?, ?, ?, ?, ?)""",
            (offre_id, besoin["id"] if besoin else None, g.user["id"], receiver_id,
             request.form.get("shared_info", "").strip()),
        )
        db.execute("UPDATE annonces SET status = 'attribuee' WHERE id = ?", (offre_id,))
        if besoin is not None and request.form.get("besoin_comble"):
            db.execute("UPDATE annonces SET status = 'attribuee' WHERE id = ?", (besoin["id"],))
        db.commit()
        notify(receiver_id, f"Un membre vous fait un don : « {offre['title']} ».",
               url_for("dons.detail", don_id=cur.lastrowid))
        flash("Merci pour ce don. « Que ta main gauche ne sache pas ce que fait ta droite. » (Mt 6,3)")
        return redirect(url_for("dons.detail", don_id=cur.lastrowid))

    avis = db.execute(
        "SELECT * FROM avis WHERE subject_id = ? ORDER BY created_at DESC", (receiver_id,),
    ).fetchall()
    return render_template("dons/preparer.html", offre=offre, receiver=receiver, besoin=besoin,
                           avis=avis)


@bp.route("/<int:don_id>")
@login_required
def detail(don_id):
    db = get_db()
    don = get_don(don_id)
    uid = g.user["id"]
    trajet = get_trajet(don)

    is_donor = uid == don["donor_id"]
    is_receiver = uid == don["receiver_id"]
    is_transporter = trajet is not None and uid == trajet["user_id"]
    if not (is_donor or is_receiver or is_transporter):
        abort(403)

    donor = db.execute("SELECT * FROM users WHERE id = ?", (don["donor_id"],)).fetchone()
    receiver = db.execute("SELECT * FROM users WHERE id = ?", (don["receiver_id"],)).fetchone()
    avis = db.execute("SELECT * FROM avis WHERE don_id = ?", (don_id,)).fetchone()
    grace = db.execute("SELECT * FROM actions_grace WHERE don_id = ?", (don_id,)).fetchone()

    messages = [
        {"label": author_label(m["author_id"], uid, don, receiver["display_name"], trajet),
         "mine": m["author_id"] == uid, "masque": m["masque"],
         "body": "" if m["masque"] else m["body"], "photo": None if m["masque"] else m["photo"],
         "id": m["id"],
         "created_at": m["created_at"]}
        for m in db.execute("SELECT * FROM messages WHERE don_id = ? ORDER BY id", (don_id,))
    ]
    ctx = {"don": don, "avis": avis, "grace": grace, "trajet": trajet, "is_donor": is_donor,
           "is_receiver": is_receiver, "is_transporter": is_transporter, "messages": messages,
           "can_write": uid in participants(don, trajet) and don["status"] != "annule"}
    if is_donor:
        ctx["receiver"] = receiver
        ctx["meme_ville"], ctx["distance"] = meme_endroit(donor, receiver)
        if don["status"] == "en_cours" and don["transport_status"] in (None, "refuse"):
            ctx["trajets"] = trajets_pour_don(db, donor, receiver)
    if is_transporter:
        # Le transporteur a besoin de savoir où livrer : il voit la ville du receveur.
        ctx["receiver_city"] = receiver["city"]
    return render_template("dons/detail.html", **ctx)


@bp.route("/<int:don_id>/statut", methods=("POST",))
@login_required
def statut(don_id):
    don = get_don(don_id)
    if g.user["id"] != don["donor_id"] or don["status"] != "en_cours":
        abort(403)
    action = request.form.get("action")
    db = get_db()
    if action == "realise":
        db.execute("UPDATE dons SET status = 'realise', completed_at = datetime('now') WHERE id = ?",
                   (don_id,))
        db.execute("UPDATE annonces SET status = 'close' WHERE id = ?", (don["offre_id"],))
        notify(don["receiver_id"], f"Le don « {don['title']} » est noté comme réalisé.",
               url_for("dons.detail", don_id=don_id))
        flash("Don réalisé. Vous pouvez laisser un avis bienveillant sur ce don.")
    elif action == "annule":
        db.execute("UPDATE dons SET status = 'annule' WHERE id = ?", (don_id,))
        db.execute("UPDATE annonces SET status = 'ouverte' WHERE id = ?", (don["offre_id"],))
        notify(don["receiver_id"], f"Le don « {don['title']} » a été annulé par le donateur.",
               url_for("main.tableau_de_bord"))
        flash("Don annulé : votre annonce est de nouveau visible.")
    else:
        abort(400)
    db.commit()
    return redirect(url_for("dons.detail", don_id=don_id))


@bp.route("/<int:don_id>/transport", methods=("POST",))
@login_required
def transport(don_id):
    don = get_don(don_id)
    db = get_db()
    action = request.form.get("action")
    if action == "demander":
        if g.user["id"] != don["donor_id"] or don["status"] != "en_cours":
            abort(403)
        trajet_id = request.form.get("trajet_id", type=int)
        trajet = db.execute("SELECT * FROM trajets WHERE id = ?", (trajet_id,)).fetchone()
        if trajet is None:
            abort(400)
        # Pour un trajet régulier, le donateur choisit l'une des prochaines dates.
        dates = [d.isoformat() for d in occurrences(trajet, nombre=6)]
        jour = request.form.get("transport_date") or (dates[0] if dates else "")
        if jour not in dates:
            abort(400)
        db.execute("UPDATE dons SET trajet_id = ?, transport_status = 'demande', transport_date = ? "
                   "WHERE id = ?", (trajet_id, jour, don_id))
        db.commit()
        heure = f" à {heure_fr(trajet['heure'])}" if trajet["heure"] else ""
        notify(trajet["user_id"],
               f"Pourriez-vous porter un don lors de votre trajet {trajet['from_city']} → "
               f"{trajet['to_city']} du {date_fr(jour)}{heure} ?",
               url_for("dons.detail", don_id=don_id))
        flash("Demande de transport envoyée au voyageur.")
    elif action in ("accepte", "refuse"):
        trajet = db.execute("SELECT * FROM trajets WHERE id = ?", (don["trajet_id"],)).fetchone()
        if trajet is None or trajet["user_id"] != g.user["id"] or don["transport_status"] != "demande":
            abort(403)
        db.execute("UPDATE dons SET transport_status = ? WHERE id = ?", (action, don_id))
        db.commit()
        notify(don["donor_id"],
               f"{g.user['display_name']} " + ("accepte de porter" if action == "accepte"
                                               else "ne peut pas porter")
               + f" le don « {don['title']} ».",
               url_for("dons.detail", don_id=don_id))
        flash("Merci de porter ce don !" if action == "accepte" else "Réponse transmise au donateur.")
    else:
        abort(400)
    db.commit()
    return redirect(url_for("dons.detail", don_id=don_id) if action != "refuse"
                    else url_for("main.tableau_de_bord"))


@bp.route("/<int:don_id>/avis/retirer", methods=("POST",))
@login_required
def retirer_avis(don_id):
    """« Jusqu'à septante fois sept fois » (Mt 18,22) : le donateur peut effacer son avis."""
    don = get_don(don_id)
    if g.user["id"] != don["donor_id"]:
        abort(403)
    db = get_db()
    db.execute("DELETE FROM avis WHERE don_id = ?", (don_id,))
    db.commit()
    flash("Votre avis est retiré.")
    return redirect(url_for("dons.detail", don_id=don_id))


@bp.route("/<int:don_id>/avis", methods=("POST",))
@login_required
def avis(don_id):
    don = get_don(don_id)
    db = get_db()
    body = request.form.get("body", "").strip()
    if not body:
        flash("Le texte est vide.", "erreur")
    elif g.user["id"] == don["donor_id"]:
        if don["status"] != "realise":
            abort(400)
        db.execute(
            "INSERT OR IGNORE INTO avis (don_id, author_id, subject_id, body) VALUES (?, ?, ?, ?)",
            (don_id, g.user["id"], don["receiver_id"], body),
        )
        db.commit()
        notify(don["receiver_id"],
               f"Le donateur a laissé un avis sur le don « {don['title']} ». Vous pouvez y répondre.",
               url_for("dons.detail", don_id=don_id))
        flash("Merci pour votre avis : il aidera les prochains donateurs.")
    elif g.user["id"] == don["receiver_id"]:
        db.execute(
            "UPDATE avis SET reply = ?, reply_at = datetime('now') WHERE don_id = ? AND reply IS NULL",
            (body, don_id),
        )
        db.commit()
        notify(don["donor_id"], f"Le receveur a répondu à votre avis sur « {don['title']} ».",
               url_for("dons.detail", don_id=don_id))
        flash("Votre réponse est publiée à côté de l'avis.")
    else:
        abort(403)
    db.commit()
    return redirect(url_for("dons.detail", don_id=don_id))


@bp.route("/<int:don_id>/messages", methods=("POST",))
@login_required
def message(don_id):
    don = get_don(don_id)
    trajet = get_trajet(don)
    members = participants(don, trajet)
    if g.user["id"] not in members or don["status"] == "annule":
        abort(403)
    body = request.form.get("body", "").strip()
    photo = None
    upload = request.files.get("photo")
    if upload and upload.filename:
        try:
            photo = save_photo(upload, "messages")
        except PhotoInvalide as e:
            flash(str(e), "erreur")
            return redirect(url_for("dons.detail", don_id=don_id) + "#messages")
    if body or photo:
        db = get_db()
        db.execute("INSERT INTO messages (don_id, author_id, body, photo) VALUES (?, ?, ?, ?)",
                   (don_id, g.user["id"], body, photo))
        db.commit()
        link = url_for("dons.detail", don_id=don_id)
        receiver_name = db.execute("SELECT display_name FROM users WHERE id = ?",
                                   (don["receiver_id"],)).fetchone()[0]
        for member in members - {g.user["id"]}:
            label = author_label(g.user["id"], member, don, receiver_name, trajet)
            notify(member, f"{label} vous a écrit au sujet de « {don['title']} ».", link)
    return redirect(url_for("dons.detail", don_id=don_id) + "#messages")


def _send_private(subdir, filename, thumb):
    folder = os.path.join(current_app.config["UPLOAD_FOLDER"], subdir)
    response = send_from_directory(folder, thumb_name(filename) if thumb else filename)
    response.headers["Cache-Control"] = "private, max-age=86400"
    return response


@bp.route("/<int:don_id>/messages/<int:message_id>/photo")
@login_required
def message_photo(don_id, message_id):
    """Photo d'un message : seuls les participants du don peuvent la voir."""
    don = get_don(don_id)
    if g.user["id"] not in participants(don, get_trajet(don)):
        abort(403)
    msg = get_db().execute("SELECT photo, masque FROM messages WHERE id = ? AND don_id = ?",
                           (message_id, don_id)).fetchone()
    if msg is None or not msg["photo"] or msg["masque"]:
        abort(404)
    return _send_private("messages", msg["photo"], request.args.get("t"))


@bp.route("/<int:don_id>/grace", methods=("POST",))
@login_required
def rendre_grace(don_id):
    """Le receveur rend grâce : un mot au donateur, publié sans nom s'il le souhaite."""
    don = get_don(don_id)
    if g.user["id"] != don["receiver_id"] or don["status"] != "realise":
        abort(403)
    db = get_db()
    if db.execute("SELECT 1 FROM actions_grace WHERE don_id = ?", (don_id,)).fetchone():
        abort(400)
    body = request.form.get("body", "").strip()
    if not body:
        flash("Le texte est vide.", "erreur")
        return redirect(url_for("dons.detail", don_id=don_id))
    photo = None
    upload = request.files.get("photo")
    if upload and upload.filename:
        try:
            photo = save_photo(upload, "grace")
        except PhotoInvalide as e:
            flash(str(e), "erreur")
            return redirect(url_for("dons.detail", don_id=don_id))
    db.execute("INSERT INTO actions_grace (don_id, author_id, body, photo, public) "
               "VALUES (?, ?, ?, ?, ?)",
               (don_id, g.user["id"], body, photo, int(bool(request.form.get("public")))))
    db.commit()
    notify(don["donor_id"], f"Le receveur rend grâce pour le don « {don['title']} ».",
           url_for("dons.detail", don_id=don_id))
    flash("Merci d'avoir rendu grâce.")
    return redirect(url_for("dons.detail", don_id=don_id))


@bp.route("/<int:don_id>/grace/depublier", methods=("POST",))
@login_required
def depublier_grace(don_id):
    don = get_don(don_id)
    if g.user["id"] != don["receiver_id"]:
        abort(403)
    db = get_db()
    db.execute("UPDATE actions_grace SET public = 0 WHERE don_id = ?", (don_id,))
    db.commit()
    flash("Votre action de grâce n'est plus publiée ; le donateur la voit toujours.")
    return redirect(url_for("dons.detail", don_id=don_id))


@bp.route("/grace/<int:grace_id>/photo")
def grace_photo(grace_id):
    """Photo d'une action de grâce : publique si elle est publiée, sinon réservée au don."""
    db = get_db()
    grace = db.execute(
        "SELECT ag.*, d.donor_id, d.receiver_id FROM actions_grace ag "
        "JOIN dons d ON d.id = ag.don_id WHERE ag.id = ?", (grace_id,),
    ).fetchone()
    if grace is None or not grace["photo"]:
        abort(404)
    if not grace["public"] and (g.user is None
                                or g.user["id"] not in (grace["donor_id"], grace["receiver_id"])):
        abort(404)
    return _send_private("grace", grace["photo"], request.args.get("t"))
