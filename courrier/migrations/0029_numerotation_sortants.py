from collections import defaultdict
from uuid import uuid4
from django.db import migrations


def numeroter_sortants(apps, schema_editor):
    Sortant = apps.get_model('courrier', 'CourrierSortant')
    Compteur = apps.get_model('courrier', 'CompteurCourrierSortant')
    using = schema_editor.connection.alias
    sortants = list(Sortant.objects.using(using).order_by('date_enregistrement', 'pk'))
    prefixe = uuid4().hex
    for sortant in sortants:
        Sortant.objects.using(using).filter(pk=sortant.pk).update(reference_sortie=f'tmp-{prefixe}-{sortant.pk}')
    compteurs = defaultdict(int)
    for sortant in sortants:
        annee = sortant.date_enregistrement.year
        compteurs[annee] += 1
        Sortant.objects.using(using).filter(pk=sortant.pk).update(reference_sortie=f'SO-{annee}-{compteurs[annee]:04d}')
    for annee, numero in compteurs.items():
        Compteur.objects.using(using).update_or_create(annee=annee, defaults={'dernier_numero': numero})


class Migration(migrations.Migration):
    dependencies = [('courrier', '0028_compteurcourriersortant')]
    operations = [migrations.RunPython(numeroter_sortants, migrations.RunPython.noop)]
