from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ('courrier', '0017_delais_par_courrier_et_alertes_echeance'),
    ]

    operations = [
        migrations.AlterField(
            model_name='courrier',
            name='statut',
            field=models.CharField(
                choices=[
                    ('ARRIVE', 'Enregistré (Secrétariat Central)'),
                    ('REJETE_SECRETAIRE', 'Rejeté par Secrétariat pour correction'),
                    ('TRANSMIS_SG', 'Transmis au SG'),
                    ('EN_COURS_SG', "En cours d'analyse (SG)"),
                    ('TRANSMIS_DC', 'Transmis au Secrétaire du DC'),
                    ('EN_COURS_DC', "En cours d'analyse (DC)"),
                    ('ANALYSE_VALIDE', 'Analyse validée (DC/SG)'),
                    ('TRANSMIS_MINISTRE', 'Transmis au Ministre'),
                    ('DECIDE', "Décidé (En attente d'affectation)"),
                    ('AFFECTE', 'Affecté aux services'),
                    ('TERMINE', 'Traité'),
                ],
                default='ARRIVE',
                max_length=50,
                verbose_name='Statut du traitement',
            ),
        ),
    ]
