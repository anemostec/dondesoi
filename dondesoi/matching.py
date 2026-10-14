"""Mise en relation des donateurs, receveurs et transporteurs.

Le système reste *explicable* : chaque score est accompagné des raisons
qui l'expliquent, affichées au donateur. Le donateur reste toujours seul
décisionnaire ; ce module ne fait que proposer et ordonner.

Deux familles de critères :
- la pertinence (le don répond-il au besoin ?) : même catégorie, mots en
  commun, et sens proche grâce au modèle d'IA de sens.py ;
- la proximité, qui ne fait que départager : distance réelle entre les
  villes (geo.py), sauf pour ce qui peut se vivre à distance (prière,
  écoute, savoir).
Un besoin sans aucune pertinence n'est jamais proposé, même tout proche.

Règle de priorité de la charte : les besoins de première nécessité
passent toujours en premier, quel que soit le score.
"""
from datetime import date

from . import CATEGORY_LABELS, ESSENTIAL_CATEGORIES
from .calendrier import SQL_A_VENIR, description, occurrences
from .geo import distance_rows, position_sur_trajet
from .photos import COVER_SQL
from .sens import similarite, vecteurs
from .textes import normalize, normalize_city, tokens  # noqa: F401 (réexportés)

# Ce qui peut se donner à distance : la proximité n'y compte pas.
A_DISTANCE = {"priere", "ecoute", "savoir"}

# Sens des mots : en dessous de SENS_BRUIT, deux annonces n'ont pas plus en
# commun que deux annonces prises au hasard ; à SENS_FORT, elles disent à peu
# près la même chose. Calibré sur le modèle MiniLM multilingue et les données
# de démonstration (bruit observé jusqu'à 0,41 ; « lit bébé » / « lit pour
# bébé » : 0,70 ; « temps d'écoute » / « quelqu'un à qui parler » : 0,67).
SENS_BRUIT = 0.43
SENS_FORT = 0.68
SENS_POINTS = 8

# Proximité : points pleins jusqu'à PROCHE_KM, puis décroissance jusqu'à LOIN_KM.
PROCHE_KM = 5
LOIN_KM = 50
PROXIMITE_POINTS = 3

# Un trajet peut porter un don si le donateur et le receveur sont à moins de
# DETOUR_KM de sa route, dans le bon ordre.
DETOUR_KM = 15

# Pertinence minimale pour qu'un besoin soit proposé.
PERTINENCE_MIN = 1.0


def is_essential(annonce):
    return bool(annonce["essential"]) or annonce["category"] in ESSENTIAL_CATEGORIES


def km(d):
    return f"{d:.0f} km" if d >= 1 else "moins d'un km"


def proximite(offre, besoin):
    """(points, raison) selon la distance entre les deux annonces."""
    if offre["category"] in A_DISTANCE or besoin["category"] in A_DISTANCE:
        return 0.0, None
    d = distance_rows(offre, besoin)
    if d is None:
        # Coordonnées inconnues : on compare au moins les noms de villes.
        if normalize_city(offre["city"]) == normalize_city(besoin["city"]):
            return 2.0, "même ville"
        return 0.0, None
    if d <= PROCHE_KM:
        return float(PROXIMITE_POINTS), f"à {km(d)}"
    if d < LOIN_KM:
        return PROXIMITE_POINTS * (LOIN_KM - d) / (LOIN_KM - PROCHE_KM), f"à {km(d)}"
    return 0.0, f"à {km(d)}"


def score_pair(offre, besoin, sim=None):
    """Pertinence d'un besoin pour une offre.

    Retourne (pertinence, proximite, raisons) ; sim est la similarité de sens
    entre les deux textes, si le modèle est disponible.
    """
    pertinence = 0.0
    reasons = []

    if offre["category"] == besoin["category"]:
        pertinence += 3
        reasons.append(f"même catégorie ({CATEGORY_LABELS.get(besoin['category'], besoin['category'])})")

    t_offre = tokens(offre["title"] + " " + offre["description"])
    t_besoin = tokens(besoin["title"] + " " + besoin["description"])
    common = t_offre & t_besoin
    if common:
        pertinence += 10 * len(common) / len(t_offre | t_besoin) + len(common)
        reasons.append("mots en commun : " + ", ".join(sorted(common)[:5]))

    if sim is not None and sim > SENS_BRUIT:
        force = min(1.0, (sim - SENS_BRUIT) / (SENS_FORT - SENS_BRUIT))
        pertinence += SENS_POINTS * force
        reasons.append("sens très proche" if force >= 0.7 else "sens proche")

    points, raison = proximite(offre, besoin)
    if raison:
        reasons.append(raison)
    return pertinence, points, reasons


def _sims(db, reference, annonces):
    vecs = vecteurs(db, [reference, *annonces])
    ref = vecs.get(reference["id"])
    if ref is None:
        return {}
    return {a["id"]: similarite(ref, vecs[a["id"]]) for a in annonces if a["id"] in vecs}


def candidats_pour_offre(db, offre, limit=30):
    """Receveurs potentiels pour un don, du plus prioritaire au moins prioritaire."""
    besoins = db.execute(
        """SELECT a.*, u.display_name, u.city AS user_city
           FROM annonces a JOIN users u ON u.id = a.user_id
           WHERE a.kind = 'besoin' AND a.status = 'ouverte' AND a.user_id != ?""",
        (offre["user_id"],),
    ).fetchall()
    interets = {
        row["user_id"]: row
        for row in db.execute(
            """SELECT i.*, u.display_name, u.city AS user_city
               FROM interets i JOIN users u ON u.id = i.user_id
               WHERE i.annonce_id = ?""",
            (offre["id"],),
        )
    }
    sims = _sims(db, offre, besoins)

    # Un seul candidat par receveur : on garde son besoin le plus pertinent.
    best = {}
    for besoin in besoins:
        pertinence, points, reasons = score_pair(offre, besoin, sims.get(besoin["id"]))
        if pertinence < PERTINENCE_MIN and besoin["user_id"] not in interets:
            continue
        essential = is_essential(besoin)
        score = pertinence + points
        current = best.get(besoin["user_id"])
        if current is None or (essential, score) > (current["essential"], current["score"]):
            best[besoin["user_id"]] = {
                "receiver_id": besoin["user_id"],
                "display_name": besoin["display_name"],
                "city": besoin["user_city"],
                "besoin": besoin,
                "score": score,
                "essential": essential,
                "reasons": reasons,
                "interet": None,
            }

    for user_id, interet in interets.items():
        cand = best.setdefault(user_id, {
            "receiver_id": user_id,
            "display_name": interet["display_name"],
            "city": interet["user_city"],
            "besoin": None,
            "score": 0.0,
            "essential": False,
            "reasons": [],
            "interet": None,
        })
        cand["interet"] = interet
        cand["score"] += 4
        cand["reasons"].insert(0, "a signalé que ce don lui serait utile")

    candidats = list(best.values())
    for cand in candidats:
        if cand["essential"]:
            cand["reasons"].insert(0, "besoin de première nécessité : prioritaire")
        cand["avis_count"] = db.execute(
            "SELECT COUNT(*) FROM avis WHERE subject_id = ?", (cand["receiver_id"],)
        ).fetchone()[0]
        cand["dons_recus"] = db.execute(
            "SELECT COUNT(*) FROM dons WHERE receiver_id = ? AND status != 'annule'",
            (cand["receiver_id"],),
        ).fetchone()[0]

    candidats.sort(key=lambda c: (c["essential"], c["score"]), reverse=True)
    return candidats[:limit]


def offres_pour_besoin(db, besoin, limit=10):
    """Dons proposés qui pourraient répondre à un besoin."""
    offres = db.execute(
        f"""SELECT a.*, {COVER_SQL} FROM annonces a
            WHERE a.kind = 'don' AND a.status = 'ouverte' AND a.user_id != ?""",
        (besoin["user_id"],),
    ).fetchall()
    sims = _sims(db, besoin, offres)
    scored = []
    for offre in offres:
        pertinence, points, reasons = score_pair(offre, besoin, sims.get(offre["id"]))
        if pertinence >= PERTINENCE_MIN:
            scored.append({"offre": offre, "score": pertinence + points, "reasons": reasons})
    scored.sort(key=lambda s: s["score"], reverse=True)
    return scored[:limit]


def meme_endroit(donor, receiver):
    """(vrai si on peut se retrouver directement, distance en km ou None)."""
    d = distance_rows(donor, receiver)
    if d is None:
        return normalize_city(donor["city"]) == normalize_city(receiver["city"]), None
    return d <= PROCHE_KM, d


def trajets_pour_don(db, donor, receiver):
    """Trajets prévus par d'autres membres qui passent près du donateur puis du receveur.

    Retourne une liste de dicts : trajet, explication (ou None), description (« le mar. 21 oct.
    à 9 h », « tous les lundis à 7 h 30 »…) et prochaines dates (pour un trajet régulier, le
    donateur choisit l'une d'elles).
    """
    proche, _ = meme_endroit(donor, receiver)
    if proche:
        return []
    aujourd_hui = date.today().isoformat()
    rows = db.execute(
        f"""SELECT t.*, u.display_name FROM trajets t JOIN users u ON u.id = t.user_id
            WHERE {SQL_A_VENIR} AND t.user_id NOT IN (?, ?) ORDER BY t.date""",
        (aujourd_hui, aujourd_hui, donor["id"], receiver["id"]),
    ).fetchall()
    src, dst = normalize_city(donor["city"]), normalize_city(receiver["city"])
    out = []
    for t in rows:
        prochaines = occurrences(t, nombre=6)
        if not prochaines:
            continue
        explication = None
        coords = (t["from_lat"], t["to_lat"], donor["lat"], receiver["lat"])
        if None in coords:
            if not (normalize_city(t["from_city"]) == src and normalize_city(t["to_city"]) == dst):
                continue
        else:
            t_d, ecart_d = position_sur_trajet(donor["lat"], donor["lon"], t)
            t_r, ecart_r = position_sur_trajet(receiver["lat"], receiver["lon"], t)
            if not (ecart_d <= DETOUR_KM and ecart_r <= DETOUR_KM and t_d < t_r):
                continue
            explication = f"passe à {km(ecart_d)} de chez vous et à {km(ecart_r)} du receveur"
        out.append({"trajet": t, "explication": explication, "description": description(t),
                    "prochaines": prochaines})
    out.sort(key=lambda x: x["prochaines"][0])
    return out
