"""Inviter de nouveaux membres : « Viens, et vois » (Jn 1,46).

Deux façons d'inviter :
- un lien personnel, que le membre partage comme il veut (WhatsApp, SMS…) :
  le site ne connaît alors rien de la personne invitée ;
- une invitation envoyée par e-mail depuis le site.

Garde-fous : 10 invitations par e-mail et par jour au plus, une seule invitation
en attente par adresse, possibilité de refuser toute invitation, et l'adresse
d'une personne qui ne s'inscrit pas est effacée au bout de 30 jours.

« Invité par » n'est visible que des deux personnes concernées.
"""
import hashlib
import re
import secrets

from flask import (Blueprint, abort, flash, g, redirect, render_template, request,
                   session, url_for)

from .db import get_db
from .notifications import notify, send_email
from .security import login_required, trop_de_demandes

bp = Blueprint("invitations", __name__)

INVITATIONS_PAR_JOUR = 10
CONSERVATION_JOURS = 30
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def email_hash(email):
    return hashlib.sha256(email.strip().lower().encode()).hexdigest()


def purger(db):
    """Efface les invitations par e-mail restées sans réponse depuis 30 jours."""
    db.execute("DELETE FROM invitations WHERE email IS NOT NULL AND accepted_at IS NULL "
               "AND created_at < datetime('now', ?)", (f"-{CONSERVATION_JOURS} days",))


def lien_personnel(db, user_id):
    """Le lien d'invitation à partager, créé au premier besoin."""
    row = db.execute("SELECT token FROM invitations WHERE inviter_id = ? AND email IS NULL "
                     "AND accepted_user_id IS NULL", (user_id,)).fetchone()
    if row is None:
        token = secrets.token_urlsafe(9)
        db.execute("INSERT INTO invitations (inviter_id, token) VALUES (?, ?)", (user_id, token))
        db.commit()
        return token
    return row["token"]


def invitation_par_token(token):
    return get_db().execute(
        "SELECT i.*, u.display_name AS inviter_name FROM invitations i "
        "JOIN users u ON u.id = i.inviter_id WHERE i.token = ?", (token,),
    ).fetchone()


def invitation_en_cours():
    """L'invitation mémorisée dans la session de la personne qui s'inscrit."""
    token = session.get("invitation")
    inv = invitation_par_token(token) if token else None
    return inv if inv is not None and inv["accepted_user_id"] is None else None


def accepter(db, user_id):
    """Appelé à l'inscription : relie le nouveau membre à la personne qui l'a invité."""
    inv = invitation_en_cours()
    session.pop("invitation", None)
    if inv is None:
        return
    db.execute("UPDATE users SET invited_by = ? WHERE id = ?", (inv["inviter_id"], user_id))
    if inv["email"] is not None:
        db.execute("UPDATE invitations SET accepted_user_id = ?, accepted_at = datetime('now'), "
                   "email = NULL WHERE id = ?", (user_id, inv["id"]))
    else:
        # Lien personnel : on garde une trace de chaque inscription par ce lien.
        db.execute("INSERT INTO invitations (inviter_id, token, accepted_user_id, accepted_at) "
                   "VALUES (?, ?, ?, datetime('now'))",
                   (inv["inviter_id"], secrets.token_urlsafe(9), user_id))
    db.commit()
    name = db.execute("SELECT display_name FROM users WHERE id = ?", (user_id,)).fetchone()[0]
    notify(inv["inviter_id"], f"{name} a rejoint la famille Don de soi grâce à votre invitation.",
           url_for("invitations.inviter"))


@bp.route("/inviter", methods=("GET", "POST"))
@login_required
def inviter():
    db = get_db()
    purger(db)
    db.commit()
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        message = request.form.get("message", "").strip()[:1000]
        if not EMAIL_RE.match(email):
            flash("Cette adresse e-mail ne semble pas valide.", "erreur")
            return redirect(url_for("invitations.inviter"))
        if trop_de_demandes(f"invitation:{g.user['id']}", INVITATIONS_PAR_JOUR, 24 * 60):
            flash(f"Vous avez déjà envoyé {INVITATIONS_PAR_JOUR} invitations aujourd'hui. "
                  "Vous pouvez aussi partager votre lien personnel.", "erreur")
            return redirect(url_for("invitations.inviter"))
        deja_membre = db.execute("SELECT 1 FROM users WHERE email = ?", (email,)).fetchone()
        deja_invite = db.execute("SELECT 1 FROM invitations WHERE email = ? AND accepted_at IS NULL",
                                 (email,)).fetchone()
        refus = db.execute("SELECT 1 FROM invitations_refusees WHERE email_hash = ?",
                           (email_hash(email),)).fetchone()
        if not (deja_membre or deja_invite or refus):
            token = secrets.token_urlsafe(16)
            db.execute("INSERT INTO invitations (inviter_id, token, email, message) VALUES (?, ?, ?, ?)",
                       (g.user["id"], token, email, message))
            db.commit()
            envoyer_invitation(email, token, message)
        # Même réponse dans tous les cas : on ne révèle pas qui est déjà membre ou a refusé.
        flash("Merci ! Si cette personne n'est pas déjà membre ni déjà invitée, elle va recevoir "
              "votre invitation.")
        return redirect(url_for("invitations.inviter"))

    uid = g.user["id"]
    en_attente = db.execute(
        "SELECT email, created_at FROM invitations WHERE inviter_id = ? AND email IS NOT NULL "
        "AND accepted_at IS NULL ORDER BY created_at DESC", (uid,),
    ).fetchall()
    rejoints = db.execute(
        "SELECT id, display_name, city, created_at FROM users WHERE invited_by = ? "
        "ORDER BY created_at DESC", (uid,),
    ).fetchall()
    lien = url_for("invitations.rejoindre", token=lien_personnel(db, uid), _external=True)
    return render_template("invitations/inviter.html", lien=lien, en_attente=en_attente,
                           rejoints=rejoints, conservation=CONSERVATION_JOURS)


def envoyer_invitation(email, token, message):
    nom = g.user["display_name"]
    lien = url_for("invitations.rejoindre", token=token, _external=True)
    refus = url_for("invitations.refuser", token=token, _external=True)
    mot = f"\n{nom} vous écrit :\n« {message} »\n" if message else ""
    send_email(
        email, f"{nom} vous invite à rejoindre Don de soi",
        f"Bonjour,\n\n{nom} vous invite à rejoindre Don de soi, une famille où l'on donne et "
        "reçoit gratuitement : objets, services, temps, écoute, prière. Sans argent entre "
        f"membres, sans publicité.\n{mot}\n"
        "« Peut-il venir de Nazareth quelque chose de bon ? Philippe lui répondit : Viens, "
        "et vois. » (Jn 1,46)\n\n"
        f"Pour découvrir le site et vous inscrire :\n{lien}\n\n"
        "Si vous ne souhaitez pas donner suite, ignorez simplement ce message : votre adresse "
        f"sera effacée dans {CONSERVATION_JOURS} jours. Pour ne plus jamais recevoir "
        f"d'invitation de Don de soi :\n{refus}\n\nDon de soi\n",
    )


@bp.route("/rejoindre/<token>")
def rejoindre(token):
    inv = invitation_par_token(token)
    if inv is None or inv["accepted_user_id"] is not None:
        # Lien inconnu, ou invitation par e-mail déjà utilisée.
        flash("Ce lien d'invitation n'est plus valable, mais vous pouvez vous inscrire.")
        return redirect(url_for("main.accueil"))
    if g.user is not None:
        flash("Vous êtes déjà membre de Don de soi.")
        return redirect(url_for("main.tableau_de_bord"))
    session["invitation"] = token
    return render_template("invitations/bienvenue.html", invitation=inv)


@bp.route("/invitation/<token>/refuser", methods=("GET", "POST"))
def refuser(token):
    inv = invitation_par_token(token)
    if inv is None or inv["email"] is None:
        abort(404)
    if request.method == "POST":
        db = get_db()
        db.execute("INSERT OR IGNORE INTO invitations_refusees (email_hash) VALUES (?)",
                   (email_hash(inv["email"]),))
        db.execute("DELETE FROM invitations WHERE email = ? AND accepted_at IS NULL", (inv["email"],))
        db.commit()
        session.pop("invitation", None)
        flash("C'est noté : vous ne recevrez plus d'invitation de Don de soi, et votre adresse "
              "a été effacée.")
        return redirect(url_for("main.accueil"))
    return render_template("invitations/refuser.html", invitation=inv)
