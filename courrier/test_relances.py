from datetime import timedelta
from django.test import TestCase
from django.utils import timezone
from django.urls import reverse

from courrier.models import User, Courrier, Relance, FicheAnalyse, FicheAnalyseSG, Decision, Affectation, Historique, ConfigurationDelai, Notification
from courrier.services import synchroniser_relances, resoudre_relances_courrier, get_relances_pour_utilisateur


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
        self.directeur_dep = User.objects.create_user(
            username="directeur_daf",
            email="dir_daf@mtca.gouv.bj",
            password="Password123!",
            role=User.Role.DIRECTEUR,
            service_direction="DAAF",
            first_name="Daniel",
            last_name="DirDAAF"
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

    def test_relance_creee_automatiquement_selon_delai(self):
        """Un courrier en attente au-delà du délai configuré génère une relance active."""
        date_4_jours_avant = timezone.now() - timedelta(days=4)
        c = Courrier.objects.create(
            reference="CR-2026-0001",
            designation="Dossier de subvention culturelle",
            expediteur_nom="Association Arts & Traditions",
            cree_par=self.sec_central,
            statut=Courrier.Statut.ARRIVE,
            date_arrivee=date_4_jours_avant
        )

        synchroniser_relances()

        relances = Relance.objects.filter(courrier=c, est_resolue=False)
        self.assertTrue(relances.exists())
        relance = relances.first()
        self.assertEqual(relance.etape, Relance.Etape.ARRIVE)
        self.assertGreaterEqual(relance.jours_sans_traitement, 3)

    def test_seul_le_ministre_peut_configurer_le_delai(self):
        """Seul le Ministre peut modifier le délai de traitement; les autres rôles obtiennent 403."""
        # Tentative par le DC (doit échouer avec 403)
        self.client.force_login(self.dc)
        response_dc = self.client.post(reverse('configuration_delai_update'), {'delai_jours': 5})
        self.assertEqual(response_dc.status_code, 403)

        # Tentative par le Secrétaire Général (doit échouer avec 403)
        self.client.force_login(self.sg)
        response_sg = self.client.post(reverse('configuration_delai_update'), {'delai_jours': 5})
        self.assertEqual(response_sg.status_code, 403)

        # Modification autorisée par le Ministre
        self.client.force_login(self.ministre)
        response_min = self.client.post(reverse('configuration_delai_update'), {'delai_jours': 5})
        self.assertEqual(response_min.status_code, 302)
        self.assertEqual(ConfigurationDelai.get_delai_jours(), 5)

        # Vérifier que le nouveau délai de 5 jours est pris en compte :
        # Un courrier vieux de 4 jours ne doit plus être en relance avec un seuil de 5 jours
        date_4_jours_avant = timezone.now() - timedelta(days=4)
        c = Courrier.objects.create(
            reference="CR-2026-0002",
            designation="Demande de partenariat",
            expediteur_nom="Société X",
            cree_par=self.sec_central,
            statut=Courrier.Statut.ARRIVE,
            date_arrivee=date_4_jours_avant
        )
        synchroniser_relances()
        self.assertFalse(Relance.objects.filter(courrier=c, est_resolue=False).exists())

    def test_visibilite_alertes_pour_utilisateurs_concernes(self):
        """Les alertes doivent être visibles par le Ministre, SG, DC, Secrétaires (SG, DC, Ministre) et Directeurs concernés."""
        date_5_jours_avant = timezone.now() - timedelta(days=5)

        # Courrier 1 chez le DC
        c1 = Courrier.objects.create(
            reference="CR-2026-0010",
            designation="Dossier en analyse chez le DC",
            expediteur_nom="Ambassade",
            cree_par=self.sec_central,
            statut=Courrier.Statut.TRANSMIS_DC,
            date_arrivee=date_5_jours_avant
        )

        # Courrier 2 affecté à la DAAF
        c2 = Courrier.objects.create(
            reference="CR-2026-0020",
            designation="Exécution budget DAAF",
            expediteur_nom="Contrôle Financier",
            cree_par=self.sec_central,
            statut=Courrier.Statut.AFFECTE,
            date_arrivee=date_5_jours_avant
        )
        dec2 = Decision.objects.create(
            courrier=c2,
            signe_par=self.ministre,
            instructions_finales="Pour exécution par la DAAF"
        )
        aff2 = Affectation.objects.create(
            courrier=c2,
            decision=dec2,
            service_concerne="DAAF",
            destinataire=self.agent_daf,
            affecte_par=self.ministre,
            statut_traitement=Affectation.StatutTraitement.RECU
        )
        Affectation.objects.filter(pk=aff2.pk).update(date_affectation=date_5_jours_avant)

        synchroniser_relances()

        # Ministre, SG, DC, Secrétaires (SG, DC, Ministre) ont la vue de supervision
        for supervisory_user in [self.ministre, self.sg, self.dc, self.sec_dc, self.sec_sg, self.sec_min]:
            relances = get_relances_pour_utilisateur(supervisory_user)
            refs = set(relances.values_list('courrier__reference', flat=True))
            self.assertIn("CR-2026-0010", refs, f"{supervisory_user.username} devrait voir CR-2026-0010")
            self.assertIn("CR-2026-0020", refs, f"{supervisory_user.username} devrait voir CR-2026-0020")

        # Directeur DAAF doit voir le courrier affecté à sa direction (DAAF)
        relances_dir = get_relances_pour_utilisateur(self.directeur_dep)
        refs_dir = set(relances_dir.values_list('courrier__reference', flat=True))
        self.assertIn("CR-2026-0020", refs_dir)

    def test_courriers_urgents_et_alertes_identifiables(self):
        """Un courrier urgent conserve son statut et génère des alertes identifiables '🚨 [Courrier urgent]'."""
        c_urgent = Courrier.objects.create(
            reference="CR-2026-URG-01",
            designation="Projet Urgent de Décret",
            expediteur_nom="Secrétariat Général du Gouvernement",
            cree_par=self.sec_central,
            statut=Courrier.Statut.ARRIVE,
            priorite=Courrier.Priorite.URGENT
        )

        # La transmission génère une notification contenant [Courrier urgent]
        self.client.force_login(self.sec_dc)
        self.client.post(reverse('courrier_transmettre', kwargs={'courrier_id': c_urgent.pk}))

        c_urgent.refresh_from_db()
        self.assertEqual(c_urgent.priorite, Courrier.Priorite.URGENT)

        notif = Notification.objects.filter(courrier=c_urgent).first()
        self.assertIsNotNone(notif)
        self.assertIn("Courrier urgent", notif.message)

    def test_resolution_automatique_lors_du_traitement(self):
        """Lorsqu'une action est effectuée, l'ancienne relance est clôturée automatiquement."""
        date_4_jours_avant = timezone.now() - timedelta(days=4)
        c = Courrier.objects.create(
            reference="CR-2026-0050",
            designation="Courrier à transmettre",
            expediteur_nom="Partenaire",
            cree_par=self.sec_central,
            statut=Courrier.Statut.ARRIVE,
            date_arrivee=date_4_jours_avant
        )

        synchroniser_relances()
        self.assertTrue(Relance.objects.filter(courrier=c, etape=Relance.Etape.ARRIVE, est_resolue=False).exists())

        # Action: transmission par le Secrétaire DC
        self.client.force_login(self.sec_dc)
        self.client.post(reverse('courrier_transmettre', kwargs={'courrier_id': c.pk}))

        # L'ancienne relance doit être résolue
        relance = Relance.objects.filter(courrier=c, etape=Relance.Etape.ARRIVE).first()
        self.assertTrue(relance.est_resolue)
        self.assertIsNotNone(relance.date_resolution)

