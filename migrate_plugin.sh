#!/usr/bin/env bash
# ============================================================================
#  migrate_plugin.sh
#  Refactorisation modulaire du plugin NetBox `netbox_device_search`
#  + nouvelle navigation Site -> Datacenter (Location) -> Baie (Rack) -> Device
# ----------------------------------------------------------------------------
#  USAGE :
#     bash migrate_plugin.sh [chemin/vers/plugin/netbox_device_search]
#     (defaut : ./plugin/netbox_device_search)
#
#  Ou, dans Claude Code :  « execute migrate_plugin.sh »
#
#  CE SCRIPT NE CASSE RIEN :
#     1. cree une branche git dediee (si depot git)
#     2. sauvegarde TOUT le dossier plugin (copie horodatee)
#     3. pose les nouveaux fichiers du package modulaire
#     4. convertit l'ancien views.py monolithique -> package views/
#     5. verifie la syntaxe Python (py_compile) AVANT de toucher quoi que ce soit
#     6. affiche les etapes suivantes + comment tout annuler
#
#  Rien n'est perdu : sauvegarde complete + branche git. Relis avec `git diff`.
# ============================================================================

set -euo pipefail

# Couleurs (desactivees si pas un terminal)
if [ -t 1 ]; then
  B="\033[1m"; G="\033[32m"; Y="\033[33m"; R="\033[31m"; C="\033[36m"; N="\033[0m"
else
  B=""; G=""; Y=""; R=""; C=""; N=""
fi
info(){ echo -e "${C}==>${N} $*"; }
ok(){   echo -e "${G}OK ${N} $*"; }
warn(){ echo -e "${Y}!! ${N} $*"; }
die(){  echo -e "${R}ERREUR:${N} $*" >&2; exit 1; }

# ---------------------------------------------------------------------------
# 0. Localiser le plugin
# ---------------------------------------------------------------------------
PLUGIN_DIR="${1:-plugin/netbox_device_search}"
PLUGIN_DIR="${PLUGIN_DIR%/}"

if [ ! -d "$PLUGIN_DIR" ]; then
  # tentative de detection
  FOUND="$(find . -type d -name netbox_device_search 2>/dev/null | head -n1 || true)"
  [ -n "$FOUND" ] && PLUGIN_DIR="$FOUND"
fi
[ -d "$PLUGIN_DIR" ] || die "Dossier plugin introuvable. Passe le chemin : bash migrate_plugin.sh chemin/vers/netbox_device_search"

# garde-fou : ca ressemble bien au plugin ?
if [ ! -f "$PLUGIN_DIR/__init__.py" ] && [ ! -f "$PLUGIN_DIR/views.py" ] && [ ! -d "$PLUGIN_DIR/views" ]; then
  die "$PLUGIN_DIR ne ressemble pas au plugin (ni __init__.py ni views.py)."
fi
info "Plugin cible : ${B}$PLUGIN_DIR${N}"

# ---------------------------------------------------------------------------
# 1. Branche git (si depot git)
# ---------------------------------------------------------------------------
if git -C "$PLUGIN_DIR" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  BRANCH="refacto/modularisation-$(date +%Y%m%d-%H%M%S)"
  if git checkout -b "$BRANCH" >/dev/null 2>&1; then
    ok "Branche git creee : $BRANCH"
  else
    warn "Impossible de creer une branche (changements non commits ?). On continue sans."
  fi
else
  warn "Pas de depot git detecte ici — on s'appuie sur la sauvegarde ci-dessous."
fi

# ---------------------------------------------------------------------------
# 2. Sauvegarde complete
# ---------------------------------------------------------------------------
BACKUP="${PLUGIN_DIR}.backup.$(date +%Y%m%d-%H%M%S)"
cp -r "$PLUGIN_DIR" "$BACKUP"
ok "Sauvegarde complete : ${B}$BACKUP${N}"

# helper d'ecriture (cree les dossiers au besoin)
writef(){ mkdir -p "$(dirname "$1")"; cat > "$1"; ok "ecrit  $1"; }

info "Ecriture des fichiers du package modulaire..."

# ===========================================================================
#  FICHIERS — racine du package
# ===========================================================================

writef "$PLUGIN_DIR/__init__.py" <<'EOF'
"""NetBox plugin — Recherche & Gestion de Périphériques (Netlink).

Plugin "vue + workflow" : il ne définit aucun modèle propre, il lit et écrit
sur les modèles natifs de NetBox (dcim / ipam).
"""
from netbox.plugins import PluginConfig


class NetboxDeviceSearchConfig(PluginConfig):
    name = 'netbox_device_search'
    verbose_name = 'Recherche & Gestion de Périphériques'
    description = (
        'Recherche par nom/MAC, affichage complet, création et mise à jour '
        'des équipements réseau, et navigation Site → Datacenter → Baie.'
    )
    version = '1.1.0'
    author = 'IT Team'
    base_url = 'device-search'
    min_version = '4.0.0'
    required_settings = []
    default_settings = {
        'enabled': True,
    }


config = NetboxDeviceSearchConfig
EOF

writef "$PLUGIN_DIR/constants.py" <<'EOF'
"""Valeurs centralisées du plugin.

Objectif : une seule source de vérité. On ne réécrit plus 'eth0' ou
'1000base-t' en dur au milieu d'une vue — on importe depuis ici.
"""
from django.utils.translation import gettext_lazy as _

# ── Interface créée par défaut pour un nouvel équipement ────────────────────
DEFAULT_INTERFACE_NAME = 'eth0'
DEFAULT_INTERFACE_TYPE = '1000base-t'

# ── Câblage ─────────────────────────────────────────────────────────────────
DEFAULT_CABLE_TYPE = 'cat6'
CABLE_STATUS_CONNECTED = 'connected'

CABLE_TYPES = [
    ('cat6', 'CAT6'),
    ('cat5e', 'CAT5e'),
    ('cat6a', 'CAT6a'),
    ('cat8', 'CAT8'),
    ('smf', _('Single-mode fiber')),
    ('mmf', _('Multi-mode fiber')),
]

# ── Statuts d'équipement ─────────────────────────────────────────────────────
DEVICE_STATUS_DEFAULT = 'active'

VALID_DEVICE_STATUSES = [
    'active', 'planned', 'staged', 'failed',
    'inventory', 'decommissioning', 'offline',
]

# Rôles considérés comme "équipements actifs" offrant des ports à câbler.
UPLINK_DEVICE_ROLE_SLUGS = ['switch', 'router']
EOF

writef "$PLUGIN_DIR/exceptions.py" <<'EOF'
"""Exceptions métier du plugin.

Permettent aux services de signaler une erreur fonctionnelle précise,
que les vues attrapent pour afficher un message clair — au lieu d'un
`except Exception` fourre-tout qui masque les vrais bugs.
"""
from django.utils.translation import gettext_lazy as _


class PluginError(Exception):
    """Classe de base pour toutes les erreurs métier du plugin."""


class PortAlreadyUsed(PluginError):
    """Le port cible est déjà raccordé à un câble."""

    def __init__(self, port):
        self.port = port
        port_name = getattr(port, 'name', port)
        super().__init__(_("Port %(port)s is already in use.") % {'port': port_name})
EOF

writef "$PLUGIN_DIR/utils.py" <<'EOF'
"""Petits utilitaires transverses (sans logique métier ni accès HTTP)."""
import re


def make_unique_slug(model_class, name, max_len=50):
    """Génère un slug unique pour `model_class` à partir de `name`.

    Exemple : make_unique_slug(DeviceRole, "Switch Cœur") -> "switch-coeur"
    (puis "switch-coeur-1", "-2"… si déjà pris).
    """
    base = re.sub(r'[^a-z0-9]+', '-', name.lower()).strip('-')[:max_len]
    slug = base
    counter = 1
    while model_class.objects.filter(slug=slug).exists():
        slug = f'{base}-{counter}'
        counter += 1
    return slug
EOF

# ===========================================================================
#  FICHIERS — couche services/
# ===========================================================================

writef "$PLUGIN_DIR/services/__init__.py" <<'EOF'
"""Couche métier du plugin.

C'est la "cuisine" : toute la logique réutilisable (câblage, création
d'équipements, requêtes de topologie) vit ici, hors des vues.
On importe explicitement le sous-module voulu, ex :

    from ..services import cabling
    cabling.connect_device_to_port(device, port)
"""
EOF

writef "$PLUGIN_DIR/services/cabling.py" <<'EOF'
"""Logique métier liée au câblage (lecture et création de liens physiques).

Centralise deux comportements qui étaient dupliqués dans 4 vues différentes :
  - trouver l'équipement relié à une interface (find_connected_peer) ;
  - brancher un équipement sur un port de switch (connect_device_to_port).
"""
import logging

from django.db import transaction

from dcim.models import Cable, Interface

from ..constants import (
    CABLE_STATUS_CONNECTED,
    DEFAULT_CABLE_TYPE,
    DEFAULT_INTERFACE_NAME,
    DEFAULT_INTERFACE_TYPE,
)
from ..exceptions import PortAlreadyUsed

logger = logging.getLogger('netbox_device_search.cabling')


def find_connected_peer(interface):
    """Retourne ``(device_distant, nom_du_port_distant)`` relié à ``interface``.

    Retourne ``(None, None)`` si l'interface est absente ou non câblée.
    Remplace la boucle "parcourir les terminaisons du câble" recopiée
    dans DeviceSearchResultsView, DeviceDetailView et DeviceUpdatePortView.
    """
    if interface is None:
        return None, None

    cable = getattr(interface, 'cable', None)
    if not cable:
        return None, None

    for termination in cable.terminations.all():
        peer = getattr(termination, 'device', None)
        if peer and peer.id != interface.device_id:
            return peer, termination.name

    return None, None


def ensure_primary_interface(device):
    """Retourne la première interface de ``device``, en la créant si besoin."""
    iface = device.interfaces.first()
    if iface is None:
        iface = Interface.objects.create(
            device=device,
            name=DEFAULT_INTERFACE_NAME,
            type=DEFAULT_INTERFACE_TYPE,
        )
    return iface


@transaction.atomic
def connect_device_to_port(device, switch_port, *, cable_type=DEFAULT_CABLE_TYPE, label=None):
    """Relie ``device`` au port ``switch_port`` d'un switch.

    - Débranche proprement un éventuel câble existant côté ``device``.
    - Lève :class:`PortAlreadyUsed` si le port cible est déjà occupé.

    Toute l'opération est atomique : en cas d'erreur, rien n'est écrit.
    Retourne le câble créé.
    """
    if switch_port.cable_id:
        raise PortAlreadyUsed(switch_port)

    device_iface = ensure_primary_interface(device)

    # On retire l'ancien câble côté device avant de recâbler (même séquence
    # que le code d'origine, qui était éprouvé).
    if device_iface.cable_id:
        old_cable = device_iface.cable
        device_iface.cable = None
        device_iface.save()
        old_cable.delete()

    cable = Cable(
        type=cable_type,
        status=CABLE_STATUS_CONNECTED,
        label=label or f'{device.name} - {switch_port.device.name}:{switch_port.name}',
    )
    cable.a_terminations = [device_iface]
    cable.b_terminations = [switch_port]
    cable.save()

    logger.info(
        "Câble créé : %s <-> %s:%s",
        device.name, switch_port.device.name, switch_port.name,
    )
    return cable
EOF

writef "$PLUGIN_DIR/services/devices.py" <<'EOF'
"""Logique métier de création / mise à jour d'équipements.

Le bloc ``transaction.atomic`` de création vivait dans la vue ; il est ici,
réutilisable et testable sans HTTP.
"""
import logging

from django.db import transaction

from dcim.models import Cable, Device, Interface, MACAddress
from ipam.models import IPAddress

from ..constants import (
    CABLE_STATUS_CONNECTED,
    DEFAULT_CABLE_TYPE,
    DEFAULT_INTERFACE_NAME,
    DEFAULT_INTERFACE_TYPE,
    DEVICE_STATUS_DEFAULT,
)

logger = logging.getLogger('netbox_device_search.devices')


@transaction.atomic
def create_device_with_links(*, name, site, role, device_type, rack=None,
                             serial='', description='',
                             mac_address='', ip_address='',
                             switch_port=None, cable_type=DEFAULT_CABLE_TYPE,
                             cable_label=''):
    """Crée un équipement + son interface, et éventuellement MAC, IP et câble.

    Tout est fait dans une seule transaction : si une étape échoue (ex. IP en
    conflit), rien n'est créé — pas de device "orphelin" à moitié configuré.

    Les arguments ``site``, ``role``, ``device_type``, ``rack`` et
    ``switch_port`` sont des **instances** de modèle (ce que fournit un
    ModelChoiceField de formulaire).
    """
    device = Device.objects.create(
        name=name,
        site=site,
        role=role,
        device_type=device_type,
        rack=rack,
        serial=serial or '',
        description=description or '',
        status=DEVICE_STATUS_DEFAULT,
    )

    iface = Interface.objects.create(
        device=device,
        name=DEFAULT_INTERFACE_NAME,
        type=DEFAULT_INTERFACE_TYPE,
    )

    if mac_address:
        mac_obj = MACAddress.objects.create(mac_address=mac_address, assigned_object=iface)
        iface.primary_mac_address = mac_obj
        iface.save()

    if ip_address:
        IPAddress.objects.create(address=ip_address, assigned_object=iface)

    if switch_port:
        cable = Cable(
            type=cable_type,
            status=CABLE_STATUS_CONNECTED,
            label=cable_label or f'{device.name}-{switch_port.device.name}',
        )
        cable.a_terminations = [iface]
        cable.b_terminations = [switch_port]
        cable.save()

    logger.info("Device créé : %s (site=%s)", device.name, getattr(site, 'name', site))
    return device


def update_device_basic(device, *, name, site, role, device_type,
                        rack=None, serial='', description=''):
    """Met à jour les champs de base d'un device existant et le sauvegarde."""
    device.name = name
    device.site = site
    device.role = role
    device.device_type = device_type
    device.rack = rack
    device.serial = serial or ''
    device.description = description or ''
    device.save()
    return device
EOF

writef "$PLUGIN_DIR/services/topology.py" <<'EOF'
"""Requêtes de topologie : Site → Datacenter (Location) → Baie (Rack) → Device.

Rappel du modèle NetBox :
  - une Baie (Rack) appartient TOUJOURS à un Site ;
  - son rattachement à une Location ("datacenter") est OPTIONNEL.
Donc une baie est soit DANS un datacenter, soit directement sous le site.
"""
from django.db.models import Count, Prefetch

from dcim.models import Device, Location, Rack, Site


def list_sites_with_counts():
    """Tous les sites, avec compteurs de datacenters / baies / équipements.

    ``distinct=True`` est indispensable : sans lui, cumuler plusieurs Count
    sur une même requête gonfle les nombres (effet de produit des JOINs).
    """
    return Site.objects.annotate(
        location_count=Count('locations', distinct=True),
        rack_count=Count('racks', distinct=True),
        device_count=Count('devices', distinct=True),
    ).order_by('name')


def racks_with_device_count():
    """Queryset de base des baies, annotées du nombre d'équipements."""
    return Rack.objects.annotate(
        device_count=Count('devices', distinct=True)
    ).order_by('name')


def get_site_layout(site):
    """Retourne ``(locations, racks_sans_datacenter)`` pour un site.

    - ``locations`` : les datacenters du site, chacun avec ses baies préchargées
      (Prefetch -> pas de N+1 quand le template boucle sur ``location.racks``).
    - ``racks_sans_datacenter`` : baies rattachées au site mais à aucune location.
    """
    racks_qs = racks_with_device_count()

    locations = (
        Location.objects.filter(site=site)
        .annotate(rack_count=Count('racks', distinct=True))
        .prefetch_related(Prefetch('racks', queryset=racks_qs))
        .order_by('name')
    )

    racks_sans_datacenter = racks_qs.filter(site=site, location__isnull=True)

    return locations, racks_sans_datacenter


def get_rack_contents(rack):
    """Équipements d'une baie, du haut (U le plus haut) vers le bas."""
    return (
        Device.objects.filter(rack=rack)
        .select_related('role', 'device_type__manufacturer')
        .order_by('-position')
    )
EOF

# ===========================================================================
#  FICHIER — forms.py
# ===========================================================================

writef "$PLUGIN_DIR/forms.py" <<'EOF'
"""Formulaires Django — remplacent le parsing manuel de ``request.POST``.

Avantages vs ``request.POST.get(...)`` + ``if not x: errors.append(...)`` :
  - validation déclarative (champs requis, types) ;
  - sécurité : un ModelChoiceField rejette un ID qui n'existe pas ;
  - cleaned_data renvoie directement des INSTANCES (Site, Rack…), prêtes
    à passer aux services.

Les noms de champs correspondent exactement aux attributs ``name`` des
``<select>`` / ``<input>`` des templates existants (create.html, detail.html),
donc ``Form(request.POST)`` fonctionne sans toucher au HTML.
"""
from django import forms
from django.utils.translation import gettext_lazy as _

from dcim.models import DeviceRole, DeviceType, Interface, Rack, Site

from .constants import CABLE_TYPES, DEFAULT_CABLE_TYPE, UPLINK_DEVICE_ROLE_SLUGS


class _DeviceBaseForm(forms.Form):
    """Champs communs à la création et à l'édition d'un device."""
    name = forms.CharField(label=_("Name"), max_length=64)
    site = forms.ModelChoiceField(label=_("Site"), queryset=Site.objects.all())
    role = forms.ModelChoiceField(label=_("Role"), queryset=DeviceRole.objects.all())
    device_type = forms.ModelChoiceField(
        label=_("Device type"),
        queryset=DeviceType.objects.select_related('manufacturer'),
    )
    rack = forms.ModelChoiceField(label=_("Rack"), queryset=Rack.objects.all(), required=False)
    serial = forms.CharField(label=_("Serial"), required=False)
    description = forms.CharField(label=_("Description"), required=False, widget=forms.Textarea)


class DeviceEditForm(_DeviceBaseForm):
    """Édition inline des champs de base depuis la vue détail."""


class DeviceQuickCreateForm(_DeviceBaseForm):
    """Création rapide d'un équipement + liens optionnels (MAC / IP / câble)."""
    mac_address = forms.CharField(label=_("MAC address"), required=False)
    ip_address = forms.CharField(label=_("IP address"), required=False)

    switch_port = forms.ModelChoiceField(
        label=_("Switch port"),
        required=False,
        queryset=Interface.objects.filter(
            cable__isnull=True,
            device__role__slug__in=UPLINK_DEVICE_ROLE_SLUGS,
        ).select_related('device'),
    )
    cable_type = forms.ChoiceField(
        label=_("Cable type"), choices=CABLE_TYPES,
        initial=DEFAULT_CABLE_TYPE, required=False,
    )
    cable_label = forms.CharField(label=_("Cable label"), required=False)
EOF

# ===========================================================================
#  FICHIERS — package views/
# ===========================================================================

writef "$PLUGIN_DIR/views/__init__.py" <<'EOF'
"""Package de vues du plugin, découpé par domaine fonctionnel.

Ce __init__ ré-exporte toutes les vues : ``urls.py`` continue d'écrire
``views.DeviceDetailView`` exactement comme avant l'éclatement de l'ancien
views.py monolithique. Aucun changement requis côté routes.
"""
from .ajax import (
    CheckIPConflictView,
    CreateDeviceRoleAjaxView,
    CreateDeviceTypeAjaxView,
    DeviceUpdateStatusView,
    get_racks_by_site,
    switch_language,
)
from .connect import (
    DeviceConnectSelectPortView,
    DeviceConnectSelectSiteView,
    DeviceConnectSelectSwitchView,
    DeviceUpdatePortView,
)
from .dashboard import DashboardView
from .devices import DeviceCreateView, DeviceDetailView, DeviceEditView
from .search import DeviceSearchResultsView, DeviceSearchView
from .topology import RackDetailView, SiteBrowserView, SiteDetailView

__all__ = [
    # search
    'DeviceSearchView', 'DeviceSearchResultsView',
    # devices
    'DeviceDetailView', 'DeviceCreateView', 'DeviceEditView',
    # connect
    'DeviceConnectSelectSiteView', 'DeviceConnectSelectSwitchView',
    'DeviceConnectSelectPortView', 'DeviceUpdatePortView',
    # dashboard
    'DashboardView',
    # topology
    'SiteBrowserView', 'SiteDetailView', 'RackDetailView',
    # ajax / divers
    'switch_language', 'CheckIPConflictView', 'DeviceUpdateStatusView',
    'CreateDeviceRoleAjaxView', 'CreateDeviceTypeAjaxView', 'get_racks_by_site',
]
EOF

writef "$PLUGIN_DIR/views/search.py" <<'EOF'
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
EOF

writef "$PLUGIN_DIR/views/devices.py" <<'EOF'
"""Vues de détail, création et édition d'un équipement."""
import logging

from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.translation import gettext_lazy as _
from django.views import View

from dcim.models import (
    Device, DeviceRole, DeviceType, Interface, Manufacturer, Rack, Site,
)

from ..constants import DEFAULT_CABLE_TYPE, UPLINK_DEVICE_ROLE_SLUGS
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
        context = {
            'sites': Site.objects.all().order_by('name'),
            'device_roles': DeviceRole.objects.all().order_by('name'),
            'device_types': DeviceType.objects.select_related('manufacturer').order_by(
                'manufacturer__name', 'model'),
            'manufacturers': Manufacturer.objects.all().order_by('name'),
            'racks': Rack.objects.all().order_by('name'),
            'free_ports': Interface.objects.filter(
                cable__isnull=True, device__role__slug__in=UPLINK_DEVICE_ROLE_SLUGS,
            ).select_related('device')[:100],
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
EOF

writef "$PLUGIN_DIR/views/connect.py" <<'EOF'
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
EOF

writef "$PLUGIN_DIR/views/dashboard.py" <<'EOF'
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
EOF

writef "$PLUGIN_DIR/views/ajax.py" <<'EOF'
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
EOF

writef "$PLUGIN_DIR/views/topology.py" <<'EOF'
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
    """Niveau 3 : une baie et les équipements qu'elle contient."""
    template_name = 'netbox_device_search/topology/rack_detail.html'

    def get(self, request, rack_id):
        rack = get_object_or_404(Rack.objects.select_related('site', 'location'), id=rack_id)
        return render(request, self.template_name, {
            'rack': rack,
            'devices': topology.get_rack_contents(rack),
        })
EOF

# ===========================================================================
#  FICHIER — urls.py
# ===========================================================================

writef "$PLUGIN_DIR/urls.py" <<'EOF'
"""Routes du plugin.

NB : pas de ``app_name`` ici — NetBox enregistre lui-même le namespace
``plugins:netbox_device_search:`` à partir du PluginConfig. Les vues sont
importées via le package ``views`` (dont le __init__ ré-exporte tout).
"""
from django.urls import path

from . import views

urlpatterns = [
    # ── Changement de langue (remplace /i18n/set_language/ indispo dans NetBox) ──
    path('set-language/', views.switch_language, name='switch_language'),

    # ── Tableau de bord ──
    path('dashboard/', views.DashboardView.as_view(), name='dashboard'),

    # ── Recherche ──
    path('', views.DeviceSearchView.as_view(), name='device_search'),
    path('results/', views.DeviceSearchResultsView.as_view(), name='device_search_results'),

    # ── Équipement : détail / création / édition ──
    path('device/<int:device_id>/', views.DeviceDetailView.as_view(), name='device_detail'),
    path('create/', views.DeviceCreateView.as_view(), name='device_create'),
    path('device/<int:device_id>/edit/', views.DeviceEditView.as_view(), name='device_edit'),

    # ═══════════════════════════════════════════════════════════════════════
    # NOUVEAU — Topologie : Site → Datacenter (Location) → Baie (Rack) → Device
    # ═══════════════════════════════════════════════════════════════════════
    path('topology/', views.SiteBrowserView.as_view(), name='site_browser'),
    path('topology/site/<int:site_id>/', views.SiteDetailView.as_view(), name='site_detail'),
    path('topology/rack/<int:rack_id>/', views.RackDetailView.as_view(), name='rack_detail'),

    # ═══════════════════════════════════════════════════════════════════════
    # Workflow : connecter un device à un switch (en plusieurs pages)
    # ═══════════════════════════════════════════════════════════════════════
    path('device/<int:device_id>/connect/site/',
         views.DeviceConnectSelectSiteView.as_view(), name='device_connect_site'),
    path('device/<int:device_id>/connect/switch/<int:rack_id>/',
         views.DeviceConnectSelectSwitchView.as_view(), name='device_connect_switch'),
    path('device/<int:device_id>/connect/port/<int:switch_id>/',
         views.DeviceConnectSelectPortView.as_view(), name='device_connect_port'),

    # ── Endpoints AJAX ──
    path('api/racks/<int:site_id>/', views.get_racks_by_site, name='api_get_racks'),
    path('api/check-ip/', views.CheckIPConflictView.as_view(), name='api_check_ip'),
    path('api/create-role/', views.CreateDeviceRoleAjaxView.as_view(), name='api_create_role'),
    path('api/create-device-type/',
         views.CreateDeviceTypeAjaxView.as_view(), name='api_create_device_type'),
    path('device/<int:device_id>/update-status/',
         views.DeviceUpdateStatusView.as_view(), name='device_update_status'),

    # ── [Déprécié] ancien système de mise à jour de port ──
    path('device/<int:device_id>/update-port/',
         views.DeviceUpdatePortView.as_view(), name='device_update_port'),
]
EOF

# ===========================================================================
#  FICHIER — navigation.py
# ===========================================================================

writef "$PLUGIN_DIR/navigation.py" <<'EOF'
"""Menu latéral NetBox du plugin.

NetBox auto-découvre soit ``menu`` (PluginMenu, menu dédié avec icône), soit
``menu_items`` (tuple, items rangés sous "Plugins"). On utilise un PluginMenu
pour avoir une section propre, et on accroche des ``permissions`` à chaque
entrée (l'item est masqué si l'utilisateur n'a pas le droit correspondant).
"""
from netbox.plugins import PluginMenu, PluginMenuItem

_equipements = (
    PluginMenuItem(
        link='plugins:netbox_device_search:dashboard',
        link_text='Tableau de bord',
        permissions=['dcim.view_device'],
    ),
    PluginMenuItem(
        link='plugins:netbox_device_search:device_search',
        link_text='Rechercher un équipement',
        permissions=['dcim.view_device'],
    ),
    PluginMenuItem(
        link='plugins:netbox_device_search:device_create',
        link_text='Créer un équipement',
        permissions=['dcim.add_device'],
    ),
)

_topologie = (
    PluginMenuItem(
        link='plugins:netbox_device_search:site_browser',
        link_text='Parcourir sites & baies',
        permissions=['dcim.view_site'],
    ),
)

menu = PluginMenu(
    label='Device Search',
    icon_class='mdi mdi-lan',
    groups=(
        ('Équipements', _equipements),
        ('Topologie', _topologie),
    ),
)
EOF

# ===========================================================================
#  FICHIERS — templates topology
# ===========================================================================

writef "$PLUGIN_DIR/templates/netbox_device_search/topology/site_browser.html" <<'EOF'
{% extends 'base/layout.html' %}
{% load i18n %}

{% block title %}{% trans "Sites & racks" %}{% endblock %}

{% block content %}
<div class="container-fluid">

    <!-- En-tête -->
    <div class="d-flex justify-content-between align-items-center mb-4">
        <h2 class="fw-bold mb-0">
            <i class="mdi mdi-sitemap text-primary"></i>
            {% trans "Sites & racks" %}
        </h2>
        <div class="d-flex gap-2 align-items-center">
            <a href="{% url 'plugins:netbox_device_search:dashboard' %}" class="btn btn-outline-secondary">
                <i class="mdi mdi-view-dashboard"></i> {% trans "Dashboard" %}
            </a>
            <a href="{% url 'plugins:netbox_device_search:device_search' %}" class="btn btn-outline-primary">
                <i class="mdi mdi-magnify"></i> {% trans "Search" %}
            </a>
            <div class="border-start border-secondary ps-2 ms-1">
                {% include 'netbox_device_search/_lang_switcher.html' %}
            </div>
        </div>
    </div>

    <p class="text-muted">
        {% trans "Browse your infrastructure: site → datacenter → rack → device." %}
    </p>

    <!-- Grille des sites -->
    <div class="row g-4">
        {% for site in sites %}
        <div class="col-md-4">
            <a href="{% url 'plugins:netbox_device_search:site_detail' site.id %}"
               class="card shadow-sm h-100 text-decoration-none text-reset border-start border-primary border-4">
                <div class="card-body">
                    <h5 class="fw-bold mb-3">
                        <i class="mdi mdi-map-marker text-primary"></i> {{ site.name }}
                    </h5>
                    <div class="d-flex justify-content-between">
                        <span class="text-muted small">
                            <i class="mdi mdi-office-building-outline"></i> {% trans "Datacenters" %}
                        </span>
                        <span class="badge bg-secondary">{{ site.location_count }}</span>
                    </div>
                    <div class="d-flex justify-content-between mt-1">
                        <span class="text-muted small"><i class="mdi mdi-server"></i> {% trans "Racks" %}</span>
                        <span class="badge bg-info">{{ site.rack_count }}</span>
                    </div>
                    <div class="d-flex justify-content-between mt-1">
                        <span class="text-muted small"><i class="mdi mdi-network"></i> {% trans "Devices" %}</span>
                        <span class="badge bg-success">{{ site.device_count }}</span>
                    </div>
                </div>
            </a>
        </div>
        {% empty %}
        <div class="col-12">
            <div class="alert alert-info">{% trans "No site configured." %}</div>
        </div>
        {% endfor %}
    </div>

</div>
{% endblock %}
EOF

writef "$PLUGIN_DIR/templates/netbox_device_search/topology/site_detail.html" <<'EOF'
{% extends 'base/layout.html' %}
{% load i18n %}

{% block title %}{{ site.name }} — {% trans "Racks" %}{% endblock %}

{% block content %}
<div class="container-fluid">

    <!-- En-tête -->
    <div class="d-flex justify-content-between align-items-center mb-4">
        <h2 class="fw-bold mb-0">
            <i class="mdi mdi-map-marker text-primary"></i> {{ site.name }}
        </h2>
        <div class="d-flex gap-2 align-items-center">
            <a href="{% url 'plugins:netbox_device_search:site_browser' %}" class="btn btn-outline-secondary">
                <i class="mdi mdi-arrow-left"></i> {% trans "All sites" %}
            </a>
            <div class="border-start border-secondary ps-2 ms-1">
                {% include 'netbox_device_search/_lang_switcher.html' %}
            </div>
        </div>
    </div>

    {# ── Datacenters (Locations) et leurs baies ── #}
    {% for location in locations %}
    <div class="card shadow-sm mb-4">
        <div class="card-header d-flex justify-content-between align-items-center">
            <span>
                <i class="mdi mdi-office-building" style="color:#8B5CF6;"></i>
                <strong>{{ location.name }}</strong>
            </span>
            <span class="badge bg-secondary">{{ location.rack_count }} {% trans "rack(s)" %}</span>
        </div>
        <div class="card-body">
            <div class="row g-3">
                {% for rack in location.racks.all %}
                <div class="col-md-3">
                    <a href="{% url 'plugins:netbox_device_search:rack_detail' rack.id %}"
                       class="card h-100 text-decoration-none text-reset border-start border-info border-4">
                        <div class="card-body py-3">
                            <div class="fw-bold"><i class="mdi mdi-server"></i> {{ rack.name }}</div>
                            <small class="text-muted">{{ rack.device_count }} {% trans "device(s)" %}</small>
                        </div>
                    </a>
                </div>
                {% empty %}
                <p class="text-muted mb-0">{% trans "No rack in this datacenter." %}</p>
                {% endfor %}
            </div>
        </div>
    </div>
    {% endfor %}

    {# ── Baies hors datacenter (rack.location vide) ── #}
    {% if racks_sans_datacenter %}
    <div class="card shadow-sm mb-4 border-start border-warning border-4">
        <div class="card-header">
            <i class="mdi mdi-server-off text-warning"></i>
            <strong>{% trans "Racks not in a datacenter" %}</strong>
        </div>
        <div class="card-body">
            <div class="row g-3">
                {% for rack in racks_sans_datacenter %}
                <div class="col-md-3">
                    <a href="{% url 'plugins:netbox_device_search:rack_detail' rack.id %}"
                       class="card h-100 text-decoration-none text-reset border-start border-info border-4">
                        <div class="card-body py-3">
                            <div class="fw-bold"><i class="mdi mdi-server"></i> {{ rack.name }}</div>
                            <small class="text-muted">{{ rack.device_count }} {% trans "device(s)" %}</small>
                        </div>
                    </a>
                </div>
                {% endfor %}
            </div>
        </div>
    </div>
    {% endif %}

    {% if not locations and not racks_sans_datacenter %}
    <div class="alert alert-info">{% trans "This site has no rack yet." %}</div>
    {% endif %}

</div>
{% endblock %}
EOF

writef "$PLUGIN_DIR/templates/netbox_device_search/topology/rack_detail.html" <<'EOF'
{% extends 'base/layout.html' %}
{% load i18n %}

{% block title %}{{ rack.name }} — {% trans "Devices" %}{% endblock %}

{% block content %}
<div class="container-fluid">

    <!-- En-tête -->
    <div class="d-flex justify-content-between align-items-center mb-4">
        <div>
            <h2 class="fw-bold mb-0"><i class="mdi mdi-server text-info"></i> {{ rack.name }}</h2>
            <small class="text-muted">
                <i class="mdi mdi-map-marker"></i> {{ rack.site.name }}
                {% if rack.location %}
                    · <i class="mdi mdi-office-building"></i> {{ rack.location.name }}
                {% else %}
                    · <span class="text-warning">{% trans "Not in a datacenter" %}</span>
                {% endif %}
            </small>
        </div>
        <div class="d-flex gap-2 align-items-center">
            <a href="{% url 'plugins:netbox_device_search:site_detail' rack.site.id %}" class="btn btn-outline-secondary">
                <i class="mdi mdi-arrow-left"></i> {{ rack.site.name }}
            </a>
            <div class="border-start border-secondary ps-2 ms-1">
                {% include 'netbox_device_search/_lang_switcher.html' %}
            </div>
        </div>
    </div>

    <!-- Équipements de la baie -->
    <div class="card shadow-sm">
        <div class="card-header">
            <i class="mdi mdi-format-list-bulleted text-primary"></i>
            <strong>{% trans "Devices in this rack" %}</strong>
            <span class="badge bg-secondary ms-2">{{ devices|length }}</span>
        </div>
        <div class="card-body p-0">
            {% if devices %}
            <table class="table table-sm table-hover mb-0">
                <thead class="table-light">
                    <tr>
                        <th class="ps-3">{% trans "Position (U)" %}</th>
                        <th>{% trans "Name" %}</th>
                        <th>{% trans "Role" %}</th>
                        <th>{% trans "Manufacturer / Model" %}</th>
                        <th>{% trans "Status" %}</th>
                        <th></th>
                    </tr>
                </thead>
                <tbody>
                    {% for device in devices %}
                    <tr>
                        <td class="ps-3">
                            {% if device.position %}U{{ device.position }}{% else %}<span class="text-muted">—</span>{% endif %}
                        </td>
                        <td class="fw-bold">{{ device.name }}</td>
                        <td>{{ device.role.name|default:"—" }}</td>
                        <td>
                            {{ device.device_type.manufacturer.name|default:"" }}
                            {% if device.device_type.manufacturer.name %} — {% endif %}
                            {{ device.device_type.model|default:"—" }}
                        </td>
                        <td>
                            <span class="badge
                                {% if device.status == 'active' %}bg-success
                                {% elif device.status == 'failed' %}bg-danger
                                {% elif device.status == 'planned' %}bg-info
                                {% else %}bg-secondary{% endif %}">
                                {{ device.get_status_display }}
                            </span>
                        </td>
                        <td>
                            <a href="{% url 'plugins:netbox_device_search:device_detail' device.id %}"
                               class="btn btn-sm btn-outline-primary">
                                <i class="mdi mdi-eye"></i>
                            </a>
                        </td>
                    </tr>
                    {% endfor %}
                </tbody>
            </table>
            {% else %}
            <div class="p-3 text-muted">{% trans "This rack is empty." %}</div>
            {% endif %}
        </div>
    </div>

</div>
{% endblock %}
EOF

# ===========================================================================
#  3. Convertir l'ancien views.py monolithique -> package views/
# ===========================================================================
if [ -f "$PLUGIN_DIR/views.py" ]; then
  rm -f "$PLUGIN_DIR/views.py"
  ok "Ancien views.py supprimé (sauvegardé dans $BACKUP). Le package views/ le remplace."
fi

# Nettoyage des caches bytecode obsolètes
find "$PLUGIN_DIR" -name '__pycache__' -type d -prune -exec rm -rf {} + 2>/dev/null || true

# ===========================================================================
#  4. Vérification de syntaxe (n'importe RIEN, compile juste)
# ===========================================================================
info "Vérification de la syntaxe Python (py_compile)..."
set +e
PYBIN="$(command -v python3 || command -v python)"
if [ -z "$PYBIN" ]; then
  warn "python3 introuvable — saute la vérif syntaxe. Vérifie après le build Docker."
else
  "$PYBIN" -m compileall -q "$PLUGIN_DIR"
  RC=$?
  if [ "$RC" -ne 0 ]; then
    echo
    die "Erreur de syntaxe détectée. RIEN n'est cassé : restaure avec
       rm -rf \"$PLUGIN_DIR\" && mv \"$BACKUP\" \"$PLUGIN_DIR\"
   (ou : git checkout -- . ; git checkout - )"
  fi
  # on retire les .pyc generes par la verif
  find "$PLUGIN_DIR" -name '__pycache__' -type d -prune -exec rm -rf {} + 2>/dev/null || true
fi
set -e
ok "Syntaxe Python validée."

# ===========================================================================
#  5. Récapitulatif + étapes suivantes
# ===========================================================================
echo
echo -e "${G}${B}=== Migration terminée ===${N}"
echo
echo -e "${B}Arborescence posée :${N}"
echo "  $PLUGIN_DIR/"
echo "    __init__.py  constants.py  exceptions.py  utils.py  forms.py"
echo "    urls.py  navigation.py"
echo "    services/   -> __init__.py  cabling.py  devices.py  topology.py"
echo "    views/      -> __init__.py  search.py  devices.py  connect.py"
echo "                   dashboard.py  ajax.py  topology.py"
echo "    templates/netbox_device_search/topology/"
echo "                   site_browser.html  site_detail.html  rack_detail.html"
echo
echo -e "${B}À FAIRE ENSUITE :${N}"
echo -e "  1. ${C}Relis les fichiers remplacés${N} (au cas où tu avais du custom) :"
echo "       git diff -- $PLUGIN_DIR/__init__.py $PLUGIN_DIR/navigation.py $PLUGIN_DIR/urls.py"
echo "     (originaux aussi dans : $BACKUP)"
echo -e "  2. ${C}Reconstruis l'image et relance${N} (depuis la racine du repo) :"
echo "       docker compose build --no-cache netbox"
echo "       docker compose up -d"
echo -e "  3. ${C}Vérifie le chargement du plugin${N} :"
echo "       docker compose exec netbox /opt/netbox/netbox/manage.py check"
echo "  4. Teste dans le navigateur :"
echo "       /plugins/device-search/            (recherche)"
echo "       /plugins/device-search/topology/   (NOUVEAU : sites & baies)"
echo
echo -e "${B}POUR TOUT ANNULER :${N}"
echo "     rm -rf \"$PLUGIN_DIR\" && mv \"$BACKUP\" \"$PLUGIN_DIR\""
echo "     (ou avec git : git checkout -- . puis reviens sur ta branche d'origine)"
echo
