"""Point d'entrée pour un serveur WSGI de production : gunicorn wsgi:app"""
from dondesoi import create_app

app = create_app()
