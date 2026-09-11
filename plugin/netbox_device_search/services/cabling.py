"""Logique métier liée au câblage (lecture et création de liens physiques).

Centralise deux comportements qui étaient dupliqués dans 4 vues différentes :
  - trouver l'équipement relié à une interface (find_connected_peer) ;
  - brancher un équipement sur un port de switch (connect_device_to_port).
"""
import logging
from collections import defaultdict

from django.db import transaction
from django.db.models import Count, Prefetch
from django.utils.translation import gettext as _t

from dcim.models import Cable, CableTermination, Device, Interface, Rack

from ..constants import (
    CABLE_STATUS_CONNECTED,
    DEFAULT_CABLE_TYPE,
    DEFAULT_INTERFACE_NAME,
    DEFAULT_INTERFACE_TYPE,
    NON_PATCHABLE_INTERFACE_TYPES,
    UPLINK_DEVICE_ROLE_SLUGS,
)
from ..exceptions import PortAlreadyUsed

logger = logging.getLogger('netbox_device_search.cabling')


def find_connected_peer(interface):
    """Retourne ``(device_distant, nom_du_port_distant)`` relié à ``interface``.

    Retourne ``(None, None)`` si l'interface est absente ou non câblée.
    Remplace la boucle "parcourir les terminaisons du câble" recopiée
    dans DeviceSearchResultsView, DeviceDetailView et DeviceUpdatePortView.
    """
    if interface is None:
        return None, None

    cable = getattr(interface, 'cable', None)
    if not cable:
        return None, None

    for termination in cable.terminations.all():
        peer = getattr(termination, 'device', None)
        if peer and peer.id != interface.device_id:
            return peer, termination.name

    return None, None


def ensure_primary_interface(device):
    """Retourne la première interface de ``device``, en la créant si besoin."""
    iface = device.interfaces.first()
    if iface is None:
        iface = Interface.objects.create(
            device=device,
            name=DEFAULT_INTERFACE_NAME,
            type=DEFAULT_INTERFACE_TYPE,
        )
    return iface


@transaction.atomic
def connect_device_to_port(device, switch_port, *, cable_type=DEFAULT_CABLE_TYPE, label=None):
    """Relie ``device`` au port ``switch_port`` d'un switch.

    - Débranche proprement un éventuel câble existant côté ``device``.
    - Lève :class:`PortAlreadyUsed` si le port cible est déjà occupé.

    Toute l'opération est atomique : en cas d'erreur, rien n'est écrit.
    Retourne le câble créé.
    """
    if switch_port.cable_id:
        raise PortAlreadyUsed(switch_port)

    device_iface = ensure_primary_interface(device)

    # On retire l'ancien câble côté device avant de recâbler (même séquence
    # que le code d'origine, qui était éprouvé).
    if device_iface.cable_id:
        old_cable = device_iface.cable
        device_iface.cable = None
        device_iface.save()
        old_cable.delete()

    cable = Cable(
        type=cable_type,
        status=CABLE_STATUS_CONNECTED,
        label=label or f'{device.name} - {switch_port.device.name}:{switch_port.name}',
    )
    cable.a_terminations = [device_iface]
    cable.b_terminations = [switch_port]
    cable.save()

    logger.info(
        "Câble créé : %s <-> %s:%s",
        device.name, switch_port.device.name, switch_port.name,
    )
    return cable


# ═══════════════════════════════════════════════════════════════════════════
#  Baie choisie  →  switches de la baie  →  ports du switch
# ═══════════════════════════════════════════════════════════════════════════
#
#  Pourquoi ici et pas dans la vue : c'est une règle MÉTIER ("que peut-on
#  brasser pour un équipement posé dans telle baie ?"). Elle doit être
#  testable sans HTTP et réutilisable ailleurs. La vue AJAX ne fait que
#  sérialiser le résultat en JSON.


def _is_free(port):
    """Un port est brassable s'il n'a pas de câble ET n'est pas marqué connecté.

    ``mark_connected`` sert dans NetBox à dire "c'est branché, mais le câble
    n'est pas modélisé". Ignorer ce champ ferait proposer un port déjà occupé
    physiquement — l'erreur qu'on veut justement éviter sur le terrain.
    """
    return port.cable_id is None and not port.mark_connected


def _peer_label(port):
    """Nom de l'équipement branché à l'autre bout du câble de ``port``.

    On lit ``CableTermination._device`` : NetBox dénormalise déjà le device de
    chaque terminaison, donc un simple ``select_related`` suffit. Passer par
    ``port.link_peers`` déclencherait plusieurs requêtes PAR port (N+1).
    """
    if port.cable_id is None:
        return _t("marked as connected") if port.mark_connected else ''
    for termination in port.cable.terminations.all():
        device = termination._device
        if device and device.id != port.device_id:
            return device.name or f'device #{device.id}'
    return _t("cabled")


def _physical_ports(devices):
    """Tous les ports physiques des ``devices``, libres ou non.

    On écarte seulement ce qui n'est PAS un port brassable : interfaces
    logiques (virtual / bridge / LAG) et ports d'administration. Les ports
    occupés sont conservés : l'utilisateur doit les voir grisés, sinon il ne
    comprend pas pourquoi "il manque" des ports sur le switch.

    L'ordre vient du ``Meta.ordering`` d'Interface, qui est un tri *naturel*
    (Gi1/0/2 avant Gi1/0/10, contrairement à un tri alphabétique).
    """
    return (
        Interface.objects
        .filter(device__in=devices, mgmt_only=False)
        .exclude(type__in=NON_PATCHABLE_INTERFACE_TYPES)
        .select_related('device', 'cable')
        .prefetch_related(Prefetch(
            'cable__terminations',
            queryset=CableTermination.objects.select_related('_device'),
        ))
    )


def _switches_of(racks):
    """Switches/routeurs des ``racks``, avec l'état de chacun de leurs ports.

    Deux requêtes principales quel que soit le nombre de switches : une pour
    les équipements, une pour toutes leurs interfaces, regroupées ensuite en
    mémoire. C'est le patron anti-N+1 — la version naïve ferait un
    ``switch.interfaces.all()`` par switch.
    """
    switches = list(
        Device.objects
        .filter(rack__in=racks, role__slug__in=UPLINK_DEVICE_ROLE_SLUGS)
        .select_related('rack')
        .order_by('name')
    )
    if not switches:
        return []

    ports_by_switch = defaultdict(list)
    for port in _physical_ports(switches):
        ports_by_switch[port.device_id].append({
            'id': port.id,
            'name': port.name,
            'free': _is_free(port),
            'occupied_by': '' if _is_free(port) else _peer_label(port),
        })

    result = []
    for switch in switches:
        ports = ports_by_switch.get(switch.id, [])
        result.append({
            'id': switch.id,
            'name': switch.name or f'switch #{switch.id}',
            'rack_id': switch.rack_id,
            'rack_name': switch.rack.name if switch.rack else '',
            # position = U d'installation ; Decimal -> float pour la sérialisation JSON
            'position': float(switch.position) if switch.position is not None else None,
            'total_count': len(ports),
            'free_count': sum(1 for p in ports if p['free']),
            'ports': ports,
        })
    return result


def get_rack_cabling_options(rack):
    """Switches proposés pour un équipement posé dans ``rack``, ports compris.

    Stratégie de repli, du plus proche au plus lointain :
        baie  →  salle (location)  →  site
    Un équipement se brasse au plus près ; mais si la baie ne contient aucun
    switch, mieux vaut proposer la baie voisine que ne rien proposer du tout.
    ``scope`` dit jusqu'où on a dû élargir, pour l'afficher honnêtement.

    Le repli ne se déclenche que s'il n'y a AUCUN switch : un switch plein
    reste affiché (ports grisés), c'est une information utile.
    """
    switches = _switches_of([rack])
    scope = 'rack'

    if not switches and rack.location_id:
        switches = _switches_of(
            Rack.objects.filter(location_id=rack.location_id).exclude(pk=rack.pk)
        )
        if switches:
            scope = 'location'

    if not switches:
        switches = _switches_of(
            Rack.objects.filter(site_id=rack.site_id).exclude(pk=rack.pk)
        )
        scope = 'site' if switches else 'empty'

    return {
        'scope': scope,
        'switches': switches,
        'free_total': sum(s['free_count'] for s in switches),
    }


def free_port_counts_by_rack():
    """``{rack_id: nombre de ports libres}`` pour TOUTES les baies, en 1 requête.

    Sert à annoter la liste des baies du formulaire ("B-1 · 15 ports libres")
    sans partir en N+1 : l'agrégation est faite par PostgreSQL (GROUP BY), pas
    par une boucle Python qui interrogerait la base baie par baie.
    """
    rows = (
        Interface.objects
        .filter(
            device__rack__isnull=False,
            device__role__slug__in=UPLINK_DEVICE_ROLE_SLUGS,
            cable__isnull=True,
            mark_connected=False,
            mgmt_only=False,
        )
        .exclude(type__in=NON_PATCHABLE_INTERFACE_TYPES)
        .values('device__rack_id')
        .annotate(n=Count('id'))
    )
    return {row['device__rack_id']: row['n'] for row in rows}
