from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [('courrier', '0016_courrier_responsable_actuel_role')]

    operations = [
        migrations.AddField(model_name='courrier', name='delai_traitement_jours', field=models.PositiveIntegerField(blank=True, null=True, verbose_name='Délai de traitement fixé par le Ministre (jours)')),
        migrations.AddField(model_name='affectation', name='date_limite_traitement', field=models.DateTimeField(blank=True, null=True, verbose_name='Date limite de traitement')),
        migrations.AddField(model_name='affectation', name='traite_par', field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='affectations_traitees', to=settings.AUTH_USER_MODEL, verbose_name='Traitement confirmé par')),
        migrations.AddField(model_name='relance', name='nature', field=models.CharField(blank=True, choices=[('ECHEANCE_PROCHE', 'Échéance proche'), ('RETARD', 'Courrier en retard')], max_length=30, null=True, verbose_name="Nature de l'alerte")),
        migrations.AddField(model_name='relance', name='date_limite', field=models.DateTimeField(blank=True, null=True, verbose_name='Date limite concernée')),
    ]
