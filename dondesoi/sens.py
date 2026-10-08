"""Le sens des mots : rapprocher « landau » et « poussette ».

Un petit modèle d'IA open source (paraphrase-multilingual-MiniLM-L12-v2,
licence Apache 2.0) transforme le texte de chaque annonce en un vecteur ;
deux annonces de sens voisin ont des vecteurs proches. Le modèle tourne sur
le serveur lui-même : aucun texte n'est envoyé à un service extérieur.

Il est téléchargé une seule fois (environ 220 Mo) dans MODEL_CACHE. Si la
bibliothèque fastembed n'est pas installée, ou si SEMANTIC_MODEL est vide,
la mise en relation se contente de comparer les mots.
"""
import os

from flask import current_app

_MISSING = object()

# Le titre dit l'essentiel d'une annonce ; une longue description noie le sens
# (« fabriqué par mes soins » rapprochait un lit bébé du bricolage). Le vecteur
# d'une annonce mélange donc titre (poids 2) et texte complet (poids 1).
POIDS_TITRE = 2.0
VERSION_CALCUL = "#titre2"   # à changer si le calcul change : les vecteurs seront refaits


class _FastEmbed:
    def __init__(self, model, cache_dir):
        from fastembed import TextEmbedding   # import tardif : dépendance facultative
        import numpy
        self.np = numpy
        self.name = model + VERSION_CALCUL
        self.model = TextEmbedding(model, cache_dir=cache_dir)

    def embed(self, texts):
        out = []
        for v in self.model.embed(list(texts)):
            v = self.np.asarray(v, dtype="float32")
            out.append(v / (self.np.linalg.norm(v) or 1.0))
        return out


def get_embedder():
    """Le modèle, chargé une fois par processus ; None si indisponible."""
    app = current_app
    embedder = app.extensions.get("embedder", _MISSING)
    if embedder is _MISSING:
        embedder = None
        model = app.config.get("SEMANTIC_MODEL")
        if model:
            try:
                cache = os.path.expanduser(app.config["MODEL_CACHE"])
                embedder = _FastEmbed(model, cache)
            except Exception as e:   # bibliothèque absente, téléchargement impossible…
                app.logger.warning("Sens des mots désactivé : %s", e)
        app.extensions["embedder"] = embedder
    return embedder


def texte_annonce(annonce):
    return f"{annonce['title']}. {annonce['description'] or ''}".strip()


def _vecteurs_annonces(embedder, annonces):
    import numpy as np
    titres = embedder.embed(a["title"] for a in annonces)
    complets = embedder.embed(texte_annonce(a) for a in annonces)
    out = []
    for t, c in zip(titres, complets):
        v = POIDS_TITRE * t + c
        out.append((v / (np.linalg.norm(v) or 1.0)).astype("float32"))
    return out


def vecteurs(db, annonces):
    """{annonce_id: vecteur normalisé} ; calcule et garde ceux qui manquent."""
    embedder = get_embedder()
    if embedder is None or not annonces:
        return {}
    import numpy as np
    ids = [a["id"] for a in annonces]
    rows = db.execute(
        f"SELECT annonce_id, vecteur FROM annonce_vecteurs WHERE modele = ? "
        f"AND annonce_id IN ({','.join('?' * len(ids))})", [embedder.name, *ids],
    ).fetchall()
    found = {r["annonce_id"]: np.frombuffer(r["vecteur"], dtype="float32") for r in rows}
    missing = [a for a in annonces if a["id"] not in found]
    if missing:
        for a, v in zip(missing, _vecteurs_annonces(embedder, missing)):
            found[a["id"]] = v
            db.execute("INSERT OR REPLACE INTO annonce_vecteurs (annonce_id, modele, vecteur) "
                       "VALUES (?, ?, ?)", (a["id"], embedder.name, v.astype("float32").tobytes()))
        db.commit()
    return found


def similarite(v1, v2):
    """Cosinus entre deux vecteurs normalisés (de -1 à 1)."""
    return float((v1 * v2).sum())


def oublier(db, annonce_id):
    """À appeler quand le texte d'une annonce change."""
    db.execute("DELETE FROM annonce_vecteurs WHERE annonce_id = ?", (annonce_id,))
