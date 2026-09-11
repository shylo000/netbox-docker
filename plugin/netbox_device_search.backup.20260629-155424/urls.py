from django.urls import path
from . import views

urlpatterns = [
    # ── Changement de langue (remplace /i18n/set_language/ non dispo dans NetBox) ──
    path('set-language/', views.switch_language, name='switch_language'),

    # Dashboard
    path('dashboard/', views.DashboardView.as_view(), name='dashboard'),

    # Page principale : recherche par nom ou MAC
    path('', views.DeviceSearchView.as_view(), name='device_search'),

    # Résultats de recherche
    path('results/', views.DeviceSearchResultsView.as_view(), name='device_search_results'),

    # Détail complet d'un device
    path('device/<int:device_id>/', views.DeviceDetailView.as_view(), name='device_detail'),

    # Créer un nouveau device
    path('create/', views.DeviceCreateView.as_view(), name='device_create'),

    # ═══════════════════════════════════════════════════════════════
    # WORKFLOW : Connecter un device à un switch (en plusieurs pages)
    # ═══════════════════════════════════════════════════════════════

    # PAGE 2 : Sélection Site → Affichage Baies
    path('device/<int:device_id>/connect/site/',
         views.DeviceConnectSelectSiteView.as_view(),
         name='device_connect_site'),

    # PAGE 3 : Sélection Switch dans une baie
    path('device/<int:device_id>/connect/switch/<int:rack_id>/',
         views.DeviceConnectSelectSwitchView.as_view(),
         name='device_connect_switch'),

    # PAGE 4 : Sélection Port graphique sur un switch
    path('device/<int:device_id>/connect/port/<int:switch_id>/',
         views.DeviceConnectSelectPortView.as_view(),
         name='device_connect_port'),

    # API AJAX : Charger les baies d'un site (pour la transition dynamique)
    path('api/racks/<int:site_id>/',
         views.get_racks_by_site,
         name='api_get_racks'),

    # Édition inline d'un device
    path('device/<int:device_id>/edit/',
         views.DeviceEditView.as_view(),
         name='device_edit'),

    # API AJAX : Vérifier si une IP est déjà utilisée
    path('api/check-ip/',
         views.CheckIPConflictView.as_view(),
         name='api_check_ip'),

    # Changer le statut d'un device (AJAX POST)
    path('device/<int:device_id>/update-status/',
         views.DeviceUpdateStatusView.as_view(),
         name='device_update_status'),

    # API AJAX : Créer un DeviceRole à la volée
    path('api/create-role/',
         views.CreateDeviceRoleAjaxView.as_view(),
         name='api_create_role'),

    # API AJAX : Créer un DeviceType (+ Manufacturer si besoin) à la volée
    path('api/create-device-type/',
         views.CreateDeviceTypeAjaxView.as_view(),
         name='api_create_device_type'),

    # Mettre à jour le port/switch d'un device (ancien système)
    path('device/<int:device_id>/update-port/',
         views.DeviceUpdatePortView.as_view(),
         name='device_update_port'),
]
