"""Requêtes de topologie : Site → Datacenter (Location) → Baie (Rack) → Device.

Rappel du modèle NetBox :
  - une Baie (Rack) appartient TOUJOURS à un Site ;
  - son rattachement à une Location ("datacenter") est OPTIONNEL.
Donc une baie est soit DANS un datacenter, soit directement sous le site.
"""
from django.db.models import Count, Prefetch

from dcim.models import Device, Location, Rack, Site

# ── Constantes d'affichage de l'élévation ───────────────────────────────────
# Hauteur d'un U en pixels dans le rendu HTML. Une seule source de vérité :
# on change ici et tout le dessin (rails, blocs, hauteur totale) suit.
RACK_UNIT_PX = 26

# Repli si la baie n'a pas de hauteur définie en base (cas rare mais possible).
DEFAULT_RACK_U_HEIGHT = 42


def list_sites_with_counts():
    """Tous les sites, avec compteurs de datacenters / baies / équipements.

    ``distinct=True`` est indispensable : sans lui, cumuler plusieurs Count
    sur une même requête gonfle les nombres (effet de produit des JOINs).
    """
    return Site.objects.annotate(
        location_count=Count('locations', distinct=True),
        rack_count=Count('racks', distinct=True),
        device_count=Count('devices', distinct=True),
    ).order_by('name')


def racks_with_device_count():
    """Queryset de base des baies, annotées du nombre d'équipements."""
    return Rack.objects.annotate(
        device_count=Count('devices', distinct=True)
    ).order_by('name')


def get_site_layout(site):
    """Retourne ``(locations, racks_sans_datacenter)`` pour un site.

    - ``locations`` : les datacenters du site, chacun avec ses baies préchargées
      (Prefetch -> pas de N+1 quand le template boucle sur ``location.racks``).
    - ``racks_sans_datacenter`` : baies rattachées au site mais à aucune location.
    """
    racks_qs = racks_with_device_count()

    locations = (
        Location.objects.filter(site=site)
        .annotate(rack_count=Count('racks', distinct=True))
        .prefetch_related(Prefetch('racks', queryset=racks_qs))
        .order_by('name')
    )

    racks_sans_datacenter = racks_qs.filter(site=site, location__isnull=True)

    return locations, racks_sans_datacenter


def get_rack_contents(rack):
    """Équipements d'une baie, du haut (U le plus haut) vers le bas."""
    return (
        Device.objects.filter(rack=rack)
        .select_related('role', 'device_type__manufacturer')
        .order_by('-position')
    )


# ── Élévation de baie ───────────────────────────────────────────────────────

def _css(value):
    """Formate un nombre pour du CSS, avec un POINT décimal.

    Piège réel : en locale française, ``{{ 1092.0 }}`` est rendu par Django
    sous la forme ``1092,0``. Injecté dans un ``style=""``, ça produit du CSS
    invalide et le bloc se colle en haut de la baie. On formate donc la valeur
    ici, côté Python, et le template ne fait plus qu'afficher une chaîne.
    ``:g`` supprime au passage les zéros inutiles (26.0 -> "26", 6.5 -> "6.5").
    """
    return f'{value:g}'


def _pretty(value):
    """Renvoie un int quand le float est rond (21.0 -> 21, 21.5 -> 21.5).

    Purement cosmétique : évite d'afficher « 21,0 U occupés » dans l'interface.
    """
    return int(value) if float(value).is_integer() else float(value)


def _unit_label(position, u_height):
    """Étiquette lisible des U occupés : "U12" ou "U12 → U15".

    Cas particulier des équipements d'un demi-U : ``position + 0.5 - 1`` donne
    un U de fin INFÉRIEUR au U de départ. On n'affiche alors que le U de départ.
    """
    start = _pretty(position)
    end = _pretty(position + u_height - 1)
    return f'U{start}' if end <= start else f'U{start} → U{end}'


def get_rack_elevation(rack, unit_px=RACK_UNIT_PX):
    """Construit tout ce qu'il faut pour DESSINER une baie, prêt pour le template.

    Principe du rendu : la baie est un conteneur en ``position: relative`` de
    hauteur ``u_count * unit_px``. Chaque équipement est un bloc en
    ``position: absolute`` dont on calcule ici le ``top`` et la ``height``.
    Cette approche (plutôt qu'un ``<table>`` avec ``rowspan``) gère nativement
    les demi-U (0.5) et les équipements multi-U, et laisse le template idiot :
    il ne fait qu'afficher des chaînes déjà calculées.

    Deux subtilités du modèle NetBox sont prises en compte :
      - ``desc_units`` : dans une baie « descendante », le U1 est EN HAUT ;
      - ``starting_unit`` : certaines baies ne commencent pas au U1.

    Un équipement est considéré comme *non mis en baie* quand il n'a pas de
    position, ou quand son type fait 0 U (caméra, borne Wi-Fi, PDU vertical…) :
    NetBox l'associe bien à la baie, mais il n'occupe aucun emplacement.
    """
    u_count = rack.u_height or DEFAULT_RACK_U_HEIGHT
    first_u = getattr(rack, 'starting_unit', 1) or 1
    last_u = first_u + u_count - 1

    # Numérotation affichée du HAUT vers le BAS de la baie.
    units = (
        list(range(first_u, last_u + 1)) if rack.desc_units
        else list(range(last_u, first_u - 1, -1))
    )

    faces = {'front': [], 'rear': []}
    unracked = []
    occupied_half_units = set()  # granularité 0.5 U, dédupliquée entre les 2 faces

    for device in get_rack_contents(rack):
        device_u = float(device.device_type.u_height or 0)

        if device.position is None or device_u <= 0:
            unracked.append(device)
            continue

        position = float(device.position)

        # Décalage vertical, en U, entre le HAUT de la baie et le HAUT du bloc.
        if rack.desc_units:
            offset_u = position - first_u
        else:
            offset_u = last_u - position - device_u + 1
        offset_u = max(offset_u, 0)  # garde-fou si la donnée déborde de la baie

        block = {
            'device': device,
            'position': _pretty(position),
            'u_height': _pretty(device_u),
            'label_u': _unit_label(position, device_u),
            'style': f'top:{_css(offset_u * unit_px)}px;height:{_css(device_u * unit_px)}px',
            'compact': device_u < 2,  # 1U ou moins -> texte sur une seule ligne
            'tiny': device_u < 1,     # demi-U -> police réduite pour tenir
        }
        faces['rear' if device.face == 'rear' else 'front'].append(block)

        # Occupation réelle : on marque chaque demi-U couvert. Un équipement en
        # face avant et un autre en face arrière au même U ne comptent qu'une
        # fois — sinon on pourrait dépasser 100 % de remplissage.
        start = int(round(position * 2))
        for half in range(start, start + int(round(device_u * 2))):
            if first_u * 2 <= half < (last_u + 1) * 2:
                occupied_half_units.add(half)

    occupied_u = len(occupied_half_units) / 2
    fill_percent = round(occupied_u / u_count * 100) if u_count else 0
    racked_count = len(faces['front']) + len(faces['rear'])

    return {
        'u_count': u_count,
        'units': units,
        'unit_px': _css(unit_px),
        'unit_band_px': _css(unit_px * 2),   # période des bandes grisées (2 U)
        'body_height': _css(u_count * unit_px),
        'front': faces['front'],
        'rear': faces['rear'],
        'front_count': len(faces['front']),
        'rear_count': len(faces['rear']),
        'unracked': unracked,
        'unracked_count': len(unracked),
        'racked_count': racked_count,
        'total_count': racked_count + len(unracked),
        'occupied_u': _pretty(occupied_u),
        'free_u': _pretty(max(u_count - occupied_u, 0)),
        'fill_percent': fill_percent,
        'fill_style': f'width:{fill_percent}%',
    }
