from django.db import migrations


def copy_legacy_sg_analysis(apps, schema_editor):
    FicheAnalyse = apps.get_model("courrier", "FicheAnalyse")
    FicheAnalyseSG = apps.get_model("courrier", "FicheAnalyseSG")

    for legacy in FicheAnalyseSG.objects.all().iterator():
        try:
            fiche = FicheAnalyse.objects.get(courrier_id=legacy.courrier_id)
        except FicheAnalyse.DoesNotExist:
            continue

        updates = {}
        if legacy.analyse_par_id and not fiche.analyse_sg_par_id:
            updates["analyse_sg_par_id"] = legacy.analyse_par_id
        if legacy.observations_sg and not fiche.observations_sg:
            updates["observations_sg"] = legacy.observations_sg
        if legacy.propositions_sg and not fiche.propositions_sg:
            updates["propositions_sg"] = legacy.propositions_sg
        if legacy.date_analyse and not fiche.date_analyse_sg:
            updates["date_analyse_sg"] = legacy.date_analyse
        if legacy.date_validation and not fiche.date_validation_sg:
            updates["date_validation_sg"] = legacy.date_validation
        if legacy.valide and not fiche.valide_sg:
            updates["valide_sg"] = True
        if updates:
            FicheAnalyse.objects.filter(pk=fiche.pk).update(**updates)


class Migration(migrations.Migration):

    dependencies = [
        ("courrier", "0025_ficheanalyse_analyse_sg_par_and_more"),
    ]

    operations = [
        migrations.RunPython(copy_legacy_sg_analysis, migrations.RunPython.noop),
    ]
