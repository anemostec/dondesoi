"""Tâches régulières, lancées par le planificateur de l'hébergeur (voir README) :

    flask --app dondesoi recap-hebdo    # le dimanche : récapitulatif aux membres qui l'ont choisi
    flask --app dondesoi sauvegarder    # chaque nuit : copie de la base, 14 jours gardés

SITE_URL sert à écrire des liens complets dans les e-mails envoyés hors d'une page.
"""
import glob
import os
import sqlite3
from datetime import date, datetime, timedelta

import click
from flask import current_app
from flask.cli import with_appcontext

from .db import get_db

GARDER_SAUVEGARDES = 14


def recapitulatif(db, user):
    """Contenu du récapitulatif d'un membre : (groupes de liens, nombre d'éléments)."""
    from .geo import distance_rows
    depuis = user["dernier_recap"] or (datetime.utcnow() - timedelta(days=7)).strftime("%Y-%m-%d %H:%M:%S")
    base = current_app.config["SITE_URL"].rstrip("/")
    notifs = db.execute(
        "SELECT body, link FROM notifications WHERE user_id = ? AND created_at > ? ORDER BY id DESC LIMIT 15",
        (user["id"], depuis),
    ).fetchall()
    besoins = []
    for a in db.execute(
        "SELECT * FROM annonces WHERE kind = 'besoin' AND status = 'ouverte' AND masquee = 0 "
        "AND user_id != ? AND created_at > ? ORDER BY essential DESC, created_at DESC",
        (user["id"], depuis),
    ):
        d = distance_rows(user, a)
        if d is None or d <= 30:
            besoins.append({"texte": a["title"], "url": f"{base}/annonces/{a['id']}",
                            "detail": a["city"] + (f", à {d:.0f} km" if d is not None else "")
                            + (" · première nécessité" if a["essential"] else "")})
        if len(besoins) >= 5:
            break
    groupes = []
    if notifs:
        groupes.append({"titre": "Pour vous cette semaine",
                        "elements": [{"texte": n["body"], "url": base + n["link"]} for n in notifs]})
    if besoins:
        groupes.append({"titre": "Nouveaux besoins près de chez vous", "elements": besoins})
    return groupes, len(notifs) + len(besoins)


@click.command("recap-hebdo")
@with_appcontext
def recap_hebdo_command():
    """Envoie le récapitulatif hebdomadaire aux membres qui l'ont choisi."""
    from .notifications import prochain_verset, rendre_email, send_email
    app = current_app
    db = get_db()
    envoyes = 0
    with app.test_request_context("/", base_url=app.config["SITE_URL"]):
        for user in db.execute("SELECT * FROM users WHERE email_frequence = 'hebdo'").fetchall():
            groupes, n = recapitulatif(db, user)
            if n:
                base = app.config["SITE_URL"].rstrip("/")
                texte = f"Bonjour {user['display_name']},\n\nVoici votre semaine sur Don de soi :\n\n"
                for g_ in groupes:
                    texte += g_["titre"] + " :\n" + "".join(
                        f"- {e['texte']}\n  {e['url']}\n" for e in g_["elements"]) + "\n"
                texte += "Que la paix soit avec vous,\nDon de soi\n"
                html = rendre_email(
                    titre="Votre semaine sur Don de soi", apercu=f"{n} nouveauté(s) pour vous",
                    paragraphes=[f"Bonjour {user['display_name']},"], liste=groupes,
                    bouton_texte="Ouvrir Don de soi", bouton_url=f"{base}/tableau-de-bord",
                    verset=prochain_verset(user["id"]),
                    pied=[{"texte": "Changer la fréquence des e-mails (Mon profil)",
                           "url": f"{base}/profil"}],
                )
                send_email(user["email"], "Don de soi : votre semaine", texte, html)
                envoyes += 1
            db.execute("UPDATE users SET dernier_recap = datetime('now') WHERE id = ?", (user["id"],))
            db.commit()
    click.echo(f"{envoyes} récapitulatif(s) envoyé(s).")


def sauvegarder(dossier=None, garder=GARDER_SAUVEGARDES):
    """Copie cohérente de la base (même pendant que le site tourne) ; garde les plus récentes."""
    dossier = dossier or os.path.join(current_app.instance_path, "sauvegardes")
    os.makedirs(dossier, exist_ok=True)
    chemin = os.path.join(dossier, f"dondesoi-{date.today().isoformat()}.sqlite")
    source = sqlite3.connect(current_app.config["DATABASE"])
    cible = sqlite3.connect(chemin)
    with cible:
        source.backup(cible)
    cible.close()
    source.close()
    for ancien in sorted(glob.glob(os.path.join(dossier, "dondesoi-*.sqlite")))[:-garder]:
        os.remove(ancien)
    return chemin


@click.command("sauvegarder")
@click.option("--garder", default=GARDER_SAUVEGARDES, help="Nombre de sauvegardes à garder.")
@with_appcontext
def sauvegarder_command(garder):
    """Sauvegarde la base de données dans instance/sauvegardes/."""
    click.echo(f"Sauvegarde : {sauvegarder(garder=garder)}")


def init_app(app):
    app.cli.add_command(recap_hebdo_command)
    app.cli.add_command(sauvegarder_command)
