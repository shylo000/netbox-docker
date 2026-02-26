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
    Retourne un dictionnaire complet avec toutes les infos d'un device.
    Compatible Netbox 4.5 (MACAddress séparé, role au lieu de device_role).
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

    # Récupérer toutes les interfaces avec leurs MACs et IPs
    interfaces = Interface.objects.filter(device=device).prefetch_related(
        'ip_addresses', 'mac_addresses'
    ).select_related('cable', 'primary_mac_address')

    for iface in interfaces:
        info['interfaces'].append(iface)

        # Adresse MAC — Netbox 4.5 : primary_mac_address ou mac_addresses
        if not info['mac_address']:
            try:
                if iface.primary_mac_address:
                    info['mac_address'] = str(iface.primary_mac_address.mac_address)
                else:
                    first_mac = iface.mac_addresses.first()
                    if first_mac:
                        info['mac_address'] = str(first_mac.mac_address)
            except Exception:
                pass

        # Adresse IP
        for ip in iface.ip_addresses.all():
            if not info['ip_address']:
                info['ip_address'] = str(ip.address)

        # Connexion via câble (switch + port)
        if iface.cable:
            cable = iface.cable
            try:
                all_terms = list(cable.a_terminations.all()) + list(cable.b_terminations.all())
                for term in all_terms:
                    if hasattr(term, 'device') and term.device and term.device != device:
                        info['switch'] = term.device
                        info['switch_port'] = term.name
            except Exception:
                pass

            info['patching'].append({
                'cable_label': cable.label or f'Câble #{cable.id}',
                'cable_type': cable.get_type_display() if cable.type else 'N/A',
                'cable_status': 'Actif' if cable.status == 'connected' else 'Inactif',
                'interface': iface.name,
            })

    # IP primaire directement sur le device (plus fiable)
    if not info['ip_address']:
        if device.primary_ip4:
            info['ip_address'] = str(device.primary_ip4.address)
        elif device.primary_ip6:
            info['ip_address'] = str(device.primary_ip6.address)

    return info


def search_devices(query):
    """
    Cherche un device par son nom ou son adresse MAC.
    Compatible Netbox 4.5 avec le modèle MACAddress séparé.
    """
    if not query:
        return Device.objects.none()

    query = query.strip()

    # Recherche par nom
    by_name = Device.objects.filter(name__icontains=query)

    # Recherche par MAC : dans Netbox 4.5, passer par le modèle MACAddress
    mac_query = query.replace(':', '').replace('-', '').replace('.', '').upper()
    by_mac = Device.objects.none()
    
    try:
        from dcim.models import MACAddress
        # Chercher les MACs qui matchent
        matching_macs = MACAddress.objects.filter(
            mac_address__icontains=mac_query
        ).select_related('assigned_object')
        
        # Récupérer les device_ids des interfaces qui ont ces MACs
        device_ids = []
        for mac_obj in matching_macs:
            if mac_obj.assigned_object and hasattr(mac_obj.assigned_object, 'device'):
                if mac_obj.assigned_object.device:
                    device_ids.append(mac_obj.assigned_object.device.id)
        
        if device_ids:
            by_mac = Device.objects.filter(id__in=device_ids)
    except Exception as e:
        # Fallback si MACAddress n'existe pas ou erreur
        pass

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
    """Résultats de la recherche par nom ET/OU MAC."""
    template_name = 'netbox_device_search/results.html'

    def get(self, request):
        name_query = request.GET.get('name', '').strip()
        mac_query = request.GET.get('mac', '').strip()
        devices = []
        not_found = False
        search_error = None

        # ═══════════════════════════════════════════
        # RECHERCHE PAR NOM
        # ═══════════════════════════════════════════
        by_name = Device.objects.none()
        if name_query:
            by_name = Device.objects.filter(name__icontains=name_query)

        # ═══════════════════════════════════════════
        # RECHERCHE PAR MAC - SIMPLIFIÉ POUR NETBOX 4.5
        # ═══════════════════════════════════════════
        by_mac = Device.objects.none()
        if mac_query:
            try:
                from dcim.models import MACAddress
                
                # Étape 1 : Nettoyer la recherche de l'utilisateur
                # Enlever TOUS les séparateurs : : - . espaces
                # Mettre en minuscules (Netbox stocke en lowercase)
                mac_clean = mac_query.replace(':', '').replace('-', '').replace('.', '').replace(' ', '').lower()
                
                if not mac_clean:
                    search_error = "Adresse MAC vide après nettoyage"
                elif len(mac_clean) > 12:
                    search_error = "Adresse MAC trop longue (max 12 caractères hexadécimaux)"
                else:
                    # Étape 2 : Récupérer TOUTES les MACs de Netbox
                    # Note: assigned_object est un GenericForeignKey, pas de select_related possible
                    all_macs = MACAddress.objects.all()
                    
                    device_ids = set()
                    
                    # Étape 3 : Pour chaque MAC dans Netbox
                    for mac_obj in all_macs:
                        # Nettoyer la MAC stockée dans Netbox pareil
                        stored_mac = str(mac_obj.mac_address).replace(':', '').replace('-', '').replace('.', '').replace(' ', '').lower()
                        
                        # Étape 4 : Vérifier si elle COMMENCE par la recherche
                        # Ex: recherche "aa" match "aabbccddeeff"
                        # Ex: recherche "aabb" match "aabbccddeeff"
                        # Ex: recherche "aabbccddeeff" match exact "aabbccddeeff"
                        if stored_mac.startswith(mac_clean):
                            # Étape 5 : Remonter à l'interface puis au device
                            if mac_obj.assigned_object and hasattr(mac_obj.assigned_object, 'device'):
                                if mac_obj.assigned_object.device:
                                    device_ids.add(mac_obj.assigned_object.device.id)
                    
                    # Étape 6 : Récupérer les devices trouvés
                    if device_ids:
                        by_mac = Device.objects.filter(id__in=device_ids)
            
            except ImportError:
                search_error = "Le modèle MACAddress n'existe pas dans cette version de Netbox"
            except Exception as e:
                search_error = f"Erreur recherche MAC: {str(e)}"

        # ═══════════════════════════════════════════
        # FUSIONNER LES RÉSULTATS
        # ═══════════════════════════════════════════
        if name_query or mac_query:
            combined = (by_name | by_mac).distinct().select_related(
                'site', 'role', 'device_type', 'device_type__manufacturer', 'rack'
            )
            devices = [get_device_full_info(d) for d in combined]
            if not devices:
                not_found = True

        context = {
            'name_query': name_query,
            'mac_query': mac_query,
            'devices': devices,
            'not_found': not_found,
            'total': len(devices),
            'search_error': search_error,
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
                role_id=role_id,
                device_type_id=device_type_id,
                serial=serial,
                description=description,
            )
            if rack_id:
                device.rack_id = rack_id
            device.save()

            # Créer l'interface principale
            iface = Interface.objects.create(
                device=device,
                name='eth0',
                type='1000base-t',
            )

            # Dans Netbox 4.5, MAC est un modèle séparé
            if mac_address:
                try:
                    from dcim.models import MACAddress
                    mac_obj = MACAddress.objects.create(
                        mac_address=mac_address,
                        assigned_object=iface,
                    )
                    iface.primary_mac_address = mac_obj
                    iface.save()
                except Exception as e:
                    messages.warning(request, f'MAC non assignée : {str(e)}')

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
            error_msg = str(e)
            if 'unique' in error_msg.lower() or 'duplicate' in error_msg.lower():
                error_msg = f'Un appareil avec ce nom existe déjà sur ce site. Cherchez-le ou utilisez un nom différent.'
            messages.error(request, f'Erreur : {error_msg}')
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