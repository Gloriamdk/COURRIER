# Generated manually: the processing deadline is defined only by the Minister.

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('courrier', '0014_configurationdelai')]

    operations = [
        migrations.AlterField(
            model_name='configurationdelai',
            name='delai_jours',
            field=models.PositiveIntegerField(
                help_text="Nombre de jours sans traitement avant déclenchement d'une alerte et relance automatique.",
                verbose_name='Délai limite de traitement (en jours)',
            ),
        ),
    ]
