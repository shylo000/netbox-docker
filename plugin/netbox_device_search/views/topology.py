"""Navigation hiérarchique : Site → Datacenter (Location) → Baie (Rack) → Device.

Vues volontairement minces : toute la logique de requête est dans
services/topology.py (couche métier réutilisable et testable).
"""
from django.shortcuts import get_object_or_404, render
from django.views import View

from dcim.models import Rack, Site

from ..services import topology


class SiteBrowserView(View):
    """Niveau 1 : tous les sites, avec compteurs (datacenters / baies / devices)."""
    template_name = 'netbox_device_search/topology/site_browser.html'

    def get(self, request):
        return render(request, self.template_name, {
            'sites': topology.list_sites_with_counts(),
        })


class SiteDetailView(View):
    """Niveau 2 : un site -> ses datacenters (Locations) avec leurs baies,
    PLUS les baies rattachées directement au site (sans datacenter)."""
    template_name = 'netbox_device_search/topology/site_detail.html'

    def get(self, request, site_id):
        site = get_object_or_404(Site, id=site_id)
        locations, racks_sans_datacenter = topology.get_site_layout(site)
        return render(request, self.template_name, {
            'site': site,
            'locations': locations,
            'racks_sans_datacenter': racks_sans_datacenter,
        })


class RackDetailView(View):
    """Niveau 3 : la baie dessinée en élévation + les équipements non placés.

    La vue reste mince : elle charge la baie et délègue tout le calcul
    (géométrie des blocs, tri racké / non racké, taux d'occupation) au
    service. Le template se contente d'afficher le dictionnaire reçu.
    """
    template_name = 'netbox_device_search/topology/rack_detail.html'

    def get(self, request, rack_id):
        rack = get_object_or_404(Rack.objects.select_related('site', 'location'), id=rack_id)
        return render(request, self.template_name, {
            'rack': rack,
            'elevation': topology.get_rack_elevation(rack),
        })
