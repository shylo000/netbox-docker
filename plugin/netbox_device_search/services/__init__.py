"""Couche métier du plugin.

C'est la "cuisine" : toute la logique réutilisable (câblage, création
d'équipements, requêtes de topologie) vit ici, hors des vues.
On importe explicitement le sous-module voulu, ex :

    from ..services import cabling
    cabling.connect_device_to_port(device, port)
"""
