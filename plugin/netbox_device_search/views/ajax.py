"""Endpoints AJAX (réponses JSON) et bascule de langue."""
import logging

from django.conf import settings
from django.db.models import Count, Q
from django.http import HttpResponseRedirect, JsonResponse
from django.shortcuts import get_object_or_404
from django.utils import translation
from django.utils.translation import gettext_lazy as _
from django.views import View

from dcim.models import Device, DeviceRole, DeviceType, Manufacturer, Rack, Site
from ipam.models import IPAddress

from ..constants import VALID_DEVICE_STATUSES
from ..services import cabling
from ..utils import make_unique_slug

logger = logging.getLogger('netbox_device_search.ajax')


def switch_language(request):
    """Bascule la langue de l'interface (EN/FR) via cookie Django."""
    lang = request.POST.get('language') or request.GET.get('lang', 'fr')
    if lang not in ('fr', 'en'):
        lang = 'fr'

    next_url = request.POST.get('next') or request.META.get('HTTP_REFERER', '/')
    # Sécurité : n'autoriser qu'une URL relative (anti open-redirect).
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


class CheckIPConflictView(View):
    """GET ?ip=x.x.x.x/xx — indique si une IP est déjà utilisée dans NetBox."""

    def get(self, request):
        ip = request.GET.get('ip', '').strip()
        if not ip:
            return JsonResponse({'conflict': False})

        existing = IPAddress.objects.filter(address=ip).first()
        if not existing:
            return JsonResponse({'conflict': False})

        device_name = None
        try:
            obj = existing.assigned_object
            if obj and hasattr(obj, 'device'):
                device_name = obj.device.name
        except Exception:
            logger.warning("Impossible de résoudre l'objet assigné de l'IP %s", ip)

        return JsonResponse({'conflict': True, 'device': device_name})


class DeviceUpdateStatusView(View):
    """POST — change le statut d'un device sans passer par l'admin NetBox."""

    def post(self, request, device_id):
        device = get_object_or_404(Device, id=device_id)
        status = request.POST.get('status', '').strip()

        if status not in VALID_DEVICE_STATUSES:
            return JsonResponse({'success': False, 'error': str(_('Invalid status'))})

        device.status = status
        device.save()
        return JsonResponse({
            'success': True,
            'status': status,
            'display': device.get_status_display(),
        })


class CreateDeviceRoleAjaxView(View):
    """POST — crée un DeviceRole à la volée depuis le formulaire de création."""

    def post(self, request):
        name = request.POST.get('name', '').strip()
        color = request.POST.get('color', '9e9e9e').strip().lstrip('#')

        if not name:
            return JsonResponse({'success': False, 'error': str(_('Name is required'))})

        slug = make_unique_slug(DeviceRole, name)
        try:
            role = DeviceRole.objects.create(name=name, slug=slug, color=color)
        except Exception as exc:
            logger.exception("Échec création DeviceRole")
            return JsonResponse({'success': False, 'error': str(exc)})

        return JsonResponse({'success': True, 'id': role.id, 'name': role.name})


class CreateDeviceTypeAjaxView(View):
    """POST — crée un DeviceType (et son Manufacturer si besoin) à la volée."""

    def post(self, request):
        manufacturer_id = request.POST.get('manufacturer_id', '').strip()
        manufacturer_name = request.POST.get('manufacturer_name', '').strip()
        model = request.POST.get('model', '').strip()

        if not model:
            return JsonResponse({'success': False, 'error': str(_('Model name is required'))})

        try:
            if manufacturer_id:
                manufacturer = Manufacturer.objects.get(id=manufacturer_id)
            elif manufacturer_name:
                # NB : on nomme la variable _created (pas _) pour ne PAS écraser
                # gettext `_` importé en haut du module.
                manufacturer, _created = Manufacturer.objects.get_or_create(
                    name=manufacturer_name,
                    defaults={'slug': make_unique_slug(Manufacturer, manufacturer_name)},
                )
            else:
                return JsonResponse({'success': False, 'error': str(_('Manufacturer is required'))})

            device_type = DeviceType.objects.create(
                manufacturer=manufacturer,
                model=model,
                slug=make_unique_slug(DeviceType, model),
            )
        except Exception as exc:
            logger.exception("Échec création DeviceType")
            return JsonResponse({'success': False, 'error': str(exc)})

        return JsonResponse({
            'success': True,
            'id': device_type.id,
            'name': f'{manufacturer.name} — {device_type.model}',
            'manufacturer_id': manufacturer.id,
            'manufacturer_name': manufacturer.name,
        })


def get_racks_by_site(request, site_id):
    """GET — baies d'un site (chargement dynamique de l'étape 1 de connexion)."""
    try:
        site = Site.objects.get(id=site_id)
    except Site.DoesNotExist:
        return JsonResponse({'success': False, 'error': str(_("Site not found"))}, status=404)

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

    return JsonResponse({'success': True, 'site_name': site.name, 'racks': racks_data})


def get_rack_ports(request, rack_id):
    """GET — switches et ports libres proposés pour une baie donnée.

    Alimente l'auto-remplissage "je choisis une baie → on me propose le switch
    et le port" du formulaire de création. Toute la décision est prise côté
    Python (services.cabling) ; cette vue ne fait que sérialiser.
    """
    try:
        rack = Rack.objects.select_related('site', 'location').get(id=rack_id)
    except Rack.DoesNotExist:
        return JsonResponse({'success': False, 'error': str(_("Rack not found"))}, status=404)

    data = cabling.get_rack_cabling_options(rack)
    data.update({
        'success': True,
        'rack_id': rack.id,
        'rack_name': rack.name,
        'site_id': rack.site_id,
        'site_name': rack.site.name if rack.site else '',
    })
    return JsonResponse(data)
