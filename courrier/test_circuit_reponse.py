from django.test import TestCase, override_settings
from django.urls import reverse
from .models import User, Courrier, Decision, Affectation, ReponseCourrier


@override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
class CircuitReponseTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.users = {role: User.objects.create_user(username=role, role=role, service_direction="DAF") for role in User.Role.values}
        cls.agent = cls.users[User.Role.AGENT]
        cls.courrier = Courrier.objects.create(reference="TEST-CIRCUIT", designation="Test réponse", cree_par=cls.users[User.Role.SECRETARIAT_CENTRAL], statut=Courrier.Statut.AFFECTE)
        decision = Decision.objects.create(courrier=cls.courrier, signe_par=cls.users[User.Role.MINISTRE])
        Affectation.objects.create(courrier=cls.courrier, decision=decision, affecte_par=cls.users[User.Role.MINISTRE], destinataire=cls.agent, service_concerne="DAF")

    def test_agent_page_and_detail_link(self):
        self.client.force_login(self.agent)
        url = reverse("circuit_reponse", args=[self.courrier.pk])
        self.assertContains(self.client.get(url), "Soumettre au Directeur")
        detail = self.client.get(reverse("courrier_detail", args=[self.courrier.pk]))
        self.assertContains(detail, url)
        self.assertNotContains(detail, 'name="fichier"')

    def test_access_requires_login_and_assignment(self):
        url = reverse("circuit_reponse", args=[self.courrier.pk])
        self.assertEqual(self.client.get(url).status_code, 302)
        outsider = User.objects.create_user(username="outsider", role=User.Role.AGENT)
        self.client.force_login(outsider)
        self.assertEqual(self.client.get(url).status_code, 404)

    def test_actions_for_each_stage(self):
        cases = [
            (User.Role.SECRETAIRE_SG, Courrier.Statut.TRANSMIS_SG, "Transmettre au SG"),
            (User.Role.SG, Courrier.Statut.EN_COURS_SG, "Observations du SG"),
            (User.Role.SECRETAIRE_DC, Courrier.Statut.TRANSMIS_DC, "Transmettre au DC"),
            (User.Role.DC, Courrier.Statut.EN_COURS_DC, "Observations du DC"),
            (User.Role.SECRETAIRE_MINISTRE, Courrier.Statut.ANALYSE_VALIDE, "Transmettre au Ministre"),
            (User.Role.MINISTRE, Courrier.Statut.TRANSMIS_MINISTRE, "Examiner et signer"),
        ]
        for role, status, label in cases:
            with self.subTest(role=role):
                self.courrier.statut = status
                self.courrier.save(update_fields=["statut"])
                self.client.force_login(self.users[role])
                self.assertContains(self.client.get(reverse("circuit_reponse", args=[self.courrier.pk])), label)

    def test_submission_validation_and_transmission_return_to_circuit(self):
        self._create_alerts()
        target = reverse("circuit_reponse", args=[self.courrier.pk])
        self.client.force_login(self.agent)
        response = self.client.post(reverse("reponse_nouveau", args=[self.courrier.pk]), {"observation": "Ma réponse", "retour": "circuit_reponse"})
        self.assertRedirects(response, target)
        reponse = ReponseCourrier.objects.get(courrier=self.courrier)
        self.client.force_login(self.users[User.Role.DIRECTEUR])
        self.assertContains(self.client.get(target), "Valider la réponse")
        response = self.client.post(reverse("reponse_valider", args=[self.courrier.pk, reponse.pk]), {"decision": "valider", "retour": "circuit_reponse"})
        self.assertRedirects(response, target)
        response = self.client.post(reverse("directeur_transmettre_sg", args=[self.courrier.pk]), {"retour": "circuit_reponse"})
        self.assertRedirects(response, target)
        self.client.force_login(self.users[User.Role.SECRETAIRE_SG])
        response = self.client.post(reverse("courrier_transmettre", args=[self.courrier.pk]), {"retour": "circuit_reponse"})
        self.assertRedirects(response, target)
        self.courrier.refresh_from_db()
        self.assertEqual(self.courrier.statut, Courrier.Statut.EN_COURS_SG)

        for role, route, payload, expected in [
            (User.Role.SG, "fiche_sg_valider", {"action": "valider", "observation": "Avis SG"}, Courrier.Statut.TRANSMIS_DC),
            (User.Role.SECRETAIRE_DC, "courrier_transmettre", {}, Courrier.Statut.EN_COURS_DC),
            (User.Role.DC, "fiche_valider", {"action": "valider", "observation": "Avis DC"}, Courrier.Statut.ANALYSE_VALIDE),
            (User.Role.SECRETAIRE_MINISTRE, "courrier_transmettre", {}, Courrier.Statut.TRANSMIS_MINISTRE),
        ]:
            with self.subTest(role=role):
                self.client.force_login(self.users[role])
                response = self.client.post(reverse(route, args=[self.courrier.pk]), {**payload, "retour": "circuit_reponse"})
                self.assertRedirects(response, target)
                self.courrier.refresh_from_db()
                self.assertEqual(self.courrier.statut, expected)
                self.assertTrue(self.courrier.relances.filter(est_resolue=False).exists())

    def test_correction_and_treatment_without_written_response(self):
        self.client.force_login(self.agent)
        self.courrier.reponse_requise = False
        self.courrier.save(update_fields=["reponse_requise"])
        target = reverse("circuit_reponse", args=[self.courrier.pk])
        self.assertContains(self.client.get(target), 'name="mode" value="sans_reponse"')
        self.client.post(reverse("reponse_nouveau", args=[self.courrier.pk]), {"mode": "sans_reponse", "observation": "Traitement effectué", "retour": "circuit_reponse"})
        reponse = ReponseCourrier.objects.get(courrier=self.courrier)
        self.client.force_login(self.users[User.Role.DIRECTEUR])
        response = self.client.post(reverse("reponse_valider", args=[self.courrier.pk, reponse.pk]), {"decision": "corriger", "observation": "Compléter le compte-rendu", "retour": "circuit_reponse"})
        self.assertRedirects(response, target)
        self.client.force_login(self.agent)
        page = self.client.get(target)
        self.assertContains(page, "Soumettre une version corrigée")
        self.assertContains(page, "Compléter le compte-rendu")

    def _create_alerts(self):
        from datetime import timedelta
        from django.utils import timezone
        from .services import synchroniser_relances
        self.courrier.delai_traitement_jours = 3
        self.courrier.save(update_fields=['delai_traitement_jours'])
        self.courrier.affectations.update(date_limite_traitement=timezone.now() - timedelta(hours=1))
        synchroniser_relances()
        self.assertTrue(self.courrier.relances.filter(est_resolue=False).exists())

    def test_terrain_validation_closes_everywhere_and_never_creates_outgoing(self):
        from .models import CourrierSortant
        from .services import synchroniser_relances
        self.courrier.reponse_requise = False
        self.courrier.save(update_fields=['reponse_requise'])
        self._create_alerts()
        self.client.force_login(self.agent)
        self.client.post(reverse('reponse_nouveau', args=[self.courrier.pk]), {'mode': 'sans_reponse', 'observation': 'Intervention réalisée'})
        reponse = ReponseCourrier.objects.get(courrier=self.courrier)
        self.assertTrue(self.courrier.relances.filter(est_resolue=False).exists())
        self.client.force_login(self.users[User.Role.DIRECTEUR])
        response = self.client.post(reverse('reponse_valider', args=[self.courrier.pk, reponse.pk]), {'decision': 'valider'})
        self.assertEqual(response.status_code, 302)
        self.courrier.refresh_from_db()
        self.assertEqual(self.courrier.statut, Courrier.Statut.TERMINE)
        self.assertFalse(self.courrier.affectations.exclude(statut_traitement='TRAITE').exists())
        synchroniser_relances()
        self.assertFalse(self.courrier.relances.filter(est_resolue=False).exists())
        self.assertFalse(CourrierSortant.objects.filter(courrier=self.courrier).exists())
        self.client.force_login(self.agent)
        self.assertEqual(self.client.post(reverse('affectation_statut_update', args=[self.courrier.affectations.first().pk]), {'statut_traitement': 'EN_COURS'}).status_code, 403)

    def test_signature_closes_and_automatically_registers_outgoing(self):
        import tempfile
        from django.core.files.uploadedfile import SimpleUploadedFile
        from .models import CourrierSortant, DecisionFinale
        from .services import synchroniser_relances, resoudre_relances_courrier
        self._create_alerts()
        self.courrier.statut = Courrier.Statut.TRANSMIS_MINISTRE
        self.courrier.save(update_fields=['statut'])
        ReponseCourrier.objects.create(courrier=self.courrier, auteur=self.agent, version=1, statut_traitement=ReponseCourrier.Statut.VALIDE, observation='Lettre validée')
        resoudre_relances_courrier(self.courrier)
        self.assertTrue(self.courrier.relances.filter(est_resolue=False).exists())
        self.client.force_login(self.users[User.Role.MINISTRE])
        url = reverse('decision_nouveau', args=[self.courrier.pk])
        page = self.client.get(url)
        self.assertNotContains(page, 'name="observation_correction"')
        response = self.client.post(url, {'action_finale': 'valider'})
        self.assertEqual(response.status_code, 200)
        self.assertFalse(CourrierSortant.objects.filter(courrier=self.courrier).exists())
        with tempfile.TemporaryDirectory() as media, override_settings(MEDIA_ROOT=media):
            response = self.client.post(url, {'action_finale': 'valider', 'document_signe': SimpleUploadedFile('signature.pdf', b'%PDF-1.4 signed', content_type='application/pdf')})
            self.assertEqual(response.status_code, 302)
            self.courrier.refresh_from_db()
            self.assertEqual(self.courrier.statut, Courrier.Statut.TERMINE)
            self.assertEqual(self.courrier.responsable_actuel_role, User.Role.SECRETARIAT_CENTRAL)
            self.assertFalse(self.courrier.affectations.exclude(statut_traitement='TRAITE').exists())
            sortie = CourrierSortant.objects.get(courrier=self.courrier)
            self.assertEqual(sortie.document_id, DecisionFinale.objects.get(courrier=self.courrier).document_signe_id)
            self.assertIsNone(sortie.date_expedition)
            synchroniser_relances()
            self.assertFalse(self.courrier.relances.filter(est_resolue=False).exists())
            self.assertEqual(self.client.post(url, {'action_finale': 'valider'}).status_code, 404)
            self.assertEqual(CourrierSortant.objects.filter(courrier=self.courrier).count(), 1)
            self.client.force_login(self.users[User.Role.SECRETARIAT_CENTRAL])
            self.assertContains(self.client.get(reverse('dashboard')), sortie.reference_sortie)

    def test_director_must_choose_treatment_at_assignment(self):
        from unittest.mock import patch
        self.courrier.affectations.update(destinataire=None)
        self.courrier.delai_traitement_jours = 3
        self.courrier.save(update_fields=['delai_traitement_jours'])
        self.client.force_login(self.users[User.Role.DIRECTEUR])
        url = reverse('affectation_nouveau', args=[self.courrier.pk])
        self.assertContains(self.client.get(url), 'name="type_traitement"')
        data = {'destinataire': self.agent.pk, 'service_concerne': '', 'note_traitement': 'Intervention sur place'}
        self.assertEqual(self.client.post(url, data).status_code, 200)
        self.assertEqual(self.courrier.affectations.count(), 1)
        with patch('courrier.views.envoyer_email_affectation'):
            response = self.client.post(url, {**data, 'type_traitement': 'TERRAIN'})
        self.assertEqual(response.status_code, 302)
        self.courrier.refresh_from_db()
        self.assertFalse(self.courrier.reponse_requise)
        self.assertTrue(self.courrier.affectations.filter(destinataire=self.agent).exists())

    def test_manual_closure_is_unavailable_and_forbidden(self):
        for role in [User.Role.AGENT, User.Role.DIRECTEUR]:
            with self.subTest(role=role):
                self.client.force_login(self.users[role])
                self.assertNotContains(self.client.get(reverse('dashboard')), 'Marquer comme traité')
                aff = self.courrier.affectations.first()
                aff.destinataire = self.users[role]
                aff.save(update_fields=['destinataire'])
                self.assertEqual(self.client.post(reverse('affectation_statut_update', args=[aff.pk]), {'statut_traitement': 'TRAITE'}).status_code, 403)
                aff.refresh_from_db()
                self.assertEqual(aff.statut_traitement, Affectation.StatutTraitement.RECU)

    def test_terrain_report_cannot_be_empty_or_validated_by_another_direction(self):
        self.courrier.reponse_requise = False
        self.courrier.save(update_fields=['reponse_requise'])
        self.client.force_login(self.agent)
        url = reverse('reponse_nouveau', args=[self.courrier.pk])
        self.client.post(url, {'mode': 'sans_reponse', 'observation': '   '})
        self.assertFalse(ReponseCourrier.objects.filter(courrier=self.courrier).exists())
        self.client.post(url, {'mode': 'sans_reponse', 'observation': 'Rapport terrain'})
        other = User.objects.create_user(username='other_director', role=User.Role.DIRECTEUR, service_direction='DEC')
        self.client.force_login(other)
        reponse = ReponseCourrier.objects.get(courrier=self.courrier)
        response = self.client.post(reverse('reponse_valider', args=[self.courrier.pk, reponse.pk]), {'decision': 'valider'})
        self.assertIn(response.status_code, [403, 404])
        self.courrier.refresh_from_db()
        self.assertEqual(self.courrier.statut, Courrier.Statut.SOUMIS_DIRECTEUR)

    def test_libelle_reponse_selon_role(self):
        for role, user in self.users.items():
            with self.subTest(role=role):
                self.client.force_login(user)
                page = self.client.get(reverse('courrier_detail', args=[self.courrier.pk]))
                if role == User.Role.AGENT:
                    self.assertContains(page, 'Rédiger une réponse')
                    self.assertNotContains(page, 'Consulter une réponse')
                else:
                    self.assertContains(page, 'Consulter une réponse')
                    self.assertNotContains(page, 'Rédiger une réponse')
