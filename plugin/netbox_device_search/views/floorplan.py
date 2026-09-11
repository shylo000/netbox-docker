"""Vues du plan d'usine interactif.

Une vue de lecture (afficher le plan et ses baies cliquables) et deux endpoints
AJAX d'écriture (poser / retirer une baie).

─── Note sécurité, à ne pas survoler ────────────────────────────────────────
Les ``permissions`` déclarées dans navigation.py ne masquent qu'une entrée de
menu. Elles ne protègent RIEN : l'URL reste appelable directement en curl par
n'importe quel utilisateur authentifié. Toute vérification de droit réelle doit
donc être faite ici, côté serveur. C'est l'erreur de débutant la plus commune
sur les plugins NetBox — cacher le bouton et croire la porte fermée.

On applique donc deux niveaux :
  - ``LoginRequiredMixin``  → il faut être connecté ;
  - ``PermissionRequiredMixin`` → il faut le droit dcim.change_rack pour écrire,
    dcim.view_rack pour lire.
"""
import json

from django.contrib.auth.mixins import LoginRequiredMixin, PermissionRequiredMixin
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, render
from django.views import View

from dcim.models import Rack, Site

from ..services import floorplan


class FloorPlanView(LoginRequiredMixin, PermissionRequiredMixin, View):
    """Affiche un plan et les baies qui y sont positionnées."""

    permission_required = 'dcim.view_rack'
    template_name = 'netbox_device_search/floorplan/plan.html'

    def get(self, request):
        plan = floorplan.get_floorplan(request.GET.get('plan'))

        # Filtre site optionnel : une grosse installation peut avoir plusieurs
        # sites NetBox partageant le même bâtiment physique.
        site = None
        site_id = request.GET.get('site')
        if site_id and site_id.isdigit():
            site = Site.objects.filter(id=int(site_id)).first()

        placed = floorplan.get_placed_racks(plan['slug'], site=site)

        return render(request, self.template_name, {
            'plan': plan,
            'plans': floorplan.get_floorplans(),
            'sites': Site.objects.order_by('name'),
            'selected_site': site,
            'racks_placed': placed,
            # On passe la liste Python brute, PAS un json.dumps().
            # Le filtre |json_script du template fait lui-même la sérialisation
            # et échappe <, > et & en séquences \u00XX — ce qui rend impossible
            # une fermeture prématurée de la balise <script>. Sérialiser deux
            # fois produirait une chaîne JSON encodée dans une chaîne JSON, et
            # JSON.parse rendrait une string au lieu d'un tableau.
            'racks_placed_json': placed,
            'racks_unplaced': floorplan.get_unplaced_racks(plan['slug'], site=site),
            'can_edit': request.user.has_perm('dcim.change_rack'),
        })


class SaveRackPositionView(LoginRequiredMixin, PermissionRequiredMixin, View):
    """POST AJAX — pose une baie à une position donnée sur un plan.

    Attendu (JSON) : {"rack_id": 12, "plan": "usine-rdc", "x": 42.5, "y": 61.3}
    """

    permission_required = 'dcim.change_rack'

    def post(self, request):
        try:
            payload = json.loads(request.body or '{}')
        except json.JSONDecodeError:
            return JsonResponse({'error': 'JSON invalide'}, status=400)

        rack_id = payload.get('rack_id')
        if not rack_id:
            return JsonResponse({'error': 'rack_id manquant'}, status=400)

        rack = get_object_or_404(Rack, id=rack_id)

        try:
            result = floorplan.save_rack_position(
                rack,
                plan_slug=payload.get('plan'),
                x=payload.get('x'),
                y=payload.get('y'),
            )
        except ValueError as exc:
            # On renvoie 400 (faute du client) et pas 500 : la donnée envoyée
            # est invalide, le serveur lui va très bien.
            return JsonResponse({'error': str(exc)}, status=400)

        return JsonResponse({'status': 'ok', 'rack': result})


class ClearRackPositionView(LoginRequiredMixin, PermissionRequiredMixin, View):
    """POST AJAX — retire une baie du plan."""

    permission_required = 'dcim.change_rack'

    def post(self, request):
        try:
            payload = json.loads(request.body or '{}')
        except json.JSONDecodeError:
            return JsonResponse({'error': 'JSON invalide'}, status=400)

        rack = get_object_or_404(Rack, id=payload.get('rack_id'))
        return JsonResponse({'status': 'ok', 'rack': floorplan.clear_rack_position(rack)})
