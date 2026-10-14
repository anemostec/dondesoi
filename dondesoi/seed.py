"""Données de démonstration (commande : flask --app dondesoi seed-demo)."""
from datetime import date, timedelta

from werkzeug.security import generate_password_hash

MEMBRES = [
    ("marie@exemple.org", "Marie", "Lyon", "Retraitée, j'aime cuisiner et rendre visite."),
    ("joseph@exemple.org", "Joseph", "Villeurbanne", "Menuisier, toujours prêt pour un coup de main."),
    ("anne@exemple.org", "Anne", "Grenoble", "Maman de trois enfants."),
    ("paul@exemple.org", "Paul", "Lyon", "Étudiant, je fais souvent Lyon-Grenoble."),
]

CODES_POSTAUX = {"Lyon": "69001", "Villeurbanne": "69100", "Grenoble": "38000"}

ANNONCES = [
    # (membre, kind, category, title, description, essential)
    (0, "don", "nourriture", "Repas maison chaque dimanche",
     "Je cuisine toujours trop : un repas chaud pour une ou deux personnes le dimanche midi.", 0),
    (0, "don", "priere", "Je prie pour vos intentions",
     "Confiez-moi une intention, je la porterai chaque soir pendant une semaine.", 0),
    (0, "besoin", "service", "Petites réparations dans mon appartement",
     "Une étagère à fixer et une porte de placard qui ferme mal.", 0),
    (1, "don", "service", "Coup de main bricolage",
     "Montage de meubles, petites réparations, fixation d'étagères. Le samedi.", 0),
    (1, "don", "objet", "Lit bébé en bois",
     "Lit à barreaux en bon état avec matelas, fabriqué par mes soins.", 0),
    (1, "besoin", "ecoute", "Quelqu'un à qui parler",
     "Mon épouse est décédée il y a peu, un moment d'écoute de temps en temps me ferait du bien.", 0),
    (2, "besoin", "objet", "Lit pour bébé",
     "Nous attendons notre troisième enfant et n'avons plus de lit bébé.", 0),
    (2, "besoin", "nourriture", "Colis alimentaire pour la fin du mois",
     "Les fins de mois sont difficiles en ce moment.", 1),
    (2, "don", "savoir", "Soutien scolaire en anglais",
     "Ancienne professeure, je peux aider collégiens et lycéens en visio.", 0),
    (3, "don", "ecoute", "Temps d'écoute",
     "Je suis disponible le soir pour un appel ou un café.", 0),
    (3, "besoin", "savoir", "Aide pour rédiger un CV",
     "Je cherche mon premier stage et mon CV manque de clarté.", 0),
    (0, "besoin", "visite", "Une visite à ma voisine hospitalisée",
     "Ma voisine est à l'hôpital Édouard-Herriot et n'a pas de famille proche. Je ne peux pas y "
     "aller tous les jours.", 0),
]


def seed(db):
    ids = []
    for email, name, city, bio in MEMBRES:
        cur = db.execute(
            """INSERT INTO users (email, password_hash, display_name, city, postal_code, bio,
                                  contact, charter_accepted_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, datetime('now'))""",
            (email, generate_password_hash("demo1234"), name, city, CODES_POSTAUX[city], bio,
             email),
        )
        ids.append(cur.lastrowid)
    for membre, kind, cat, title, desc, essential in ANNONCES:
        db.execute(
            """INSERT INTO annonces (user_id, kind, category, title, description, city,
                                    postal_code, essential)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (ids[membre], kind, cat, title, desc, MEMBRES[membre][2],
             CODES_POSTAUX[MEMBRES[membre][2]], essential),
        )
    # Joseph et Paul portent dans la prière le colis alimentaire d'Anne.
    db.executemany("INSERT INTO prieres (annonce_id, user_id) VALUES (8, ?)", [(ids[1],), (ids[3],)])
    db.execute(
        "INSERT INTO trajets (user_id, from_city, to_city, from_cp, to_cp, date, note) "
        "VALUES (?, ?, ?, '69100', '38000', ?, ?)",
        (ids[3], "Villeurbanne", "Grenoble", (date.today() + timedelta(days=5)).isoformat(),
         "Place dans le coffre."),
    )
    db.commit()
