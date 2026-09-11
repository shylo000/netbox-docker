from netbox.plugins import PluginConfig


class NetboxDeviceSearchConfig(PluginConfig):
    name = 'netbox_device_search'
    verbose_name = 'Recherche & Gestion de Périphériques'
    description = 'Recherche par nom/MAC, affichage complet, création et mise à jour des équipements réseau'
    version = '1.0.0'
    author = 'IT Team'
    base_url = 'device-search'
    min_version = '4.0.0'
    required_settings = []
    default_settings = {
        'enabled': True,
    }


config = NetboxDeviceSearchConfig