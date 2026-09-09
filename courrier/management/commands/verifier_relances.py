from django.core.management.base import BaseCommand
from courrier.services import synchroniser_relances
from courrier.models import Relance


class Command(BaseCommand):
    help = "Examine les courriers en attente et génère/actualise les relances pour les courriers sans traitement depuis plus de 3 jours."

    def handle(self, *args, **options):
        self.stdout.write(self.style.NOTICE("Synchronisation des alertes et relances en cours..."))
        synchroniser_relances()
        nb_actives = Relance.objects.filter(est_resolue=False).count()
        self.stdout.write(self.style.SUCCESS(f"Synchronisation terminée avec succès. {nb_actives} relance(s) active(s)."))
