from django.shortcuts import render, get_object_or_404, redirect
from django.views.generic import View
from django.contrib import messages
from django.db.models import Q

from dcim.models import Device, Interface, Cable, Site, DeviceRole, DeviceType, Manufacturer, Rack
from ipam.models import IPAddress


# ─────────────────────────────────────────────
# Fonctions utilitaires
# ─────────────────────────────────────────────

def get_free_switch_ports():
    """
    Retourne les ports libres sur n'importe quel device
    (pas de filtre sur le rôle pour éviter les erreurs de lookup).
    """
    return Interface.objects.filter(
        cable__isnull=True,
    ).select_related('device', 'device__role').order_by('device__name', 'name')[:200]


def get_device_full_info(device):
    """
    Retourne un dictionnaire complet avec toutes les infos d'un device :
    IP, MAC, switch, port, patch, rack, série...
    """
    info = {
        'device': device,
        'ip_address': None,
        'mac_address': None,
        'rack': device.rack,
        'serial': device.serial or '—',
        'description': device.description or '—',
        'switch': None,
        'switch_port': None,
        'patching': [],
        'interfaces': [],
    }

    # Récupérer toutes les interfaces
    interfaces = Interface.objects.filter(device=device).prefetch_related(
        'ip_addresses'
    ).select_related('cable')

    for iface in interfaces:
        info['interfaces'].append(iface)

        # Adresse MAC depuis l'interface
        if iface.mac_address and not info['mac_address']:
            info['mac_address'] = str(iface.mac_address)

        # Adresse IP
        for ip in iface.ip_addresses.all():
            if not info['ip_address']:
                info['ip_address'] = str(ip.address)

        # Connexion via câble (switch + port)
        if iface.cable:
            cable = iface.cable
            # Chercher l'autre bout du câble
            try:
                all_terms = list(cable.a_terminations.all()) + list(cable.b_terminations.all())
                for term in all_terms:
                    if hasattr(term, 'device') and term.device and term.device != device:
                        info['switch'] = term.device
                        info['switch_port'] = term.name
            except Exception:
                pass

            # Info patching
            info['patching'].append({
                'cable_label': cable.label or f'Câble #{cable.id}',
                'cable_type': cable.get_type_display() if cable.type else 'N/A',
                'cable_status': 'Actif' if cable.status == 'connected' else 'Inactif',
                'interface': iface.name,
            })

    return info


def search_devices(query):
    """
    Cherche un device par son nom ou son adresse MAC.
    Utilise Q objects pour éviter les erreurs de lookup.
    """
    if not query:
        return Device.objects.none()

    query = query.strip()

    # Recherche par nom
    by_name = Device.objects.filter(name__icontains=query)

    # Recherche par MAC : dans Netbox 4.5, mac_address est une relation séparée
    # On cherche dans MACAddress puis on remonte aux interfaces puis aux devices
    mac_query = query.replace(':', '').replace('-', '').replace('.', '')
    try:
        from dcim.models import MACAddress
        mac_iface_ids = MACAddress.objects.filter(
            mac_address__icontains=mac_query
        ).values_list('assigned_object_id', flat=True)
        by_mac = Device.objects.filter(interfaces__id__in=mac_iface_ids)
    except Exception:
        by_mac = Device.objects.none()

    # Fusionner les résultats
    combined = (by_name | by_mac).distinct().select_related(
        'site', 'role', 'device_type', 'device_type__manufacturer', 'rack'
    )

    return combined


# ─────────────────────────────────────────────
# Vues
# ─────────────────────────────────────────────

class DeviceSearchView(View):
    """Page principale avec le formulaire de recherche."""
    template_name = 'netbox_device_search/search.html'

    def get(self, request):
        return render(request, self.template_name)


class DeviceSearchResultsView(View):
    """Résultats de la recherche par nom ou MAC."""
    template_name = 'netbox_device_search/results.html'

    def get(self, request):
        query = request.GET.get('q', '').strip()
        devices = []
        not_found = False

        if query:
            qs = search_devices(query)
            devices = [get_device_full_info(d) for d in qs]
            if not devices:
                not_found = True

        context = {
            'query': query,
            'devices': devices,
            'not_found': not_found,
            'total': len(devices),
        }
        return render(request, self.template_name, context)


class DeviceDetailView(View):
    """Affiche toutes les informations d'un device."""
    template_name = 'netbox_device_search/detail.html'

    def get(self, request, device_id):
        device = get_object_or_404(Device, id=device_id)
        info = get_device_full_info(device)

        free_ports = get_free_switch_ports()

        context = {
            **info,
            'free_ports': free_ports,
        }
        return render(request, self.template_name, context)


class DeviceCreateView(View):
    """Formulaire pour créer un nouveau device."""
    template_name = 'netbox_device_search/create.html'

    def get(self, request):
        context = {
            'sites': Site.objects.all().order_by('name'),
            'device_roles': DeviceRole.objects.all().order_by('name'),
            'device_types': DeviceType.objects.select_related('manufacturer').order_by('manufacturer__name', 'model'),
            'manufacturers': Manufacturer.objects.all().order_by('name'),
            'racks': Rack.objects.all().order_by('name'),
            'free_ports': get_free_switch_ports(),
            'prefill': request.GET.get('q', ''),
        }
        return render(request, self.template_name, context)

    def post(self, request):
        name = request.POST.get('name', '').strip()
        site_id = request.POST.get('site')
        role_id = request.POST.get('role')
        device_type_id = request.POST.get('device_type')
        rack_id = request.POST.get('rack')
        serial = request.POST.get('serial', '').strip()
        description = request.POST.get('description', '').strip()
        mac_address = request.POST.get('mac_address', '').strip()
        ip_address = request.POST.get('ip_address', '').strip()
        switch_port_id = request.POST.get('switch_port')
        cable_type = request.POST.get('cable_type', 'cat6')
        cable_label = request.POST.get('cable_label', '').strip()

        errors = []
        if not name:
            errors.append("Le nom de l'appareil est obligatoire.")
        if not site_id:
            errors.append("Le site est obligatoire.")
        if not role_id:
            errors.append("Le rôle est obligatoire.")
        if not device_type_id:
            errors.append("Le type de device est obligatoire.")

        if errors:
            context = {
                'errors': errors,
                'form_data': request.POST,
                'sites': Site.objects.all().order_by('name'),
                'device_roles': DeviceRole.objects.all().order_by('name'),
                'device_types': DeviceType.objects.select_related('manufacturer').order_by('manufacturer__name', 'model'),
                'manufacturers': Manufacturer.objects.all().order_by('name'),
                'racks': Rack.objects.all().order_by('name'),
                'free_ports': get_free_switch_ports(),
            }
            return render(request, self.template_name, context)

        try:
            device = Device(
                name=name,
                site_id=site_id,
                device_role_id=role_id,
                device_type_id=device_type_id,
                serial=serial,
                description=description,
            )
            if rack_id:
                device.rack_id = rack_id
            device.save()

            # Créer l'interface principale
            iface_data = {
                'device': device,
                'name': 'eth0',
                'type': '1000base-t',
            }
            if mac_address:
                iface_data['mac_address'] = mac_address
            iface = Interface.objects.create(**iface_data)

            # Assigner une IP si fournie
            if ip_address:
                try:
                    ip_obj, _ = IPAddress.objects.get_or_create(address=ip_address)
                    ip_obj.assigned_object = iface
                    ip_obj.save()
                    device.primary_ip4 = ip_obj
                    device.save()
                except Exception as e:
                    messages.warning(request, f'IP non assignée : {str(e)}')

            # Créer le câblage si un port switch est sélectionné
            if switch_port_id:
                try:
                    switch_port = Interface.objects.get(id=switch_port_id)
                    if switch_port.cable is None:
                        cable = Cable(
                            type=cable_type or 'cat6',
                            label=cable_label or f'{device.name} - {switch_port.device.name}:{switch_port.name}',
                            status='connected',
                        )
                        cable.save()
                        cable.a_terminations.set([iface])
                        cable.b_terminations.set([switch_port])
                        messages.success(request, f'Câblage créé vers {switch_port.device.name}/{switch_port.name}')
                    else:
                        messages.warning(request, f'Port {switch_port.name} déjà occupé. Câblage non créé.')
                except Interface.DoesNotExist:
                    messages.warning(request, 'Port switch introuvable.')

            messages.success(request, f'Appareil {device.name} créé avec succès.')
            return redirect('plugins:netbox_device_search:device_detail', device_id=device.id)

        except Exception as e:
            messages.error(request, f'Erreur : {str(e)}')
            context = {
                'errors': [str(e)],
                'form_data': request.POST,
                'sites': Site.objects.all().order_by('name'),
                'device_roles': DeviceRole.objects.all().order_by('name'),
                'device_types': DeviceType.objects.select_related('manufacturer').order_by('manufacturer__name', 'model'),
                'manufacturers': Manufacturer.objects.all().order_by('name'),
                'racks': Rack.objects.all().order_by('name'),
                'free_ports': get_free_switch_ports(),
            }
            return render(request, self.template_name, context)


class DeviceUpdatePortView(View):
    """Met à jour le port/switch d'un device existant."""
    template_name = 'netbox_device_search/update_port.html'

    def get(self, request, device_id):
        device = get_object_or_404(Device, id=device_id)
        info = get_device_full_info(device)

        context = {
            **info,
            'free_ports': get_free_switch_ports(),
            'cable_types': [
                ('cat5e', 'CAT5e'),
                ('cat6', 'CAT6'),
                ('cat6a', 'CAT6a'),
                ('cat8', 'CAT8'),
                ('smf', 'Fibre mono-mode'),
                ('mmf', 'Fibre multi-mode'),
                ('dac-active', 'DAC Actif'),
                ('dac-passive', 'DAC Passif'),
            ],
        }
        return render(request, self.template_name, context)

    def post(self, request, device_id):
        device = get_object_or_404(Device, id=device_id)
        switch_port_id = request.POST.get('switch_port')
        cable_type = request.POST.get('cable_type', 'cat6')
        cable_label = request.POST.get('cable_label', '').strip()
        force_update = request.POST.get('force_update') == '1'

        if not switch_port_id:
            messages.error(request, 'Veuillez sélectionner un port.')
            return redirect('plugins:netbox_device_search:device_update_port', device_id=device_id)

        try:
            switch_port = Interface.objects.select_related('device').get(id=switch_port_id)
        except Interface.DoesNotExist:
            messages.error(request, 'Port introuvable.')
            return redirect('plugins:netbox_device_search:device_update_port', device_id=device_id)

        # Récupérer ou créer l'interface principale du device
        device_iface = Interface.objects.filter(device=device).first()
        if not device_iface:
            device_iface = Interface.objects.create(
                device=device,
                name='eth0',
                type='1000base-t',
            )

        # Port occupé et pas de force → demander confirmation
        if switch_port.cable and not force_update:
            occupied_by = None
            try:
                all_terms = list(switch_port.cable.a_terminations.all()) + list(switch_port.cable.b_terminations.all())
                for term in all_terms:
                    if hasattr(term, 'device') and term.device and term.device != device:
                        occupied_by = term.device
            except Exception:
                pass

            info = get_device_full_info(device)
            context = {
                **info,
                'free_ports': get_free_switch_ports(),
                'port_occupied': True,
                'occupied_port': switch_port,
                'occupied_by': occupied_by,
                'selected_port_id': switch_port_id,
                'cable_type': cable_type,
                'cable_label': cable_label,
                'cable_types': [
                    ('cat5e', 'CAT5e'), ('cat6', 'CAT6'), ('cat6a', 'CAT6a'),
                    ('cat8', 'CAT8'), ('smf', 'Fibre mono-mode'), ('mmf', 'Fibre multi-mode'),
                    ('dac-active', 'DAC Actif'), ('dac-passive', 'DAC Passif'),
                ],
            }
            return render(request, self.template_name, context)

        # Supprimer l'ancien câble du port cible si occupé
        if switch_port.cable:
            switch_port.cable.delete()
            messages.info(request, f'Ancien câblage sur {switch_port.device.name}/{switch_port.name} supprimé.')

        # Supprimer l'ancien câble du device
        if device_iface.cable:
            device_iface.cable.delete()
            messages.info(request, 'Ancien câblage du device supprimé.')

        # Créer le nouveau câble
        label = cable_label or f'{device.name} - {switch_port.device.name}:{switch_port.name}'
        cable = Cable(
            type=cable_type,
            label=label,
            status='connected',
        )
        cable.save()
        cable.a_terminations.set([device_iface])
        cable.b_terminations.set([switch_port])

        messages.success(request, f'Câblage mis à jour : {device.name} vers {switch_port.device.name}/{switch_port.name}')
        return redirect('plugins:netbox_device_search:device_detail', device_id=device_id)