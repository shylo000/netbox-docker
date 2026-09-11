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
    get_rack_ports,
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
from .floorplan import ClearRackPositionView, FloorPlanView, SaveRackPositionView
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
    # floorplan
    'FloorPlanView', 'SaveRackPositionView', 'ClearRackPositionView',
    # ajax / divers
    'switch_language', 'CheckIPConflictView', 'DeviceUpdateStatusView',
    'CreateDeviceRoleAjaxView', 'CreateDeviceTypeAjaxView', 'get_racks_by_site',
    'get_rack_ports',
]
