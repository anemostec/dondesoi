"""Passages d'Évangile cités dans le site.

Traduction Louis Segond (1910), domaine public. Chaque passage est placé là
où il éclaire le geste demandé au membre. Pour en ajouter un, l'inscrire ici
puis l'appeler dans un gabarit avec {{ verset("cle") }}.
"""
from datetime import date

PASSAGES = {
    # Le fondement : donner gratuitement, se donner soi-même.
    "gratuitement": ("Vous avez reçu gratuitement, donnez gratuitement.", "Mt 10,8"),
    "servir": ("Le Fils de l'homme est venu, non pour être servi, mais pour servir et donner sa vie "
               "comme la rançon de plusieurs.", "Mt 20,28"),
    "plus_grand_amour": ("Il n'y a pas de plus grand amour que de donner sa vie pour ses amis.",
                         "Jn 15,13"),
    "plus_heureux": ("Il y a plus de bonheur à donner qu'à recevoir.",
                     "Paroles du Seigneur Jésus, Ac 20,35"),
    "commandement": ("Je vous donne un commandement nouveau : Aimez-vous les uns les autres ; comme "
                     "je vous ai aimés, vous aussi, aimez-vous les uns les autres.", "Jn 13,34"),
    "famille": ("Quiconque fait la volonté de Dieu, celui-là est mon frère, ma sœur, et ma mère.",
                "Mc 3,35"),
    "temoignage_silencieux": ("À ceci tous connaîtront que vous êtes mes disciples, si vous avez "
                              "de l'amour les uns pour les autres.", "Jn 13,35"),

    # Chacun peut donner, même le plus pauvre.
    "veuve": ("Cette pauvre veuve a donné plus qu'aucun de ceux qui ont mis dans le tronc ; car tous "
              "ont mis de leur superflu, mais elle a mis de son nécessaire.", "Mc 12,43-44"),
    "cinq_pains": ("Il y a ici un jeune garçon qui a cinq pains d'orge et deux poissons ; mais "
                   "qu'est-ce que cela pour tant de gens ?", "Jn 6,9"),
    "deux_tuniques": ("Que celui qui a deux tuniques partage avec celui qui n'en a point, et que "
                      "celui qui a de quoi manger agisse de même.", "Lc 3,11"),
    "laver_les_pieds": ("Si donc je vous ai lavé les pieds, moi, le Seigneur et le Maître, vous "
                        "devez aussi vous laver les pieds les uns aux autres.", "Jn 13,14"),

    # Donner sans rien attendre, dans le secret.
    "sans_rien_esperer": ("Faites du bien, et prêtez sans rien espérer.", "Lc 6,35"),
    "festin": ("Lorsque tu donnes un festin, invite des pauvres, des estropiés, des boiteux, des "
               "aveugles. Et tu seras heureux de ce qu'ils ne peuvent pas te rendre la pareille.",
               "Lc 14,13-14"),
    "main_gauche": ("Quand tu fais l'aumône, que ta main gauche ne sache pas ce que fait ta droite, "
                    "afin que ton aumône se fasse en secret ; et ton Père, qui voit dans le secret, "
                    "te le rendra.", "Mt 6,3-4"),
    "donne_a_qui_demande": ("Donne à celui qui te demande, et ne te détourne pas de celui qui veut "
                            "emprunter de toi.", "Mt 5,42"),

    # Recevoir, demander.
    "demandez": ("Demandez, et l'on vous donnera ; cherchez, et vous trouverez ; frappez, et l'on "
                 "vous ouvrira.", "Mt 7,7"),
    "venez_a_moi": ("Venez à moi, vous tous qui êtes fatigués et chargés, et je vous donnerai du "
                    "repos.", "Mt 11,28"),

    # Les plus petits d'abord.
    "jai_eu_faim": ("Car j'ai eu faim, et vous m'avez donné à manger ; j'ai eu soif, et vous m'avez "
                    "donné à boire ; j'étais étranger, et vous m'avez recueilli ; j'étais nu, et "
                    "vous m'avez vêtu ; j'étais malade, et vous m'avez visité ; j'étais en prison, "
                    "et vous êtes venus vers moi.", "Mt 25,35-36"),
    "plus_petits": ("Toutes les fois que vous avez fait ces choses à l'un de ces plus petits de mes "
                    "frères, c'est à moi que vous les avez faites.", "Mt 25,40"),

    # Le chemin : porter le don.
    "samaritain": ("Il le mit sur sa propre monture, le conduisit à une hôtellerie, et prit soin "
                   "de lui.", "Lc 10,34"),
    "fais_de_meme": ("Va, et toi, fais de même.", "Lc 10,37"),

    # La prière les uns pour les autres.
    "deux_ou_trois": ("Là où deux ou trois sont assemblés en mon nom, je suis au milieu d'eux.",
                      "Mt 18,20"),
    "accord_priere": ("Si deux d'entre vous s'accordent sur la terre pour demander une chose "
                      "quelconque, elle leur sera accordée par mon Père qui est dans les cieux.",
                      "Mt 18,19"),

    # Rendre grâce.
    "lepreux": ("L'un d'eux, se voyant guéri, revint sur ses pas, glorifiant Dieu à haute voix.",
                "Lc 17,15"),
    "lumiere": ("Que votre lumière luise ainsi devant les hommes, afin qu'ils voient vos bonnes "
                "œuvres, et qu'ils glorifient votre Père qui est dans les cieux.", "Mt 5,16"),

    # Les conflits : ne pas juger, reprendre en frère, pardonner.
    "ne_jugez_point": ("Ne jugez point, afin que vous ne soyez point jugés.", "Mt 7,1"),
    "reprendre_son_frere": ("Si ton frère a péché, va et reprends-le entre toi et lui seul. S'il "
                            "t'écoute, tu as gagné ton frère.", "Mt 18,15"),
    "septante_fois_sept": ("Je ne te dis pas jusqu'à sept fois, mais jusqu'à septante fois sept "
                           "fois.", "Mt 18,22"),

    # L'argent.
    "mammon": ("Nul ne peut servir deux maîtres… Vous ne pouvez servir Dieu et Mammon.", "Mt 6,24"),
    "onzieme_heure": ("Ceux de la onzième heure vinrent, et reçurent chacun un denier… Je veux donner "
                      "à ce dernier autant qu'à toi.", "Mt 20,9.14"),
    "maison_de_trafic": ("Ne faites pas de la maison de mon Père une maison de trafic.", "Jn 2,16"),
    "zachee": ("Voici, Seigneur, je donne aux pauvres la moitié de mes biens.", "Lc 19,8"),

    # L'accueil et la liberté.
    "pas_contre_nous": ("Qui n'est pas contre nous est pour nous.", "Mc 9,40"),
    "vous_en_aller": ("Et vous, ne voulez-vous pas aussi vous en aller ?", "Jn 6,67"),
}

# Paroles proposées chaque jour sur l'accueil et dans « Mon espace ».
PAROLES_DU_JOUR = [
    "gratuitement", "plus_heureux", "commandement", "veuve", "deux_tuniques", "sans_rien_esperer",
    "main_gauche", "demandez", "plus_petits", "fais_de_meme", "deux_ou_trois", "lumiere",
    "septante_fois_sept", "laver_les_pieds", "servir", "festin", "venez_a_moi", "cinq_pains",
]


def passage(key):
    text, ref = PASSAGES[key]
    return {"text": text, "ref": ref}


def parole_du_jour(day=None):
    day = day or date.today()
    return passage(PAROLES_DU_JOUR[day.toordinal() % len(PAROLES_DU_JOUR)])
