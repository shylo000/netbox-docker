"""Vues de recherche d'équipements (par nom ou adresse MAC)."""
from django.shortcuts import render
from django.views import View

from dcim.models import Device

from ..services import cabling


class DeviceSearchView(View):
    """Page de recherche principale (formulaire)."""
    template_name = 'netbox_device_search/search.html'

    def get(self, request):
        return render(request, self.template_name)


class DeviceSearchResultsView(View):
    """Résultats de recherche par nom ou MAC."""
    template_name = 'netbox_device_search/results.html'

    def get(self, request):
        name_query = request.GET.get('name', '').strip()
        mac_query = request.GET.get('mac', '').strip()

        if not name_query and not mac_query:
            return render(request, self.template_name, {
                'devices': [], 'total': 0,
                'name_query': name_query, 'mac_query': mac_query,
            })

        # select_related / prefetch_related : on précharge ce que la boucle
        # va lire -> on évite le N+1 (≈ 4 requêtes par device sans ça).
        base_qs = Device.objects.select_related(
            'rack', 'site', 'role', 'device_type__manufacturer',
        ).prefetch_related('interfaces__ip_addresses')

        if name_query:
            devices_found = base_qs.filter(name__icontains=name_query)
        else:
            devices_found = base_qs.filter(
                interfaces__mac_addresses__mac_address__icontains=mac_query
            ).distinct()

        if not devices_found.exists():
            return render(request, self.template_name, {
                'not_found': True,
                'name_query': name_query, 'mac_query': mac_query,
            })

        devices = []
        for device in devices_found:
            iface = device.interfaces.first()
            ip_address = None
            if iface:
                first_ip = iface.ip_addresses.first()
                ip_address = first_ip.address if first_ip else None
            mac_address = (
                iface.primary_mac_address.mac_address
                if iface and iface.primary_mac_address else None
            )
            switch, switch_port = cabling.find_connected_peer(iface)

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
