import re
from datetime import date

from flask import Blueprint, abort, flash, g, redirect, render_template, request, url_for

from .calendrier import JOURS, SQL_A_VENIR, description, occurrences
from .db import get_db
from .geo import VilleInvalide, verifier_ville
from .security import login_required

bp = Blueprint("trajets", __name__, url_prefix="/trajets")

HEURE_RE = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")


def lire_formulaire(f):
    """Valide le formulaire ; retourne (valeurs, erreur)."""
    v = {
        "from_city": f.get("from_city", "").strip(),
        "to_city": f.get("to_city", "").strip(),
        "from_cp": f.get("from_cp", "").strip(),
        "to_cp": f.get("to_cp", "").strip(),
        "regulier": f.get("frequence") == "regulier",
        "date": f.get("date", ""),
        "date_fin": f.get("date_fin", "") or None,
        "heure": f.get("heure", "").strip(),
        "heure_retour": f.get("heure_retour", "").strip(),
        "retour": bool(f.get("retour")),
        "jours": ",".join(sorted({j for j in f.getlist("jours") if len(j) == 1 and j in "0123456"})),
        "note": f.get("note", "").strip(),
    }
    aujourd_hui = date.today().isoformat()
    if not v["from_city"] or not v["to_city"]:
        return v, "Merci d'indiquer le départ et l'arrivée."
    if v["regulier"]:
        if not v["jours"]:
            return v, "Merci de cocher au moins un jour de la semaine."
        v["date"] = v["date"] or aujourd_hui
        if v["date_fin"] and v["date_fin"] < max(v["date"], aujourd_hui):
            return v, "La date de fin est déjà passée."
    else:
        v["jours"], v["date_fin"] = "", None
        if not v["date"]:
            return v, "Merci d'indiquer la date du trajet."
        if v["date"] < aujourd_hui:
            return v, "La date est déjà passée."
    for h in (v["heure"], v["heure_retour"] if v["retour"] else ""):
        if h and not HEURE_RE.match(h):
            return v, "L'heure doit être au format hh:mm."
    try:
        v["depart"] = (*verifier_ville(v["from_city"], v["from_cp"]), v["from_cp"])
        v["arrivee"] = (*verifier_ville(v["to_city"], v["to_cp"]), v["to_cp"])
    except VilleInvalide as e:
        return v, str(e)
    return v, None


def enregistrer(db, v, depart, arrivee, heure):
    """depart / arrivee : (nom officiel, lat, lon, code postal), vérifiés par verifier_ville."""
    (dnom, dlat, dlon, dcp), (anom, alat, alon, acp) = depart, arrivee
    db.execute(
        """INSERT INTO trajets (user_id, from_city, to_city, from_cp, to_cp, date, jours, heure,
                                date_fin, note, from_lat, from_lon, to_lat, to_lon)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (g.user["id"], dnom, anom, dcp, acp, v["date"], v["jours"], heure, v["date_fin"],
         v["note"], dlat, dlon, alat, alon),
    )


@bp.route("/", methods=("GET", "POST"))
@login_required
def mes_trajets():
    db = get_db()
    form = request.form
    if request.method == "POST":
        v, erreur = lire_formulaire(form)
        if erreur:
            flash(erreur, "erreur")
        else:
            enregistrer(db, v, v["depart"], v["arrivee"], v["heure"])
            if v["retour"]:
                enregistrer(db, v, v["arrivee"], v["depart"], v["heure_retour"])
            db.commit()
            flash("Trajet enregistré" + (" avec son retour" if v["retour"] else "")
                  + ". Merci : un don pourra peut-être voyager avec vous.")
            return redirect(url_for("trajets.mes_trajets"))
    aujourd_hui = date.today().isoformat()
    trajets = [
        {"t": t, "description": description(t), "prochaines": occurrences(t, nombre=3)}
        for t in db.execute(
            f"SELECT * FROM trajets t WHERE t.user_id = ? AND {SQL_A_VENIR} "
            "ORDER BY t.jours != '', t.date, t.heure",
            (g.user["id"], aujourd_hui, aujourd_hui),
        )
    ]
    return render_template("trajets/mes_trajets.html", trajets=trajets, today=aujourd_hui,
                           jours=JOURS, form=form)


@bp.route("/<int:trajet_id>/supprimer", methods=("POST",))
@login_required
def supprimer(trajet_id):
    db = get_db()
    trajet = db.execute("SELECT * FROM trajets WHERE id = ?", (trajet_id,)).fetchone()
    if trajet is None or trajet["user_id"] != g.user["id"]:
        abort(403)
    db.execute("DELETE FROM trajets WHERE id = ?", (trajet_id,))
    db.commit()
    flash("Trajet supprimé.")
    return redirect(url_for("trajets.mes_trajets"))
