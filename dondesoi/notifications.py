"""Notifications dans le site, doublées d'un e-mail si le membre le souhaite.

Envoi des e-mails selon MAIL_BACKEND :
- "smtp"    : via SMTP_HOST / SMTP_PORT / SMTP_USER / SMTP_PASSWORD / MAIL_FROM ;
- "sendmail": via le programme d'envoi local (SENDMAIL_PATH), sans mot de passe
              quand l'hébergeur le préconfigure (c'est le cas chez alwaysdata) ;
- "console" : écrits dans le journal du serveur (par défaut, pour développer) ;
- "memory"  : gardés dans app.extensions["outbox"] (pour les tests).

Chaque e-mail part en deux versions : texte brut, et HTML aux couleurs du site
(gabarit templates/email/message.html, composé par rendre_email).

Les textes ne révèlent jamais l'identité d'un donateur.
"""
import smtplib
import subprocess
import sys
from email.message import EmailMessage

from flask import (Blueprint, current_app, g, redirect, render_template, request,
                   url_for)

from .db import get_db
from .security import login_required

bp = Blueprint("notifications", __name__, url_prefix="/notifications")


def notify(user_id, body, link):
    """Crée une notification. Un e-mail part seulement s'il n'y a pas déjà une
    notification non lue vers la même page, pour ne pas inonder la boîte."""
    db = get_db()
    already_pending = db.execute(
        "SELECT 1 FROM notifications WHERE user_id = ? AND link = ? AND read_at IS NULL",
        (user_id, link),
    ).fetchone()
    db.execute("INSERT INTO notifications (user_id, body, link) VALUES (?, ?, ?)",
               (user_id, body, link))
    db.commit()
    if already_pending:
        return
    user = db.execute("SELECT email, display_name, email_frequence FROM users WHERE id = ?",
                      (user_id,)).fetchone()
    # 'hebdo' : la notification attendra le récapitulatif du dimanche (recap.py).
    if user is not None and user["email_frequence"] == "immediat":
        url = request.host_url.rstrip("/") + link
        text = (f"Bonjour {user['display_name']},\n\n{body}\n\n{url}\n\n"
                "Que la paix soit avec vous,\nDon de soi\n\n"
                "Pour ne plus recevoir ces e-mails : décochez l'option dans « Mon profil ».\n")
        html = rendre_email(
            titre=body, apercu=body,
            paragraphes=[f"Bonjour {user['display_name']},"],
            bouton_texte="Voir sur Don de soi", bouton_url=url,
            pied=[{"texte": "Ne plus recevoir ces e-mails (Mon profil)",
                   "url": url_for("auth.profil", _external=True)}],
            verset=prochain_verset(user_id),
        )
        send_email(user["email"], "Don de soi : " + body, text, html)


def prochain_verset(user_id):
    """Clé de la parole d'Évangile du prochain e-mail de ce membre : une nouvelle à chaque fois."""
    from .evangile import cle_pour_email
    db = get_db()
    row = db.execute("SELECT versets_envoyes FROM users WHERE id = ?", (user_id,)).fetchone()
    rang = row["versets_envoyes"] if row is not None else 0
    db.execute("UPDATE users SET versets_envoyes = versets_envoyes + 1 WHERE id = ?", (user_id,))
    db.commit()
    return cle_pour_email(user_id if row is not None else None, rang)


def rendre_email(titre, paragraphes=(), bouton_texte=None, bouton_url=None, citation=None,
                 citation_auteur=None, notes=(), verset="gratuitement", apercu=None, pied=(),
                 liste=()):
    """Version HTML d'un e-mail, aux couleurs du site (à appeler pendant une requête)."""
    from .evangile import passage
    return render_template(
        "email/message.html", titre=titre, paragraphes=paragraphes, bouton_texte=bouton_texte,
        bouton_url=bouton_url, citation=citation, citation_auteur=citation_auteur, notes=notes,
        verset=passage(verset) if verset else None, apercu=apercu, pied=pied, liste=liste,
        site_url=url_for("main.accueil", _external=True),
        logo_url=url_for("static", filename="email/croix.png", _external=True),
    )


def send_email(to, subject, text, html=None):
    app = current_app
    backend = app.config.get("MAIL_BACKEND", "console")
    if backend == "memory":
        app.extensions.setdefault("outbox", []).append({"to": to, "subject": subject, "text": text,
                                                        "html": html})
        return
    if backend not in ("smtp", "sendmail"):
        print(f"--- E-mail (non envoyé, MAIL_BACKEND=console) à {to} : {subject}\n{text}"
              f"{'(+ version HTML)' if html else ''}---", file=sys.stderr)
        return
    msg = EmailMessage()
    msg["From"] = app.config["MAIL_FROM"]
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content(text)
    if html:
        msg.add_alternative(html, subtype="html")
    if app.config.get("MAIL_REPLY_TO"):
        msg["Reply-To"] = app.config["MAIL_REPLY_TO"]
    if backend == "sendmail":
        try:
            subprocess.run([app.config.get("SENDMAIL_PATH", "/usr/sbin/sendmail"), "-t", "-i"],
                           input=msg.as_bytes(), check=True, timeout=20)
        except (OSError, subprocess.SubprocessError):
            app.logger.exception("Échec de l'envoi d'un e-mail à %s", to)
        return
    try:
        with smtplib.SMTP(app.config["SMTP_HOST"], int(app.config.get("SMTP_PORT", 587)),
                          timeout=10) as smtp:
            smtp.starttls()
            if app.config.get("SMTP_USER"):
                smtp.login(app.config["SMTP_USER"], app.config["SMTP_PASSWORD"])
            smtp.send_message(msg)
    except (OSError, smtplib.SMTPException):
        # Un e-mail perdu ne doit jamais empêcher un don : la notification reste sur le site.
        app.logger.exception("Échec de l'envoi d'un e-mail à %s", to)


def unread_count():
    user = g.get("user")   # absent hors d'une page (ex. e-mail composé en tâche de fond)
    if user is None:
        return 0
    return get_db().execute(
        "SELECT COUNT(*) FROM notifications WHERE user_id = ? AND read_at IS NULL", (user["id"],),
    ).fetchone()[0]


def mark_current_page_read():
    """Visiter la page visée par une notification la marque comme lue."""
    if g.user is not None and request.method == "GET":
        db = get_db()
        cur = db.execute(
            "UPDATE notifications SET read_at = datetime('now') "
            "WHERE user_id = ? AND link = ? AND read_at IS NULL",
            (g.user["id"], request.path),
        )
        if cur.rowcount:
            db.commit()


@bp.route("/")
@login_required
def liste():
    notifications = get_db().execute(
        "SELECT * FROM notifications WHERE user_id = ? ORDER BY id DESC LIMIT 100",
        (g.user["id"],),
    ).fetchall()
    return render_template("notifications.html", notifications=notifications)


@bp.route("/tout-lu", methods=("POST",))
@login_required
def tout_lu():
    db = get_db()
    db.execute("UPDATE notifications SET read_at = datetime('now') "
               "WHERE user_id = ? AND read_at IS NULL", (g.user["id"],))
    db.commit()
    return redirect(url_for("notifications.liste"))


def init_app(app):
    app.before_request(mark_current_page_read)
    app.context_processor(lambda: {"unread_notifications": unread_count()})
