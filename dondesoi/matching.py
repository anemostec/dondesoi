"""Mise en relation des donateurs, receveurs et transporteurs.

Première version volontairement simple et *explicable* : chaque score est
accompagné des raisons qui l'expliquent, affichées au donateur. Le
donateur reste toujours seul décisionnaire ; ce module ne fait que
proposer et ordonner.

Règle de priorité de la charte : les besoins de première nécessité
(nourriture, logement, ...) passent toujours en premier.

Pistes pour la suite (contributions bienvenues) : embeddings sémantiques
open source, distance géographique réelle, apprentissage des préférences
de chaque donateur.
"""
import re
import unicodedata
from datetime import date

from . import CATEGORY_LABELS, ESSENTIAL_CATEGORIES

STOPWORDS = set("""
a au aux avec ce ces cet cette dans de des du elle en et eux il ils je la le les
leur leurs lui ma mais me mes moi mon ne nos notre nous on ou par pas pour qu que
qui sa se ses son sur ta te tes toi ton tu un une vos votre vous est sont suis
etre avoir ai as avons avez ont tres plus bien tout tous toute toutes besoin
cherche recherche donne propose offre souhaite aimerais voudrais peux peut faire
""".split())


def normalize(text):
    text = unicodedata.normalize("NFKD", text or "")
    text = "".join(c for c in text if not unicodedata.combining(c))
    return text.lower()


def normalize_city(city):
    return " ".join(re.findall(r"[a-z0-9]+", normalize(city)))


def tokens(text):
    out = set()
    for word in re.findall(r"[a-z0-9]+", normalize(text)):
        if len(word) < 3 or word in STOPWORDS:
            continue
        if len(word) > 4 and word[-1] in "sx":
            word = word[:-1]
        out.add(word)
    return out


def is_essential(annonce):
    return bool(annonce["essential"]) or annonce["category"] in ESSENTIAL_CATEGORIES


def score_pair(offre, besoin):
    """Pertinence d'un besoin pour une offre. Retourne (score, raisons)."""
    score = 0.0
    reasons = []

    if offre["category"] == besoin["category"]:
        score += 3
        reasons.append(f"même catégorie ({CATEGORY_LABELS.get(besoin['category'], besoin['category'])})")

    t_offre = tokens(offre["title"] + " " + offre["description"])
    t_besoin = tokens(besoin["title"] + " " + besoin["description"])
    common = t_offre & t_besoin
    if common:
        score += 10 * len(common) / len(t_offre | t_besoin) + len(common)
        reasons.append("mots en commun : " + ", ".join(sorted(common)[:5]))

    if normalize_city(offre["city"]) == normalize_city(besoin["city"]):
        score += 2
        reasons.append("même ville")

    return score, reasons


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

    # Un seul candidat par receveur : on garde son besoin le plus pertinent.
    best = {}
    for besoin in besoins:
        score, reasons = score_pair(offre, besoin)
        essential = is_essential(besoin)
        if score <= 0 and besoin["user_id"] not in interets:
            continue
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
        """SELECT * FROM annonces
           WHERE kind = 'don' AND status = 'ouverte' AND user_id != ?""",
        (besoin["user_id"],),
    ).fetchall()
    scored = []
    for offre in offres:
        score, reasons = score_pair(offre, besoin)
        if score > 0:
            scored.append({"offre": offre, "score": score, "reasons": reasons})
    scored.sort(key=lambda s: s["score"], reverse=True)
    return scored[:limit]


def trajets_pour_don(db, donor, receiver):
    """Trajets prévus par d'autres membres, de la ville du donateur à celle du receveur."""
    src, dst = normalize_city(donor["city"]), normalize_city(receiver["city"])
    if src == dst:
        return []
    rows = db.execute(
        """SELECT t.*, u.display_name FROM trajets t JOIN users u ON u.id = t.user_id
           WHERE t.date >= ? AND t.user_id NOT IN (?, ?) ORDER BY t.date""",
        (date.today().isoformat(), donor["id"], receiver["id"]),
    ).fetchall()
    return [t for t in rows
            if normalize_city(t["from_city"]) == src and normalize_city(t["to_city"]) == dst]
