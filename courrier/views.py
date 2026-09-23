"""
Vues principales — GEC Ministère.

Organisation :
- DashboardView         : Tableau de bord adapté au rôle
- CourrierListView      : Liste filtrée des courriers
- CourrierDetailView    : Détail complet d'un courrier
- CourrierCreateView    : Enregistrement (Secrétariat Central)
- FicheAnalyseCreateView: Rédaction fiche d'analyse (DC)
- FicheAnalyseValidateView: Validation de la fiche par le DC
- DecisionCreateView    : Prise de décision (Ministre)
- AffectationCreateView : Affectation aux services (DC/Ministre)
- marquer_notification_lue : Marquer une notification comme lue (AJAX)
"""

from django.urls import reverse_lazy, reverse
from django.views.generic import CreateView, TemplateView, ListView, DetailView, View, UpdateView
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.auth import logout
from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect
from django.http import FileResponse, Http404, JsonResponse
from django.utils import timezone
from django.db import IntegrityError, transaction
from django.db.models import Q, Prefetch
from django.core.mail import send_mail
from django.core.exceptions import ObjectDoesNotExist, PermissionDenied, ValidationError
from django.conf import settings
from pathlib import Path

from .models import Courrier, User, FicheAnalyse, FicheAnalyseSG, Decision, DecisionFinale, Document, Historique, Notification, Affectation, Relance, ConfigurationDelai, ReponseCourrier, CourrierSortant
from .forms import CourrierForm, FicheAnalyseForm, FicheAnalyseSGForm, AffectationForm, CourrierSortantForm, normalize_service
from .decision_forms import DecisionForm
from .utils import RoleRequiredMixin
from .validators import MAX_UPLOAD_SIZE, validate_document_upload
from .services import cloturer_traitement, synchroniser_relances, resoudre_relances_courrier, get_relances_pour_utilisateur
import mimetypes


# ==============================================================================
# HELPER — Créer un historique et une notification
# ==============================================================================

def creer_historique(courrier, utilisateur, action, description, role=None, direction=None,
                     ancien_statut=None, nouveau_statut=None, observation=None,
                     document=None):
    """Raccourci pour créer une entrée dans le journal d'audit avec les champs structurés utiles au workflow."""
    Historique.objects.create(
        courrier=courrier,
        utilisateur=utilisateur,
        action=action,
        description=description,
        role=role or (utilisateur.role if utilisateur else None),
        direction=direction,
        ancien_statut=ancien_statut,
        nouveau_statut=nouveau_statut,
        observation=observation,
        document=document,
    )


def notifier(destinataire, courrier, message):
    """Raccourci pour créer une notification interne."""
    if courrier and courrier.priorite in [Courrier.Priorite.URGENT, Courrier.Priorite.TRES_URGENT]:
        if "COURRIER URGENT" not in message:
            message = f"🚨 [COURRIER URGENT] {message}"
    # Une même action peut être rejouée (double clic / requête répétée) : ne pas
    # empiler des alertes identiques non lues pour le même courrier.
    Notification.objects.get_or_create(
        destinataire=destinataire,
        courrier=courrier,
        message=message,
        lu=False,
    )


def notifier_role(role, courrier, message):
    """Envoie une notification à tous les utilisateurs d'un rôle donné."""
    for user in User.objects.filter(role=role, is_active=True):
        notifier(user, courrier, message)


def envoyer_email(destinataires, sujet, contenu):
    """Envoie un email aux adresses valides sans bloquer le workflow métier."""
    emails = sorted({email.strip() for email in destinataires if email and email.strip()})
    if emails:
        send_mail(
            sujet,
            contenu,
            settings.DEFAULT_FROM_EMAIL,
            emails,
            fail_silently=True,
        )


def envoyer_email_nouveau_courrier(courrier):
    destinataires = User.objects.filter(
        role=User.Role.MINISTRE,
        is_active=True,
    ).exclude(email='').values_list('email', flat=True)
    envoyer_email(
        destinataires,
        f"Nouveau courrier enregistré : {courrier.reference}",
        "Un nouveau courrier est disponible dans la GEC.\n\n"
        f"Référence : {courrier.reference}\n"
        f"Objet : {courrier.designation}\n"
        f"Résumé : {courrier.resume or 'Aucun résumé renseigné.'}\n"
        f"Expéditeur : {courrier.expediteur_nom}\n"
        f"Priorité : {courrier.get_priorite_display()}\n",
    )


def normalize_service_label(service):
    if not service:
        return ''
    value = str(service).strip()
    return {'DAF': 'DAAF'}.get(value, value)


def envoyer_email_affectation(affectation):
    raw_service = affectation.service_concerne or (
        affectation.destinataire.service_direction if affectation.destinataire else None
    )
    service = normalize_service_label(raw_service)

    destinataires = []
    if service:
        destinataires = list(
            User.objects.filter(
                role=User.Role.DIRECTEUR,
                service_direction__in=[service, service.replace('DAAF', 'DAF')],
                is_active=True,
            ).exclude(email='').values_list('email', flat=True)
        )

    if affectation.destinataire and affectation.destinataire.role == User.Role.DIRECTEUR:
        email_destinataire = (affectation.destinataire.email or '').strip()
        if email_destinataire:
            destinataires.append(email_destinataire)

    courrier = affectation.courrier
    envoyer_email(
        destinataires,
        f"Courrier affecté à votre direction : {courrier.reference}",
        "Un courrier vient d'être affecté à votre direction.\n\n"
        f"Référence : {courrier.reference}\n"
        f"Objet : {courrier.designation}\n"
        f"Résumé : {courrier.resume or 'Aucun résumé renseigné.'}\n"
        f"Service : {service or 'Non précisé'}\n"
        f"Délai : {courrier.delai_traitement_jours or 'Non précisé'} jour(s)\n",
    )


class SecureLogoutView(LoginRequiredMixin, View):
    """Déconnexion uniquement par POST pour éviter les actions CSRF par lien."""
    http_method_names = ['post', 'options']

    def post(self, request):
        logout(request)
        return redirect('landing')


# ==============================================================================
# TABLEAU DE BORD
# ==============================================================================

class DashboardView(LoginRequiredMixin, TemplateView):
    """
    Tableau de bord adapté au rôle de l'utilisateur connecté.
    Chaque rôle voit uniquement les informations pertinentes pour lui.
    """
    template_name = 'dashboard.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        user = self.request.user

        # Synchronisation automatique des relances et alertes en arrière-plan
        synchroniser_relances()
        active_alert_affectations = Affectation.objects.filter(
            statut_traitement__in=[
                Affectation.StatutTraitement.RECU,
                Affectation.StatutTraitement.EN_COURS,
            ],
        ).select_related('destinataire').order_by('date_affectation')
        relances_qs = get_relances_pour_utilisateur(user).prefetch_related(
            Prefetch(
                'courrier__affectations',
                queryset=active_alert_affectations,
                to_attr='affectations_en_alerte',
            )
        )
        context['relances_actives'] = relances_qs.order_by('-date_creation')
        context['nb_relances'] = relances_qs.count()
        context['courriers_en_retard_ids'] = set(relances_qs.values_list('courrier_id', flat=True))

        # Délai réglementaire actuel configuré par le Ministre
        context['delai_traitement_actuel'] = ConfigurationDelai.get_delai_jours()
        context['delai_traitement_configure'] = context['delai_traitement_actuel'] is not None

        # Courriers urgents sous la responsabilité de l'utilisateur
        context['courriers_urgents_en_cours'] = Courrier.objects.pour_utilisateur(user).filter(
            priorite__in=[Courrier.Priorite.URGENT, Courrier.Priorite.TRES_URGENT]
        ).exclude(statut=Courrier.Statut.TERMINE).order_by('-date_arrivee')[:10]

        # Notifications non lues (commun à tous les rôles)
        context['notifications_non_lues'] = user.notifications.filter(lu=False).select_related('courrier').order_by('-date_notification')[:5]
        context['nb_notifications'] = user.notifications.filter(lu=False).count()

        if user.role == User.Role.SECRETARIAT_CENTRAL:
            context['courriers_sortants'] = CourrierSortant.objects.select_related('courrier', 'document').order_by('-date_enregistrement')[:20]
            context['courriers_recents'] = Courrier.objects.filter(cree_par=user).select_related('cree_par').order_by('-date_enregistrement')[:10]
            context['total_courriers'] = Courrier.objects.filter(cree_par=user).count()
            context['courriers_en_attente'] = Courrier.objects.filter(statut=Courrier.Statut.ARRIVE).count()

        elif user.role == User.Role.SG:
            context['courriers_a_analyser'] = Courrier.objects.filter(statut__in=[Courrier.Statut.TRANSMIS_SG, Courrier.Statut.EN_COURS_SG]).select_related('cree_par').order_by('-date_arrivee')[:10]
            context['courriers_recents'] = context['courriers_a_analyser']
            context['analyses_faites'] = FicheAnalyseSG.objects.filter(analyse_par=user).select_related('courrier').order_by('-date_analyse')[:10]
            context['total_a_analyser'] = Courrier.objects.filter(statut__in=[Courrier.Statut.TRANSMIS_SG, Courrier.Statut.EN_COURS_SG]).count()
            context['en_cours'] = Courrier.objects.filter(statut=Courrier.Statut.EN_COURS_SG).count()

        elif user.role == User.Role.DC:
            context['courriers_a_analyser'] = Courrier.objects.filter(statut=Courrier.Statut.EN_COURS_DC).select_related('cree_par').order_by('-date_arrivee')[:10]
            context['analyses_faites'] = FicheAnalyse.objects.filter(analyse_par=user).select_related('courrier').order_by('-date_analyse')[:10]
            context['total_a_analyser'] = Courrier.objects.filter(statut=Courrier.Statut.EN_COURS_DC).count()
            context['en_cours'] = Courrier.objects.filter(statut=Courrier.Statut.EN_COURS_DC).count()

        elif user.role == User.Role.SECRETAIRE_MINISTRE:
            context['courriers_recents'] = Courrier.objects.filter(statut=Courrier.Statut.ANALYSE_VALIDE).select_related('cree_par').order_by('-date_arrivee')[:10]
            context['total_courriers'] = Courrier.objects.filter(statut=Courrier.Statut.ANALYSE_VALIDE).count()

        elif user.role == User.Role.MINISTRE:
            context['courriers_a_decider'] = Courrier.objects.filter(statut=Courrier.Statut.TRANSMIS_MINISTRE).select_related('cree_par').order_by('-date_arrivee')[:10]
            context['decisions_prises'] = Decision.objects.filter(signe_par=user).select_related('courrier').order_by('-date_decision')[:10]
            context['total_a_decider'] = Courrier.objects.filter(statut=Courrier.Statut.TRANSMIS_MINISTRE).count()
            context['total_decides'] = Decision.objects.filter(signe_par=user).count()

        elif user.role == User.Role.SECRETAIRE_SG:
            context['courriers_recents'] = Courrier.objects.filter(
                statut__in=[Courrier.Statut.ARRIVE, Courrier.Statut.TRANSMIS_SG]
            ).select_related('cree_par').order_by('-date_arrivee')[:10]
            context['total_courriers'] = Courrier.objects.filter(
                statut__in=[Courrier.Statut.ARRIVE, Courrier.Statut.TRANSMIS_SG]
            ).count()

        elif user.role == User.Role.SECRETAIRE_DC:
            context['courriers_recents'] = Courrier.objects.filter(statut=Courrier.Statut.TRANSMIS_DC).select_related('cree_par').order_by('-date_arrivee')[:10]
            context['total_courriers'] = Courrier.objects.filter(statut=Courrier.Statut.TRANSMIS_DC).count()

        elif user.role in [User.Role.DIRECTEUR, User.Role.AGENT]:
            # Les directeurs/agents voient les courriers qui leur ont été affectés
            if user.role == User.Role.DIRECTEUR and user.service_direction:
                service = normalize_service_label(user.service_direction)
                services = {service}
                services.add('DAF' if service == 'DAAF' else 'DAAF')
                qs_aff = Affectation.objects.filter(
                    Q(destinataire=user) |
                    Q(destinataire__isnull=True, service_concerne__in=services)
                )
            else:
                qs_aff = Affectation.objects.filter(destinataire=user)
                
            # Déduplication par courrier_id pour éviter que le même courrier 
            # s'affiche plusieurs fois (ex: multiple affectations correspondantes)
            affectations = []
            seen_courriers = set()
            for aff in qs_aff.select_related('courrier', 'decision').order_by('-date_affectation'):
                if aff.courrier_id not in seen_courriers:
                    affectations.append(aff)
                    seen_courriers.add(aff.courrier_id)
                if len(affectations) >= 10:
                    break
            context['mes_affectations'] = affectations
            context['affectations_a_affecter'] = {
                aff.pk for aff in affectations
                if (
                    user.role == User.Role.DIRECTEUR
                    and aff.destinataire_id is None
                    and not Affectation.objects.filter(
                        courrier=aff.courrier,
                        destinataire__role=User.Role.AGENT,
                        service_concerne__in=services,
                    ).exists()
                )
            } if user.role == User.Role.DIRECTEUR else set()
            # Réutiliser le même queryset pour les différents comptes évite des hits répétés
            context['affectations_en_cours'] = qs_aff.filter(statut_traitement=Affectation.StatutTraitement.EN_COURS).count()
            context['affectations_recues'] = qs_aff.filter(statut_traitement=Affectation.StatutTraitement.RECU).count()

        return context


# ==============================================================================
# LISTE DES COURRIERS
# ==============================================================================

class CourrierListView(LoginRequiredMixin, ListView):
    """
    Liste de tous les courriers accessibles à l'utilisateur connecté.
    La sécurité d'accès est assurée par le CourrierQuerySet (ORM-level security).
    """
    model = Courrier
    template_name = 'courrier_list.html'
    context_object_name = 'courriers'
    paginate_by = 20

    def get_queryset(self):
        qs = Courrier.objects.pour_utilisateur(self.request.user).select_related('cree_par')
        
        # Application des filtres depuis l'URL
        statut = self.request.GET.get('statut')
        priorite = self.request.GET.get('priorite')
        
        if statut:
            qs = qs.filter(statut=statut)
        if priorite:
            qs = qs.filter(priorite=priorite)
            
        return qs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        # Filtres actifs
        context['statut_filter'] = self.request.GET.get('statut', '')
        context['priorite_filter'] = self.request.GET.get('priorite', '')
        context['statuts'] = Courrier.Statut.choices
        context['priorites'] = Courrier.Priorite.choices
        return context


# ==============================================================================
# DÉTAIL D'UN COURRIER
# ==============================================================================

class CourrierDetailView(LoginRequiredMixin, DetailView):
    """
    Page de détail complet d'un courrier : informations, documents, fiche d'analyse,
    décision, affectations et historique d'audit.
    """
    model = Courrier
    template_name = 'courrier_detail.html'
    context_object_name = 'courrier'

    def get_queryset(self):
        # Sécurité ORM : l'utilisateur ne peut voir que les courriers autorisés
        return Courrier.objects.pour_utilisateur(self.request.user).select_related(
            'cree_par', 'fiche_analyse', 'fiche_analyse_sg', 'decision'
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        courrier = self.object
        user = self.request.user

        context['documents'] = courrier.documents.order_by('-date_televersement')[:100]
        context['historiques'] = courrier.historiques.select_related('utilisateur').order_by('-date_action')[:100]

        # Fiche d'analyse (si elle existe)
        try:
            context['fiche_analyse'] = courrier.fiche_analyse
        except FicheAnalyse.DoesNotExist:
            context['fiche_analyse'] = None

        # Décision (si elle existe)
        try:
            context['decision'] = courrier.decision
        except Decision.DoesNotExist:
            context['decision'] = None
        context['decision_finale'] = getattr(courrier, 'decision_finale', None)
        context['courrier_sortant'] = getattr(courrier, 'courrier_sortant', None)

        # Affectations
        context['affectations'] = courrier.affectations.select_related('destinataire', 'affecte_par').order_by('-date_affectation')[:100]
        context['reponses'] = courrier.reponses_courrier.select_related(
            'auteur', 'document'
        ).order_by('-version', '-date_preparation')[:20]
        context['peut_enregistrer_sortant'] = (
            user.role == User.Role.SECRETARIAT_CENTRAL
            and courrier.statut == Courrier.Statut.SIGNE_PAR_MINISTRE
            and context['decision_finale'] is not None
            and not CourrierSortant.objects.filter(courrier=courrier).exists()
        )
        context['peut_repondre'] = (
            user.role == User.Role.AGENT
            and courrier.affectations.filter(destinataire=user).exists()
            and courrier.statut in [
                Courrier.Statut.AFFECTE,
                Courrier.Statut.CORRECTION_DEMANDEE,
            ]
        )
        context['peut_valider_reponse'] = (
            user.role == User.Role.DIRECTEUR
            and courrier.statut == Courrier.Statut.SOUMIS_DIRECTEUR
            and courrier.reponses_courrier.filter(
                auteur__service_direction=user.service_direction,
                statut_traitement=ReponseCourrier.Statut.ENVOYE_DIRECTEUR,
            ).exists()
        )
        service = normalize_service_label(user.service_direction)
        services = {service, 'DAF' if service == 'DAAF' else 'DAAF'}
        context['peut_transmettre_sg'] = (
            user.role == User.Role.DIRECTEUR
            and courrier.statut == Courrier.Statut.VALIDE_DIRECTEUR
            and courrier.reponses_courrier.filter(
                auteur__service_direction__in=services,
                statut_traitement=ReponseCourrier.Statut.VALIDE,
            ).exists()
        )

        # Fiche d'analyse du SG
        try:
            fiche_sg = courrier.fiche_analyse_sg
        except FicheAnalyseSG.DoesNotExist:
            fiche_sg = None
        context['fiche_analyse_sg'] = fiche_sg

        # Permissions d'action affichées dans le template
        context['peut_analyser'] = False
        if user.role == User.Role.SG:
            context['peut_analyser'] = (
                fiche_sg is None
                and courrier.statut in [Courrier.Statut.TRANSMIS_SG, Courrier.Statut.EN_COURS_SG]
                and getattr(courrier, 'decision', None) is None
            )
        elif user.role == User.Role.DC:
            context['peut_analyser'] = (
                context['fiche_analyse'] is None
                and courrier.statut == Courrier.Statut.EN_COURS_DC
                and getattr(courrier, 'decision', None) is None
            )
        context['peut_valider_fiche'] = (
            user.role == User.Role.DC
            and context['fiche_analyse'] is not None
            and not context['fiche_analyse'].valide
            and context['fiche_analyse'].analyse_par_id == user.id
            and (fiche_sg is None or fiche_sg.valide)
            and courrier.statut == Courrier.Statut.EN_COURS_DC
        )
        # Permission pour le SG de valider sa propre fiche SG
        context['peut_valider_fiche_sg'] = (
            user.role == User.Role.SG
            and fiche_sg is not None
            and not fiche_sg.valide
            and fiche_sg.analyse_par_id == user.id
            and courrier.statut == Courrier.Statut.EN_COURS_SG
            and getattr(courrier, 'decision', None) is None
        )
        context['peut_observer_traitement_sg'] = (
            user.role == User.Role.SG
            and getattr(courrier, 'decision', None) is not None
            and courrier.statut == Courrier.Statut.EN_COURS_SG
        )
        context['peut_observer_traitement_dc'] = (
            user.role == User.Role.DC
            and getattr(courrier, 'decision', None) is not None
            and courrier.statut == Courrier.Statut.EN_COURS_DC
        )
        context['peut_decider'] = (
            user.role == User.Role.MINISTRE
            and (
                context['decision'] is not None
                or (
                    (context['fiche_analyse'] is not None and context['fiche_analyse'].valide)
                    or (fiche_sg is not None and fiche_sg.valide)
                )
            )
            and context['decision_finale'] is None
            and courrier.statut == Courrier.Statut.TRANSMIS_MINISTRE
        )
        context['peut_affecter'] = (
            user.role in [
                User.Role.MINISTRE,
                User.Role.DC,
                User.Role.SECRETARIAT_CENTRAL,
                User.Role.DIRECTEUR,
            ]
            and context['decision'] is not None
            and courrier.statut in [
                Courrier.Statut.DECIDE,
            ]
            and (
                not courrier.affectations.exists()
                or (
                    user.role == User.Role.DIRECTEUR
                    and courrier.affectations.filter(
                        Q(destinataire=user) |
                        Q(destinataire__isnull=True, service_concerne__in=[
                            normalize_service_label(user.service_direction),
                            'DAF' if normalize_service_label(user.service_direction) == 'DAAF' else 'DAAF',
                        ])
                    ).exists()
                    and not courrier.affectations.filter(
                        destinataire__role=User.Role.AGENT,
                        service_concerne__in=[
                            normalize_service_label(user.service_direction),
                            'DAF' if normalize_service_label(user.service_direction) == 'DAAF' else 'DAAF',
                        ],
                    ).exists()
                )
            )
        )

        context['circuit_reponse_actif'] = (
            context['decision'] is not None and (
                courrier.affectations.exists() or courrier.reponses_courrier.exists()
            )
        )

        return context


# ==============================================================================
class CircuitReponseView(CourrierDetailView):
    """Espace de réponse avec les mêmes droits d'accès que le courrier."""
    template_name = 'circuit_reponse.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        if not context['circuit_reponse_actif']:
            raise Http404("Le circuit de réponse n'a pas encore commencé.")
        context['destinataire_transmission'] = {
            ('SECRETAIRE_SG', 'TRANSMIS_SG'): 'SG',
            ('SECRETAIRE_DC', 'TRANSMIS_DC'): 'DC',
            ('SECRETAIRE_MINISTRE', 'ANALYSE_VALIDE'): 'Ministre',
        }.get((self.request.user.role, self.object.statut))
        return context


# ENREGISTREMENT D'UN COURRIER (Secrétariat Central)
# ==============================================================================

class CourrierCreateView(LoginRequiredMixin, RoleRequiredMixin, CreateView):
    """
    Enregistrement d'un nouveau courrier par le Secrétariat Central.
    Crée automatiquement le document scanné si un fichier est joint,
    et enregistre la première entrée dans le journal d'audit.
    """
    model = Courrier
    form_class = CourrierForm
    template_name = 'courrier_form.html'
    success_url = reverse_lazy('courrier_liste')
    allowed_roles = [User.Role.SECRETARIAT_CENTRAL]

    def form_valid(self, form):
        form.instance.cree_par = self.request.user
        response = super().form_valid(form)
        courrier = self.object
        courrier.responsable_actuel_role = User.Role.SECRETAIRE_SG
        courrier.save(update_fields=['responsable_actuel_role'])

        # Enregistrement du fichier scanné si fourni
        fichier = form.cleaned_data.get('fichier_scan')
        if fichier:
            validate_document_upload(fichier)
            Document.objects.create(
                courrier=courrier,
                nom=f"Scan original — {courrier.reference}",
                fichier=fichier,
                taille_octets=fichier.size,
            )

        # Journal d'audit : enregistrement
        creer_historique(
            courrier=courrier,
            utilisateur=self.request.user,
            action='ENREGISTREMENT',
            description=f"Courrier enregistré par {self.request.user.get_full_name() or self.request.user.username}. "
                        f"Expéditeur : {courrier.expediteur_nom}. Priorité : {courrier.get_priorite_display()}."
        )

        # Le Secrétariat Central remet le courrier au Secrétariat du SG.
        notifier_role(
            role=User.Role.SECRETAIRE_SG,
            courrier=courrier,
            message=f"Nouveau courrier à transmettre au SG : {courrier.reference} — {courrier.designation[:60]}."
        )
        transaction.on_commit(lambda: envoyer_email_nouveau_courrier(courrier))

        messages.success(
            self.request,
            f"✅ Courrier {courrier.reference} enregistré avec succès et transmis au Secrétaire du SG."
        )
        return response


class CourrierUpdateView(LoginRequiredMixin, RoleRequiredMixin, UpdateView):
    """
    Permet au Secrétariat Central de modifier un courrier retourné pour correction.
    """
    model = Courrier
    form_class = CourrierForm
    template_name = 'courrier_form.html'
    allowed_roles = [User.Role.SECRETARIAT_CENTRAL]

    def get_object(self, queryset=None):
        obj = get_object_or_404(Courrier.objects.pour_utilisateur(self.request.user), pk=self.kwargs['pk'])
        # Autoriser l'édition si le courrier a été rejeté par un secrétaire
        if obj.statut != Courrier.Statut.REJETE_SECRETAIRE and obj.cree_par_id != self.request.user.id:
            raise Http404("Édition non autorisée.")
        return obj

    def form_valid(self, form):
        response = super().form_valid(form)
        courrier = self.object
        # Journal d'audit
        creer_historique(
            courrier=courrier,
            utilisateur=self.request.user,
            action='MODIFICATION',
            description=f"Courrier modifié par le Secrétariat Central {self.request.user.get_full_name() or self.request.user.username}."
        )

        # Notifier le secrétariat qui avait rejeté
        notifier_role(role=User.Role.SECRETAIRE_DC, courrier=courrier,
                     message=f"Le courrier {courrier.reference} a été modifié par le Secrétariat Central après rejet.")

        messages.success(self.request, f"✅ Courrier {courrier.reference} mis à jour.")
        return response

    def get_success_url(self):
        return reverse('courrier_detail', kwargs={'pk': self.object.pk})


class DocumentDownloadView(LoginRequiredMixin, View):
    """Téléchargement de document avec contrôle d'accès sur le courrier parent."""

    def get(self, request, pk):
        document = get_object_or_404(Document.objects.select_related('courrier'), pk=pk)
        is_authorized = Courrier.objects.pour_utilisateur(request.user).filter(
            pk=document.courrier_id
        ).exists()
        # Protection serveur stricte : aucun utilisateur non autorisé ni rôle de vue ne doit
        # avoir accès au document en manipulant l'ID du document ou celle du courrier.
        if not is_authorized or not request.user.is_active:
            raise Http404("Document introuvable.")

        try:
            file_handle = document.fichier.open("rb")
        except FileNotFoundError:
            raise Http404("Fichier introuvable.")

        # Liste blanche de types MIME autorisés selon l'extension du fichier.
        # Ne jamais faire confiance à mimetypes.guess_type() qui peut être manipulé.
        SAFE_MIME_TYPES = {
            '.pdf': 'application/pdf',
            '.jpg': 'image/jpeg',
            '.jpeg': 'image/jpeg',
            '.png': 'image/png',
            '.docx': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
            '.xlsx': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        }

        extension = Path(document.fichier.name).suffix.lower()
        content_type = SAFE_MIME_TYPES.get(extension, 'application/octet-stream')

        # Le nom est généré statiquement pour éviter toute injection de nom de fichier (CWE-73)
        safe_name = f"document_{document.pk}{extension}"
        response = FileResponse(file_handle, as_attachment=True, filename=safe_name, content_type=content_type)
        # Défense supplémentaire : s'assurer que le navigateur n'interprète pas le contenu
        response['X-Content-Type-Options'] = 'nosniff'
        return response


# ==============================================================================
# FICHE D'ANALYSE — Rédaction (DC)
# ==============================================================================

class FicheAnalyseCreateView(LoginRequiredMixin, RoleRequiredMixin, CreateView):
    """
    Rédaction de la fiche d'analyse par le Directeur de Cabinet.
    Met le statut du courrier à EN_COURS_DC dès la soumission.
    """
    model = FicheAnalyse
    form_class = FicheAnalyseForm
    template_name = 'fiche_analyse_form.html'
    allowed_roles = [User.Role.DC]

    def get_courrier(self):
        return get_object_or_404(
            Courrier.objects.pour_utilisateur(self.request.user).filter(
                statut=Courrier.Statut.EN_COURS_DC,
                fiche_analyse_sg__valide=True,
                decision__isnull=True,
            ),
            pk=self.kwargs['courrier_id'],
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['courrier'] = self.get_courrier()
        return context

    def form_valid(self, form):
        try:
            with transaction.atomic():
                courrier = self.get_courrier()
                fiche_sg = courrier.fiche_analyse_sg
                
                fiche = form.save(commit=False)
                fiche.courrier = courrier
                fiche.analyse_par = self.request.user
                
                # Pré-remplir avec les données du SG si c'est la première fois
                if not fiche.analyse_sg_par and fiche_sg:
                    fiche.analyse_sg_par = fiche_sg.analyse_par
                    fiche.observations_sg = fiche_sg.observations_sg
                    fiche.propositions_sg = fiche_sg.propositions_sg
                    fiche.valide_sg = True
                    fiche.date_analyse_sg = fiche_sg.date_analyse
                    fiche.date_validation_sg = fiche_sg.date_validation

                fiche.save()
                self.object = fiche
                response = redirect(self.get_success_url())

                courrier.statut = Courrier.Statut.EN_COURS_DC
                courrier.save(update_fields=['statut'])

                creer_historique(
                    courrier=courrier,
                    utilisateur=self.request.user,
                    action='ANALYSE_REDIGEE',
                    description=f"Fiche d'analyse rédigée par le DC {self.request.user.get_full_name() or self.request.user.username}."
                )
        except IntegrityError:
            messages.error(self.request, "Une fiche d'analyse existe déjà pour ce courrier.")
            return redirect('courrier_detail', pk=self.kwargs['courrier_id'])

        messages.success(
            self.request,
            f"✅ Fiche d'analyse enregistrée. Vous pouvez maintenant la valider pour la transmettre au Secrétaire du Ministre."
        )
        return response

    def get_success_url(self):
        return reverse('courrier_detail', kwargs={'pk': self.kwargs['courrier_id']})


class FicheAnalyseSGCreateView(LoginRequiredMixin, RoleRequiredMixin, CreateView):
    """
    Rédaction de la fiche d'analyse par le Secrétaire Général (SG).
    Même comportement que pour le DC.
    """
    model = FicheAnalyseSG
    form_class = FicheAnalyseSGForm
    template_name = 'fiche_analyse_form.html'
    allowed_roles = [User.Role.SG]

    def get_courrier(self):
        return get_object_or_404(
            Courrier.objects.pour_utilisateur(self.request.user).filter(
                statut__in=[Courrier.Statut.TRANSMIS_SG, Courrier.Statut.EN_COURS_SG],
                fiche_analyse_sg__isnull=True,
            ),
            pk=self.kwargs['courrier_id'],
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['courrier'] = self.get_courrier()
        return context

    def form_valid(self, form):
        try:
            with transaction.atomic():
                courrier = self.get_courrier()
                form.instance.analyse_par = self.request.user
                form.instance.courrier = courrier
                response = super().form_valid(form)

                courrier.statut = Courrier.Statut.EN_COURS_SG
                courrier.save(update_fields=['statut'])

                creer_historique(
                    courrier=courrier,
                    utilisateur=self.request.user,
                    action='ANALYSE_SG_REDIGEE',
                    description=f"Fiche d'analyse (SG) rédigée par {self.request.user.get_full_name() or self.request.user.username}."
                )
        except IntegrityError:
            messages.error(self.request, "Une fiche d'analyse (SG) existe déjà pour ce courrier.")
            return redirect('courrier_detail', pk=self.kwargs['courrier_id'])

        messages.success(
            self.request,
            f"✅ Fiche d'analyse (SG) enregistrée. Vous pouvez maintenant la valider."
        )
        return response

    def get_success_url(self):
        return reverse('courrier_detail', kwargs={'pk': self.kwargs['courrier_id']})


# ==============================================================================
# FICHE D'ANALYSE — Validation par le DC
# ==============================================================================

class FicheAnalyseValidateView(LoginRequiredMixin, RoleRequiredMixin, View):
    """
    Validation de la fiche d'analyse par le DC.
    Rend le courrier disponible au Secrétaire du Ministre pour transmission.
    """
    allowed_roles = [User.Role.DC]

    def post(self, request, courrier_id):
        if (
            request.user.role == User.Role.DC
            and Courrier.objects.filter(
                pk=courrier_id, statut=Courrier.Statut.EN_COURS_DC,
                decision__isnull=False,
            ).exists()
        ):
            courrier = get_object_or_404(Courrier.objects.pour_utilisateur(request.user), pk=courrier_id)
            observation = (request.POST.get('observation') or '').strip()
            if not observation:
                messages.error(request, "L'observation du DC est obligatoire.")
                target_view = 'circuit_reponse' if request.POST.get('retour') == 'circuit_reponse' else 'courrier_detail'
                return redirect(target_view, pk=courrier_id)
            ancien = courrier.statut
            
            # Mise à jour de la lettre si modifiée
            lettre_html = (request.POST.get('lettre_html') or '').strip()
            if lettre_html:
                reponse = courrier.reponses_courrier.filter(statut_traitement=ReponseCourrier.Statut.VALIDE).order_by('-version').first()
                if reponse:
                    reponse.observation = lettre_html
                    reponse.save(update_fields=['observation'])

            if request.POST.get('action') == 'correction':
                courrier.statut = Courrier.Statut.CORRECTION_DEMANDEE
                courrier.responsable_actuel_role = User.Role.AGENT
                courrier.save(update_fields=['statut', 'responsable_actuel_role'])
                creer_historique(courrier, request.user, 'CORRECTION_DEMANDEE_DC',
                                 "Correction demandée par le DC sur le travail de l'agent.",
                                 ancien_statut=ancien,
                                 nouveau_statut=courrier.statut, observation=observation)
                notifier_role(User.Role.AGENT, courrier,
                              f"Le DC demande une correction pour {courrier.reference}.")
                target_view = 'circuit_reponse' if request.POST.get('retour') == 'circuit_reponse' else 'courrier_detail'
                return redirect(target_view, pk=courrier_id)
            courrier.statut = Courrier.Statut.ANALYSE_VALIDE
            courrier.responsable_actuel_role = User.Role.SECRETAIRE_MINISTRE
            courrier.save(update_fields=['statut', 'responsable_actuel_role'])
            creer_historique(courrier, request.user, 'OBSERVATION_DC_TRAITEMENT',
                             "Observations du DC sur le travail de l'agent.",
                             ancien_statut=ancien,
                             nouveau_statut=courrier.statut, observation=observation)
            notifier_role(User.Role.SECRETAIRE_MINISTRE, courrier,
                          f"Le DC a validé le traitement de {courrier.reference}.")
            target_view = 'circuit_reponse' if request.POST.get('retour') == 'circuit_reponse' else 'courrier_detail'
            return redirect(target_view, pk=courrier_id)
        courrier = get_object_or_404(
            Courrier.objects.pour_utilisateur(request.user).filter(
                statut=Courrier.Statut.EN_COURS_DC,
                fiche_analyse__analyse_par=request.user,
                fiche_analyse__valide=False,
            ).filter(
                Q(fiche_analyse_sg__isnull=True) | Q(fiche_analyse_sg__valide=True)
            ),
            pk=courrier_id,
        )
        fiche = courrier.fiche_analyse
        observation = (request.POST.get('observation') or '').strip()

        # Validation de la fiche
        fiche.valide = True
        fiche.date_validation = timezone.now()
        fields_to_update = ['valide', 'date_validation']
        if observation:
            fiche.observations_dc = observation
            fields_to_update.append('observations_dc')
        fiche.save(update_fields=fields_to_update)

        # Résolution automatique des relances de l'étape Analyse DC
        resoudre_relances_courrier(courrier, etapes=Relance.Etape.ANALYSE_DC)

        # Passage au statut ANALYSE_VALIDE pour transmission au Ministre
        ancien_statut = courrier.statut
        courrier.statut = Courrier.Statut.ANALYSE_VALIDE
        courrier.responsable_actuel_role = User.Role.SECRETAIRE_MINISTRE
        courrier.save(update_fields=['statut', 'responsable_actuel_role'])

        # Journal d'audit
        creer_historique(
            courrier=courrier,
            utilisateur=request.user,
            action='VALIDATION_ANALYSE',
            description=f"Fiche d'analyse validée par le DC {request.user.get_full_name() or request.user.username}.",
            direction=request.user.service_direction,
            ancien_statut=ancien_statut,
            nouveau_statut=Courrier.Statut.ANALYSE_VALIDE,
            observation=observation or None,
        )

        notifier_role(
            role=User.Role.SECRETAIRE_MINISTRE,
            courrier=courrier,
            message=f"Nouveau courrier à soumettre au Ministre : {courrier.reference} — {courrier.designation[:60]}."
        )
        messages.success(
            request,
            f"✅ Fiche d'analyse validée. Le Secrétariat du Ministre a été notifié pour transmission."
        )
        target_view = 'circuit_reponse' if request.POST.get('retour') == 'circuit_reponse' else 'courrier_detail'
        return redirect(target_view, pk=courrier_id)


class FicheAnalyseSGValidateView(LoginRequiredMixin, RoleRequiredMixin, View):
    """
    Validation de la fiche SG par le Secrétaire Général.
    Si la fiche DC est validée aussi, on notifie le Secrétariat du Ministre.
    """
    allowed_roles = [User.Role.SG]

    def post(self, request, courrier_id):
        if (
            request.user.role == User.Role.SG
            and Courrier.objects.filter(
                pk=courrier_id, statut=Courrier.Statut.EN_COURS_SG,
                decision__isnull=False,
            ).exists()
        ):
            courrier = get_object_or_404(Courrier.objects.pour_utilisateur(request.user), pk=courrier_id)
            observation = (request.POST.get('observation') or '').strip()
            if not observation:
                messages.error(request, "L'observation du SG est obligatoire.")
                target_view = 'circuit_reponse' if request.POST.get('retour') == 'circuit_reponse' else 'courrier_detail'
                return redirect(target_view, pk=courrier_id)
            ancien = courrier.statut
            
            # Mise à jour de la lettre si modifiée
            lettre_html = (request.POST.get('lettre_html') or '').strip()
            if lettre_html:
                reponse = courrier.reponses_courrier.filter(statut_traitement=ReponseCourrier.Statut.VALIDE).order_by('-version').first()
                if reponse:
                    reponse.observation = lettre_html
                    reponse.save(update_fields=['observation'])

            if request.POST.get('action') == 'correction':
                courrier.statut = Courrier.Statut.CORRECTION_DEMANDEE
                courrier.responsable_actuel_role = User.Role.AGENT
                courrier.save(update_fields=['statut', 'responsable_actuel_role'])
                creer_historique(courrier, request.user, 'CORRECTION_DEMANDEE_SG',
                                 "Correction demandée par le SG sur le travail de l'agent.",
                                 ancien_statut=ancien,
                                 nouveau_statut=courrier.statut, observation=observation)
                notifier_role(User.Role.AGENT, courrier,
                              f"Le SG demande une correction pour {courrier.reference}.")
                target_view = 'circuit_reponse' if request.POST.get('retour') == 'circuit_reponse' else 'courrier_detail'
                return redirect(target_view, pk=courrier_id)
            courrier.statut = Courrier.Statut.TRANSMIS_DC
            courrier.responsable_actuel_role = User.Role.SECRETAIRE_DC
            courrier.save(update_fields=['statut', 'responsable_actuel_role'])
            creer_historique(courrier, request.user, 'OBSERVATION_SG_TRAITEMENT',
                             "Observations du SG sur le travail de l'agent.",
                             ancien_statut=ancien,
                             nouveau_statut=courrier.statut, observation=observation)
            notifier_role(User.Role.SECRETAIRE_DC, courrier,
                          f"Le SG a validé le traitement de {courrier.reference}.")
            target_view = 'circuit_reponse' if request.POST.get('retour') == 'circuit_reponse' else 'courrier_detail'
            return redirect(target_view, pk=courrier_id)
        courrier = get_object_or_404(
            Courrier.objects.pour_utilisateur(request.user).filter(
                statut=Courrier.Statut.EN_COURS_SG,
                fiche_analyse_sg__analyse_par=request.user,
                fiche_analyse_sg__valide=False,
            ),
            pk=courrier_id,
        )
        fiche_sg = courrier.fiche_analyse_sg
        observation = (request.POST.get('observation') or '').strip()

        fiche_sg.valide = True
        fiche_sg.date_validation = timezone.now()
        fields_to_update = ['valide', 'date_validation']
        if observation:
            fiche_sg.observations_sg = observation
            fields_to_update.append('observations_sg')
        fiche_sg.save(update_fields=fields_to_update)

        # Résolution automatique des relances de l'étape Analyse SG
        resoudre_relances_courrier(courrier, etapes=Relance.Etape.ANALYSE_SG)

        ancien_statut = courrier.statut
        courrier.statut = Courrier.Statut.TRANSMIS_DC
        courrier.responsable_actuel_role = User.Role.SECRETAIRE_DC
        courrier.save(update_fields=['statut', 'responsable_actuel_role'])

        creer_historique(
            courrier=courrier,
            utilisateur=request.user,
            action='VALIDATION_ANALYSE_SG',
            description=f"Fiche d'analyse (SG) validée par {request.user.get_full_name() or request.user.username}.",
            direction=request.user.service_direction,
            ancien_statut=ancien_statut,
            nouveau_statut=Courrier.Statut.TRANSMIS_DC,
            observation=observation or None,
        )

        notifier_role(
            role=User.Role.SECRETAIRE_DC,
            courrier=courrier,
            message=f"La fiche d'analyse (SG) pour {courrier.reference} est validée. Vous pouvez transmettre le dossier au DC."
        )
        messages.success(
            request,
            f"✅ Fiche d'analyse (SG) validée avec succès. Courrier transmis au Secrétariat du DC."
        )
        target_view = 'circuit_reponse' if request.POST.get('retour') == 'circuit_reponse' else 'courrier_detail'
        return redirect(target_view, pk=courrier_id)


class FicheAnalyseCorrectionView(LoginRequiredMixin, RoleRequiredMixin, View):
    """Retourne le dossier à l'agent pour reprendre le circuit de validation."""
    allowed_roles = [User.Role.SG, User.Role.DC]

    def post(self, request, courrier_id):
        courrier = get_object_or_404(Courrier.objects.pour_utilisateur(request.user), pk=courrier_id)
        motif = (request.POST.get('motif') or '').strip()
        if not motif:
            messages.error(request, "Le motif de correction est obligatoire.")
            return redirect('courrier_detail', pk=courrier_id)

        if request.user.role == User.Role.SG:
            fiche = get_object_or_404(FicheAnalyseSG, courrier=courrier)
            if fiche.valide or courrier.statut != Courrier.Statut.EN_COURS_SG:
                raise PermissionDenied("Cette fiche SG n'est pas en attente de décision.")
        else:
            fiche = get_object_or_404(FicheAnalyse, courrier=courrier)
            if fiche.valide or courrier.statut != Courrier.Statut.EN_COURS_DC:
                raise PermissionDenied("Cette fiche DC n'est pas en attente de décision.")

        # Une correction de fond reprend nécessairement le circuit depuis
        # l'agent ; les validations SG/DC précédentes ne doivent pas rester
        # valides pour la nouvelle version de la réponse.
        agent = courrier.reponses_courrier.order_by('-version', '-date_preparation').values_list(
            'auteur_id', flat=True
        ).first()
        if not agent:
            agent = courrier.affectations.filter(
                destinataire__role=User.Role.AGENT
            ).values_list('destinataire_id', flat=True).first()
        if not agent:
            raise PermissionDenied("Aucun agent responsable n'est associé à ce courrier.")

        ancien_statut = courrier.statut
        FicheAnalyse.objects.filter(courrier=courrier).delete()
        FicheAnalyseSG.objects.filter(courrier=courrier).delete()
        courrier.statut = Courrier.Statut.CORRECTION_DEMANDEE
        courrier.responsable_actuel_role = User.Role.AGENT
        courrier.save(update_fields=['statut', 'responsable_actuel_role'])
        creer_historique(
            courrier, request.user, 'CORRECTION_ANALYSE',
            f"Correction demandée : {motif}", ancien_statut=ancien_statut,
            nouveau_statut=Courrier.Statut.CORRECTION_DEMANDEE,
            observation=motif,
        )
        notifier(
            User.objects.get(pk=agent),
            courrier,
            f"Correction demandée par le {request.user.get_role_display()} : {motif}",
        )
        messages.success(request, "La correction a été enregistrée.")
        return redirect('courrier_detail', pk=courrier_id)


class SGTransmettreDCView(LoginRequiredMixin, RoleRequiredMixin, View):
    """Relais SG du circuit initial, sans créer une fiche d'analyse."""
    allowed_roles = [User.Role.SG]

    def post(self, request, courrier_id):
        courrier = get_object_or_404(
            Courrier.objects.pour_utilisateur(request.user).filter(
                pk=courrier_id,
                statut__in=[Courrier.Statut.TRANSMIS_SG, Courrier.Statut.EN_COURS_SG],
                decision__isnull=True,
            )
        )
        ancien_statut = courrier.statut
        courrier.statut = Courrier.Statut.TRANSMIS_DC
        courrier.responsable_actuel_role = User.Role.SECRETAIRE_DC
        courrier.save(update_fields=['statut', 'responsable_actuel_role'])
        creer_historique(
            courrier, request.user, 'TRANSMISSION_SG_SECRETAIRE_DC',
            "Dossier transmis au Secrétaire du DC par le SG.",
            ancien_statut=ancien_statut,
            nouveau_statut=Courrier.Statut.TRANSMIS_DC,
        )
        notifier_role(
            User.Role.SECRETAIRE_DC, courrier,
            f"Le SG a transmis {courrier.reference}. Vous pouvez le transmettre au DC.",
        )
        return redirect('courrier_detail', pk=courrier_id)


class DCTransmettreMinistreView(LoginRequiredMixin, RoleRequiredMixin, View):
    """Relais DC du circuit initial, sans créer une fiche d'analyse."""
    allowed_roles = [User.Role.DC]

    def post(self, request, courrier_id):
        courrier = get_object_or_404(
            Courrier.objects.pour_utilisateur(request.user).filter(
                pk=courrier_id,
                statut=Courrier.Statut.EN_COURS_DC,
                decision__isnull=True,
            )
        )
        ancien_statut = courrier.statut
        courrier.statut = Courrier.Statut.ANALYSE_VALIDE
        courrier.responsable_actuel_role = User.Role.SECRETAIRE_MINISTRE
        courrier.save(update_fields=['statut', 'responsable_actuel_role'])
        creer_historique(
            courrier, request.user, 'TRANSMISSION_DC_SECRETAIRE_MINISTRE',
            "Dossier transmis au Secrétaire particulier du Ministre par le DC.",
            ancien_statut=ancien_statut,
            nouveau_statut=Courrier.Statut.ANALYSE_VALIDE,
        )
        notifier_role(
            User.Role.SECRETAIRE_MINISTRE, courrier,
            f"Le DC a transmis {courrier.reference}. Vous pouvez le transmettre au Ministre.",
        )
        return redirect('courrier_detail', pk=courrier_id)


# ==============================================================================
# DÉCISION DU MINISTRE
# ==============================================================================

class DecisionCreateView(LoginRequiredMixin, RoleRequiredMixin, CreateView):
    """
    Prise de décision finale par le Ministre.
    Met le statut du courrier à DECIDE et notifie les parties prenantes.
    """
    model = Decision
    form_class = DecisionForm
    template_name = 'decision_form.html'
    allowed_roles = [User.Role.MINISTRE]

    def get_courrier(self):
        return get_object_or_404(
            Courrier.objects.pour_utilisateur(self.request.user).filter(
                statut=Courrier.Statut.TRANSMIS_MINISTRE,
            ).filter(
                Q(decision__isnull=False)
                | (
                    Q(decision__isnull=True)
                    & (Q(fiche_analyse__valide=True) | Q(fiche_analyse_sg__valide=True))
                )
            ),
            pk=self.kwargs['courrier_id'],
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        courrier = self.get_courrier()
        context['courrier'] = courrier
        context['decision_initiale'] = getattr(courrier, 'decision', None)
        context['decision_finale'] = getattr(courrier, 'decision_finale', None)
        context['courrier_sortant'] = getattr(courrier, 'courrier_sortant', None)
        context['circuit_traitement_final'] = context['decision_initiale'] is not None

        try:
            context['fiche_analyse'] = courrier.fiche_analyse
        except FicheAnalyse.DoesNotExist:
            context['fiche_analyse'] = None

        try:
            context['fiche_analyse_sg'] = courrier.fiche_analyse_sg
        except FicheAnalyseSG.DoesNotExist:
            context['fiche_analyse_sg'] = None

        if courrier.reponse_requise:
            context['lettre_reponse_validee'] = courrier.reponses_courrier.filter(
                statut_traitement='VALIDE'
            ).order_by('-date_preparation').first()
        else:
            context['lettre_reponse_validee'] = None

        return context

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['circuit_final'] = getattr(self.get_courrier(), 'decision', None) is not None
        if self.request.method != 'POST':
            kwargs['initial'] = {'delai_traitement_jours': self.get_courrier().delai_traitement_jours}
        return kwargs

    def form_valid(self, form):
        try:
            with transaction.atomic():
                Courrier.objects.select_for_update().get(pk=self.kwargs['courrier_id'])
                courrier = self.get_courrier()
                action_finale = self.request.POST.get('action_finale') or 'valider'
                decision_initiale = getattr(courrier, 'decision', None)

                if decision_initiale is not None:
                    if getattr(courrier, 'decision_finale', None) is not None:
                        messages.error(self.request, "La décision finale de ce courrier existe déjà.")
                        return redirect('courrier_detail', pk=courrier.pk)
                    if action_finale != 'valider':
                        raise PermissionDenied("Seule la signature finale est disponible à cette étape.")
                    if not courrier.reponse_requise or not courrier.reponses_courrier.filter(statut_traitement=ReponseCourrier.Statut.VALIDE).exists():
                        raise PermissionDenied("Une lettre validée par le Directeur est nécessaire avant signature.")
                    lettre_html = self.request.POST.get('lettre_html')
                    fichier_signe = form.cleaned_data.get('document_signe')
                    
                    if lettre_html:
                        import weasyprint
                        from django.core.files.base import ContentFile
                        
                        # Créer un PDF basique à partir du HTML
                        pdf_bytes = weasyprint.HTML(string=lettre_html).write_pdf()
                        pdf_file = ContentFile(pdf_bytes, name=f"Lettre_Signee_{courrier.reference.replace('/', '_')}.pdf")
                        
                        document_signe = Document.objects.create(
                            courrier=courrier,
                            nom=f"Décision finale signée — {courrier.reference}",
                            fichier=pdf_file,
                            taille_octets=len(pdf_bytes),
                        )
                    elif fichier_signe:
                        validate_document_upload(fichier_signe)
                        document_signe = Document.objects.create(
                            courrier=courrier,
                            nom=f"Décision finale signée — {courrier.reference}",
                            fichier=fichier_signe,
                            taille_octets=fichier_signe.size,
                        )
                    else:
                        form.add_error(None, "Veuillez signer la lettre électroniquement en l'ouvrant dans l'éditeur.")
                        return self.form_invalid(form)
                    DecisionFinale.objects.create(
                        courrier=courrier,
                        signe_par=self.request.user,
                        instructions_finales=form.cleaned_data.get('instructions_finales') or '',
                        document_signe=document_signe,
                    )
                    cloturer_traitement(courrier, self.request.user)
                    sortant, _ = CourrierSortant.objects.get_or_create(
                        courrier=courrier,
                        defaults={
                            'enregistre_par': self.request.user,
                            'destinataire': courrier.expediteur_nom or courrier.expediteur_institution,
                            'objet': courrier.designation,
                            'document': document_signe,
                            'date_expedition': None,
                            'observation': "Enregistrement automatique après signature finale, transmis au Secrétariat central.",
                        },
                    )
                    creer_historique(courrier, self.request.user, 'ENREGISTREMENT_COURRIER_SORTANT',
                        f"Courrier sortant {sortant.reference_sortie} enregistré automatiquement pour le Secrétariat central.",
                        document=document_signe)
                    creer_historique(
                        courrier, self.request.user, 'DECISION_FINALE_MINISTRE',
                        f"Décision finale signée par {self.request.user.get_full_name() or self.request.user.username}.",
                        role=self.request.user.role,
                        ancien_statut=Courrier.Statut.TRANSMIS_MINISTRE,
                        nouveau_statut=Courrier.Statut.TERMINE,
                        document=document_signe,
                    )
                    notifier_role(
                        User.Role.SECRETARIAT_CENTRAL, courrier,
                        f"Le courrier signé {courrier.reference} est traité et enregistré comme courrier sortant.",
                    )
                    messages.success(self.request, "Courrier traité, alertes levées et courrier sortant enregistré pour le Secrétariat central.")
                    return redirect('courrier_detail', pk=courrier.pk)

                form.instance.signe_par = self.request.user
                form.instance.courrier = courrier
                form.instance.fiche_analyse = courrier.fiche_analyse
                if not form.cleaned_data.get('delai_traitement_jours'):
                    form.add_error(
                        'delai_traitement_jours',
                        "Le délai de traitement doit être défini par le Ministre avant l'affectation.",
                    )
                    return self.form_invalid(form)
                fichier_signe = form.cleaned_data.get('document_signe')
                if fichier_signe:
                    form.add_error('document_signe', "La signature est réservée à la décision finale après traitement.")
                    return self.form_invalid(form)

                response = super().form_valid(form)

                courrier.statut = (
                    Courrier.Statut.SIGNE_PAR_MINISTRE
                    if form.instance.document_signe_id
                    else Courrier.Statut.DECIDE
                )
                courrier.delai_traitement_jours = form.cleaned_data['delai_traitement_jours']
                courrier.save(update_fields=['statut', 'delai_traitement_jours'])

                # Résolution automatique de la relance Décision Ministre
                resoudre_relances_courrier(courrier, etapes=Relance.Etape.DECISION)

                creer_historique(
                    courrier=courrier,
                    utilisateur=self.request.user,
                    action='DECISION_MINISTRE',
                    description=f"Décision du Ministre {self.request.user.get_full_name() or self.request.user.username} : "
                                f"{(self.object.instructions_finales or '')[:100]}..."
                )

                notifier_role(
                    role=User.Role.DC,
                    courrier=courrier,
                    message=f"Le Ministre a pris sa décision sur {courrier.reference}. "
                            f"Le courrier est prêt à être affecté."
                )
                notifier_role(
                    role=User.Role.SECRETARIAT_CENTRAL,
                    courrier=courrier,
                    message=f"Décision rendue sur {courrier.reference} : {courrier.designation[:60]}."
                )
        except IntegrityError:
            messages.error(self.request, "Une décision existe déjà pour ce courrier.")
            return redirect('courrier_detail', pk=self.kwargs['courrier_id'])

        messages.success(
            self.request,
            f"✅ Décision enregistrée pour {courrier.reference}. Vous pouvez maintenant affecter le courrier."
        )
        return response

    def get_success_url(self):
        return reverse('affectation_nouveau', kwargs={'courrier_id': self.kwargs['courrier_id']})


# ==============================================================================
# COURRIER SORTANT — Secrétariat central
# ==============================================================================

class CourrierSortantCreateView(LoginRequiredMixin, RoleRequiredMixin, CreateView):
    model = CourrierSortant
    form_class = CourrierSortantForm
    template_name = 'courrier_sortant_form.html'
    allowed_roles = [User.Role.SECRETARIAT_CENTRAL]

    def get_courrier(self):
        return get_object_or_404(
            Courrier.objects.pour_utilisateur(self.request.user).filter(
                statut=Courrier.Statut.SIGNE_PAR_MINISTRE,
                ).filter(
                    Q(decision_finale__document_signe__isnull=False)
                    | Q(decision__document_signe__isnull=False),
            ),
            pk=self.kwargs['courrier_id'],
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['courrier'] = self.get_courrier()
        return context

    def form_valid(self, form):
        courrier = self.get_courrier()
        if CourrierSortant.objects.filter(courrier=courrier).exists():
            messages.error(self.request, "Ce courrier sortant est déjà enregistré.")
            return redirect('courrier_detail', pk=courrier.pk)
        fichier = form.cleaned_data.get('document_signe')
        decision_finale = getattr(courrier, 'decision_finale', None)
        document = (
            decision_finale.document_signe
            if decision_finale is not None
            else courrier.decision.document_signe
        )
        if fichier:
            validate_document_upload(fichier)
            document = Document.objects.create(
                courrier=courrier,
                nom=f"Courrier sortant signé — {courrier.reference}",
                fichier=fichier,
                taille_octets=fichier.size,
            )
        form.instance.courrier = courrier
        form.instance.enregistre_par = self.request.user
        form.instance.document = document
        response = super().form_valid(form)
        ancien = courrier.statut
        courrier.statut = Courrier.Statut.COURRIER_SORTANT
        courrier.save(update_fields=['statut'])
        creer_historique(
            courrier, self.request.user, 'ENREGISTREMENT_COURRIER_SORTANT',
            f"Courrier sortant {self.object.reference_sortie} enregistré pour {self.object.destinataire}.",
            role=self.request.user.role, ancien_statut=ancien,
            nouveau_statut=Courrier.Statut.COURRIER_SORTANT,
            document=document,
        )
        notifier_role(
            User.Role.MINISTRE, courrier,
            f"Le courrier signé {courrier.reference} a été enregistré comme courrier sortant."
        )
        messages.success(self.request, f"Courrier sortant {self.object.reference_sortie} enregistré.")
        return response

    def get_success_url(self):
        return reverse('courrier_detail', kwargs={'pk': self.kwargs['courrier_id']})


# AFFECTATION AUX SERVICES/DIRECTIONS (Phase 10)
# ==============================================================================

class ReponseCourrierCreateView(LoginRequiredMixin, RoleRequiredMixin, View):
    """Crée une réponse écrite pour un courrier déjà affecté à un agent d’une direction.
    L’agent prépare la réponse et la soumet ensuite à son directeur pour validation.
    """
    allowed_roles = [User.Role.AGENT]

    @transaction.atomic
    def post(self, request, courrier_id):
        courrier = get_object_or_404(
            Courrier.objects.select_for_update().pour_utilisateur(request.user).filter(
                statut__in=[Courrier.Statut.AFFECTE, Courrier.Statut.CORRECTION_DEMANDEE],
                affectations__destinataire=request.user,
            ),
            pk=courrier_id,
        )

        sans_reponse = request.POST.get('mode') == 'sans_reponse'
        if courrier.reponse_requise and sans_reponse:
            raise PermissionDenied("Une réponse écrite est obligatoire pour ce courrier.")
        if not courrier.reponse_requise and not sans_reponse:
            raise PermissionDenied("Ce courrier doit être clôturé sans réponse écrite.")

        observation = (request.POST.get('observation') or '').strip()
        if not observation:
            messages.error(request, "Veuillez saisir la réponse ou le rapport de traitement avant soumission.")
            target_view = 'circuit_reponse' if request.POST.get('retour') == 'circuit_reponse' else 'courrier_detail'
            return redirect(target_view, pk=courrier_id)

        if courrier.reponse_requise:
            import bleach
            allowed_tags = ['p', 'b', 'i', 'u', 'em', 'strong', 'a', 'br', 'ul', 'ol', 'li', 'h1', 'h2', 'h3', 'h4', 'blockquote', 'span']
            allowed_attributes = {'a': ['href', 'title', 'target'], 'span': ['style'], 'p': ['style', 'class']}
            observation = bleach.clean(
                observation,
                tags=allowed_tags,
                attributes=allowed_attributes,
                strip=True
            )

        libelle_traitement = 'Lettre de réponse' if courrier.reponse_requise else 'Rapport d’action terrain'
        
        est_brouillon = request.POST.get('action_brouillon') == '1'
        nouveau_statut = ReponseCourrier.Statut.BROUILLON if est_brouillon else ReponseCourrier.Statut.ENVOYE_DIRECTEUR
        
        document = None
        fichier = request.FILES.get('fichier')
        if fichier and fichier.size > MAX_UPLOAD_SIZE:
            messages.error(request, "Le fichier est trop grand (max 10 Mo).")
            return redirect('courrier_detail', pk=courrier_id)
            
        brouillon_existant = ReponseCourrier.objects.filter(
            courrier=courrier, auteur=request.user, statut_traitement=ReponseCourrier.Statut.BROUILLON
        ).first()

        if brouillon_existant:
            if fichier:
                validate_document_upload(fichier)
                document = Document.objects.create(
                    courrier=courrier,
                    nom=f"Réponse V{brouillon_existant.version} — {courrier.reference}",
                    fichier=fichier,
                    taille_octets=fichier.size,
                )
                brouillon_existant.document = document
            brouillon_existant.observation = observation
            brouillon_existant.statut_traitement = nouveau_statut
            brouillon_existant.save()
        else:
            version = (ReponseCourrier.objects.filter(
                courrier=courrier, auteur=request.user
            ).exclude(statut_traitement=ReponseCourrier.Statut.BROUILLON).order_by('-version').values_list('version', flat=True).first() or 0) + 1
            
            if fichier:
                validate_document_upload(fichier)
                document = Document.objects.create(
                    courrier=courrier,
                    nom=f"Réponse V{version} — {courrier.reference}",
                    fichier=fichier,
                    taille_octets=fichier.size,
                )
                
            ReponseCourrier.objects.create(
                courrier=courrier,
                auteur=request.user,
                version=version,
                statut_traitement=nouveau_statut,
                observation=observation,
                document=document,
            )

        if est_brouillon:
            messages.success(request, "Le brouillon a été enregistré avec succès.")
            target_view = 'circuit_reponse' if request.POST.get('retour') == 'circuit_reponse' else 'courrier_detail'
            return redirect(target_view, pk=courrier_id)

        ancien_statut = courrier.statut
        courrier.statut = Courrier.Statut.SOUMIS_DIRECTEUR
        courrier.responsable_actuel_role = User.Role.DIRECTEUR
        courrier.save(update_fields=['statut', 'responsable_actuel_role'])

        creer_historique(
            courrier=courrier,
            utilisateur=request.user,
            action='REPONSE_AGENT_SOUVISEE',
            description=f"{libelle_traitement} préparé par l’agent {request.user.get_full_name() or request.user.username} pour soumission au directeur.",
            direction=request.user.service_direction,
            ancien_statut=ancien_statut,
            nouveau_statut=Courrier.Statut.SOUMIS_DIRECTEUR,
            observation=None,
        )

        # Notifier le directeur de la même direction
        for directeur in User.objects.filter(
            role=User.Role.DIRECTEUR,
            service_direction=request.user.service_direction,
            is_active=True,
        ):
            notifier(
                destinataire=directeur,
                courrier=courrier,
                message=f"{libelle_traitement} soumis par l’agent {request.user.get_full_name() or request.user.username} pour {courrier.reference}."
            )

        messages.success(request, f"✅ {libelle_traitement} enregistré pour {courrier.reference} et envoyée à validation hiérarchique.")
        target_view = 'circuit_reponse' if request.POST.get('retour') == 'circuit_reponse' else 'courrier_detail'
        return redirect(target_view, pk=courrier_id)


class ReponseCourrierValidateView(LoginRequiredMixin, RoleRequiredMixin, View):
    """La validation d’une réponse écrite par le directeur de la même direction.
    Le directeur valide ou demande une correction en fermant le cycle de réponse.
    """
    allowed_roles = [User.Role.DIRECTEUR]

    @transaction.atomic
    def post(self, request, courrier_id, pk):
        courrier = get_object_or_404(
            Courrier.objects.select_for_update().pour_utilisateur(request.user).filter(
                statut=Courrier.Statut.SOUMIS_DIRECTEUR,
            ),
            pk=courrier_id,
        )
        reponse = get_object_or_404(ReponseCourrier.objects.select_related('courrier', 'auteur'), pk=pk, courrier=courrier)

        if not request.user.service_direction or normalize_service(request.user.service_direction) != normalize_service(reponse.auteur.service_direction):
            raise PermissionDenied("Un directeur ne peut valider que la réponse d’un agent de sa propre direction.")

        if reponse.statut_traitement != ReponseCourrier.Statut.ENVOYE_DIRECTEUR:
            raise PermissionDenied("Cette réponse a déjà été examinée.")
        decision = (request.POST.get('decision') or '').strip()
        if decision not in ['valider', 'corriger']:
            decision = 'valider'

        if decision == 'corriger':
            courrier.statut = Courrier.Statut.CORRECTION_DEMANDEE
            courrier.responsable_actuel_role = User.Role.AGENT
            courrier.save(update_fields=['statut', 'responsable_actuel_role'])
            reponse.statut_traitement = ReponseCourrier.Statut.CORRECTION
            observation_directeur = (request.POST.get('observation') or '').strip()
            reponse.save(update_fields=['statut_traitement'])

            creer_historique(
                courrier=courrier,
                utilisateur=request.user,
                action='REPONSE_CORRECTION_DEMANDEE',
                description=f"Correction demandée par le directeur {request.user.get_full_name() or request.user.username} sur la réponse du courrier.",
                direction=request.user.service_direction,
                ancien_statut=Courrier.Statut.SOUMIS_DIRECTEUR,
                nouveau_statut=Courrier.Statut.CORRECTION_DEMANDEE,
                observation=observation_directeur,
            )
            messages.error(request, f"✅ Correction demandée sur la réponse de {courrier.reference}.")
        else:
            lettre_html = (request.POST.get('lettre_html') or '').strip()
            if lettre_html:
                reponse.observation = lettre_html

            if not courrier.reponse_requise:
                courrier.statut = Courrier.Statut.VALIDE_DIRECTEUR
                courrier.responsable_actuel_role = User.Role.DIRECTEUR
                courrier.save(update_fields=['statut', 'responsable_actuel_role'])
                reponse.statut_traitement = ReponseCourrier.Statut.VALIDE
                reponse.save(update_fields=['statut_traitement', 'observation'])
                
                creer_historique(
                    courrier=courrier,
                    utilisateur=request.user,
                    action='REPONSE_VALIDE_DIRECTEUR',
                    description=f"Rapport validé par le directeur {request.user.get_full_name() or request.user.username}.",
                    direction=request.user.service_direction,
                    ancien_statut=Courrier.Statut.SOUMIS_DIRECTEUR,
                    nouveau_statut=Courrier.Statut.VALIDE_DIRECTEUR,
                    observation='Validation du rapport.',
                )

                cloturer_traitement(courrier, request.user)
                creer_historique(courrier, request.user, 'CLOTURE_ACTION_TERRAIN',
                    "Rapport d’action terrain validé par le Directeur. Courrier traité.",
                    ancien_statut=Courrier.Statut.VALIDE_DIRECTEUR,
                    nouveau_statut=Courrier.Statut.TERMINE)
                messages.success(request, "Rapport validé : le courrier est traité et les alertes sont levées.")
                return redirect('circuit_reponse', pk=courrier_id)
            
            else:
                # Validation ET transmission au SG immédiate
                courrier.statut = Courrier.Statut.TRANSMIS_SG
                courrier.responsable_actuel_role = User.Role.SECRETAIRE_SG
                courrier.save(update_fields=['statut', 'responsable_actuel_role'])
                reponse.statut_traitement = ReponseCourrier.Statut.VALIDE
                reponse.save(update_fields=['statut_traitement', 'observation'])

                creer_historique(
                    courrier=courrier,
                    utilisateur=request.user,
                    action='REPONSE_VALIDE_ET_TRANSMISE_SG',
                    description=f"Réponse écrite validée et transmise au Secrétariat Général par le directeur {request.user.get_full_name() or request.user.username}.",
                    direction=request.user.service_direction,
                    ancien_statut=Courrier.Statut.SOUMIS_DIRECTEUR,
                    nouveau_statut=Courrier.Statut.TRANSMIS_SG,
                    observation='Réponse validée et transmise.',
                )
                
                notifier_role(
                    role=User.Role.SECRETAIRE_SG,
                    courrier=courrier,
                    message=f"Le Directeur a validé et transmis le courrier {courrier.reference} au Secrétariat Général.",
                )
                messages.success(request, f"✅ Réponse écrite validée et transmise au Secrétaire SG pour {courrier.reference}.")

        target_view = 'circuit_reponse' if request.POST.get('retour') == 'circuit_reponse' else 'courrier_detail'
        return redirect(target_view, pk=courrier_id)


class DirecteurTransmettreSGView(LoginRequiredMixin, RoleRequiredMixin, View):
    """Transmet au Secrétaire SG une réponse validée par le Directeur."""

    allowed_roles = [User.Role.DIRECTEUR]

    @transaction.atomic
    def post(self, request, courrier_id):
        courrier = get_object_or_404(
            Courrier.objects.select_for_update().pour_utilisateur(request.user).filter(
                statut=Courrier.Statut.VALIDE_DIRECTEUR,
            ),
            pk=courrier_id,
        )
        if not courrier.reponse_requise:
            raise PermissionDenied("Une action terrain est clôturée par le Directeur et ne suit pas le circuit de signature.")
        service = normalize_service(request.user.service_direction)
        services = {service, 'DAF' if service == 'DAAF' else 'DAAF'}
        if not courrier.reponses_courrier.filter(
            auteur__service_direction__in=services,
            statut_traitement=ReponseCourrier.Statut.VALIDE,
        ).exists():
            raise PermissionDenied(
                "Aucune réponse validée de votre direction ne peut être transmise."
            )
        ancien_statut = courrier.statut
        courrier.statut = Courrier.Statut.TRANSMIS_SG
        courrier.responsable_actuel_role = User.Role.SECRETAIRE_SG
        courrier.save(update_fields=['statut', 'responsable_actuel_role'])
        creer_historique(
            courrier=courrier,
            utilisateur=request.user,
            action='TRANSMISSION_DIRECTEUR_SECRETAIRE_SG',
            description=(
                f"Courrier transmis au Secrétaire du SG par "
                f"{request.user.get_full_name() or request.user.username}."
            ),
            direction=request.user.service_direction,
            ancien_statut=ancien_statut,
            nouveau_statut=Courrier.Statut.TRANSMIS_SG,
        )
        notifier_role(
            role=User.Role.SECRETAIRE_SG,
            courrier=courrier,
            message=f"Le Directeur a validé et transmis le courrier {courrier.reference} au Secrétaire du SG.",
        )
        messages.success(request, f"✅ {courrier.reference} a été transmis au Secrétaire du SG.")
        target_view = 'circuit_reponse' if request.POST.get('retour') == 'circuit_reponse' else 'courrier_detail'
        return redirect(target_view, pk=courrier_id)


class AffectationCreateView(LoginRequiredMixin, RoleRequiredMixin, CreateView):
    """
    Affectation du courrier aux directions/services/agents après la décision du Ministre.
    Peut créer plusieurs affectations pour un même courrier.
    Met le statut du courrier à AFFECTE et notifie les destinataires.
    Le directeur reçoit un droit d'affectation interne limité à sa propre direction.
    """
    model = Affectation
    form_class = AffectationForm
    template_name = 'affectation_form.html'
    allowed_roles = [
        User.Role.MINISTRE,
        User.Role.DC,
        User.Role.SECRETARIAT_CENTRAL,
        User.Role.DIRECTEUR,
    ]

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['request_user'] = self.request.user
        return kwargs

    def get_courrier(self):
        return get_object_or_404(
            Courrier.objects.pour_utilisateur(self.request.user).filter(decision__isnull=False),
            pk=self.kwargs['courrier_id'],
            statut__in=[
                Courrier.Statut.DECIDE,
                Courrier.Statut.AFFECTE,
            ]
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        courrier = self.get_courrier()
        context['courrier'] = courrier
        context['affectations_existantes'] = courrier.affectations.select_related('destinataire').order_by('-date_affectation')[:100]
        context['decision'] = courrier.decision
        context['user'] = self.request.user
        return context

    def form_valid(self, form):
        with transaction.atomic():
            Courrier.objects.select_for_update().get(pk=self.kwargs['courrier_id'])
            courrier = self.get_courrier()
            user = self.request.user
            if courrier.affectations.exists() and user.role != User.Role.DIRECTEUR:
                raise PermissionDenied("Ce courrier a déjà été affecté ; aucune nouvelle affectation n'est autorisée.")

            if not courrier.delai_traitement_jours:
                messages.error(
                    self.request,
                    "Le délai de traitement doit être défini par le Ministre avant l'affectation."
                )
                return redirect('courrier_detail', pk=courrier.pk)

            # ── Multi-sélection pour le Ministre ──
            services_multiples = self.request.POST.getlist('services_multiples')
            if user.role == User.Role.MINISTRE and services_multiples:
                from datetime import timedelta
                note = form.cleaned_data.get('note_traitement', '')
                noms_services = []

                for service_nom in services_multiples:
                    aff = Affectation(
                        courrier=courrier,
                        decision=courrier.decision,
                        affecte_par=user,
                        service_concerne=service_nom,
                        note_traitement=note,
                    )
                    aff.save()
                    aff.date_limite_traitement = aff.date_affectation + timedelta(days=courrier.delai_traitement_jours)
                    aff.save(update_fields=['date_limite_traitement'])
                    noms_services.append(service_nom)

                    # Notifier les directeurs du département
                    for directeur in User.objects.filter(
                        role=User.Role.DIRECTEUR,
                        service_direction=service_nom,
                        is_active=True,
                    ):
                        notifier(
                            destinataire=directeur,
                            courrier=courrier,
                            message=f"Nouveau courrier affecté à votre direction : {courrier.reference} — {courrier.designation[:60]}."
                        )
                    
                    transaction.on_commit(lambda a=aff: envoyer_email_affectation(a))

                ancien_statut = courrier.statut
                courrier.statut = Courrier.Statut.AFFECTE
                courrier.responsable_actuel_role = User.Role.DIRECTEUR
                courrier.save(update_fields=['statut', 'responsable_actuel_role'])

                resoudre_relances_courrier(courrier, etapes=Relance.Etape.AFFECTATION)

                liste_services = ', '.join(noms_services)
                creer_historique(
                    courrier=courrier,
                    utilisateur=user,
                    action='AFFECTATION',
                    description=f"Courrier affecté aux directions : {liste_services} par {user.get_full_name() or user.username}.",
                    role=user.role,
                    ancien_statut=ancien_statut,
                    nouveau_statut=Courrier.Statut.AFFECTE,
                    observation=f"Affectation multi-directions : {liste_services}.",
                )

                messages.success(
                    self.request,
                    f"✅ Courrier {courrier.reference} affecté à {len(noms_services)} département(s) : {liste_services}."
                )
                return redirect('courrier_detail', pk=courrier.pk)

            # ── Affectation simple (Directeur, DC, Secrétariat Central) ──
            form.instance.affecte_par = self.request.user
            form.instance.courrier = courrier
            form.instance.decision = courrier.decision

            # Contrôle serveur strict pour la sécurité du workflow directeur → agent.
            destinataire = form.cleaned_data.get('destinataire')
            service = normalize_service(form.cleaned_data.get('service_concerne'))

            # Sécurité métier stricte :
            # - le Ministre peut choisir une direction ou un agent sans direction;
            # - le Directeur ne doit pas réaffecter un courrier deux fois;
            # - le Directeur ne peut affecter qu'un seul agent de sa propre direction;
            # - le Directeur ne peut pas remettre le courrier vers une autre direction.
            if user.role == User.Role.DIRECTEUR and user.service_direction:
                expected = normalize_service(user.service_direction)
                # Le Ministre affecte d'abord la direction (sans destinataire).
                # Le Directeur complète ensuite cette affectation par un agent,
                # sans créer un second destinataire directeur.
                direction_affectee = Affectation.objects.filter(
                    courrier=courrier,
                    destinataire__isnull=True,
                    service_concerne__in={expected, 'DAF' if expected == 'DAAF' else 'DAAF'},
                ).exists() or Affectation.objects.filter(
                    courrier=courrier,
                    destinataire=user,
                ).exists()
                if not direction_affectee:
                    raise PermissionDenied("Ce courrier n'est pas affecté à votre direction.")
                if not destinataire:
                    raise PermissionDenied("Le directeur doit sélectionner un agent de sa direction.")

                if destinataire and getattr(destinataire, 'service_direction', None):
                    agent_service = normalize_service(destinataire.service_direction)
                    if agent_service != expected:
                        raise PermissionDenied("Vous ne pouvez affecter qu'un agent de votre propre direction.")

                if service and normalize_service(service) != expected:
                    raise PermissionDenied("Vous ne pouvez affecter un courrier qu'à une direction de votre propre service.")

                if Affectation.objects.filter(
                    courrier=courrier,
                    destinataire__role=User.Role.AGENT,
                    service_concerne__in={expected, 'DAF' if expected == 'DAAF' else 'DAAF'},
                ).exists():
                    raise PermissionDenied("Un agent est déjà affecté à ce courrier dans votre direction.")

                # Le directeur laisse l'agent se choisir ; le service est alors
                # pleinement inféré à sa propre direction, tel que requis.
                if destinataire and not service:
                    service = expected
                    form.cleaned_data['service_concerne'] = service
                    form.instance.service_concerne = service

            # Contrôle serveur de cohérence direction / destinataire.
            if destinataire and getattr(destinataire, 'service_direction', None):
                inferred_service = normalize_service(destinataire.service_direction)
                if service and inferred_service and inferred_service != service:
                    raise PermissionDenied("Le destinataire choisi ne correspond pas au service sélectionné.")
                if not service:
                    form.cleaned_data['service_concerne'] = inferred_service
                    service = inferred_service
                form.instance.service_concerne = service

            if user.role == User.Role.DIRECTEUR:
                reponse_requise = form.cleaned_data['type_traitement'] == 'LETTRE'
                if courrier.affectations.filter(destinataire__role=User.Role.AGENT).exists() and courrier.reponse_requise != reponse_requise:
                    form.add_error('type_traitement', "Ce courrier a déjà un type de traitement pour ses agents. Conservez le même type.")
                    return self.form_invalid(form)
                courrier.reponse_requise = reponse_requise
                courrier.save(update_fields=['reponse_requise'])

            response = super().form_valid(form)
            affectation = self.object

            # La date limite part de l'affectation et du délai propre au courrier.
            from datetime import timedelta
            affectation.date_limite_traitement = affectation.date_affectation + timedelta(days=courrier.delai_traitement_jours)
            affectation.save(update_fields=['date_limite_traitement'])
            informations_delai = (
                f"Délai fixé par le Ministre : {courrier.delai_traitement_jours} jour(s). "
                f"Date limite : {affectation.date_limite_traitement:%d/%m/%Y %H:%M}."
            )

            ancien_statut = courrier.statut
            courrier.statut = Courrier.Statut.AFFECTE
            courrier.responsable_actuel_role = (
                affectation.destinataire.role if affectation.destinataire else User.Role.DIRECTEUR
            )
            courrier.save(update_fields=['statut', 'responsable_actuel_role'])

            # Résolution automatique de la relance Affectation
            resoudre_relances_courrier(courrier, etapes=Relance.Etape.AFFECTATION)

            service_nom = affectation.service_concerne or "aucun service"
            if affectation.destinataire:
                destination_description = (
                    f"{affectation.destinataire.get_full_name() or affectation.destinataire.username}"
                )
            elif self.request.user.role == User.Role.MINISTRE and service_nom != "aucun service":
                destination_description = f"au Directeur de la direction {service_nom}"
            else:
                destination_description = f"à la direction {service_nom}"

            creer_historique(
                courrier=courrier,
                utilisateur=self.request.user,
                action='AFFECTATION',
                description=f"Courrier transmis {destination_description} par "
                            f"{self.request.user.get_full_name() or self.request.user.username}.",
                role=self.request.user.role,
                direction=service_nom,
                ancien_statut=ancien_statut,
                nouveau_statut=Courrier.Statut.AFFECTE,
                observation=f"Affectation {service_nom} par {self.request.user.get_full_name() or self.request.user.username}.",
            )

            if affectation.destinataire:
                notifier(
                    destinataire=affectation.destinataire,
                    courrier=courrier,
                    message=f"Nouveau courrier affecté à votre service : {courrier.reference} — {courrier.designation[:60]}. "
                            f"{informations_delai} Décision du Ministre : {(courrier.decision.instructions_finales or '')[:80]}..."
                )
            elif affectation.service_concerne:
                # Lorsqu'une affectation vise un service sans agent nommé, son
                # directeur est le détenteur opérationnel du courrier.
                for directeur in User.objects.filter(
                    role=User.Role.DIRECTEUR,
                    service_direction=affectation.service_concerne,
                    is_active=True,
                ):
                    notifier(
                        destinataire=directeur,
                        courrier=courrier,
                        message=f"Nouveau courrier affecté à votre direction : {courrier.reference} — {courrier.designation[:60]}. {informations_delai}"
                    )

            transaction.on_commit(lambda: envoyer_email_affectation(affectation))

        messages.success(
            self.request,
            f"✅ Courrier {courrier.reference} affecté à {affectation.service_concerne}. Le destinataire a été notifié."
        )
        return response

    def get_success_url(self):
        return reverse('courrier_detail', kwargs={'pk': self.kwargs['courrier_id']})


class TransmettreCourrierView(LoginRequiredMixin, RoleRequiredMixin, View):
    """
    Vue permettant au Secrétaire de transmettre un courrier à son supérieur.
    Modifie le statut, crée un historique et une notification.
    """
    allowed_roles = [User.Role.SECRETAIRE_DC, User.Role.SECRETAIRE_SG, User.Role.SECRETAIRE_MINISTRE]

    def post(self, request, courrier_id):
        courrier = get_object_or_404(
            Courrier.objects.pour_utilisateur(request.user),
            pk=courrier_id
        )

        ancien_statut = courrier.statut
        # Déterminer le destinataire et le nouveau statut
        if request.user.role == User.Role.SECRETAIRE_SG:
            if courrier.statut not in [Courrier.Statut.ARRIVE, Courrier.Statut.TRANSMIS_SG]:
                messages.error(request, "Transmission impossible : le courrier n'est pas en attente au Secrétaire du SG.")
                target_view = 'circuit_reponse' if request.POST.get('retour') == 'circuit_reponse' else 'courrier_detail'
                return redirect(target_view, pk=courrier_id)

            role_destinataire = User.Role.SG
            titre_destinataire = "Secrétaire Général"
            nouveau_statut = Courrier.Statut.EN_COURS_SG
            message_notif = f"Nouveau courrier transmis par votre secrétariat : {courrier.reference} — {courrier.designation[:60]}."

        elif request.user.role == User.Role.SECRETAIRE_DC:
            if courrier.statut != Courrier.Statut.TRANSMIS_DC:
                messages.error(request, "Transmission impossible : le courrier n'est pas en attente au Secrétariat du DC.")
                target_view = 'circuit_reponse' if request.POST.get('retour') == 'circuit_reponse' else 'courrier_detail'
                return redirect(target_view, pk=courrier_id)

            role_destinataire = User.Role.DC
            titre_destinataire = "Directeur de Cabinet"
            nouveau_statut = Courrier.Statut.EN_COURS_DC
            message_notif = f"Courrier transmis au Directeur de Cabinet : {courrier.reference} — {courrier.designation[:60]}."

        elif request.user.role == User.Role.SECRETAIRE_MINISTRE:
            # Le Secrétaire du Ministre ne peut transmettre que si l'analyse est validée
            if courrier.statut != Courrier.Statut.ANALYSE_VALIDE:
                messages.error(request, "Transmission impossible : le courrier n'est pas prêt pour transmission au Ministre.")
                target_view = 'circuit_reponse' if request.POST.get('retour') == 'circuit_reponse' else 'courrier_detail'
                return redirect(target_view, pk=courrier_id)

            role_destinataire = User.Role.MINISTRE
            titre_destinataire = "Ministre"
            nouveau_statut = Courrier.Statut.TRANSMIS_MINISTRE
            message_notif = f"Courrier validé transmis pour votre décision : {courrier.reference} — {courrier.designation[:60]}."

        else:
            messages.error(request, "Vous n'êtes pas autorisé à transmettre ce courrier.")
            target_view = 'circuit_reponse' if request.POST.get('retour') == 'circuit_reponse' else 'courrier_detail'
            return redirect(target_view, pk=courrier_id)

        # Mise à jour de la lettre si modifiée
        lettre_html = (request.POST.get('lettre_html') or '').strip()
        if lettre_html:
            reponse = courrier.reponses_courrier.filter(statut_traitement=ReponseCourrier.Statut.VALIDE).order_by('-version').first()
            if reponse:
                reponse.observation = lettre_html
                reponse.save(update_fields=['observation'])

        # Mise à jour du statut
        courrier.statut = nouveau_statut
        courrier.responsable_actuel_role = role_destinataire
        courrier.save(update_fields=['statut', 'responsable_actuel_role'])

        # Résoudre les relances actives de l'étape précédente
        resoudre_relances_courrier(courrier)

        # Créer un historique
        creer_historique(
            courrier=courrier,
            utilisateur=request.user,
            action='TRANSMISSION',
            description=f"Courrier transmis au {titre_destinataire} par {request.user.get_full_name() or request.user.username}.",
            ancien_statut=ancien_statut,
            nouveau_statut=nouveau_statut,
        )

        # Envoyer une notification au(x) destinataire(s)
        notifier_role(
            role=role_destinataire,
            courrier=courrier,
            message=message_notif
        )

        messages.success(
            request,
            f"✅ Le courrier {courrier.reference} a été transmis au {titre_destinataire}."
        )
        if request.POST.get('retour') == 'circuit_reponse':
            return redirect('circuit_reponse', pk=courrier_id)
        return redirect('dashboard')


class RefuserCourrierView(LoginRequiredMixin, RoleRequiredMixin, View):
    """
    Vue permettant à un secrétaire (DC ou SG) de rejeter un courrier (ex: infos manquantes).
    Le courrier retourne au Secrétariat Central.
    """
    allowed_roles = [User.Role.SECRETAIRE_SG]

    def post(self, request, courrier_id):
        courrier = get_object_or_404(
            Courrier.objects.pour_utilisateur(request.user),
            pk=courrier_id,
            statut=Courrier.Statut.ARRIVE
        )
        motif = (request.POST.get('motif') or '').strip()

        # Exiger un motif pour les secrétaires
        if not motif:
            messages.error(request, "Veuillez fournir un motif de rejet avant de renvoyer le courrier.")
            return redirect('courrier_detail', pk=courrier_id)

        # Mise à jour du statut et du motif
        courrier.statut = Courrier.Statut.REJETE_SECRETAIRE
        courrier.motif_rejet = motif
        courrier.save(update_fields=['statut', 'motif_rejet'])

        # Résoudre les relances de l'étape arrivée
        resoudre_relances_courrier(courrier, etapes=Relance.Etape.ARRIVE)

        # Créer un historique
        creer_historique(
            courrier=courrier,
            utilisateur=request.user,
            action='REJET',
            description=f"Courrier rejeté par {request.user.get_full_name() or request.user.username}. Motif: {motif or 'Non précisé'}."
        )

        # Envoyer une notification au Secrétariat Central
        notifier_role(
            role=User.Role.SECRETARIAT_CENTRAL,
            courrier=courrier,
            message=f"Le courrier {courrier.reference} a été rejeté par le secrétariat. Motif: {motif or 'Non précisé'}."
        )

        messages.error(
            request,
            f"❌ Le courrier {courrier.reference} a été renvoyé au Secrétariat Central. Motif: {motif or 'Non précisé'}."
        )
        return redirect('dashboard')

# ==============================================================================
# NOTIFICATIONS — Marquer comme lue (AJAX)
# ==============================================================================

class MarquerNotificationLueView(LoginRequiredMixin, View):
    """
    Vue AJAX pour marquer une notification comme lue.
    Retourne du JSON pour une mise à jour sans rechargement de page.
    """
    def post(self, request, pk):
        notif = get_object_or_404(Notification, pk=pk, destinataire=request.user)
        notif.lu = True
        notif.save()
        return JsonResponse({'status': 'ok', 'nb_non_lues': request.user.notifications.filter(lu=False).count()})


# ==============================================================================
# AFFECTATION — Mise à jour du statut de traitement
# ==============================================================================

class AffectationStatutUpdateView(LoginRequiredMixin, RoleRequiredMixin, View):
    """
    Permet au destinataire d'une affectation de mettre à jour son statut d'exécution
    La clôture est réservée aux validations métier du Directeur ou du Ministre.
    """
    allowed_roles = [User.Role.DIRECTEUR, User.Role.AGENT]

    def post(self, request, pk):
        affectations = Affectation.objects.filter(destinataire=request.user)
        # Le directeur est responsable des affectations non nominatives de sa
        # direction; un expéditeur ou un affectant ne peut pas les modifier.
        if request.user.role == User.Role.DIRECTEUR and request.user.service_direction:
            affectations = Affectation.objects.filter(
                Q(destinataire=request.user) |
                Q(destinataire__isnull=True, service_concerne=request.user.service_direction)
            )
        affectation = get_object_or_404(affectations, pk=pk)
        nouveau_statut = request.POST.get('statut_traitement')
        if nouveau_statut == Affectation.StatutTraitement.TRAITE:
            raise PermissionDenied("La clôture nécessite la validation du rapport par le Directeur ou la signature finale du Ministre.")
        if affectation.statut_traitement == Affectation.StatutTraitement.TRAITE or affectation.courrier.statut == Courrier.Statut.TERMINE:
            raise PermissionDenied("Ce traitement est déjà clôturé.")
        note = (request.POST.get('note_traitement') or '').strip()

        if nouveau_statut in Affectation.StatutTraitement.values:
            affectation.statut_traitement = nouveau_statut
            if note:
                affectation.note_traitement = note
            
            if nouveau_statut == Affectation.StatutTraitement.EN_COURS and not affectation.date_reception:
                affectation.date_reception = timezone.now()

            affectation.save()
            messages.success(request, f"✅ Statut de traitement mis à jour : {affectation.get_statut_traitement_display()}.")

        return redirect('courrier_detail', pk=affectation.courrier.pk)


# ==============================================================================
# CONFIGURATION DU DÉLAI DE TRAITEMENT (RÉSERVÉ AU MINISTRE)
# ==============================================================================

class ConfigurationDelaiUpdateView(LoginRequiredMixin, RoleRequiredMixin, View):
    """
    Vue permettant exclusivement au Ministre de définir ou modifier le délai
    réglementaire de traitement des courriers (timing).
    """
    http_method_names = ['post', 'options']
    allowed_roles = [User.Role.MINISTRE]

    def post(self, request):
        delai_str = (request.POST.get('delai_jours') or '').strip()
        try:
            delai = int(delai_str)
            if delai <= 0 or delai > 180:
                messages.error(request, "Veuillez spécifier un délai valide (entre 1 et 180 jours).")
                return redirect('dashboard')
        except ValueError:
            messages.error(request, "Valeur du délai de traitement invalide.")
            return redirect('dashboard')

        config = ConfigurationDelai.objects.order_by('pk').first()
        ancien_delai = config.delai_jours if config else None
        if config is None:
            config = ConfigurationDelai()
        config.delai_jours = delai
        config.modifie_par = request.user
        config.save()

        # Synchroniser immédiatement les alertes et relances avec le nouveau délai
        synchroniser_relances()

        messages.success(
            request,
            f"✅ Le délai réglementaire de traitement des courriers a été fixé à {delai} jour(s)"
            + (f" (anciennement {ancien_delai} jour(s))." if ancien_delai else ".")
        )
        return redirect('dashboard')
