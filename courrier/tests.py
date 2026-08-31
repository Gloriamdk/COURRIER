from django.test import TestCase
from django.contrib.auth import get_user_model
from django.utils import timezone
from courrier.models import Courrier, Document, FicheAnalyse, Decision, Affectation, Historique, Notification

User = get_user_model()

class CourrierModelsTestCase(TestCase):
    def setUp(self):
        # 1. Création des utilisateurs avec différents rôles
        self.sc = User.objects.create_user(
            username="sc_user", password="password123", role=User.Role.SECRETARIAT_CENTRAL, first_name="Jean", last_name="Dupont"
        )
        self.dc = User.objects.create_user(
            username="dc_user", password="password123", role=User.Role.DC, first_name="Paul", last_name="Cabinet"
        )
        self.ministre = User.objects.create_user(
            username="ministre_user", password="password123", role=User.Role.MINISTRE, first_name="Grand", last_name="Ministre"
        )
        self.dir_daf = User.objects.create_user(
            username="daf_user", password="password123", role=User.Role.DIRECTEUR, service_direction="DAF", first_name="Alice", last_name="Finances"
        )
        self.agent = User.objects.create_user(
            username="agent_user", password="password123", role=User.Role.AGENT, service_direction="DAF", first_name="Marc", last_name="Saisie"
        )

        # 2. Création de courriers avec différents niveaux de confidentialité
        self.courrier_normal = Courrier.objects.create(
            reference="CR-2026-001",
            designation="Demande d'audience pour projet routier",
            resume="Demande d'audience formulée par l'entreprise XYZ.",
            expediteur_nom="Entreprise XYZ",
            cree_par=self.sc
        )



    def test_user_creation_and_roles(self):
        """Vérifie la bonne création des utilisateurs et l'attribution des rôles."""
        self.assertEqual(self.sc.role, User.Role.SECRETARIAT_CENTRAL)
        self.assertEqual(self.dc.role, User.Role.DC)
        self.assertEqual(self.ministre.role, User.Role.MINISTRE)
        self.assertEqual(self.dir_daf.service_direction, "DAF")
        self.assertTrue("Jean Dupont" in str(self.sc) or "sc_user" in str(self.sc))

    def test_role_filters(self):
        """
        Vérifie la sécurité ORM (Risque 1) : Les utilisateurs n'accèdent qu'aux
        courriers autorisés par leur rôle.
        """
        # Ministre doit avoir accès à TOUT (1 courrier)
        courriers_ministre = Courrier.objects.pour_utilisateur(self.ministre)
        self.assertEqual(courriers_ministre.count(), 1)

        # DC doit avoir accès à TOUT (1 courrier)
        courriers_dc = Courrier.objects.pour_utilisateur(self.dc)
        self.assertEqual(courriers_dc.count(), 1)

        # Secrétariat Central enregistre tout et accède à tout (1 courrier)
        courriers_sc = Courrier.objects.pour_utilisateur(self.sc)
        self.assertEqual(courriers_sc.count(), 1)

        # Un Directeur d'un département non affecté n'accède à aucun courrier au début
        courriers_daf = Courrier.objects.pour_utilisateur(self.dir_daf)
        self.assertEqual(courriers_daf.count(), 0)

    def test_service_affectation_visible_for_same_department(self):
        """Un directeur doit voir un courrier affecté à son service même sans destinataire explicite."""
        decision = Decision.objects.create(
            courrier=self.courrier_normal,
            signe_par=self.ministre,
            instructions_finales="Affecter le courrier à la DAF pour traitement."
        )
        self.courrier_normal.statut = Courrier.Statut.DECIDE
        self.courrier_normal.save()

        Affectation.objects.create(
            courrier=self.courrier_normal,
            decision=decision,
            affecte_par=self.ministre,
            destinataire=None,
            service_concerne="DAF",
            statut_traitement=Affectation.StatutTraitement.RECU
        )

        courriers_daf = Courrier.objects.pour_utilisateur(self.dir_daf)
        self.assertEqual(courriers_daf.count(), 1)
        self.assertIn(self.courrier_normal, courriers_daf)

    def test_complete_workflow_models(self):
        """
        Simule le cycle de vie complet en créant les objets liés :
        Courrier -> Fiche Analyse -> Décision -> Affectation -> Historique -> Notification
        """
        # 1. Le DC rédige et valide une fiche d'analyse
        fiche = FicheAnalyse.objects.create(
            courrier=self.courrier_normal,
            analyse_par=self.dc,
            observations_dc="Dossier éligible et d'intérêt public.",
            valide=True,
            date_validation=timezone.now()
        )
        self.courrier_normal.statut = Courrier.Statut.ANALYSE_VALIDE
        self.courrier_normal.save()

        # 2. Le Ministre prend une décision
        decision = Decision.objects.create(
            courrier=self.courrier_normal,
            fiche_analyse=fiche,
            signe_par=self.ministre,
            instructions_finales="Accordé. DAF, veuillez procéder au déblocage des fonds."
        )
        self.courrier_normal.statut = Courrier.Statut.DECIDE
        self.courrier_normal.save()

        # 3. Affectation au Directeur de la DAF
        affectation = Affectation.objects.create(
            courrier=self.courrier_normal,
            decision=decision,
            affecte_par=self.dc,
            destinataire=self.dir_daf,
            service_concerne="DAF",
            statut_traitement=Affectation.StatutTraitement.RECU
        )
        self.courrier_normal.statut = Courrier.Statut.AFFECTE
        self.courrier_normal.save()

        # Une fois affecté, le Directeur de la DAF doit pouvoir voir ce courrier !
        courriers_daf = Courrier.objects.pour_utilisateur(self.dir_daf)
        self.assertEqual(courriers_daf.count(), 1)
        self.assertIn(self.courrier_normal, courriers_daf)

        # 4. Création d'une notification pour le directeur DAF
        notification = Notification.objects.create(
            destinataire=self.dir_daf,
            courrier=self.courrier_normal,
            message=f"Nouveau courrier affecté : {self.courrier_normal.reference}"
        )
        self.assertFalse(notification.lu)

        # 5. Enregistrement d'audit (Historique)
        historique = Historique.objects.create(
            courrier=self.courrier_normal,
            utilisateur=self.dc,
            action="AFFECTATION",
            description=f"Le courrier {self.courrier_normal.reference} a été affecté à la DAF."
        )
        self.assertEqual(historique.utilisateur, self.dc)
        self.assertEqual(self.courrier_normal.historiques.count(), 1)
