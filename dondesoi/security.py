import functools
import secrets

from flask import abort, g, redirect, request, session, url_for

from .db import get_db


def csrf_token():
    if "_csrf" not in session:
        session["_csrf"] = secrets.token_urlsafe(32)
    return session["_csrf"]


def trop_de_demandes(cle, maximum, minutes):
    """Vrai si l'action « cle » a déjà eu lieu « maximum » fois dans les dernières minutes.
    Sinon, la compte et retourne faux."""
    db = get_db()
    depuis = f"-{int(minutes)} minutes"
    db.execute("DELETE FROM limites WHERE created_at < datetime('now', '-1 day')")
    n = db.execute("SELECT COUNT(*) FROM limites WHERE cle = ? AND created_at >= datetime('now', ?)",
                   (cle, depuis)).fetchone()[0]
    if n >= maximum:
        db.commit()
        return True
    db.execute("INSERT INTO limites (cle) VALUES (?)", (cle,))
    db.commit()
    return False


def login_required(view):
    @functools.wraps(view)
    def wrapped(**kwargs):
        if g.user is None:
            return redirect(url_for("auth.connexion", next=request.path))
        return view(**kwargs)
    return wrapped


def init_app(app):
    app.jinja_env.globals["csrf_token"] = csrf_token

    @app.before_request
    def load_user_and_check_csrf():
        user_id = session.get("user_id")
        g.user = None
        if user_id is not None:
            g.user = get_db().execute(
                "SELECT * FROM users WHERE id = ?", (user_id,)
            ).fetchone()

        if request.method == "POST" and not app.config.get("TESTING_NO_CSRF"):
            token = request.form.get("_csrf", "")
            if not token or not secrets.compare_digest(token, session.get("_csrf", "")):
                abort(400, "Jeton de sécurité invalide, rechargez la page.")
