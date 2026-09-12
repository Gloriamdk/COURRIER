import io
import os
import zipfile

from django.test import TestCase
from django.test import override_settings
from django.core import mail
from django.contrib.auth import get_user_model
from django.utils import timezone
from django.utils.crypto import get_random_string
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse
from courrier.models import Courrier, CourrierSortant, Document, FicheAnalyse, FicheAnalyseSG, Decision, DecisionFinale, Affectation, Historique, Notification, ReponseCourrier
from courrier.forms import CourrierForm, AffectationForm
from courrier.views import envoyer_email_affectation, envoyer_email_nouveau_courrier
from courrier import validators
from django.conf import settings

User = get_user_model()

class CourrierModelsTestCase(TestCase):
    def setUp(self):
        self.test_password = get_random_string(32)

        # 1. Création des utilisateurs avec différents rôles
        self.sc = User.objects.create_user(
            username="sc_user", password=self.test_password, role=User.Role.SECRETARIAT_CENTRAL, first_name="Jean", last_name="Dupont"
        )
        self.dc = User.objects.create_user(
            username="dc_user", password=self.test_password, role=User.Role.DC, first_name="Paul", last_name="Cabinet"
        )
        self.ministre = User.objects.create_user(
            username="ministre_user", password=self.test_password, role=User.Role.MINISTRE, first_name="Grand", last_name="Ministre"
        )
        self.dir_daf = User.objects.create_user(
            username="daf_user", password=self.test_password, role=User.Role.DIRECTEUR, service_direction="DAF", first_name="Alice", last_name="Finances"
        )
        self.agent = User.objects.create_user(
            username="agent_user", password=self.test_password, role=User.Role.AGENT, service_direction="DAF", first_name="Marc", last_name="Saisie"
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

    @override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
    def test_email_nouveau_courrier_au_ministre(self):
        self.ministre.email = 'ministre@example.test'
        self.ministre.save(update_fields=['email'])

        envoyer_email_nouveau_courrier(self.courrier_normal)

        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, ['ministre@example.test'])
        self.assertIn(self.courrier_normal.reference, mail.outbox[0].body)
        self.assertIn(self.courrier_normal.designation, mail.outbox[0].body)
        self.assertIn(self.courrier_normal.resume, mail.outbox[0].body)

    @override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
    def test_email_affectation_aux_directeurs_du_service(self):
        self.dir_daf.email = 'directeur@example.test'
        self.dir_daf.save(update_fields=['email'])
        decision = Decision.objects.create(
            courrier=self.courrier_normal,
            signe_par=self.ministre,
        )
        affectation = Affectation.objects.create(
            courrier=self.courrier_normal,
            decision=decision,
            affecte_par=self.ministre,
            service_concerne='DAF',
        )

        envoyer_email_affectation(affectation)

        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, ['directeur@example.test'])
        self.assertIn(self.courrier_normal.reference, mail.outbox[0].body)
        self.assertIn(self.courrier_normal.designation, mail.outbox[0].body)

    def test_affectation_form_infer_service_from_agent_direction_and_blocks_other_direction(self):
        from courrier.forms import AffectationForm

        agent_same_direction = User.objects.create_user(
            username='agent_daf_same',
            password=self.test_password,
            role=User.Role.AGENT,
            service_direction='DAF',
            first_name='Marc',
            last_name='Daf',
        )
        agent_other_direction = User.objects.create_user(
            username='agent_dpt_other',
            password=self.test_password,
            role=User.Role.AGENT,
            service_direction='DPT',
            first_name='Jean',
            last_name='Dpt',
        )

        # Service should be inferred from a selected agent's service_direction.
        form_from_agent = AffectationForm(data={'destinataire': agent_same_direction.pk})
        self.assertTrue(form_from_agent.is_valid(), form_from_agent.errors)
        self.assertEqual(form_from_agent.cleaned_data['service_concerne'], 'DAAF')

        # And a selected agent must not be matched to a different service.
        form_cross_service = AffectationForm(data={
            'destinataire': agent_other_direction.pk,
            'service_concerne': 'DAAF',
        })
        self.assertFalse(form_cross_service.is_valid())
        self.assertIn('Le destinataire choisi ne correspond pas au service sélectionné.', str(form_cross_service.errors))

    @override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
    def test_email_affectation_normalise_le_service_concerne(self):
        self.dir_daf.email = 'directeur@example.test'
        self.dir_daf.save(update_fields=['email'])
        decision = Decision.objects.create(
            courrier=self.courrier_normal,
            signe_par=self.ministre,
        )
        affectation = Affectation.objects.create(
            courrier=self.courrier_normal,
            decision=decision,
            affecte_par=self.ministre,
            service_concerne='  DAF  ',
        )

        envoyer_email_affectation(affectation)

        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, ['directeur@example.test'])

    def test_ministre_voit_les_analyses_dc_et_sg_avant_decision(self):
        fiche_dc = FicheAnalyse.objects.create(
            courrier=self.courrier_normal,
            analyse_par=self.dc,
            observations_dc='Observation du DC',
            propositions_dc='Proposition du DC',
            valide=True,
            date_validation=timezone.now(),
        )
        FicheAnalyseSG.objects.create(
            courrier=self.courrier_normal,
            analyse_par=User.objects.create_user(
                username='sg_circuit',
                password=self.test_password,
                role=User.Role.SG,
            ),
            observations_sg='Observation du SG',
            propositions_sg='Proposition du SG',
            valide=True,
            date_validation=timezone.now(),
        )
        self.courrier_normal.statut = Courrier.Statut.TRANSMIS_MINISTRE
        self.courrier_normal.save(update_fields=['statut'])

        self.client.force_login(self.ministre)
        response = self.client.get(
            reverse('decision_nouveau', kwargs={'courrier_id': self.courrier_normal.pk})
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Observation du DC')
        self.assertContains(response, 'Proposition du DC')
        self.assertContains(response, 'Observation du SG')
        self.assertContains(response, 'Proposition du SG')

    def test_fiche_sg_affiche_observations_et_propositions(self):
        Decision.objects.create(courrier=self.courrier_normal, signe_par=self.ministre)
        self.courrier_normal.statut = Courrier.Statut.EN_COURS_SG
        self.courrier_normal.save(update_fields=['statut'])
        self.client.force_login(User.objects.create_user(
            username='sg_interface',
            password=self.test_password,
            role=User.Role.SG,
        ))

        response = self.client.get(
            reverse('fiche_sg_nouveau', kwargs={'courrier_id': self.courrier_normal.pk})
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'id_observations_sg')
        self.assertContains(response, 'id_propositions_sg')

    def test_dc_ne_peut_pas_valider_sans_fiche_sg_validee(self):
        FicheAnalyse.objects.create(
            courrier=self.courrier_normal,
            analyse_par=self.dc,
            observations_dc='Observation DC',
        )
        self.courrier_normal.statut = Courrier.Statut.EN_COURS_DC
        self.courrier_normal.save(update_fields=['statut'])
        self.client.force_login(self.dc)

        response = self.client.post(
            reverse('fiche_valider', kwargs={'courrier_id': self.courrier_normal.pk})
        )
        self.assertEqual(response.status_code, 404)

    def test_reponse_courrier_agent_directeur_workflow_endpoint_exists(self):
        decision = Decision.objects.create(
            courrier=self.courrier_normal,
            signe_par=self.ministre,
            instructions_finales='Instruction finale de décision.',
        )
        Affectation.objects.create(
            courrier=self.courrier_normal,
            decision=decision,
            affecte_par=self.ministre,
            destinataire=self.agent,
            service_concerne='DAAF',
            statut_traitement=Affectation.StatutTraitement.RECU,
        )
        self.courrier_normal.statut = Courrier.Statut.AFFECTE
        self.courrier_normal.responsable_actuel_role = User.Role.AGENT
        self.courrier_normal.save(update_fields=['statut', 'responsable_actuel_role'])

        self.client.force_login(self.agent)
        response = self.client.post(
            reverse('reponse_nouveau', kwargs={'courrier_id': self.courrier_normal.pk}),
            {'observation': 'Réponse proposée par l’agent.'},
            follow=False,
        )

        self.assertEqual(response.status_code, 302)
        self.assertTrue(ReponseCourrier.objects.filter(courrier=self.courrier_normal, auteur=self.agent).exists())

    def test_agent_ne_peut_pas_forcer_une_reponse_si_non_requise(self):
        decision = Decision.objects.create(
            courrier=self.courrier_normal,
            signe_par=self.ministre,
        )
        Affectation.objects.create(
            courrier=self.courrier_normal,
            decision=decision,
            affecte_par=self.ministre,
            destinataire=self.agent,
            service_concerne='DAAF',
        )
        self.courrier_normal.reponse_requise = False
        self.courrier_normal.statut = Courrier.Statut.AFFECTE
        self.courrier_normal.save(update_fields=['reponse_requise', 'statut'])

        self.client.force_login(self.agent)
        response = self.client.post(
            reverse('reponse_nouveau', kwargs={'courrier_id': self.courrier_normal.pk}),
            {'observation': 'Réponse forcée'},
        )
        self.assertEqual(response.status_code, 403)
        self.assertFalse(ReponseCourrier.objects.filter(courrier=self.courrier_normal).exists())

        response = self.client.post(
            reverse('reponse_nouveau', kwargs={'courrier_id': self.courrier_normal.pk}),
            {'mode': 'sans_reponse', 'observation': 'Traitement effectué'},
        )
        self.assertEqual(response.status_code, 302)
        self.assertTrue(ReponseCourrier.objects.filter(courrier=self.courrier_normal).exists())

    def test_directeur_can_transmit_validated_response_to_secretaire_sg(self):
        decision = Decision.objects.create(
            courrier=self.courrier_normal,
            signe_par=self.ministre,
            instructions_finales='Instruction finale.',
        )
        Affectation.objects.create(
            courrier=self.courrier_normal,
            decision=decision,
            affecte_par=self.ministre,
            destinataire=self.agent,
            service_concerne='DAAF',
        )
        ReponseCourrier.objects.create(
            courrier=self.courrier_normal,
            auteur=self.agent,
            version=1,
            statut_traitement=ReponseCourrier.Statut.VALIDE,
            observation='Réponse validée.',
        )
        self.courrier_normal.statut = Courrier.Statut.VALIDE_DIRECTEUR
        self.courrier_normal.save(update_fields=['statut'])

        self.client.force_login(self.dir_daf)
        response = self.client.post(
            reverse(
                'directeur_transmettre_sg',
                kwargs={'courrier_id': self.courrier_normal.pk},
            )
        )

        self.assertEqual(response.status_code, 302)
        self.courrier_normal.refresh_from_db()
        self.assertEqual(self.courrier_normal.statut, Courrier.Statut.EN_COURS_SG)
        self.assertEqual(
            self.courrier_normal.responsable_actuel_role,
            User.Role.SECRETAIRE_SG,
        )
        self.assertTrue(Historique.objects.filter(
            courrier=self.courrier_normal,
            action='TRANSMISSION_DIRECTEUR_SECRETAIRE_SG',
        ).exists())

    def test_ministre_signe_puis_secretariat_enregistre_courrier_sortant(self):
        document = Document.objects.create(
            courrier=self.courrier_normal,
            nom='decision-signee.pdf',
            fichier=SimpleUploadedFile('decision-signee.pdf', b'%PDF-1.4 signed'),
            taille_octets=15,
        )
        decision = Decision.objects.create(
            courrier=self.courrier_normal, signe_par=self.ministre,
            document_signe=document,
        )
        self.courrier_normal.statut = Courrier.Statut.SIGNE_PAR_MINISTRE
        self.courrier_normal.save(update_fields=['statut'])
        self.client.force_login(self.sc)
        response = self.client.post(
            reverse('courrier_sortant_nouveau', kwargs={'courrier_id': self.courrier_normal.pk}),
            {'destinataire': 'Entreprise XYZ', 'objet': 'Réponse officielle'},
        )
        self.assertEqual(response.status_code, 302)
        self.assertTrue(CourrierSortant.objects.filter(courrier=self.courrier_normal).exists())
        self.courrier_normal.refresh_from_db()
        self.assertEqual(self.courrier_normal.statut, Courrier.Statut.COURRIER_SORTANT)
        self.assertTrue(Historique.objects.filter(
            courrier=self.courrier_normal, action='ENREGISTREMENT_COURRIER_SORTANT'
        ).exists())

    def test_decision_finale_apres_affectation_ne_remplace_pas_decision_initiale(self):
        Decision.objects.create(
            courrier=self.courrier_normal,
            signe_par=self.ministre,
            instructions_finales='Instruction initiale.',
        )
        FicheAnalyse.objects.create(
            courrier=self.courrier_normal,
            analyse_par=self.dc,
            valide=True,
        )
        FicheAnalyseSG.objects.create(
            courrier=self.courrier_normal,
            analyse_par=User.objects.create_user(
                username='sg_final_decision', password=self.test_password, role=User.Role.SG,
            ),
            valide=True,
        )
        Affectation.objects.create(
            courrier=self.courrier_normal,
            decision=self.courrier_normal.decision,
            affecte_par=self.ministre,
            destinataire=self.agent,
            service_concerne='DAAF',
        )
        self.courrier_normal.statut = Courrier.Statut.TRANSMIS_MINISTRE
        self.courrier_normal.delai_traitement_jours = 10
        self.courrier_normal.save(update_fields=['statut', 'delai_traitement_jours'])

        self.client.force_login(self.ministre)
        response = self.client.post(
            reverse('decision_nouveau', kwargs={'courrier_id': self.courrier_normal.pk}),
            {
                'instruction_standard': 'POUR_ATTRIBUTION',
                'instructions_finales': 'Décision finale.',
                'delai_traitement_jours': '10',
                'action_finale': 'valider',
                'document_signe': SimpleUploadedFile(
                    'final.pdf', b'%PDF-1.4 final', content_type='application/pdf'
                ),
            },
        )
        self.assertEqual(response.status_code, 302)
        self.assertTrue(DecisionFinale.objects.filter(courrier=self.courrier_normal).exists())
        self.assertEqual(Decision.objects.filter(courrier=self.courrier_normal).count(), 1)
        self.courrier_normal.refresh_from_db()
        self.assertEqual(self.courrier_normal.statut, Courrier.Statut.SIGNE_PAR_MINISTRE)

    def test_directeur_can_see_affectation_button_on_decided_courrier_detail(self):
        decision = Decision.objects.create(
            courrier=self.courrier_normal,
            signe_par=self.ministre,
            instructions_finales='Instruction finale veloutée.',
        )
        Affectation.objects.create(
            courrier=self.courrier_normal,
            decision=decision,
            affecte_par=self.ministre,
            destinataire=self.dir_daf,
            service_concerne='DAAF',
            statut_traitement=Affectation.StatutTraitement.RECU,
        )
        self.courrier_normal.statut = Courrier.Statut.DECIDE
        self.courrier_normal.save(update_fields=['statut'])

        self.client.force_login(self.dir_daf)
        response = self.client.get(
            reverse('courrier_detail', kwargs={'pk': self.courrier_normal.pk})
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Affecter aux services')

    def test_ministre_assignment_history_names_director_destination(self):
        decision = Decision.objects.create(
            courrier=self.courrier_normal,
            signe_par=self.ministre,
            instructions_finales='Transmettre à la direction.',
        )
        self.courrier_normal.statut = Courrier.Statut.DECIDE
        self.courrier_normal.delai_traitement_jours = 5
        self.courrier_normal.save(update_fields=['statut', 'delai_traitement_jours'])

        self.client.force_login(self.ministre)
        response = self.client.post(
            reverse('affectation_nouveau', kwargs={'courrier_id': self.courrier_normal.pk}),
            {
                'destinataire': '',
                'service_concerne': 'DAAF',
                'note_traitement': 'Transmettre au directeur DAAF.',
            },
        )

        self.assertEqual(response.status_code, 302)
        historique = Historique.objects.get(
            courrier=self.courrier_normal,
            action='AFFECTATION',
        )
        self.assertIn('au Directeur de la direction DAAF', historique.description)
        self.assertNotIn('aucun agent', historique.description)

    def test_directeur_dashboard_shows_agent_affectation_action_for_unassigned_direction(self):
        decision = Decision.objects.create(
            courrier=self.courrier_normal,
            signe_par=self.ministre,
            instructions_finales='Affectation à la direction.',
        )
        Affectation.objects.create(
            courrier=self.courrier_normal,
            decision=decision,
            affecte_par=self.ministre,
            destinataire=None,
            service_concerne='DAAF',
            statut_traitement=Affectation.StatutTraitement.RECU,
        )
        self.courrier_normal.statut = Courrier.Statut.AFFECTE
        self.courrier_normal.delai_traitement_jours = 5
        self.courrier_normal.save(update_fields=['statut', 'delai_traitement_jours'])
        self.dir_daf.service_direction = 'DAAF'
        self.dir_daf.save(update_fields=['service_direction'])

        self.client.force_login(self.dir_daf)
        response = self.client.get(reverse('dashboard'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Affecter à un agent')

    def test_affectation_button_hidden_after_courrier_already_affecte(self):
        decision = Decision.objects.create(
            courrier=self.courrier_normal,
            signe_par=self.ministre,
            instructions_finales='Instruction finale.',
        )
        Affectation.objects.create(
            courrier=self.courrier_normal,
            decision=decision,
            affecte_par=self.ministre,
            destinataire=self.agent,
            service_concerne='DAAF',
            statut_traitement=Affectation.StatutTraitement.RECU,
        )
        self.courrier_normal.statut = Courrier.Statut.AFFECTE
        self.courrier_normal.save(update_fields=['statut'])

        self.client.force_login(self.ministre)
        response = self.client.get(
            reverse('courrier_detail', kwargs={'pk': self.courrier_normal.pk})
        )

        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, 'Affecter aux services')

    def test_affectation_create_view_handles_missing_delay_gracefully(self):
        agent_sans_direction = User.objects.create_user(
            username='agent_sans_direction_missing_delay',
            password=self.test_password,
            role=User.Role.AGENT,
            service_direction='',
            first_name='Agent',
            last_name='Sans Direction',
        )
        decision = Decision.objects.create(
            courrier=self.courrier_normal,
            signe_par=self.ministre,
            instructions_finales='Instruction finale.',
        )
        self.courrier_normal.statut = Courrier.Statut.DECIDE
        self.courrier_normal.delai_traitement_jours = None
        self.courrier_normal.decision = decision
        self.courrier_normal.save(update_fields=['statut', 'delai_traitement_jours'])

        self.client.force_login(self.ministre)
        response = self.client.post(
            reverse('affectation_nouveau', kwargs={'courrier_id': self.courrier_normal.pk}),
            {
                'destinataire': agent_sans_direction.pk,
                'service_concerne': '',
                'note_traitement': 'Affectation de test.',
            },
            follow=False,
        )

        self.assertEqual(response.status_code, 302)
        self.assertRedirects(response, reverse('courrier_detail', kwargs={'pk': self.courrier_normal.pk}))

    def test_affectation_create_view_reuses_normalize_service_helper(self):
        agent_sans_direction = User.objects.create_user(
            username='agent_sans_direction_ministre',
            password=self.test_password,
            role=User.Role.AGENT,
            service_direction='',
            first_name='Agent',
            last_name='Hors Direction',
        )
        decision = Decision.objects.create(
            courrier=self.courrier_normal,
            signe_par=self.ministre,
            instructions_finales='Instruction finale.',
        )
        self.courrier_normal.statut = Courrier.Statut.DECIDE
        self.courrier_normal.delai_traitement_jours = 5
        self.courrier_normal.save(update_fields=['statut', 'delai_traitement_jours'])

        self.client.force_login(self.ministre)
        response = self.client.post(
            reverse('affectation_nouveau', kwargs={'courrier_id': self.courrier_normal.pk}),
            {
                'destinataire': agent_sans_direction.pk,
                'service_concerne': '',
                'note_traitement': 'Affectation de test.',
            },
            follow=False,
        )

        self.assertEqual(response.status_code, 302)

    def test_directeur_daff_can_access_courrier_detail_after_service_affectation(self):
        decision = Decision.objects.create(
            courrier=self.courrier_normal,
            signe_par=self.ministre,
            instructions_finales='Affectation service DAAF.',
        )
        Affectation.objects.create(
            courrier=self.courrier_normal,
            decision=decision,
            affecte_par=self.ministre,
            destinataire=None,
            service_concerne='DAAF',
            statut_traitement=Affectation.StatutTraitement.RECU,
        )
        self.courrier_normal.statut = Courrier.Statut.AFFECTE
        self.courrier_normal.responsable_actuel_role = User.Role.DIRECTEUR
        self.courrier_normal.save(update_fields=['statut', 'responsable_actuel_role'])

        # Simule le directeur DAAF : l’utilisateur a la valeur historique DAF
        # mais le courrier porte la valeur métier DAAF.
        self.dir_daf.service_direction = 'DAF'
        self.dir_daf.save(update_fields=['service_direction'])

        self.client.force_login(self.dir_daf)
        response = self.client.get(
            reverse('courrier_detail', kwargs={'pk': self.courrier_normal.pk})
        )

        self.assertEqual(response.status_code, 200)

    def test_affectation_form_exposes_only_agents_as_destinataires(self):
        director = User.objects.create_user(
            username='director_only_in_form',
            password=self.test_password,
            role=User.Role.DIRECTEUR,
            service_direction='DAAF',
        )
        agent_direction = User.objects.create_user(
            username='agent_direction_only_in_form',
            password=self.test_password,
            role=User.Role.AGENT,
            service_direction='DAAF',
        )
        agent_hors_direction = User.objects.create_user(
            username='agent_without_service_direction',
            password=self.test_password,
            role=User.Role.AGENT,
            service_direction='',
        )
        ministre = User.objects.create_user(
            username='minister_user_for_form_scope',
            password=self.test_password,
            role=User.Role.MINISTRE,
            service_direction='',
        )
        form = AffectationForm(request_user=ministre)
        qs = form.fields['destinataire'].queryset
        self.assertFalse(qs.filter(role=User.Role.DIRECTEUR).exists())
        self.assertTrue(qs.filter(role=User.Role.AGENT).exists())
        self.assertFalse(qs.filter(pk=agent_direction.pk).exists())
        self.assertTrue(qs.filter(pk=agent_hors_direction.pk).exists())

    def test_circuit_sequentiel_sc_sg_dc_ministre(self):
        secretaire_sg = User.objects.create_user(
            username='sec_sg_circuit', password=self.test_password,
            role=User.Role.SECRETAIRE_SG,
        )
        secretaire_dc = User.objects.create_user(
            username='sec_dc_circuit', password=self.test_password,
            role=User.Role.SECRETAIRE_DC,
        )
        secretaire_ministre = User.objects.create_user(
            username='sec_min_circuit', password=self.test_password,
            role=User.Role.SECRETAIRE_MINISTRE,
        )
        sg = User.objects.create_user(
            username='sg_circuit', password=self.test_password,
            role=User.Role.SG,
        )

        self.courrier_normal.statut = Courrier.Statut.ARRIVE
        self.courrier_normal.save(update_fields=['statut'])

        self.client.force_login(secretaire_dc)
        self.client.post(reverse('courrier_transmettre', kwargs={'courrier_id': self.courrier_normal.pk}))
        self.courrier_normal.refresh_from_db()
        self.assertEqual(self.courrier_normal.statut, Courrier.Statut.ARRIVE)

        self.client.force_login(secretaire_sg)
        self.client.post(reverse('courrier_transmettre', kwargs={'courrier_id': self.courrier_normal.pk}))
        self.courrier_normal.refresh_from_db()
        self.assertEqual(self.courrier_normal.statut, Courrier.Statut.EN_COURS_SG)

        # Le circuit initial ne crée pas de fiche : le SG et le DC sont des relais.
        self.client.force_login(sg)
        self.client.post(reverse('sg_transmettre_dc', kwargs={'courrier_id': self.courrier_normal.pk}))
        self.courrier_normal.refresh_from_db()
        self.assertEqual(self.courrier_normal.statut, Courrier.Statut.TRANSMIS_DC)

        self.client.force_login(secretaire_dc)
        self.client.post(reverse('courrier_transmettre', kwargs={'courrier_id': self.courrier_normal.pk}))
        self.courrier_normal.refresh_from_db()
        self.assertEqual(self.courrier_normal.statut, Courrier.Statut.EN_COURS_DC)

        self.client.force_login(self.dc)
        self.client.post(reverse('dc_transmettre_ministre', kwargs={'courrier_id': self.courrier_normal.pk}))
        self.courrier_normal.refresh_from_db()
        self.assertEqual(self.courrier_normal.statut, Courrier.Statut.ANALYSE_VALIDE)

        self.client.force_login(secretaire_ministre)
        self.client.post(reverse('courrier_transmettre', kwargs={'courrier_id': self.courrier_normal.pk}))
        self.courrier_normal.refresh_from_db()
        self.assertEqual(self.courrier_normal.statut, Courrier.Statut.TRANSMIS_MINISTRE)

    def test_actions_analyse_visibles_des_reception_du_dossier(self):
        sg = User.objects.create_user(
            username='sg_actions', password=self.test_password,
            role=User.Role.SG,
        )

        self.courrier_normal.statut = Courrier.Statut.TRANSMIS_SG
        self.courrier_normal.save(update_fields=['statut'])
        self.client.force_login(sg)
        response = self.client.get(
            reverse('courrier_detail', kwargs={'pk': self.courrier_normal.pk})
        )
        self.assertContains(response, 'btn-sg-transmettre-dc')
        self.assertNotContains(response, 'btn-rediger-fiche-sg')

        decision = Decision.objects.create(courrier=self.courrier_normal, signe_par=self.ministre)
        Affectation.objects.create(
            courrier=self.courrier_normal, decision=decision,
            affecte_par=self.ministre, destinataire=self.agent, service_concerne='DAAF',
        )
        self.courrier_normal.statut = Courrier.Statut.EN_COURS_SG
        self.courrier_normal.save(update_fields=['statut'])
        FicheAnalyseSG.objects.create(
            courrier=self.courrier_normal, analyse_par=sg, valide=True,
        )
        self.courrier_normal.statut = Courrier.Statut.EN_COURS_DC
        self.courrier_normal.save(update_fields=['statut'])
        self.client.force_login(self.dc)
        response = self.client.get(
            reverse('courrier_detail', kwargs={'pk': self.courrier_normal.pk})
        )
        self.assertContains(response, 'btn-rediger-fiche')
        self.assertContains(response, 'Rédiger les observations du DC')

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

    def test_historique_supports_structured_audit_fields(self):
        """Le journal d'audit doit pouvoir conserver le rôle, la direction, les statuts et l'observation de manière structurée."""
        historique = Historique.objects.create(
            courrier=self.courrier_normal,
            utilisateur=self.sc,
            action='AFFECTATION',
            description='Courrier affecté à la direction DAAF.',
            role=User.Role.SECRETARIAT_CENTRAL,
            direction='DAAF',
            ancien_statut=Courrier.Statut.ARRIVE,
            nouveau_statut=Courrier.Statut.AFFECTE,
            observation='Transmission au directeur de la DAAF.',
        )
        self.assertEqual(historique.role, User.Role.SECRETARIAT_CENTRAL)
        self.assertEqual(historique.direction, 'DAAF')
        self.assertEqual(historique.ancien_statut, Courrier.Statut.ARRIVE)
        self.assertEqual(historique.nouveau_statut, Courrier.Statut.AFFECTE)
        self.assertIn('Transmission', historique.observation)

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

    def test_upload_rejects_spoofed_pdf(self):
        fichier = SimpleUploadedFile(
            "scan.pdf",
            b"<html>not a pdf</html>",
            content_type="application/pdf",
        )
        form = CourrierForm(
            data={
                "designation": "Objet",
                "resume": "",
                "expediteur_nom": "Expediteur",
                "expediteur_institution": "",
                "expediteur_telephone": "",
                "priorite": Courrier.Priorite.NORMAL,
                "date_arrivee": timezone.now().strftime("%Y-%m-%dT%H:%M"),
            },
            files={"fichier_scan": fichier},
        )
        self.assertFalse(form.is_valid())
        self.assertIn("fichier_scan", form.errors)

    def test_document_model_rejects_invalid_content(self):
        fichier = SimpleUploadedFile(
            "scan.pdf",
            b"not really a pdf",
            content_type="application/pdf",
        )
        document = Document(
            courrier=self.courrier_normal,
            nom="Scan",
            fichier=fichier,
            taille_octets=fichier.size,
        )
        with self.assertRaises(ValidationError):
            document.full_clean()

    def test_document_download_requires_login_and_courrier_access(self):
        fichier = SimpleUploadedFile(
            "scan.pdf",
            b"%PDF-1.4\n%valid test pdf",
            content_type="application/pdf",
        )
        document = Document.objects.create(
            courrier=self.courrier_normal,
            nom="Scan",
            fichier=fichier,
            taille_octets=fichier.size,
        )
        url = reverse("document_telecharger", kwargs={"pk": document.pk})

        anonymous_response = self.client.get(url)
        self.assertEqual(anonymous_response.status_code, 302)

        self.client.force_login(self.agent)
        forbidden_response = self.client.get(url)
        self.assertEqual(forbidden_response.status_code, 404)

        self.client.force_login(self.sc)
        authorized_response = self.client.get(url)
        self.assertEqual(authorized_response.status_code, 200)
        self.assertIn("attachment", authorized_response["Content-Disposition"])

    def test_decision_requires_validated_analysis(self):
        self.client.force_login(self.ministre)
        response = self.client.post(
            reverse("decision_nouveau", kwargs={"courrier_id": self.courrier_normal.pk}),
            data={
                "instruction_standard": "POUR_ATTRIBUTION",
                "instructions_finales": "Traiter.",
            },
        )
        self.assertEqual(response.status_code, 404)
        self.assertFalse(Decision.objects.filter(courrier=self.courrier_normal).exists())

    def test_dc_cannot_validate_another_dc_analysis(self):
        other_dc = User.objects.create_user(
            username="dc_other",
            password=self.test_password,
            role=User.Role.DC,
        )
        FicheAnalyse.objects.create(
            courrier=self.courrier_normal,
            analyse_par=other_dc,
            observations_dc="Analyse",
        )
        self.courrier_normal.statut = Courrier.Statut.EN_COURS_DC
        self.courrier_normal.save(update_fields=["statut"])

        self.client.force_login(self.dc)
        response = self.client.post(reverse("fiche_valider", kwargs={"courrier_id": self.courrier_normal.pk}))
        self.assertEqual(response.status_code, 404)
        self.courrier_normal.refresh_from_db()
        self.assertEqual(self.courrier_normal.statut, Courrier.Statut.EN_COURS_DC)

    def test_login_rate_limit_blocks_repeated_failures(self):
        url = reverse("login")
        for _ in range(5):
            response = self.client.post(url, {"username": self.sc.username, "password": "wrong-password"})
            self.assertEqual(response.status_code, 200)

        blocked_response = self.client.post(url, {"username": self.sc.username, "password": "wrong-password"})
        self.assertEqual(blocked_response.status_code, 429)

    # --- Security-focused upload / access tests requested ---
    def test_upload_allowed_pdf_and_storage(self):
        # Valid PDF upload should be accepted and create a Document
        data = b"%PDF-1.4\n%valid pdf content\n"
        fichier = SimpleUploadedFile("allowed.pdf", data, content_type="application/pdf")
        document = Document.objects.create(
            courrier=self.courrier_normal,
            nom="Scan valide",
            fichier=fichier,
            taille_octets=fichier.size,
        )
        self.assertIsNotNone(document.pk)
        # file must exist on disk
        self.assertTrue(os.path.exists(document.fichier.path))

    def test_upload_allowed_office_formats(self):
        for filename, content_type in (
            (
                "allowed.docx",
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            ),
            (
                "allowed.xlsx",
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            ),
        ):
            stream = io.BytesIO()
            with zipfile.ZipFile(stream, "w") as archive:
                archive.writestr("[Content_Types].xml", "<Types/>")
            fichier = SimpleUploadedFile(filename, stream.getvalue(), content_type=content_type)
            document = Document.objects.create(
                courrier=self.courrier_normal,
                nom=filename,
                fichier=fichier,
                taille_octets=fichier.size,
            )
            self.assertTrue(os.path.exists(document.fichier.path))

    def test_upload_office_macros_are_rejected(self):
        stream = io.BytesIO()
        with zipfile.ZipFile(stream, "w") as archive:
            archive.writestr("word/vbaProject.bin", b"macro")
        fichier = SimpleUploadedFile(
            "macro.docx",
            stream.getvalue(),
            content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        )
        document = Document(
            courrier=self.courrier_normal,
            nom="Macro",
            fichier=fichier,
            taille_octets=fichier.size,
        )
        with self.assertRaises(ValidationError):
            document.full_clean()

    def test_upload_too_large_is_rejected(self):
        big = b"0" * (validators.MAX_UPLOAD_SIZE + 1)
        fichier = SimpleUploadedFile("big.pdf", big, content_type="application/pdf")
        form = CourrierForm(
            data={
                "designation": "Objet",
                "resume": "",
                "expediteur_nom": "Expediteur",
                "expediteur_institution": "",
                "expediteur_telephone": "",
                "priorite": Courrier.Priorite.NORMAL,
                "date_arrivee": timezone.now().strftime("%Y-%m-%dT%H:%M"),
            },
            files={"fichier_scan": fichier},
        )
        self.assertFalse(form.is_valid())
        self.assertIn("fichier_scan", form.errors)

    def test_forbidden_extension_rejected(self):
        exe = SimpleUploadedFile("malware.exe", b"MZ...", content_type="application/octet-stream")
        document = Document(
            courrier=self.courrier_normal,
            nom="Exe",
            fichier=exe,
            taille_octets=exe.size,
        )
        with self.assertRaises(Exception):
            document.full_clean()

    def test_mime_falsified_is_rejected(self):
        # content looks like PDF header but labeled as image/jpeg
        fichier = SimpleUploadedFile("fake.jpg", b"%PDF-1.4\n%fake", content_type="image/jpeg")
        document = Document(
            courrier=self.courrier_normal,
            nom="Fake",
            fichier=fichier,
            taille_octets=fichier.size,
        )
        with self.assertRaises(Exception):
            document.full_clean()

    def test_double_extension_attack_blocked(self):
        # Attempt filename with double extension where last extension is executable
        fichier = SimpleUploadedFile("report.pdf.php", b"%PDF-1.4\n%valid", content_type="application/pdf")
        form = CourrierForm(
            data={
                "designation": "Objet",
                "resume": "",
                "expediteur_nom": "Expediteur",
                "expediteur_institution": "",
                "expediteur_telephone": "",
                "priorite": Courrier.Priorite.NORMAL,
                "date_arrivee": timezone.now().strftime("%Y-%m-%dT%H:%M"),
            },
            files={"fichier_scan": fichier},
        )
        self.assertFalse(form.is_valid())

    def test_path_traversal_filename_rejected(self):
        # Many clients strip path components from filenames. The important
        # property is that the application must not store the file using
        # attacker-controlled paths. We assert the stored path is under
        # MEDIA_ROOT and contains no '..' or path separators from the original name.
        fichier = SimpleUploadedFile("../../secret.pdf", b"%PDF-1.4\n%valid", content_type="application/pdf")
        form = CourrierForm(
            data={
                "designation": "Objet",
                "resume": "",
                "expediteur_nom": "Expediteur",
                "expediteur_institution": "",
                "expediteur_telephone": "",
                "priorite": Courrier.Priorite.NORMAL,
                "date_arrivee": timezone.now().strftime("%Y-%m-%dT%H:%M"),
            },
            files={"fichier_scan": fichier},
        )
        # Form may be valid because the client-supplied filename is normalized.
        self.assertTrue(form.is_valid())
        # Save courrier and attach document to verify safe storage
        courrier = form.save(commit=False)
        courrier.cree_par = self.sc
        courrier.save()
        doc = Document.objects.create(
            courrier=courrier,
            nom='Test',
            fichier=fichier,
            taille_octets=fichier.size,
        )
        self.assertTrue(doc.fichier.path.startswith(str(settings.MEDIA_ROOT)))
        self.assertNotIn('..', doc.fichier.path)

    def test_download_requires_authorization_and_direct_url_is_not_exposed(self):
        fichier = SimpleUploadedFile(
            "scan.pdf",
            b"%PDF-1.4\n%valid test pdf",
            content_type="application/pdf",
        )
        document = Document.objects.create(
            courrier=self.courrier_normal,
            nom="Scan",
            fichier=fichier,
            taille_octets=fichier.size,
        )

        # Another user must not be able to download
        self.client.force_login(self.agent)
        resp = self.client.get(reverse("document_telecharger", kwargs={"pk": document.pk}))
        self.assertEqual(resp.status_code, 404)

        # Direct access to the underlying file URL should not be accessible via the app
        file_url = settings.MEDIA_URL + document.fichier.name
        anon = self.client.logout() or self.client.get(file_url)
        # Depending on deployment the MEDIA URL might not be served by Django; accept 404 or 302 to login
        self.assertIn(anon.status_code, (302, 404))

    def test_non_staff_cannot_access_admin_delete(self):
        # Ensure non-staff users cannot reach the admin delete view for Documents
        fichier = SimpleUploadedFile(
            "scan2.pdf",
            b"%PDF-1.4\n%valid",
            content_type="application/pdf",
        )
        document = Document.objects.create(
            courrier=self.courrier_normal,
            nom="Scan2",
            fichier=fichier,
            taille_octets=fichier.size,
        )
        admin_delete_url = f"/admin/courrier/document/{document.pk}/delete/"
        self.client.force_login(self.agent)
        resp = self.client.get(admin_delete_url)
        # Expect redirect to login or permission denied (302 -> login)
        self.assertIn(resp.status_code, (302, 403))
