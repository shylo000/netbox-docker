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

# Types d'interfaces NetBox qui ne correspondent à AUCUN port physique :
# on ne peut pas y brancher un câble, donc on ne les propose jamais au brassage.
NON_PATCHABLE_INTERFACE_TYPES = ['virtual', 'bridge', 'lag']
