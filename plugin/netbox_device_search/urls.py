from django.urls import path
from . import views

urlpatterns = [
    # Page principale : recherche par nom ou MAC
    path('', views.DeviceSearchView.as_view(), name='device_search'),

    # Résultats de recherche
    path('results/', views.DeviceSearchResultsView.as_view(), name='device_search_results'),

    # Détail complet d'un device
    path('device/<int:device_id>/', views.DeviceDetailView.as_view(), name='device_detail'),

    # Créer un nouveau device
    path('create/', views.DeviceCreateView.as_view(), name='device_create'),

    # Mettre à jour le port/switch d'un device
    path('device/<int:device_id>/update-port/', views.DeviceUpdatePortView.as_view(), name='device_update_port'),
]