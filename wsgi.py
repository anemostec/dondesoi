"""Point d'entrée pour un serveur WSGI de production.

gunicorn wsgi:app (voir deploy/) ; uWSGI (alwaysdata) cherche « application ».
"""
from dondesoi import create_app

app = application = create_app()
