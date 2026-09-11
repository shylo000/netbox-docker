"""Vues de détail, création et édition d'un équipement."""
import logging
from collections import defaultdict

from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.translation import gettext_lazy as _
from django.views import View

from dcim.models import (
    Device, DeviceRole, DeviceType, Manufacturer, Rack, Site,
)

from ..constants import DEFAULT_CABLE_TYPE
from ..forms import DeviceEditForm, DeviceQuickCreateForm
from ..services import cabling
from ..services import devices as devices_service

logger = logging.getLogger('netbox_device_search.views')


def _flatten_form_errors(form):
    """Transforme form.errors en liste de chaînes 'Label : message'."""
    result = []
    for field, errs in form.errors.items():
        label = form.fields[field].label if field in form.fields else field
        result.append(f"{label} : {', '.join(errs)}")
    return result


class DeviceDetailView(View):
    """Détail complet d'un device."""
    template_name = 'netbox_device_search/detail.html'

    def get(self, request, device_id):
        device = get_object_or_404(Device, id=device_id)

        interfaces = device.interfaces.all()
        first_iface = interfaces.first()

        ip_address = None
        if first_iface:
            first_ip = first_iface.ip_addresses.first()
            ip_address = first_ip.address if first_ip else None
        mac_address = (
            first_iface.primary_mac_address.mac_address
            if first_iface and first_iface.primary_mac_address else None
        )
        switch, switch_port = cabling.find_connected_peer(first_iface)

        context = {
            'device': device,
            'rack': device.rack,
            'interfaces': interfaces,
            'ip_address': ip_address,
            'mac_address': mac_address,
            'switch': switch,
            'switch_port': switch_port,
            'description': device.description or '—',
            'serial': device.serial or '—',
            # Pour le formulaire d'édition inline
            'sites': Site.objects.all().order_by('name'),
            'device_roles': DeviceRole.objects.all().order_by('name'),
            'device_types': DeviceType.objects.select_related('manufacturer').order_by(
                'manufacturer__name', 'model'),
            'racks': Rack.objects.all().order_by('name'),
        }
        return render(request, self.template_name, context)


class DeviceCreateView(View):
    """Créer un nouveau device. Le template rend lui-même les <select>,
    donc on lui fournit les querysets ; la validation passe par un Form."""
    template_name = 'netbox_device_search/create.html'

    def _form_context(self, **extra):
        """Données des <select> du formulaire.

        Sites et baies sont annotés avec leur nombre de ports libres. On les
        calcule ici, en 2 requêtes au total, plutôt que de laisser le template
        appeler une méthode par ligne (N+1 classique des templates Django).

        Les ports, eux, ne sont PAS envoyés : ils arrivent en AJAX une fois la
        baie choisie. Envoyer les milliers de ports du site à chaque affichage
        du formulaire serait du gâchis, et proposer un port d'une autre baie
        n'aurait aucun sens fonctionnel.
        """
        free_by_rack = cabling.free_port_counts_by_rack()

        racks = list(Rack.objects.select_related('site').order_by('site__name', 'name'))
        free_by_site = defaultdict(int)
        racks_by_site = defaultdict(int)
        for rack in racks:
            # Attribut posé sur l'instance : le template y accède comme à un
            # champ normal ({{ rack.free_port_count }}), sans requête.
            rack.free_port_count = free_by_rack.get(rack.id, 0)
            free_by_site[rack.site_id] += rack.free_port_count
            racks_by_site[rack.site_id] += 1

        sites = list(Site.objects.all().order_by('name'))
        for site in sites:
            site.free_port_count = free_by_site.get(site.id, 0)
            site.rack_count = racks_by_site.get(site.id, 0)

        context = {
            'sites': sites,
            'device_roles': DeviceRole.objects.all().order_by('name'),
            'device_types': DeviceType.objects.select_related('manufacturer').order_by(
                'manufacturer__name', 'model'),
            'manufacturers': Manufacturer.objects.all().order_by('name'),
            'racks': racks,
        }
        context.update(extra)
        return context

    def get(self, request):
        context = self._form_context(
            prefill=request.GET.get('q', '') or request.GET.get('name', ''),
            prefill_site=request.GET.get('site', ''),
            prefill_role=request.GET.get('role', ''),
            prefill_device_type=request.GET.get('device_type', ''),
            errors=[],
        )
        return render(request, self.template_name, context)

    def post(self, request):
        form = DeviceQuickCreateForm(request.POST)
        if not form.is_valid():
            return render(request, self.template_name,
                          self._form_context(errors=_flatten_form_errors(form)))

        cd = form.cleaned_data
        try:
            device = devices_service.create_device_with_links(
                name=cd['name'], site=cd['site'], role=cd['role'],
                device_type=cd['device_type'], rack=cd['rack'],
                serial=cd['serial'], description=cd['description'],
                mac_address=cd['mac_address'], ip_address=cd['ip_address'],
                switch_port=cd['switch_port'],
                cable_type=cd['cable_type'] or DEFAULT_CABLE_TYPE,
                cable_label=cd['cable_label'],
            )
        except Exception as exc:
            # Trace complète dans les logs du conteneur, message lisible à l'écran.
            logger.exception("Échec de la création du device")
            return render(request, self.template_name,
                          self._form_context(errors=[str(exc)]))

        messages.success(
            request,
            str(_("Device %(name)s created successfully!")) % {'name': device.name},
        )
        return redirect('plugins:netbox_device_search:device_detail', device_id=device.id)


class DeviceEditView(View):
    """Édition inline d'un device depuis la vue détail (POST uniquement)."""

    def post(self, request, device_id):
        device = get_object_or_404(Device, id=device_id)
        form = DeviceEditForm(request.POST)

        if not form.is_valid():
            for msg in _flatten_form_errors(form):
                messages.error(request, msg)
            return redirect('plugins:netbox_device_search:device_detail', device_id=device_id)

        cd = form.cleaned_data
        try:
            devices_service.update_device_basic(
                device,
                name=cd['name'], site=cd['site'], role=cd['role'],
                device_type=cd['device_type'], rack=cd['rack'],
                serial=cd['serial'], description=cd['description'],
            )
            messages.success(
                request,
                str(_("Device %(name)s updated successfully!")) % {'name': device.name},
            )
        except Exception as exc:
            logger.exception("Échec de la mise à jour du device %s", device_id)
            messages.error(request, str(_("Error: %(error)s")) % {'error': str(exc)})

        return redirect('plugins:netbox_device_search:device_detail', device_id=device_id)
