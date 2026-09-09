from datetime import timedelta
from django.test import TestCase
from django.utils import timezone
from django.urls import reverse

from courrier.models import User, Courrier, Relance, FicheAnalyse, FicheAnalyseSG, Decision, Affectation, Historique
from courrier.services import synchroniser_relances, resoudre_relances_courrier, get_relances_pour_utilisateur, DELAI_RELANCE_JOURS


class RelanceSystemTests(TestCase):
    def setUp(self):
        # Création des utilisateurs avec différents rôles
        self.sec_central = User.objects.create_user(
            username="sec_central",
            email="sec_central@mtca.gouv.bj",
            password="Password123!",
            role=User.Role.SECRETARIAT_CENTRAL,
            first_name="Alice",
            last_name="Central"
        )
        self.sec_dc = User.objects.create_user(
            username="sec_dc",
            email="sec_dc@mtca.gouv.bj",
            password="Password123!",
            role=User.Role.SECRETAIRE_DC,
            first_name="Bruno",
            last_name="SecDC"
        )
        self.dc = User.objects.create_user(
            username="dc_user",
            email="dc@mtca.gouv.bj",
            password="Password123!",
            role=User.Role.DC,
            first_name="Charles",
            last_name="DirecteurCab"
        )
        self.sec_sg = User.objects.create_user(
            username="sec_sg",
            email="sec_sg@mtca.gouv.bj",
            password="Password123!",
            role=User.Role.SECRETAIRE_SG,
            first_name="Diane",
            last_name="SecSG"
        )
        self.sg = User.objects.create_user(
            username="sg_user",
            email="sg@mtca.gouv.bj",
            password="Password123!",
            role=User.Role.SG,
            first_name="Eric",
            last_name="SecGen"
        )
        self.sec_min = User.objects.create_user(
            username="sec_min",
            email="sec_min@mtca.gouv.bj",
            password="Password123!",
            role=User.Role.SECRETAIRE_MINISTRE,
            first_name="Fanny",
            last_name="SecMin"
        )
        self.ministre = User.objects.create_user(
            username="ministre_user",
            email="ministre@mtca.gouv.bj",
            password="Password123!",
            role=User.Role.MINISTRE,
            first_name="Guy",
            last_name="Ministre"
        )
        self.agent_daf = User.objects.create_user(
            username="agent_daf",
            email="agent@mtca.gouv.bj",
            password="Password123!",
            role=User.Role.AGENT,
            service_direction="DAAF",
            first_name="Henri",
            last_name="AgentDAAF"
        )

    def test_relance_creee_automatiquement_apres_3_jours(self):
        """Un courrier arrivé il y a 4 jours doit générer une relance active."""
        date_4_jours_avant = timezone.now() - timedelta(days=4)
        c = Courrier.objects.create(
            reference="CR-2026-0001",
            designation="Dossier de subvention culturelle",
            expediteur_nom="Association Arts & Traditions",
            cree_par=self.sec_central,
            statut=Courrier.Statut.ARRIVE,
            date_arrivee=date_4_jours_avant
        )

        # Synchroniser
        synchroniser_relances()

        # Vérifier qu'une relance active existe pour l'étape ARRIVE
        relances = Relance.objects.filter(courrier=c, est_resolue=False)
        self.assertTrue(relances.exists())
        relance = relances.first()
        self.assertEqual(relance.etape, Relance.Etape.ARRIVE)
        self.assertGreaterEqual(relance.jours_sans_traitement, 3)

    def test_pas_de_relance_si_moins_de_3_jours(self):
        """Un courrier arrivé il y a 1 jour ne doit pas générer de relance."""
        date_1_jour_avant = timezone.now() - timedelta(days=1)
        c = Courrier.objects.create(
            reference="CR-2026-0002",
            designation="Demande d'audience",
            expediteur_nom="Société Bénin Tour",
            cree_par=self.sec_central,
            statut=Courrier.Statut.ARRIVE,
            date_arrivee=date_1_jour_avant
        )

        synchroniser_relances()
        relances = Relance.objects.filter(courrier=c, est_resolue=False)
        self.assertFalse(relances.exists())

    def test_non_duplication_des_relances(self):
        """Deux synchronisations successives ne doivent pas créer de doublon pour le même retard."""
        date_5_jours_avant = timezone.now() - timedelta(days=5)
        c = Courrier.objects.create(
            reference="CR-2026-0003",
            designation="Projet Festival des Arts",
            expediteur_nom="Mairie de Ouidah",
            cree_par=self.sec_central,
            statut=Courrier.Statut.ARRIVE,
            date_arrivee=date_5_jours_avant
        )

        synchroniser_relances()
        count_apres_1 = Relance.objects.filter(courrier=c, est_resolue=False).count()

        synchroniser_relances()
        count_apres_2 = Relance.objects.filter(courrier=c, est_resolue=False).count()

        self.assertEqual(count_apres_1, count_apres_2)

    def test_resolution_automatique_lors_de_la_transmission(self):
        """Dès que le secrétaire transmet le courrier, la relance d'arrivée est résolue."""
        date_4_jours_avant = timezone.now() - timedelta(days=4)
        c = Courrier.objects.create(
            reference="CR-2026-0004",
            designation="Courrier pour le DC",
            expediteur_nom="Ambassade",
            cree_par=self.sec_central,
            statut=Courrier.Statut.ARRIVE,
            date_arrivee=date_4_jours_avant
        )

        synchroniser_relances()
        self.assertTrue(Relance.objects.filter(courrier=c, etape=Relance.Etape.ARRIVE, est_resolue=False).exists())

        # Le secrétaire DC transmet le courrier
        self.client.force_login(self.sec_dc)
        response = self.client.post(reverse('courrier_transmettre', kwargs={'courrier_id': c.pk}))
        self.assertEqual(response.status_code, 302)

        # L'ancienne relance de l'étape arrivée doit être résolue
        relance_arrivee = Relance.objects.filter(courrier=c, etape=Relance.Etape.ARRIVE).first()
        self.assertTrue(relance_arrivee.est_resolue)
        self.assertIsNotNone(relance_arrivee.date_resolution)

        # Le courrier est passé à TRANSMIS_DC, pas de nouvelle relance immédiate car nouveau délai commence
        c.refresh_from_db()
        self.assertEqual(c.statut, Courrier.Statut.TRANSMIS_DC)
        relances_actives = Relance.objects.filter(courrier=c, est_resolue=False)
        self.assertFalse(relances_actives.exists())

    def test_filtrage_roles_secretaires_vs_acteurs(self):
        """Les secrétaires voient toutes les relances, tandis que le DC ne voit que la sienne."""
        date_4_jours_avant = timezone.now() - timedelta(days=4)
        
        # Courrier 1: Bloqué chez le DC
        c1 = Courrier.objects.create(
            reference="CR-2026-0010",
            designation="Dossier stratégique DC",
            expediteur_nom="Partenaire",
            cree_par=self.sec_central,
            statut=Courrier.Statut.TRANSMIS_DC,
            date_arrivee=date_4_jours_avant
        )
        # Courrier 2: Bloqué chez le Ministre
        c2 = Courrier.objects.create(
            reference="CR-2026-0020",
            designation="Dossier décision Ministre",
            expediteur_nom="Présidence",
            cree_par=self.sec_central,
            statut=Courrier.Statut.TRANSMIS_MINISTRE,
            date_arrivee=date_4_jours_avant
        )

        synchroniser_relances()

        # Secrétaire DC : doit voir TOUTES les relances actives (vue globale)
        relances_sec = get_relances_pour_utilisateur(self.sec_dc)
        refs_sec = set(relances_sec.values_list('courrier__reference', flat=True))
        self.assertIn("CR-2026-0010", refs_sec)
        self.assertIn("CR-2026-0020", refs_sec)

        # DC : ne doit voir QUE sa relance (CR-2026-0010), pas celle du Ministre (CR-2026-0020)
        relances_dc = get_relances_pour_utilisateur(self.dc)
        refs_dc = set(relances_dc.values_list('courrier__reference', flat=True))
        self.assertIn("CR-2026-0010", refs_dc)
        self.assertNotIn("CR-2026-0020", refs_dc)

        # Ministre : ne doit voir QUE sa relance (CR-2026-0020)
        relances_min = get_relances_pour_utilisateur(self.ministre)
        refs_min = set(relances_min.values_list('courrier__reference', flat=True))
        self.assertIn("CR-2026-0020", refs_min)
        self.assertNotIn("CR-2026-0010", refs_min)

    def test_dashboard_contient_alertes_et_badges(self):
        """Le tableau de bord doit contenir les variables de contexte de relance."""
        date_4_jours_avant = timezone.now() - timedelta(days=4)
        Courrier.objects.create(
            reference="CR-2026-0099",
            designation="Courrier très en retard",
            expediteur_nom="UNESCO",
            cree_par=self.sec_central,
            statut=Courrier.Statut.ARRIVE,
            date_arrivee=date_4_jours_avant
        )

        self.client.force_login(self.sec_central)
        response = self.client.get(reverse('dashboard'))
        self.assertEqual(response.status_code, 200)
        self.assertIn('relances_actives', response.context)
        self.assertIn('nb_relances', response.context)
        self.assertGreaterEqual(response.context['nb_relances'], 1)
        self.assertContains(response, "CR-2026-0099")
        self.assertContains(response, "Système d'Alertes et Relances")
