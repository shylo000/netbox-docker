"""Petits utilitaires transverses (sans logique métier ni accès HTTP)."""
import re


def make_unique_slug(model_class, name, max_len=50):
    """Génère un slug unique pour `model_class` à partir de `name`.

    Exemple : make_unique_slug(DeviceRole, "Switch Cœur") -> "switch-coeur"
    (puis "switch-coeur-1", "-2"… si déjà pris).
    """
    base = re.sub(r'[^a-z0-9]+', '-', name.lower()).strip('-')[:max_len]
    slug = base
    counter = 1
    while model_class.objects.filter(slug=slug).exists():
        slug = f'{base}-{counter}'
        counter += 1
    return slug
