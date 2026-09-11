"""Logique métier de création / mise à jour d'équipements.

Le bloc ``transaction.atomic`` de création vivait dans la vue ; il est ici,
réutilisable et testable sans HTTP.
"""
import logging

from django.db import transaction

from dcim.models import Cable, Device, Interface, MACAddress
from ipam.models import IPAddress

from ..constants import (
    CABLE_STATUS_CONNECTED,
    DEFAULT_CABLE_TYPE,
    DEFAULT_INTERFACE_NAME,
    DEFAULT_INTERFACE_TYPE,
    DEVICE_STATUS_DEFAULT,
)

logger = logging.getLogger('netbox_device_search.devices')


@transaction.atomic
def create_device_with_links(*, name, site, role, device_type, rack=None,
                             serial='', description='',
                             mac_address='', ip_address='',
                             switch_port=None, cable_type=DEFAULT_CABLE_TYPE,
                             cable_label=''):
    """Crée un équipement + son interface, et éventuellement MAC, IP et câble.

    Tout est fait dans une seule transaction : si une étape échoue (ex. IP en
    conflit), rien n'est créé — pas de device "orphelin" à moitié configuré.

    Les arguments ``site``, ``role``, ``device_type``, ``rack`` et
    ``switch_port`` sont des **instances** de modèle (ce que fournit un
    ModelChoiceField de formulaire).
    """
    device = Device.objects.create(
        name=name,
        site=site,
        role=role,
        device_type=device_type,
        rack=rack,
        serial=serial or '',
        description=description or '',
        status=DEVICE_STATUS_DEFAULT,
    )

    iface = Interface.objects.create(
        device=device,
        name=DEFAULT_INTERFACE_NAME,
        type=DEFAULT_INTERFACE_TYPE,
    )

    if mac_address:
        mac_obj = MACAddress.objects.create(mac_address=mac_address, assigned_object=iface)
        iface.primary_mac_address = mac_obj
        iface.save()

    if ip_address:
        IPAddress.objects.create(address=ip_address, assigned_object=iface)

    if switch_port:
        cable = Cable(
            type=cable_type,
            status=CABLE_STATUS_CONNECTED,
            label=cable_label or f'{device.name}-{switch_port.device.name}',
        )
        cable.a_terminations = [iface]
        cable.b_terminations = [switch_port]
        cable.save()

    logger.info("Device créé : %s (site=%s)", device.name, getattr(site, 'name', site))
    return device


def update_device_basic(device, *, name, site, role, device_type,
                        rack=None, serial='', description=''):
    """Met à jour les champs de base d'un device existant et le sauvegarde."""
    device.name = name
    device.site = site
    device.role = role
    device.device_type = device_type
    device.rack = rack
    device.serial = serial or ''
    device.description = description or ''
    device.save()
    return device
