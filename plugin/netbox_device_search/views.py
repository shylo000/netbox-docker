# views.py - VERSION i18n (EN/FR)
from django.shortcuts import render, redirect, get_object_or_404
from django.views import View
from django.contrib import messages
from django.http import JsonResponse, HttpResponseRedirect
from django.db.models import Q, Count
from django.db import transaction
from django.utils.translation import gettext_lazy as _
from django.utils import translation
from django.conf import settings

from dcim.models import Device, Interface, Site, Rack, Cable, DeviceRole, DeviceType, Manufacturer, MACAddress
from ipam.models import IPAddress


def switch_language(request):
    """Bascule la langue de l'interface (EN/FR) via cookie Django."""
    lang = request.POST.get('language') or request.GET.get('lang', 'fr')
    if lang not in ['fr', 'en']:
        lang = 'fr'

    next_url = request.POST.get('next') or request.META.get('HTTP_REFERER', '/')
    # Sécurité : s'assurer que next_url est une URL relative (pas une redirection externe)
    if next_url and not next_url.startswith('/'):
        next_url = '/'

    translation.activate(lang)
    response = HttpResponseRedirect(next_url or '/')
    response.set_cookie(
        settings.LANGUAGE_COOKIE_NAME,
        lang,
        max_age=getattr(settings, 'LANGUAGE_COOKIE_AGE', 365 * 24 * 3600),
        path=getattr(settings, 'LANGUAGE_COOKIE_PATH', '/'),
        domain=getattr(settings, 'LANGUAGE_COOKIE_DOMAIN', None),
        samesite=getattr(settings, 'LANGUAGE_COOKIE_SAMESITE', 'Lax'),
    )
    return response


class DeviceSearchView(View):
    """Page de recherche principale"""
    template_name = 'netbox_device_search/search.html'

    def get(self, request):
        return render(request, self.template_name)


class DeviceSearchResultsView(View):
    """Résultats de recherche par nom ou MAC"""
    template_name = 'netbox_device_search/results.html'

    def get(self, request):
        name_query = request.GET.get('name', '').strip()
        mac_query = request.GET.get('mac', '').strip()

        if not name_query and not mac_query:
            return render(request, self.template_name, {
                'devices': [],
                'total': 0,
                'name_query': name_query,
                'mac_query': mac_query,
            })

        devices = []

        if name_query:
            devices_found = Device.objects.filter(name__icontains=name_query)
        elif mac_query:
            devices_found = Device.objects.filter(
                interfaces__mac_addresses__mac_address__icontains=mac_query
            ).distinct()
        else:
            devices_found = Device.objects.none()

        if not devices_found.exists():
            return render(request, self.template_name, {
                'not_found': True,
                'name_query': name_query,
                'mac_query': mac_query,
            })

        for device in devices_found:
            iface = device.interfaces.first()
            ip_address = iface.ip_addresses.first().address if iface and iface.ip_addresses.exists() else None
            mac_address = iface.primary_mac_address.mac_address if iface and iface.primary_mac_address else None

            switch = None
            switch_port = None
            if iface and iface.cable:
                for term in iface.cable.terminations.all():
                    if hasattr(term, 'device') and term.device and term.device.id != device.id:
                        switch = term.device
                        switch_port = term.name
                        break

            devices.append({
                'device': device,
                'ip_address': ip_address,
                'mac_address': mac_address,
                'rack': device.rack,
                'switch': switch,
                'switch_port': switch_port,
                'serial': device.serial or '—',
            })

        return render(request, self.template_name, {
            'devices': devices,
            'total': len(devices),
            'name_query': name_query,
            'mac_query': mac_query,
        })


class DeviceDetailView(View):
    """Détail complet d'un device"""
    template_name = 'netbox_device_search/detail.html'

    def get(self, request, device_id):
        device = get_object_or_404(Device, id=device_id)

        interfaces = device.interfaces.all()
        first_iface = interfaces.first()
        ip_address = first_iface.ip_addresses.first().address if first_iface and first_iface.ip_addresses.exists() else None
        mac_address = first_iface.primary_mac_address.mac_address if first_iface and first_iface.primary_mac_address else None

        switch = None
        switch_port = None
        if first_iface and first_iface.cable:
            for term in first_iface.cable.terminations.all():
                if hasattr(term, 'device') and term.device and term.device.id != device.id:
                    switch = term.device
                    switch_port = term.name
                    break

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
        }

        return render(request, self.template_name, context)


class DeviceCreateView(View):
    """Créer un nouveau device"""
    template_name = 'netbox_device_search/create.html'

    def get(self, request):
        context = {
            'sites': Site.objects.all().order_by('name'),
            'device_roles': DeviceRole.objects.all().order_by('name'),
            'device_types': DeviceType.objects.select_related('manufacturer').all().order_by('manufacturer__name', 'model'),
            'racks': Rack.objects.all().order_by('name'),
            'free_ports': Interface.objects.filter(cable__isnull=True, device__role__slug__in=['switch', 'router']).select_related('device')[:100],
            'prefill': request.GET.get('q', ''),
            'errors': [],
        }
        return render(request, self.template_name, context)

    def post(self, request):
        errors = []

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

        # Validation — chaînes traduites
        if not name:
            errors.append(str(_("Name is required")))
        if not site_id:
            errors.append(str(_("Site is required")))
        if not role_id:
            errors.append(str(_("Role is required")))
        if not device_type_id:
            errors.append(str(_("Device type is required")))

        if errors:
            context = {
                'sites': Site.objects.all(),
                'device_roles': DeviceRole.objects.all(),
                'device_types': DeviceType.objects.all(),
                'racks': Rack.objects.all(),
                'free_ports': Interface.objects.filter(cable__isnull=True),
                'errors': errors,
            }
            return render(request, self.template_name, context)

        try:
            with transaction.atomic():
                device = Device.objects.create(
                    name=name,
                    site_id=site_id,
                    role_id=role_id,
                    device_type_id=device_type_id,
                    rack_id=rack_id if rack_id else None,
                    serial=serial if serial else '',
                    description=description if description else '',
                    status='active',
                )

                iface = Interface.objects.create(
                    device=device,
                    name='eth0',
                    type='1000base-t',
                )

                if mac_address:
                    mac_obj = MACAddress.objects.create(
                        mac_address=mac_address,
                        assigned_object=iface,
                    )
                    iface.primary_mac_address = mac_obj
                    iface.save()

                if ip_address:
                    IPAddress.objects.create(
                        address=ip_address,
                        assigned_object=iface,
                    )

                if switch_port_id:
                    switch_port = Interface.objects.get(id=switch_port_id)
                    cable = Cable(
                        type=cable_type,
                        label=cable_label if cable_label else f'{device.name}-{switch_port.device.name}',
                        status='connected',
                    )
                    cable.a_terminations = [iface]
                    cable.b_terminations = [switch_port]
                    cable.save()

            messages.success(request, str(_("Device %(name)s created successfully!")) % {'name': device.name})
            return redirect('plugins:netbox_device_search:device_detail', device_id=device.id)

        except Exception as e:
            messages.error(request, str(_("Error during creation: %(error)s")) % {'error': str(e)})
            context = {
                'sites': Site.objects.all(),
                'device_roles': DeviceRole.objects.all(),
                'device_types': DeviceType.objects.all(),
                'racks': Rack.objects.all(),
                'free_ports': Interface.objects.filter(cable__isnull=True),
                'errors': [str(e)],
            }
            return render(request, self.template_name, context)


class DeviceConnectSelectSiteView(View):
    """PAGE 2 : Sélection Site → Baies"""
    template_name = 'netbox_device_search/connect_select_site.html'

    def get(self, request, device_id):
        device = get_object_or_404(Device, id=device_id)
        sites = Site.objects.all().order_by('name')
        return render(request, self.template_name, {
            'device': device,
            'sites': sites,
        })


class DeviceConnectSelectSwitchView(View):
    """PAGE 3 : Sélection Switch dans une baie"""
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
    """PAGE 4 : Sélection Port avec panneau frontal"""
    template_name = 'netbox_device_search/connect_select_port.html'

    def get(self, request, device_id, switch_id):
        device = get_object_or_404(Device, id=device_id)
        switch = get_object_or_404(Device, id=switch_id)

        ports = Interface.objects.filter(device=switch).select_related('cable').order_by('name')

        ports_data = []
        for port in ports:
            port_info = {
                'port': port,
                'connected_device_id': None,
                'connected_device_name': None,
                'connected_device_manufacturer': None,
                'connected_device_model': None,
                'connected_device_role': None,
                'connected_port_name': None,
            }

            if port.cable:
                try:
                    all_terminations = list(port.cable.terminations.all())
                    for termination in all_terminations:
                        if termination.id != port.id:
                            if hasattr(termination, 'device') and termination.device:
                                connected_dev = termination.device
                                port_info['connected_device_id'] = connected_dev.id
                                port_info['connected_device_name'] = connected_dev.name
                                if connected_dev.device_type:
                                    if connected_dev.device_type.manufacturer:
                                        port_info['connected_device_manufacturer'] = connected_dev.device_type.manufacturer.name
                                    port_info['connected_device_model'] = connected_dev.device_type.model
                                if connected_dev.role:
                                    port_info['connected_device_role'] = connected_dev.role.name
                                port_info['connected_port_name'] = termination.name
                                break
                except Exception as e:
                    print(f"Erreur récupération device connecté pour port {port.name}: {str(e)}")

            ports_data.append(port_info)

        return render(request, self.template_name, {
            'device': device,
            'switch': switch,
            'ports_data': ports_data,
        })

    def post(self, request, device_id, switch_id):
        device = get_object_or_404(Device, id=device_id)
        switch = get_object_or_404(Device, id=switch_id)

        port_id = request.POST.get('port_id')
        cable_type = request.POST.get('cable_type', 'cat6')

        if not port_id:
            messages.error(request, str(_("No port selected.")))
            return redirect('plugins:netbox_device_search:device_connect_port',
                            device_id=device_id, switch_id=switch_id)

        try:
            switch_port = Interface.objects.get(id=port_id, device=switch)

            if switch_port.cable:
                messages.error(request, str(_("Port %(port)s is already in use.")) % {'port': switch_port.name})
                return redirect('plugins:netbox_device_search:device_connect_port',
                                device_id=device_id, switch_id=switch_id)

            device_iface = Interface.objects.filter(device=device).first()
            if not device_iface:
                device_iface = Interface.objects.create(
                    device=device,
                    name='eth0',
                    type='1000base-t',
                )

            if device_iface.cable:
                old_cable = device_iface.cable
                device_iface.cable = None
                device_iface.save()
                old_cable.delete()

            cable = Cable(
                type=cable_type,
                label=f'{device.name} - {switch.name}:{switch_port.name}',
                status='connected',
            )
            cable.a_terminations = [device_iface]
            cable.b_terminations = [switch_port]
            cable.save()

            messages.success(request,
                str(_("%(device)s connected to port %(port)s on %(switch)s")) % {
                    'device': device.name,
                    'port': switch_port.name,
                    'switch': switch.name,
                })
            return redirect('plugins:netbox_device_search:device_detail', device_id=device.id)

        except Interface.DoesNotExist:
            messages.error(request, str(_("Port not found.")))
            return redirect('plugins:netbox_device_search:device_connect_port',
                            device_id=device_id, switch_id=switch_id)
        except Exception as e:
            messages.error(request, str(_("Error: %(error)s")) % {'error': str(e)})
            return redirect('plugins:netbox_device_search:device_connect_port',
                            device_id=device_id, switch_id=switch_id)


class DeviceUpdatePortView(View):
    """Ancien système de mise à jour port"""
    template_name = 'netbox_device_search/update_port.html'

    def get(self, request, device_id):
        device = get_object_or_404(Device, id=device_id)

        first_iface = device.interfaces.first()
        switch = None
        switch_port = None

        if first_iface and first_iface.cable:
            for term in first_iface.cable.terminations.all():
                if hasattr(term, 'device') and term.device and term.device.id != device.id:
                    switch = term.device
                    switch_port = term.name
                    break

        free_ports = Interface.objects.filter(
            cable__isnull=True,
            device__role__slug__in=['switch', 'router']
        ).select_related('device').order_by('device__name', 'name')[:200]

        cable_types = [
            ('cat6', 'CAT6'),
            ('cat5e', 'CAT5e'),
            ('cat6a', 'CAT6a'),
            ('cat8', 'CAT8'),
            ('smf', str(_('Single-mode fiber'))),
            ('mmf', str(_('Multi-mode fiber'))),
        ]

        return render(request, self.template_name, {
            'device': device,
            'switch': switch,
            'switch_port': switch_port,
            'free_ports': free_ports,
            'cable_types': cable_types,
            'patching': [],
        })

    def post(self, request, device_id):
        device = get_object_or_404(Device, id=device_id)

        port_id = request.POST.get('switch_port')
        cable_type = request.POST.get('cable_type', 'cat6')

        if not port_id:
            messages.error(request, str(_("No port selected.")))
            return redirect('plugins:netbox_device_search:device_update_port', device_id=device_id)

        try:
            switch_port = Interface.objects.get(id=port_id)

            if switch_port.cable:
                messages.error(request,
                    str(_("Port %(port)s on %(device)s is already in use.")) % {
                        'port': switch_port.name,
                        'device': switch_port.device.name,
                    })
                return redirect('plugins:netbox_device_search:device_update_port', device_id=device_id)

            device_iface = device.interfaces.first()
            if not device_iface:
                device_iface = Interface.objects.create(
                    device=device,
                    name='eth0',
                    type='1000base-t',
                )

            if device_iface.cable:
                old_cable = device_iface.cable
                device_iface.cable = None
                device_iface.save()
                old_cable.delete()

            cable = Cable(
                type=cable_type,
                label=f'{device.name} - {switch_port.device.name}',
                status='connected',
            )
            cable.a_terminations = [device_iface]
            cable.b_terminations = [switch_port]
            cable.save()

            messages.success(request, str(_("Connection updated successfully!")))
            return redirect('plugins:netbox_device_search:device_detail', device_id=device.id)

        except Exception as e:
            messages.error(request, str(_("Error: %(error)s")) % {'error': str(e)})
            return redirect('plugins:netbox_device_search:device_update_port', device_id=device_id)


class DashboardView(View):
    """Dashboard global du parc réseau"""
    template_name = 'netbox_device_search/dashboard.html'

    def get(self, request):
        total_devices = Device.objects.count()
        active_devices = Device.objects.filter(status='active').count()
        failed_devices = Device.objects.filter(status='failed').count()
        other_devices = total_devices - active_devices - failed_devices

        devices_without_ip = Device.objects.filter(
            status='active'
        ).exclude(
            interfaces__ip_addresses__isnull=False
        ).distinct().count()

        total_free_ports = Interface.objects.filter(cable__isnull=True).count()

        sites_stats = []
        for site in Site.objects.order_by('name'):
            free = Interface.objects.filter(device__site=site, cable__isnull=True).count()
            total = Interface.objects.filter(device__site=site).count()
            used = total - free
            sites_stats.append({
                'site': site,
                'free_ports': free,
                'used_ports': used,
                'total_ports': total,
                'percent_used': round((used / total * 100) if total else 0),
            })

        recent_cables = []
        for cable in Cable.objects.order_by('-last_updated')[:10]:
            a_terms = list(cable.a_terminations) if cable.a_terminations else []
            b_terms = list(cable.b_terminations) if cable.b_terminations else []
            device_a = a_terms[0].device if a_terms and hasattr(a_terms[0], 'device') else None
            device_b = b_terms[0].device if b_terms and hasattr(b_terms[0], 'device') else None
            recent_cables.append({
                'cable': cable,
                'device_a': device_a,
                'port_a': a_terms[0].name if a_terms else '—',
                'device_b': device_b,
                'port_b': b_terms[0].name if b_terms else '—',
            })

        recent_devices = Device.objects.order_by('-created').select_related(
            'site', 'rack', 'role', 'device_type__manufacturer'
        )[:8]

        context = {
            'total_devices': total_devices,
            'active_devices': active_devices,
            'failed_devices': failed_devices,
            'other_devices': other_devices,
            'devices_without_ip': devices_without_ip,
            'total_free_ports': total_free_ports,
            'sites_stats': sites_stats,
            'recent_cables': recent_cables,
            'recent_devices': recent_devices,
        }
        return render(request, self.template_name, context)


def get_racks_by_site(request, site_id):
    """API AJAX : Baies d'un site"""
    try:
        site = Site.objects.get(id=site_id)

        racks = Rack.objects.filter(site=site).annotate(
            device_count=Count('devices')
        ).order_by('name')

        racks_data = []
        for rack in racks:
            switches_with_free_ports = Device.objects.filter(rack=rack).annotate(
                free_ports_count=Count('interfaces', filter=Q(interfaces__cable__isnull=True))
            ).filter(free_ports_count__gt=0).count()

            racks_data.append({
                'id': rack.id,
                'name': rack.name,
                'device_count': rack.device_count,
                'switches_with_free_ports': switches_with_free_ports,
                'description': rack.description or '',
            })

        return JsonResponse({
            'success': True,
            'site_name': site.name,
            'racks': racks_data,
        })

    except Site.DoesNotExist:
        return JsonResponse({
            'success': False,
            'error': str(_("Site not found"))
        }, status=404)
    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': str(e)
        }, status=500)
