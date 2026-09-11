"""Plan d'usine interactif : positionnement des baies sur un plan 2D.

─── Pourquoi cette couche existe ────────────────────────────────────────────
NetBox sait où est une baie *logiquement* (Site → Location → Rack), mais pas
où elle est *physiquement* dans le bâtiment. Un technicien qui lit "Rack B12,
Location Production" doit encore deviner de quel côté de l'usine marcher.

On comble ce trou sans créer de modèle : on stocke la position dans les
**Custom Fields** natifs de NetBox, accrochés au modèle Rack. Le plugin reste
donc "vue + workflow" (cf. docstring de __init__.py) — aucune migration, aucune
table propre, et l'équipe IT peut corriger une position depuis l'UI NetBox
standard sans passer par le code.

─── Pourquoi des pourcentages et pas des pixels ─────────────────────────────
Les coordonnées sont stockées en % (0–100) de la largeur/hauteur du plan, pas
en pixels. Conséquence : on peut remplacer l'image du plan par un export plus
grand ou plus propre sans invalider une seule position déjà saisie. Stocker des
pixels aurait couplé les données à une résolution d'image — dette technique
garantie le jour où quelqu'un ré-exporte le DWG.
"""
from django.conf import settings
from django.db import transaction
from django.db.models import Count

from dcim.models import Rack

# ── Noms des Custom Fields NetBox (source de vérité unique) ─────────────────
CF_PLAN = 'plan_niveau'   # sur quel plan la baie est posée (slug)
CF_X = 'plan_x'           # abscisse en % de la largeur du plan
CF_Y = 'plan_y'           # ordonnée en % de la hauteur du plan

# Plan servi par défaut si PLUGINS_CONFIG n'en déclare aucun.
DEFAULT_FLOORPLANS = [
    {
        'slug': 'usine-rdc',
        'label': 'Usine — Plan de masse',
        'image': 'netbox_device_search/img/site_clarebout.jpg',
    },
]


# ═══════════════════════════════════════════════════════════════════════════
#  Configuration des plans
# ═══════════════════════════════════════════════════════════════════════════

def get_floorplans():
    """Liste des plans disponibles, lue depuis PLUGINS_CONFIG.

    Déclarer les plans en configuration plutôt qu'en dur permet de livrer
    l'image réelle de l'usine par un volume monté, sans la versionner dans Git
    ni la figer dans l'image Docker (un plan de site industriel est une donnée
    sensible : il cartographie les accès physiques).

    Exemple dans configuration/plugins.py ::

        PLUGINS_CONFIG = {
            'netbox_device_search': {
                'floorplans': [
                    {'slug': 'usine-rdc',
                     'label': 'Usine — RDC',
                     'image_url': '/media/plans/usine_rdc.png'},
                ],
            }
        }
    """
    conf = settings.PLUGINS_CONFIG.get('netbox_device_search', {})
    return conf.get('floorplans') or DEFAULT_FLOORPLANS


def get_floorplan(slug=None):
    """Retourne un plan par son slug, ou le premier déclaré si slug est None.

    Ne lève jamais : un slug inconnu (plan retiré de la config alors que des
    baies y référaient encore) retombe sur le premier plan plutôt que de
    casser la page.
    """
    plans = get_floorplans()
    if slug:
        for plan in plans:
            if plan['slug'] == slug:
                return plan
    return plans[0]


def get_plan_choices():
    """Couples (slug, label) — utilisé pour peupler le sélecteur de plan."""
    return [(p['slug'], p.get('label', p['slug'])) for p in get_floorplans()]


# ═══════════════════════════════════════════════════════════════════════════
#  Lecture des positions
# ═══════════════════════════════════════════════════════════════════════════

def _base_rack_queryset(site=None):
    """Baies annotées du nombre d'équipements, avec leurs FK préchargées.

    ``distinct=True`` sur le Count : sans lui, un JOIN multiple gonflerait le
    compteur (même piège que dans services/topology.py).

    Attention : on précharge ``site`` et ``location`` (de vraies ForeignKey)
    mais surtout PAS ``status``. Dans NetBox, ``Rack.status`` est un CharField
    à choix, pas une relation — le passer à select_related lève un FieldError
    au premier appel. Piège classique : "status" a l'air d'un objet parce que
    ``get_status_display()`` existe, mais c'est juste du sucre Django.
    """
    qs = (
        Rack.objects
        .select_related('site', 'location')
        .annotate(device_count=Count('devices', distinct=True))
        .order_by('name')
    )
    if site is not None:
        qs = qs.filter(site=site)
    return qs


def _read_coord(rack, field):
    """Lit une coordonnée du JSONField custom_field_data et la rend en float.

    Les Custom Fields NetBox de type "decimal" transitent dans un JSONField :
    selon qu'ils ont été écrits par l'UI, l'API REST ou l'ORM, on peut y
    retrouver un float, une string ou un Decimal. On normalise ici une bonne
    fois pour toutes, plutôt que de laisser le template s'en dépatouiller.
    """
    raw = (rack.custom_field_data or {}).get(field)
    if raw is None or raw == '':
        return None
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None


def get_placed_racks(plan_slug, site=None):
    """Baies positionnées sur ce plan, prêtes à être dessinées.

    Le filtrage se fait en Python et non en SQL : interroger un JSONField
    imbriqué reste possible (``custom_field_data__plan_x__isnull=False``) mais
    devient illisible et non indexé. Le parc de Clarebout se compte en dizaines
    de baies, pas en millions de lignes — la lisibilité prime ici.
    """
    placed = []
    for rack in _base_rack_queryset(site):
        data = rack.custom_field_data or {}
        if data.get(CF_PLAN) != plan_slug:
            continue
        x, y = _read_coord(rack, CF_X), _read_coord(rack, CF_Y)
        if x is None or y is None:
            continue
        placed.append({
            'id': rack.id,
            'name': rack.name,
            'x': x,
            'y': y,
            'site': rack.site.name if rack.site else '',
            'location': rack.location.name if rack.location else '',
            'device_count': rack.device_count,
            'status': rack.get_status_display(),
            'status_value': rack.status,
        })
    return placed


def get_unplaced_racks(plan_slug, site=None):
    """Baies pas encore posées sur CE plan (jamais placées, ou sur un autre).

    C'est le vivier du mode placement : la liste de gauche dans laquelle on
    pioche la baie à poser.
    """
    unplaced = []
    for rack in _base_rack_queryset(site):
        data = rack.custom_field_data or {}
        if data.get(CF_PLAN) == plan_slug and _read_coord(rack, CF_X) is not None:
            continue
        unplaced.append({
            'id': rack.id,
            'name': rack.name,
            'site': rack.site.name if rack.site else '',
            'location': rack.location.name if rack.location else '',
            'device_count': rack.device_count,
            'other_plan': data.get(CF_PLAN) or None,
        })
    return unplaced


# ═══════════════════════════════════════════════════════════════════════════
#  Écriture des positions
# ═══════════════════════════════════════════════════════════════════════════

def _clamp_percent(value):
    """Contraint une valeur dans [0, 100] et l'arrondit à 2 décimales.

    Défense en profondeur : le JS envoie déjà des valeurs propres, mais
    l'endpoint est une URL HTTP que n'importe qui d'authentifié peut appeler
    à la main. Ne jamais faire confiance à une donnée qui vient du client —
    même quand c'est notre propre JS qui l'a produite.
    """
    try:
        number = float(value)
    except (TypeError, ValueError):
        raise ValueError('coordonnée non numérique')
    return round(min(100.0, max(0.0, number)), 2)


@transaction.atomic
def save_rack_position(rack, plan_slug, x, y):
    """Enregistre la position d'une baie sur un plan.

    Deux points non évidents :

    1. ``snapshot()`` avant ``save()`` — c'est le mécanisme de journalisation
       de NetBox. Il fige l'état "avant" de l'objet pour que le ChangeLog
       affiche un vrai diff. Sans lui, la modification apparaît dans l'historique
       sans valeur précédente : on perd la traçabilité, et sur un parc partagé
       c'est exactement ce qu'on veut pouvoir auditer.

    2. On **réassigne** le dictionnaire au lieu de le muter en place. Django ne
       détecte pas toujours la mutation interne d'un JSONField ; réassigner rend
       la modification explicite et le save fiable. Piège classique des
       JSONField, qui produit des "ça ne s'enregistre pas" inexplicables.
    """
    x, y = _clamp_percent(x), _clamp_percent(y)

    valid_slugs = {p['slug'] for p in get_floorplans()}
    if plan_slug not in valid_slugs:
        raise ValueError(f'plan inconnu : {plan_slug}')

    rack.snapshot()

    data = dict(rack.custom_field_data or {})
    data[CF_PLAN] = plan_slug
    data[CF_X] = x
    data[CF_Y] = y
    rack.custom_field_data = data
    rack.save()

    return {'id': rack.id, 'name': rack.name, 'x': x, 'y': y, 'plan': plan_slug}


@transaction.atomic
def clear_rack_position(rack):
    """Retire une baie du plan (les trois custom fields repassent à None).

    On met à None plutôt que de supprimer les clés : NetBox attend que chaque
    custom field déclaré existe dans le JSON, et un dict amputé produit des
    incohérences dans l'UI de détail du Rack.
    """
    rack.snapshot()

    data = dict(rack.custom_field_data or {})
    for field in (CF_PLAN, CF_X, CF_Y):
        data[field] = None
    rack.custom_field_data = data
    rack.save()

    return {'id': rack.id, 'name': rack.name}
