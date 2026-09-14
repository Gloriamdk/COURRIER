from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('courrier', '0015_remove_configurationdelai_default')]

    operations = [
        migrations.AddField(
            model_name='courrier',
            name='responsable_actuel_role',
            field=models.CharField(blank=True, choices=[
                ('SECRETARIAT_CENTRAL', 'Secrétariat Central'), ('SECRETAIRE_DC', 'Secrétaire du Directeur de Cabinet (DC)'),
                ('DC', 'Directeur de Cabinet (DC)'), ('SECRETAIRE_MINISTRE', 'Secrétaire Particulier du Ministre'),
                ('MINISTRE', 'Ministre'), ('SECRETAIRE_SG', 'Secrétaire du Secrétaire Général (SG)'),
                ('SG', 'Secrétaire Général (SG)'), ('DIRECTEUR', 'Directeur de Département'), ('AGENT', 'Agent'),
            ], max_length=50, null=True, verbose_name='Rôle actuellement détenteur du courrier'),
        ),
    ]
