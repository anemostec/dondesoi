"""Normalisation des textes et des noms de villes, partagée par la mise en relation."""
import re
import unicodedata

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
