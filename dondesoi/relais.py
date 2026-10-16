"""Lieux relais : paroisses, locaux associatifs, commerces amis où déposer et retirer des dons.

Tout membre peut proposer un lieu (après accord du lieu lui-même) ; il n'y a pas de
validation par un responsable, mais chacun peut le signaler (modération collégiale).
"""
from flask import Blueprint, flash, g, redirect, render_template, request, url_for

from .db import get_db
from .geo import VilleInvalide, distance_rows, verifier_ville
from .security import login_required

bp = Blueprint("relais", __name__, url_prefix="/relais")

PROCHE_KM = 15


def relais_proches(db, *lieux, limite=3):
    """Lieux relais à moins de PROCHE_KM de l'un des lieux donnés (lignes avec lat/lon),
    du plus pratique au moins pratique (somme des distances)."""
    out = []
    for r in db.execute("SELECT * FROM lieux_relais WHERE masque = 0"):
        distances = [distance_rows(r, lieu) for lieu in lieux]
        connues = [d for d in distances if d is not None]
        if connues and min(connues) <= PROCHE_KM:
            out.append((sum(connues), r))
    out.sort(key=lambda x: x[0])
    return [r for _, r in out[:limite]]


@bp.route("/", methods=("GET", "POST"))
def liste():
    db = get_db()
    form = request.form
    if request.method == "POST":
        if g.user is None:
            return redirect(url_for("auth.connexion", next=request.path))
        nom, adresse = form.get("nom", "").strip(), form.get("adresse", "").strip()
        try:
            if not nom or not adresse:
                raise VilleInvalide("Merci d'indiquer le nom du lieu et son adresse.")
            city, lat, lon = verifier_ville(form.get("city", ""), form.get("postal_code", ""))
        except VilleInvalide as e:
            flash(str(e), "erreur")
        else:
            db.execute(
                "INSERT INTO lieux_relais (nom, adresse, postal_code, city, lat, lon, horaires, "
                "description, propose_par) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (nom[:120], adresse[:200], form.get("postal_code", "").strip(), city, lat, lon,
                 form.get("horaires", "").strip()[:200], form.get("description", "").strip()[:1000],
                 g.user["id"]),
            )
            db.commit()
            flash("Merci ! Ce lieu relais est maintenant proposé aux membres.")
            return redirect(url_for("relais.liste"))
    lieux = [dict(r) for r in db.execute("SELECT * FROM lieux_relais WHERE masque = 0")]
    for lieu in lieux:
        lieu["distance"] = distance_rows(g.user, lieu) if g.user is not None else None
    lieux.sort(key=lambda x: (x["distance"] is None, x["distance"] or 0, x["city"]))
    return render_template("relais.html", lieux=lieux, form=form)
