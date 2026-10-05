from datetime import date

from flask import Blueprint, abort, flash, g, redirect, render_template, request, url_for

from .db import get_db
from .security import login_required

bp = Blueprint("trajets", __name__, url_prefix="/trajets")


@bp.route("/", methods=("GET", "POST"))
@login_required
def mes_trajets():
    db = get_db()
    if request.method == "POST":
        f = request.form
        from_city, to_city, day = (f.get("from_city", "").strip(), f.get("to_city", "").strip(),
                                   f.get("date", ""))
        if not from_city or not to_city or not day:
            flash("Merci d'indiquer le départ, l'arrivée et la date.", "erreur")
        elif day < date.today().isoformat():
            flash("La date est déjà passée.", "erreur")
        else:
            db.execute(
                "INSERT INTO trajets (user_id, from_city, to_city, date, note) VALUES (?, ?, ?, ?, ?)",
                (g.user["id"], from_city, to_city, day, f.get("note", "").strip()),
            )
            db.commit()
            flash("Trajet enregistré. Merci : un don pourra peut-être voyager avec vous.")
            return redirect(url_for("trajets.mes_trajets"))
    trajets = db.execute(
        "SELECT * FROM trajets WHERE user_id = ? AND date >= ? ORDER BY date",
        (g.user["id"], date.today().isoformat()),
    ).fetchall()
    return render_template("trajets/mes_trajets.html", trajets=trajets,
                           today=date.today().isoformat())


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
