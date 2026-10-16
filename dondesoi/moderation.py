"""Signalements et modération collégiale.

Aucun membre n'a de pouvoir de modération attitré. Un contenu signalé (annonce,
message, profil, action de grâce) est confié à trois membres tirés au sort, autres
que l'auteur et la personne qui signale ; il est retiré si la majorité d'entre eux
le décide. S'il n'y a encore personne à tirer au sort (communauté naissante), le
contenu est masqué par précaution en attendant.
"""
import random

from flask import Blueprint, abort, flash, g, redirect, render_template, request, url_for

from .db import get_db
from .notifications import notify
from .security import login_required, trop_de_demandes

bp = Blueprint("moderation", __name__)

JURES = 3
MOTIFS = {
    "illicite": "Contenu illicite ou dangereux",
    "argent": "Demande d'argent ou arnaque",
    "charte": "Contraire à la charte (objet interdit, prosélytisme, irrespect…)",
    "personnel": "Données personnelles d'autrui",
    "autre": "Autre",
}


def contenu(kind, objet_id):
    """(auteur_id, texte à montrer aux jurés) d'un contenu, ou None s'il n'existe pas."""
    db = get_db()
    if kind == "annonce":
        r = db.execute("SELECT user_id, title, description FROM annonces WHERE id = ?", (objet_id,)).fetchone()
        return r and (r["user_id"], f"{r['title']}\n{r['description']}")
    if kind == "message":
        r = db.execute("SELECT author_id, body FROM messages WHERE id = ?", (objet_id,)).fetchone()
        return r and (r["author_id"], r["body"] or "(photo)")
    if kind == "membre":
        r = db.execute("SELECT id, display_name, bio, contact FROM users WHERE id = ?", (objet_id,)).fetchone()
        return r and (r["id"], f"{r['display_name']}\n{r['bio']}\n{r['contact']}")
    if kind == "grace":
        r = db.execute("SELECT author_id, body FROM actions_grace WHERE id = ?", (objet_id,)).fetchone()
        return r and (r["author_id"], r["body"])
    if kind == "relais":
        r = db.execute("SELECT propose_par, nom, adresse, city, description FROM lieux_relais "
                       "WHERE id = ?", (objet_id,)).fetchone()
        return r and (r["propose_par"], f"{r['nom']}\n{r['adresse']}, {r['city']}\n{r['description']}")
    return None


def masquer(kind, objet_id, masque=True):
    db = get_db()
    v = int(masque)
    if kind == "annonce":
        db.execute("UPDATE annonces SET masquee = ? WHERE id = ?", (v, objet_id))
    elif kind == "message":
        db.execute("UPDATE messages SET masque = ? WHERE id = ?", (v, objet_id))
    elif kind == "membre":
        db.execute("UPDATE users SET profil_masque = ? WHERE id = ?", (v, objet_id))
    elif kind == "grace" and masque:
        db.execute("UPDATE actions_grace SET public = 0 WHERE id = ?", (objet_id,))
    elif kind == "relais":
        db.execute("UPDATE lieux_relais SET masque = ? WHERE id = ?", (v, objet_id))


@bp.route("/signaler", methods=("POST",))
@login_required
def signaler():
    f = request.form
    kind, motif = f.get("kind", ""), f.get("motif", "")
    objet_id = f.get("objet_id", type=int)
    retour = f.get("retour", "")
    if not retour.startswith("/") or retour.startswith("//"):
        retour = url_for("main.accueil")
    if motif not in MOTIFS or objet_id is None:
        abort(400)
    trouve = contenu(kind, objet_id)
    if not trouve:
        abort(404)
    auteur_id, _ = trouve
    if auteur_id == g.user["id"]:
        abort(400)
    if trop_de_demandes(f"signalement:{g.user['id']}", 10, 24 * 60):
        flash("Vous avez déjà fait plusieurs signalements aujourd'hui.", "erreur")
        return redirect(retour)
    db = get_db()
    cur = db.execute("INSERT OR IGNORE INTO signalements (kind, objet_id, auteur_id, signale_par, "
                     "motif, precision) VALUES (?, ?, ?, ?, ?, ?)",
                     (kind, objet_id, auteur_id, g.user["id"], motif, f.get("precision", "").strip()[:1000]))
    if not cur.rowcount:
        db.commit()
        flash("Vous avez déjà signalé ce contenu.")
        return redirect(retour)
    signalement_id = cur.lastrowid
    candidats = [r["id"] for r in db.execute(
        "SELECT id FROM users WHERE id NOT IN (?, ?)", (g.user["id"], auteur_id or 0))]
    jures = random.sample(candidats, min(JURES, len(candidats)))
    db.executemany("INSERT INTO moderations (signalement_id, user_id) VALUES (?, ?)",
                   [(signalement_id, j) for j in jures])
    if not jures:
        masquer(kind, objet_id)   # personne à tirer au sort : précaution en attendant
    db.commit()
    for j in jures:
        notify(j, "Vous avez été tiré au sort pour examiner un contenu signalé : votre avis est "
                  "demandé.", url_for("moderation.examiner"))
    flash("Merci. Ce contenu va être examiné par trois membres tirés au sort.")
    return redirect(retour)


@bp.route("/moderation")
@login_required
def examiner():
    db = get_db()
    cas = []
    for m in db.execute(
        "SELECT m.*, s.kind, s.objet_id, s.motif, s.precision, s.statut, s.created_at AS signale_le "
        "FROM moderations m JOIN signalements s ON s.id = m.signalement_id "
        "WHERE m.user_id = ? ORDER BY s.statut != 'ouvert', s.created_at DESC LIMIT 50",
        (g.user["id"],),
    ):
        trouve = contenu(m["kind"], m["objet_id"])
        cas.append({"m": m, "texte": trouve[1] if trouve else "(contenu supprimé)",
                    "motif": MOTIFS.get(m["motif"], m["motif"])})
    return render_template("moderation.html", cas=cas)


@bp.route("/moderation/<int:moderation_id>/vote", methods=("POST",))
@login_required
def voter(moderation_id):
    db = get_db()
    m = db.execute("SELECT m.*, s.kind, s.objet_id, s.auteur_id, s.statut, s.motif "
                   "FROM moderations m JOIN signalements s ON s.id = m.signalement_id "
                   "WHERE m.id = ?", (moderation_id,)).fetchone()
    if m is None or m["user_id"] != g.user["id"]:
        abort(403)
    vote = request.form.get("vote")
    if vote not in ("retirer", "maintenir") or m["statut"] != "ouvert":
        abort(400)
    db.execute("UPDATE moderations SET vote = ?, voted_at = datetime('now') WHERE id = ?",
               (vote, moderation_id))
    votes = db.execute("SELECT vote FROM moderations WHERE signalement_id = ?",
                       (m["signalement_id"],)).fetchall()
    majorite = len(votes) // 2 + 1
    retirer = sum(v["vote"] == "retirer" for v in votes)
    maintenir = sum(v["vote"] == "maintenir" for v in votes)
    decision = "retire" if retirer >= majorite else "maintenu" if maintenir >= majorite else None
    if decision:
        db.execute("UPDATE signalements SET statut = ?, decided_at = datetime('now') WHERE id = ?",
                   (decision, m["signalement_id"]))
        masquer(m["kind"], m["objet_id"], decision == "retire")
    db.commit()
    if decision == "retire" and m["auteur_id"]:
        notify(m["auteur_id"], "Un de vos contenus a été retiré après examen par des membres tirés "
               f"au sort (motif : {MOTIFS.get(m['motif'], m['motif']).lower()}).",
               url_for("main.charte"))
    flash("Merci pour votre avis." + (" La décision est prise." if decision else ""))
    return redirect(url_for("moderation.examiner"))
