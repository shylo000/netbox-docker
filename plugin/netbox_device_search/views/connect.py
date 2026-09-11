"""Workflow de connexion d'un équipement à un switch, en plusieurs pages.

  Étape 1 : choisir un site   -> voir ses baies
  Étape 2 : choisir une baie  -> voir ses switchs ayant des ports libres
  Étape 3 : choisir un switch -> panneau de ports -> brancher
"""
import logging

from django.contrib import messages
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.translation import gettext_lazy as _
from django.views import View

from dcim.models import Device, Interface, Rack, Site

from ..constants import CABLE_TYPES, DEFAULT_CABLE_TYPE, UPLINK_DEVICE_ROLE_SLUGS
from ..exceptions import PortAlreadyUsed
from ..services import cabling

logger = logging.getLogger('netbox_device_search.connect')


class DeviceConnectSelectSiteView(View):
    """Étape 1 : sélection du site (les baies se chargent ensuite en AJAX)."""
    template_name = 'netbox_device_search/connect_select_site.html'

    def get(self, request, device_id):
        device = get_object_or_404(Device, id=device_id)
        return render(request, self.template_name, {
            'device': device,
            'sites': Site.objects.all().order_by('name'),
        })


class DeviceConnectSelectSwitchView(View):
    """Étape 2 : sélection d'un switch (avec ports libres) dans une baie."""
    template_name = 'netbox_device_search/connect_select_switch.html'

    def get(self, request, device_id, rack_id):
        device = get_object_or_404(Device, id=device_id)
        rack = get_object_or_404(Rack, id=rack_id)

        switches = Device.objects.filter(rack=rack).annotate(
            free_ports_count=Count('interfaces', filter=Q(interfaces__cable__isnull=True))
        ).filter(free_ports_count__gt=0).order_by('name')

        return render(request, self.template_name, {
            'device': device,
            'rack': rack,
            'switches': switches,
        })


class DeviceConnectSelectPortView(View):
    """Étape 3 : panneau frontal des ports + branchement effectif."""
    template_name = 'netbox_device_search/connect_select_port.html'

    def get(self, request, device_id, switch_id):
        device = get_object_or_404(Device, id=device_id)
        switch = get_object_or_404(Device, id=switch_id)

        ports = Interface.objects.filter(device=switch).select_related('cable').order_by('name')

        ports_data = []
        for port in ports:
            info = {
                'port': port,
                'connected_device_id': None,
                'connected_device_name': None,
                'connected_device_manufacturer': None,
                'connected_device_model': None,
                'connected_device_role': None,
                'connected_port_name': None,
            }
            peer, peer_port = cabling.find_connected_peer(port)
            if peer:
                info['connected_device_id'] = peer.id
                info['connected_device_name'] = peer.name
                if peer.device_type:
                    if peer.device_type.manufacturer:
                        info['connected_device_manufacturer'] = peer.device_type.manufacturer.name
                    info['connected_device_model'] = peer.device_type.model
                if peer.role:
                    info['connected_device_role'] = peer.role.name
                info['connected_port_name'] = peer_port
            ports_data.append(info)

        return render(request, self.template_name, {
            'device': device,
            'switch': switch,
            'ports_data': ports_data,
        })

    def post(self, request, device_id, switch_id):
        device = get_object_or_404(Device, id=device_id)
        switch = get_object_or_404(Device, id=switch_id)

        port_id = request.POST.get('port_id')
        cable_type = request.POST.get('cable_type', DEFAULT_CABLE_TYPE)

        if not port_id:
            messages.error(request, str(_("No port selected.")))
            return redirect('plugins:netbox_device_search:device_connect_port',
                            device_id=device_id, switch_id=switch_id)

        switch_port = get_object_or_404(Interface, id=port_id, device=switch)

        try:
            cabling.connect_device_to_port(device, switch_port, cable_type=cable_type)
        except PortAlreadyUsed as exc:
            messages.error(request, str(exc))
            return redirect('plugins:netbox_device_search:device_connect_port',
                            device_id=device_id, switch_id=switch_id)
        except Exception as exc:
            logger.exception("Échec connexion device %s -> switch %s", device_id, switch_id)
            messages.error(request, str(_("Error: %(error)s")) % {'error': str(exc)})
            return redirect('plugins:netbox_device_search:device_connect_port',
                            device_id=device_id, switch_id=switch_id)

        messages.success(
            request,
            str(_("%(device)s connected to port %(port)s on %(switch)s")) % {
                'device': device.name, 'port': switch_port.name, 'switch': switch.name,
            },
        )
        return redirect('plugins:netbox_device_search:device_detail', device_id=device.id)


class DeviceUpdatePortView(View):
    """[DÉPRÉCIÉ] Ancien système de mise à jour de port en une seule page.

    Conservé pour ne casser aucun lien existant. La logique de câblage passe
    désormais par services.cabling.connect_device_to_port(). À supprimer (avec
    sa route et update_port.html) une fois confirmé qu'aucun template n'y pointe.
    """
    template_name = 'netbox_device_search/update_port.html'

    def get(self, request, device_id):
        device = get_object_or_404(Device, id=device_id)
        first_iface = device.interfaces.first()
        switch, switch_port = cabling.find_connected_peer(first_iface)

        free_ports = Interface.objects.filter(
            cable__isnull=True,
            device__role__slug__in=UPLINK_DEVICE_ROLE_SLUGS,
        ).select_related('device').order_by('device__name', 'name')[:200]

        return render(request, self.template_name, {
            'device': device,
            'switch': switch,
            'switch_port': switch_port,
            'free_ports': free_ports,
            'cable_types': CABLE_TYPES,
            'patching': [],
        })

    def post(self, request, device_id):
        device = get_object_or_404(Device, id=device_id)
        port_id = request.POST.get('switch_port')
        cable_type = request.POST.get('cable_type', DEFAULT_CABLE_TYPE)

        if not port_id:
            messages.error(request, str(_("No port selected.")))
            return redirect('plugins:netbox_device_search:device_update_port', device_id=device_id)

        switch_port = get_object_or_404(Interface, id=port_id)
        try:
            cabling.connect_device_to_port(device, switch_port, cable_type=cable_type)
            messages.success(request, str(_("Connection updated successfully!")))
            return redirect('plugins:netbox_device_search:device_detail', device_id=device.id)
        except PortAlreadyUsed as exc:
            messages.error(request, str(exc))
        except Exception as exc:
            logger.exception("Échec update port device %s", device_id)
            messages.error(request, str(_("Error: %(error)s")) % {'error': str(exc)})
        return redirect('plugins:netbox_device_search:device_update_port', device_id=device_id)
