"""Trajets réguliers : prochaines dates et description en français.

Un trajet ponctuel a une date. Un trajet régulier a des jours de la semaine
(« 0,3 » = lundi et jeudi), une date de début (colonne date) et une date de fin
facultative. Les deux peuvent avoir une heure (« 07:30 »).
"""
from datetime import date, timedelta

JOURS = ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"]
JOURS_COURTS = ["lun.", "mar.", "mer.", "jeu.", "ven.", "sam.", "dim."]
MOIS = ["janv.", "févr.", "mars", "avr.", "mai", "juin", "juil.", "août", "sept.", "oct.",
        "nov.", "déc."]

# Condition SQL (alias t) : trajets encore à venir à la date passée en paramètre (deux fois).
SQL_A_VENIR = ("((t.jours = '' AND t.date >= ?) "
               "OR (t.jours != '' AND (t.date_fin IS NULL OR t.date_fin >= ?)))")


def jours_de(trajet):
    return [int(j) for j in (trajet["jours"] or "").split(",") if j.strip().isdigit()]


def est_regulier(trajet):
    return bool(jours_de(trajet))


def occurrences(trajet, depuis=None, nombre=4):
    """Les prochaines dates (objets date) du trajet, à partir de « depuis » inclus."""
    depuis = depuis or date.today()
    debut = date.fromisoformat(trajet["date"])
    if not est_regulier(trajet):
        return [debut] if debut >= depuis else []
    fin = date.fromisoformat(trajet["date_fin"]) if trajet["date_fin"] else None
    jours = set(jours_de(trajet))
    jour = max(depuis, debut)
    dates = []
    for _ in range(7 * 60):   # au plus ~60 semaines d'examen
        if fin and jour > fin:
            break
        if jour.weekday() in jours:
            dates.append(jour)
            if len(dates) >= nombre:
                break
        jour += timedelta(days=1)
    return dates


def date_fr(d):
    if isinstance(d, str):
        d = date.fromisoformat(d)
    return f"{JOURS_COURTS[d.weekday()]} {d.day} {MOIS[d.month - 1]}"


def heure_fr(heure):
    if not heure:
        return ""
    h, m = heure.split(":")[:2]
    return f"{int(h)} h {m}" if m != "00" else f"{int(h)} h"


def liste_fr(mots):
    return mots[0] if len(mots) == 1 else ", ".join(mots[:-1]) + " et " + mots[-1]


def description(trajet):
    """Ex. « tous les lundis et jeudis à 7 h 30, jusqu'au ven. 19 déc. » ou « le mar. 21 oct. à 9 h »."""
    heure = f" à {heure_fr(trajet['heure'])}" if trajet["heure"] else ""
    if not est_regulier(trajet):
        return f"le {date_fr(trajet['date'])}{heure}"
    jours = jours_de(trajet)
    if jours == [0, 1, 2, 3, 4]:
        quand = "du lundi au vendredi"
    elif len(jours) == 7:
        quand = "tous les jours"
    else:
        quand = "tous les " + liste_fr([JOURS[j] + "s" for j in jours])
    debut = date.fromisoformat(trajet["date"])
    suite = ""
    if debut > date.today():
        suite += f", à partir du {date_fr(debut)}"
    if trajet["date_fin"]:
        suite += f", jusqu'au {date_fr(trajet['date_fin'])}"
    return f"{quand}{heure}{suite}"
