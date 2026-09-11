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
    PluginMenuItem(
        link='plugins:netbox_device_search:floorplan',
        link_text="Plan de l'usine",
        permissions=['dcim.view_rack'],
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
