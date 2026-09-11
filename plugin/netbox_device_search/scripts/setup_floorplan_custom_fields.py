"""Crée les Custom Fields NetBox nécessaires au plan d'usine.

À lancer UNE fois après le déploiement de la version du plugin ::

    docker compose exec netbox /opt/netbox/netbox/manage.py shell \
        -c "exec(open('/opt/netbox/netbox/netbox_device_search/scripts/setup_floorplan_custom_fields.py').read())"

Le script est **idempotent** : le relancer ne duplique rien et ne réinitialise
aucune position déjà saisie. On peut donc le rejouer sans réfléchir à chaque
déploiement — c'est ce qui le rend intégrable dans un initContainer Kubernetes
ou un job post-déploiement.

Note NetBox 4.x : le champ de rattachement d'un CustomField s'appelle
``object_types`` (M2M vers core.ObjectType). Il s'appelait ``content_types``
et pointait vers ContentType jusqu'en NetBox 3.x — c'est le piège si tu
recopies un tutoriel un peu ancien.
"""
from core.models import ObjectType
from dcim.models import Rack
from extras.choices import CustomFieldTypeChoices
from extras.models import CustomField

RACK_TYPE = ObjectType.objects.get_for_model(Rack)

FIELDS = [
    {
        'name': 'plan_niveau',
        'label': "Plan (niveau)",
        'type': CustomFieldTypeChoices.TYPE_TEXT,
        'description': "Slug du plan sur lequel la baie est positionnée.",
    },
    {
        'name': 'plan_x',
        'label': "Position X sur le plan (%)",
        'type': CustomFieldTypeChoices.TYPE_DECIMAL,
        'description': "Abscisse en % de la largeur du plan (0 = bord gauche).",
        'validation_minimum': 0,
        'validation_maximum': 100,
    },
    {
        'name': 'plan_y',
        'label': "Position Y sur le plan (%)",
        'type': CustomFieldTypeChoices.TYPE_DECIMAL,
        'description': "Ordonnée en % de la hauteur du plan (0 = bord haut).",
        'validation_minimum': 0,
        'validation_maximum': 100,
    },
]

for weight, spec in enumerate(FIELDS, start=100):
    name = spec.pop('name')

    # update_or_create plutôt que create : c'est ce qui rend le script rejouable.
    field, created = CustomField.objects.update_or_create(
        name=name,
        defaults={
            **spec,
            'required': False,
            'group_name': "Plan d'usine",   # regroupe les 3 champs dans l'UI du Rack
            'weight': weight,               # ordre d'affichage
        },
    )
    field.object_types.set([RACK_TYPE])

    print(f"{'CRÉÉ  ' if created else 'MAJ   '} custom field « {name} »")

print("\nTerminé. Les 3 champs sont visibles dans l'onglet d'un Rack, "
      "section « Plan d'usine ».")
