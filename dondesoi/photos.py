"""Enregistrement des photos envoyées par les membres.

Chaque image est réencodée en JPEG : cela la redimensionne, refuse tout
fichier qui n'est pas vraiment une image, et supprime les métadonnées
(notamment la position GPS que les téléphones inscrivent dans les photos).
Une vignette est créée à côté pour les listes.
"""
import os
import uuid

from flask import current_app
from PIL import Image, ImageOps, UnidentifiedImageError

MAX_SIZE = 1600
THUMB_SIZE = 600
MAX_PHOTOS_PAR_ANNONCE = 6

# Première photo d'une annonce (alias « a »), pour les cartes des listes.
COVER_SQL = ("(SELECT filename FROM annonce_photos ph WHERE ph.annonce_id = a.id "
             "ORDER BY ph.position, ph.id LIMIT 1) AS cover")

# Protection contre les images piégées (des milliards de pixels dans un petit fichier).
Image.MAX_IMAGE_PIXELS = 50_000_000


class PhotoInvalide(ValueError):
    pass


def _folder(subdir):
    path = os.path.join(current_app.config["UPLOAD_FOLDER"], subdir)
    os.makedirs(path, exist_ok=True)
    return path


def thumb_name(filename):
    return filename.replace(".jpg", "_t.jpg")


def save_photo(file_storage, subdir="annonces"):
    """Enregistre l'image et retourne son nom de fichier (relatif à subdir)."""
    try:
        img = Image.open(file_storage.stream)
        img.load()
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError):
        raise PhotoInvalide(f"« {file_storage.filename} » n'est pas une image lisible.")
    img = ImageOps.exif_transpose(img)
    if img.mode != "RGB":
        background = Image.new("RGB", img.size, "white")
        background.paste(img, mask=img.convert("RGBA").getchannel("A"))
        img = background

    name = f"{uuid.uuid4().hex}.jpg"
    folder = _folder(subdir)
    full = img.copy()
    full.thumbnail((MAX_SIZE, MAX_SIZE))
    full.save(os.path.join(folder, name), "JPEG", quality=85, optimize=True)
    img.thumbnail((THUMB_SIZE, THUMB_SIZE))
    img.save(os.path.join(folder, thumb_name(name)), "JPEG", quality=80, optimize=True)
    return name


def save_photos(files, subdir="annonces", limit=MAX_PHOTOS_PAR_ANNONCE):
    """Enregistre plusieurs images envoyées ; ignore les champs vides."""
    files = [f for f in files if f and f.filename]
    if len(files) > limit:
        raise PhotoInvalide(f"{limit} photos au maximum.")
    saved = []
    try:
        for f in files:
            saved.append(save_photo(f, subdir))
    except PhotoInvalide:
        for name in saved:
            delete_photo(name, subdir)
        raise
    return saved


def delete_photo(name, subdir="annonces"):
    folder = _folder(subdir)
    for n in (name, thumb_name(name)):
        try:
            os.remove(os.path.join(folder, n))
        except FileNotFoundError:
            pass
