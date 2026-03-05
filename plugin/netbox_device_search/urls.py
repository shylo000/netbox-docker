from django.urls import path
from . import views

urlpatterns = [
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

    # Mettre à jour le port/switch d'un device (ancien système)
    path('device/<int:device_id>/update-port/', 
         views.DeviceUpdatePortView.as_view(), 
         name='device_update_port'),
]