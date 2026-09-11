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

from .constants import (
    CABLE_TYPES, DEFAULT_CABLE_TYPE, NON_PATCHABLE_INTERFACE_TYPES,
    UPLINK_DEVICE_ROLE_SLUGS,
)


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

    # Filet de sécurité côté serveur : même définition d'un port "libre" que
    # services.cabling._is_free. Le <select> HTML grise les ports occupés,
    # mais un POST forgé (ou une page restée ouverte pendant qu'un collègue
    # brasse le port) doit être rejeté ici — on ne fait jamais confiance au
    # client pour la validation.
    switch_port = forms.ModelChoiceField(
        label=_("Switch port"),
        required=False,
        queryset=Interface.objects.filter(
            cable__isnull=True,
            mark_connected=False,
            mgmt_only=False,
            device__role__slug__in=UPLINK_DEVICE_ROLE_SLUGS,
        ).exclude(
            type__in=NON_PATCHABLE_INTERFACE_TYPES,
        ).select_related('device'),
    )
    cable_type = forms.ChoiceField(
        label=_("Cable type"), choices=CABLE_TYPES,
        initial=DEFAULT_CABLE_TYPE, required=False,
    )
    cable_label = forms.CharField(label=_("Cable label"), required=False)
