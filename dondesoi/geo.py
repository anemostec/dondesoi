"""Coordonnées des villes et distances.

Les coordonnées viennent de geo.api.gouv.fr, service public gratuit de
l'État. Seuls le nom de la ville et le code postal saisis lui sont envoyés,
une seule fois par ville : le résultat (même un échec) est gardé dans la
table « lieux ». Si le service ne répond pas, la mise en relation revient
simplement à la comparaison des noms de villes.

GEOCODER : "api" (défaut) ou "none" ; les tests installent leur propre
géocodeur dans app.extensions["geocoder"].
"""
import json
import math
import urllib.parse
import urllib.request

from flask import current_app

from .db import get_db
from .textes import normalize_city

EARTH_RADIUS_KM = 6371.0


def distance_km(lat1, lon1, lat2, lon2):
    """Distance à vol d'oiseau (formule de haversine)."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * EARTH_RADIUS_KM * math.asin(math.sqrt(a))


def distance_rows(a, b, a_prefix="", b_prefix=""):
    """Distance entre deux lignes ayant des colonnes lat/lon, ou None."""
    try:
        lat1, lon1 = a[a_prefix + "lat"], a[a_prefix + "lon"]
        lat2, lon2 = b[b_prefix + "lat"], b[b_prefix + "lon"]
    except (IndexError, KeyError):
        return None
    if None in (lat1, lon1, lat2, lon2):
        return None
    return distance_km(lat1, lon1, lat2, lon2)


def position_sur_trajet(lat, lon, trajet):
    """Situe un point par rapport au trajet (départ → arrivée).

    Retourne (t, ecart_km) : t vaut 0 au départ et 1 à l'arrivée, ecart_km est
    la distance du point à la ligne droite du trajet. Approximation plane,
    suffisante à l'échelle d'un pays.
    """
    lat0 = math.radians(trajet["from_lat"])
    def xy(la, lo):
        return (math.radians(lo - trajet["from_lon"]) * math.cos(lat0) * EARTH_RADIUS_KM,
                math.radians(la - trajet["from_lat"]) * EARTH_RADIUS_KM)
    bx, by = xy(trajet["to_lat"], trajet["to_lon"])
    px, py = xy(lat, lon)
    length2 = bx * bx + by * by
    t = 0.0 if length2 == 0 else (px * bx + py * by) / length2
    tc = min(1.0, max(0.0, t))
    return t, math.hypot(px - tc * bx, py - tc * by)


def _api_geocode(city, postal_code):
    base = current_app.config["GEO_API_URL"].rstrip("/")
    if postal_code:
        query = {"codePostal": postal_code, "fields": "nom,centre"}
    else:
        query = {"nom": city, "fields": "nom,centre", "boost": "population", "limit": "5"}
    url = f"{base}/communes?{urllib.parse.urlencode(query)}"
    req = urllib.request.Request(url, headers={"User-Agent": "DonDeSoi (logiciel libre)"})
    with urllib.request.urlopen(req, timeout=4) as resp:
        communes = json.load(resp)
    communes = [c for c in communes if c.get("centre")]
    if not communes:
        return None
    wanted = normalize_city(city)
    best = next((c for c in communes if normalize_city(c["nom"]) == wanted), communes[0])
    lon, lat = best["centre"]["coordinates"]
    return best["nom"], lat, lon


def geocode(city, postal_code=""):
    """(lat, lon) d'une ville, ou None si elle est introuvable ou le service absent."""
    city, postal_code = (city or "").strip(), (postal_code or "").strip()
    if not city and not postal_code:
        return None
    key = f"{normalize_city(city)}|{postal_code}"
    db = get_db()
    cached = db.execute("SELECT * FROM lieux WHERE cle = ?", (key,)).fetchone()
    if cached is not None:
        return None if cached["lat"] is None else (cached["lat"], cached["lon"])

    geocoder = current_app.extensions.get("geocoder")
    try:
        if geocoder is not None:
            found = geocoder(city, postal_code)
        elif current_app.config.get("GEOCODER", "api") == "api":
            found = _api_geocode(city, postal_code)
        else:
            return None
    except (OSError, ValueError, KeyError) as e:
        # Service injoignable : on ne met rien en cache, on réessaiera plus tard.
        current_app.logger.warning("Géocodage impossible pour %r : %s", city, e)
        return None
    nom, lat, lon = found if found else (None, None, None)
    db.execute("INSERT OR REPLACE INTO lieux (cle, nom, lat, lon) VALUES (?, ?, ?, ?)",
               (key, nom, lat, lon))
    db.commit()
    return None if lat is None else (lat, lon)


def coords_or_none(city, postal_code=""):
    found = geocode(city, postal_code)
    return found if found else (None, None)
