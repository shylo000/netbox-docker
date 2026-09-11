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
    # NOUVEAU — Plan d'usine interactif : baies cliquables sur le plan 2D
    # ═══════════════════════════════════════════════════════════════════════
    path('plan/', views.FloorPlanView.as_view(), name='floorplan'),
    path('api/plan/save-position/',
         views.SaveRackPositionView.as_view(), name='api_plan_save_position'),
    path('api/plan/clear-position/',
         views.ClearRackPositionView.as_view(), name='api_plan_clear_position'),

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
    path('api/rack/<int:rack_id>/ports/', views.get_rack_ports, name='api_get_rack_ports'),
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
