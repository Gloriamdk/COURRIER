from datetime import timedelta

from django.test import TestCase
from django.utils import timezone

from courrier.models import Affectation, Courrier, Decision, Relance, User
from courrier.services import get_relances_pour_utilisateur, synchroniser_relances


class AlertesEcheanceTests(TestCase):
    def setUp(self):
        self.ministre = User.objects.create_user(username='min', password='Password123!', role=User.Role.MINISTRE)
        self.sec_min = User.objects.create_user(username='secmin', password='Password123!', role=User.Role.SECRETAIRE_MINISTRE)
        self.sg = User.objects.create_user(username='sg', password='Password123!', role=User.Role.SG)
        self.dc = User.objects.create_user(username='dc', password='Password123!', role=User.Role.DC)
        self.directeur = User.objects.create_user(username='daf', password='Password123!', role=User.Role.DIRECTEUR, service_direction='DAAF')
        self.courrier = Courrier.objects.create(reference='CR-TEST-001', designation='Objet test', expediteur_nom='Test', cree_par=self.ministre, statut=Courrier.Statut.AFFECTE, delai_traitement_jours=5)
        self.decision = Decision.objects.create(courrier=self.courrier, signe_par=self.ministre)

    def affecter(self, limite):
        aff = Affectation.objects.create(courrier=self.courrier, decision=self.decision, affecte_par=self.ministre, destinataire=self.directeur, service_concerne='DAAF')
        Affectation.objects.filter(pk=aff.pk).update(date_limite_traitement=limite)
        aff.refresh_from_db()
        return aff

    def test_alerte_j2_cible_suivi_et_responsable_sans_doublon(self):
        self.affecter(timezone.now() + timedelta(days=2))
        synchroniser_relances()
        self.assertEqual(Relance.objects.filter(courrier=self.courrier, est_resolue=False, nature=Relance.Nature.ECHEANCE_PROCHE).count(), 5)
        self.assertTrue(get_relances_pour_utilisateur(self.ministre).exists())
        self.assertTrue(get_relances_pour_utilisateur(self.directeur).exists())
        synchroniser_relances()
        self.assertEqual(Relance.objects.filter(courrier=self.courrier, est_resolue=False).count(), 5)

    def test_retard_et_confirmation_resolvent_alertes(self):
        aff = self.affecter(timezone.now() - timedelta(minutes=1))
        synchroniser_relances()
        self.assertTrue(Relance.objects.filter(courrier=self.courrier, nature=Relance.Nature.RETARD, est_resolue=False).exists())
        self.client.force_login(self.directeur)
        response = self.client.post(f'/courrier/affectation/{aff.pk}/statut/', {'statut_traitement': 'TRAITE'})
        self.assertEqual(response.status_code, 302)
        aff.refresh_from_db()
        self.assertEqual(aff.traite_par, self.directeur)
        self.assertIsNotNone(aff.date_traitement)
        self.assertFalse(Relance.objects.filter(courrier=self.courrier, est_resolue=False).exists())
