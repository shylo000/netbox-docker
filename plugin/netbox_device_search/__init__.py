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
        'des équipements réseau, navigation Site → Datacenter → Baie, '
        "et plan d'usine interactif."
    )
    version = '1.2.0'
    author = 'IT Team'
    base_url = 'device-search'
    min_version = '4.0.0'
    required_settings = []
    default_settings = {
        'enabled': True,

        # ── Plan d'usine ────────────────────────────────────────────────────
        # Laisser vide utilise le plan livré dans les statics du plugin.
        # Pour servir le VRAI plan de l'usine sans le versionner dans Git ni
        # le figer dans l'image Docker (un plan de site industriel cartographie
        # les accès physiques : c'est une donnée sensible), on le monte en
        # volume et on le déclare ici avec 'image_url' :
        #
        #   'floorplans': [
        #       {'slug': 'usine-rdc',
        #        'label': 'Usine — Rez-de-chaussée',
        #        'image_url': '/media/plans/usine_rdc.png'},
        #       {'slug': 'usine-etage',
        #        'label': 'Usine — Étage',
        #        'image_url': '/media/plans/usine_etage.png'},
        #   ]
        'floorplans': [],
    }


config = NetboxDeviceSearchConfig
