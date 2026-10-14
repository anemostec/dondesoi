import re
from datetime import date

from flask import Blueprint, abort, flash, g, redirect, render_template, request, url_for

from .calendrier import JOURS, SQL_A_VENIR, date_fr, description, occurrences
from .db import get_db
from .geo import VilleInvalide, verifier_ville
from .notifications import notify
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
        "public": int(bool(f.get("public"))),
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
                                date_fin, note, public, from_lat, from_lon, to_lat, to_lon)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (g.user["id"], dnom, anom, dcp, acp, v["date"], v["jours"], heure, v["date_fin"],
         v["note"], v["public"], dlat, dlon, alat, alon),
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
    trajets = []
    for t in db.execute(
        f"SELECT * FROM trajets t WHERE t.user_id = ? AND {SQL_A_VENIR} "
        "ORDER BY t.jours != '', t.date, t.heure",
        (g.user["id"], aujourd_hui, aujourd_hui),
    ):
        demandes = db.execute(
            "SELECT d.*, u.display_name, u.city FROM trajet_demandes d JOIN users u ON u.id = d.user_id "
            "WHERE d.trajet_id = ? AND d.date >= ? ORDER BY d.date", (t["id"], aujourd_hui),
        ).fetchall()
        trajets.append({"t": t, "description": description(t), "demandes": demandes,
                        "prochaines": occurrences(t, nombre=3)})
    mes_demandes = db.execute(
        "SELECT d.*, t.from_city, t.to_city FROM trajet_demandes d JOIN trajets t ON t.id = d.trajet_id "
        "WHERE d.user_id = ? AND d.date >= ? ORDER BY d.date", (g.user["id"], aujourd_hui),
    ).fetchall()
    return render_template("trajets/mes_trajets.html", trajets=trajets, today=aujourd_hui,
                           jours=JOURS, form=form, mes_demandes=mes_demandes)


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


def get_trajet_public(trajet_id):
    t = get_db().execute("SELECT * FROM trajets WHERE id = ? AND public = 1", (trajet_id,)).fetchone()
    if t is None:
        abort(404)
    return t


@bp.route("/<int:trajet_id>/visibilite", methods=("POST",))
@login_required
def visibilite(trajet_id):
    db = get_db()
    trajet = db.execute("SELECT * FROM trajets WHERE id = ?", (trajet_id,)).fetchone()
    if trajet is None or trajet["user_id"] != g.user["id"]:
        abort(403)
    public = int(not trajet["public"])
    db.execute("UPDATE trajets SET public = ? WHERE id = ?", (public, trajet_id))
    db.commit()
    flash("Ce trajet est maintenant visible dans les annonces (sans votre nom ni l'heure)."
          if public else "Ce trajet n'est plus visible dans les annonces.")
    return redirect(url_for("trajets.mes_trajets"))


def lieu_recherche(f, prefixe):
    """(nom, lat, lon) d'un champ « code postal + ville » facultatif de la recherche."""
    ville, cp = f.get(f"{prefixe}_city", "").strip(), f.get(f"{prefixe}_cp", "").strip()
    if not ville and not cp:
        return None
    if not cp:
        return ville, None, None   # sans code postal : comparaison des noms seulement
    return verifier_ville(ville, cp)


@bp.route("/recherche")
@login_required
def recherche():
    """Rechercher un trajet proposé par un autre membre (visible des membres seulement)."""
    from .matching import DETOUR_KM, rechercher_trajets
    f = request.args
    erreur, resultats, cherche = None, [], bool(f)
    jour = None
    try:
        depart, arrivee = lieu_recherche(f, "from"), lieu_recherche(f, "to")
        if f.get("date"):
            jour = date.fromisoformat(f["date"])
    except VilleInvalide as e:
        erreur, depart, arrivee = str(e), None, None
    except ValueError:
        erreur, depart, arrivee = "Date invalide.", None, None
    detour = min(max(f.get("detour", type=int) or DETOUR_KM, 1), 100)
    if erreur:
        flash(erreur, "erreur")
    else:
        resultats = rechercher_trajets(get_db(), g.user["id"], depart, arrivee, jour, detour)
    return render_template("trajets/recherche.html", resultats=resultats, form=f, cherche=cherche,
                           detour=detour, today=date.today().isoformat())


@bp.route("/<int:trajet_id>/demande", methods=("POST",))
@login_required
def demande(trajet_id):
    """« Ce trajet m'intéresse » : prévient le voyageur, qui reste anonyme."""
    t = get_trajet_public(trajet_id)
    if t["user_id"] == g.user["id"]:
        abort(400)
    jour = request.form.get("date", "")
    if jour not in [d.isoformat() for d in occurrences(t, nombre=6)]:
        abort(400)
    message = request.form.get("message", "").strip()[:1000]
    db = get_db()
    cur = db.execute("INSERT OR IGNORE INTO trajet_demandes (trajet_id, user_id, date, message) "
                     "VALUES (?, ?, ?, ?)", (trajet_id, g.user["id"], jour, message))
    db.commit()
    if cur.rowcount:
        notify(t["user_id"],
               f"{g.user['display_name']} aimerait faire porter quelque chose lors de votre trajet "
               f"{t['from_city']} → {t['to_city']} du {date_fr(jour)}.",
               url_for("trajets.mes_trajets"))
        flash("Le voyageur est prévenu. Vous recevrez sa réponse ici et par notification.")
    else:
        flash("Vous avez déjà fait cette demande pour cette date.")
    return redirect(url_for("trajets.mes_trajets") + "#mes-demandes")


@bp.route("/demandes/<int:demande_id>/reponse", methods=("POST",))
@login_required
def repondre(demande_id):
    db = get_db()
    d = db.execute("SELECT d.*, t.user_id AS voyageur_id, t.from_city, t.to_city "
                   "FROM trajet_demandes d JOIN trajets t ON t.id = d.trajet_id WHERE d.id = ?",
                   (demande_id,)).fetchone()
    if d is None or d["voyageur_id"] != g.user["id"]:
        abort(403)
    statut = request.form.get("statut")
    if statut not in ("acceptee", "refusee"):
        abort(400)
    db.execute("UPDATE trajet_demandes SET statut = ?, reponse = ?, reponse_at = datetime('now') "
               "WHERE id = ?", (statut, request.form.get("reponse", "").strip()[:1000], demande_id))
    db.commit()
    verbe = "accepte" if statut == "acceptee" else "ne peut pas accepter"
    notify(d["user_id"], f"Le voyageur {verbe} votre demande pour le trajet {d['from_city']} → "
           f"{d['to_city']} du {date_fr(d['date'])}.", url_for("trajets.mes_trajets"))
    flash("Réponse envoyée.")
    return redirect(url_for("trajets.mes_trajets"))
