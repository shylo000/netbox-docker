"""Tableau de bord global du parc réseau."""
from django.shortcuts import render
from django.views import View

from dcim.models import Cable, Device, Interface, Site


class DashboardView(View):
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
