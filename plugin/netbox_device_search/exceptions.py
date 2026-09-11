"""Exceptions métier du plugin.

Permettent aux services de signaler une erreur fonctionnelle précise,
que les vues attrapent pour afficher un message clair — au lieu d'un
`except Exception` fourre-tout qui masque les vrais bugs.
"""
from django.utils.translation import gettext_lazy as _


class PluginError(Exception):
    """Classe de base pour toutes les erreurs métier du plugin."""


class PortAlreadyUsed(PluginError):
    """Le port cible est déjà raccordé à un câble."""

    def __init__(self, port):
        self.port = port
        port_name = getattr(port, 'name', port)
        super().__init__(_("Port %(port)s is already in use.") % {'port': port_name})
