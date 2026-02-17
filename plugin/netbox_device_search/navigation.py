from netbox.plugins import PluginMenuItem, PluginMenuButton

menu_items = (
    PluginMenuItem(
        link='plugins:netbox_device_search:device_search',
        link_text='Recherche Périphérique',
        permissions=['dcim.view_device'],
        buttons=(
            PluginMenuButton(
                link='plugins:netbox_device_search:device_create',
                title='Ajouter un périphérique',
                icon_class='mdi mdi-plus-thick',
                color='green',
                permissions=['dcim.add_device'],
            ),
        ),
    ),
)