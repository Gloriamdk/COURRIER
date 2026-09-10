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
from django.db.models import Q
from pathlib import Path

from .models import Courrier, User, FicheAnalyse, FicheAnalyseSG, Decision, Document, Historique, Notification, Affectation, Relance, ConfigurationDelai
from .forms import CourrierForm, FicheAnalyseForm, FicheAnalyseSGForm, AffectationForm
from .decision_forms import DecisionForm
from .utils import RoleRequiredMixin
from .validators import validate_document_upload
from .services import synchroniser_relances, resoudre_relances_courrier, get_relances_pour_utilisateur
import mimetypes


# ==============================================================================
# HELPER — Créer un historique et une notification
# ==============================================================================

def creer_historique(courrier, utilisateur, action, description):
    """Raccourci pour créer une entrée dans le journal d'audit."""
    Historique.objects.create(
        courrier=courrier,
        utilisateur=utilisateur,
        action=action,
        description=description,
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
        relances_qs = get_relances_pour_utilisateur(user)
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
            context['courriers_recents'] = Courrier.objects.filter(cree_par=user).select_related('cree_par').order_by('-date_enregistrement')[:10]
            context['total_courriers'] = Courrier.objects.filter(cree_par=user).count()
            context['courriers_en_attente'] = Courrier.objects.filter(statut=Courrier.Statut.ARRIVE).count()

        elif user.role in [User.Role.DC, User.Role.SG]:
            context['courriers_a_analyser'] = Courrier.objects.filter(statut__in=[Courrier.Statut.TRANSMIS_DC, Courrier.Statut.EN_COURS_DC]).select_related('cree_par').order_by('-date_arrivee')[:10]
            context['analyses_faites'] = FicheAnalyse.objects.filter(analyse_par=user).select_related('courrier').order_by('-date_analyse')[:10]
            context['total_a_analyser'] = Courrier.objects.filter(statut__in=[Courrier.Statut.TRANSMIS_DC, Courrier.Statut.EN_COURS_DC]).count()
            context['en_cours'] = Courrier.objects.filter(statut=Courrier.Statut.EN_COURS_DC).count()

        elif user.role == User.Role.SECRETAIRE_MINISTRE:
            context['courriers_recents'] = Courrier.objects.filter(statut=Courrier.Statut.ANALYSE_VALIDE).select_related('cree_par').order_by('-date_arrivee')[:10]
            context['total_courriers'] = Courrier.objects.filter(statut=Courrier.Statut.ANALYSE_VALIDE).count()

        elif user.role == User.Role.MINISTRE:
            context['courriers_a_decider'] = Courrier.objects.filter(statut=Courrier.Statut.TRANSMIS_MINISTRE).select_related('cree_par').order_by('-date_arrivee')[:10]
            context['decisions_prises'] = Decision.objects.filter(signe_par=user).select_related('courrier').order_by('-date_decision')[:10]
            context['total_a_decider'] = Courrier.objects.filter(statut=Courrier.Statut.TRANSMIS_MINISTRE).count()
            context['total_decides'] = Decision.objects.filter(signe_par=user).count()

        elif user.role in [User.Role.SECRETAIRE_SG, User.Role.SECRETAIRE_DC]:
            context['courriers_recents'] = Courrier.objects.filter(statut=Courrier.Statut.ARRIVE).select_related('cree_par').order_by('-date_arrivee')[:10]
            context['total_courriers'] = Courrier.objects.filter(statut=Courrier.Statut.ARRIVE).count()

        elif user.role in [User.Role.DIRECTEUR, User.Role.AGENT]:
            # Les directeurs/agents voient les courriers qui leur ont été affectés
            qs_aff = Affectation.objects.filter(destinataire=user)
            context['mes_affectations'] = qs_aff.select_related('courrier', 'decision').order_by('-date_affectation')[:10]
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

        # Affectations
        context['affectations'] = courrier.affectations.select_related('destinataire', 'affecte_par').order_by('-date_affectation')[:100]

        # Permissions d'action affichées dans le template
        context['peut_analyser'] = (
            user.role in [User.Role.DC, User.Role.SG]
            and context['fiche_analyse'] is None
            and courrier.statut in [Courrier.Statut.TRANSMIS_DC, Courrier.Statut.EN_COURS_DC]
        )
        context['peut_valider_fiche'] = (
            user.role == User.Role.DC
            and context['fiche_analyse'] is not None
            and not context['fiche_analyse'].valide
            and context['fiche_analyse'].analyse_par_id == user.id
            and courrier.statut == Courrier.Statut.EN_COURS_DC
        )
        # Permission pour le SG de valider sa propre fiche
        try:
            fiche_sg = courrier.fiche_analyse_sg
        except FicheAnalyseSG.DoesNotExist:
            fiche_sg = None

        context['peut_valider_fiche_sg'] = (
            user.role == User.Role.SG
            and fiche_sg is not None
            and not fiche_sg.valide
            and fiche_sg.analyse_par_id == user.id
            and courrier.statut == Courrier.Statut.EN_COURS_DC
        )
        context['peut_decider'] = (
            user.role == User.Role.MINISTRE
            and context['fiche_analyse'] is not None
            and context['fiche_analyse'].valide
            and context['decision'] is None
            and courrier.statut == Courrier.Statut.TRANSMIS_MINISTRE
        )
        context['peut_affecter'] = (
            user.role in [User.Role.MINISTRE, User.Role.DC, User.Role.SECRETARIAT_CENTRAL]
            and context['decision'] is not None
            and courrier.statut == Courrier.Statut.DECIDE
        )

        return context


# ==============================================================================
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

        # Notification vers tous les DC
        notifier_role(
            role=User.Role.DC,
            courrier=courrier,
            message=f"Nouveau courrier enregistré : {courrier.reference} — {courrier.designation[:60]}. "
                    f"Priorité : {courrier.get_priorite_display()}."
        )

        messages.success(
            self.request,
            f"✅ Courrier {courrier.reference} enregistré avec succès et transmis au Directeur de Cabinet."
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
        if not is_authorized:
            raise Http404("Document introuvable.")

        try:
            file_handle = document.fichier.open("rb")
        except FileNotFoundError:
            raise Http404("Fichier introuvable.")

        # Détermination sûre du type MIME pour l'en-tête Content-Type
        guessed_type, _ = mimetypes.guess_type(document.fichier.name)
        content_type = guessed_type or 'application/octet-stream'

        extension = Path(document.fichier.name).suffix.lower()
        filename = f"document-{document.pk}{extension}"
        response = FileResponse(file_handle, as_attachment=True, filename=filename, content_type=content_type)
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
                statut__in=[Courrier.Statut.TRANSMIS_DC, Courrier.Statut.EN_COURS_DC],
                fiche_analyse__isnull=True,
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
            f"✅ Fiche d'analyse enregistrée. Vous pouvez maintenant la valider pour la transmettre au Ministre."
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
                statut__in=[Courrier.Statut.TRANSMIS_DC, Courrier.Statut.EN_COURS_DC],
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

                # Keep in EN_COURS_DC so DC/SG can work in parallel
                courrier.statut = Courrier.Statut.EN_COURS_DC
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
    Passe le statut du courrier à ANALYSE_VALIDE et notifie le Ministre.
    """
    allowed_roles = [User.Role.DC]

    def post(self, request, courrier_id):
        courrier = get_object_or_404(
            Courrier.objects.pour_utilisateur(request.user).filter(
                statut=Courrier.Statut.EN_COURS_DC,
                fiche_analyse__analyse_par=request.user,
                fiche_analyse__valide=False,
            ),
            pk=courrier_id,
        )
        fiche = courrier.fiche_analyse

        # Validation de la fiche
        fiche.valide = True
        fiche.date_validation = timezone.now()
        fiche.save(update_fields=['valide', 'date_validation'])

        # Résolution automatique des relances de l'étape Analyse DC
        resoudre_relances_courrier(courrier, etapes=Relance.Etape.ANALYSE_DC)

        # Journal d'audit
        creer_historique(
            courrier=courrier,
            utilisateur=request.user,
            action='VALIDATION_ANALYSE',
            description=f"Fiche d'analyse validée par le DC {request.user.get_full_name() or request.user.username}."
        )

        # Si la fiche SG existe et est validée, on marque l'analyse globale comme validée
        try:
            fiche_sg = courrier.fiche_analyse_sg
        except FicheAnalyseSG.DoesNotExist:
            fiche_sg = None

        if fiche_sg and fiche_sg.valide:
            courrier.statut = Courrier.Statut.ANALYSE_VALIDE
            courrier.save(update_fields=['statut'])

            notifier_role(
                role=User.Role.SECRETAIRE_MINISTRE,
                courrier=courrier,
                message=f"Nouveau courrier à soumettre au Ministre : {courrier.reference} — {courrier.designation[:60]}."
            )
            messages.success(
                request,
                f"✅ Analyse validée. Le Secrétariat du Ministre a été notifié pour transmission."
            )
        else:
            # On reste en attente de la validation complémentaire du SG
            messages.success(
                request,
                f"✅ Votre validation a été enregistrée. En attente de la validation complémentaire du SG."
            )
        return redirect('courrier_detail', pk=courrier_id)


class FicheAnalyseSGValidateView(LoginRequiredMixin, RoleRequiredMixin, View):
    """
    Validation de la fiche SG par le Secrétaire Général.
    Si la fiche DC est validée aussi, on notifie le Secrétariat du Ministre.
    """
    allowed_roles = [User.Role.SG]

    def post(self, request, courrier_id):
        courrier = get_object_or_404(
            Courrier.objects.pour_utilisateur(request.user).filter(
                statut=Courrier.Statut.EN_COURS_DC,
                fiche_analyse_sg__analyse_par=request.user,
                fiche_analyse_sg__valide=False,
            ),
            pk=courrier_id,
        )
        fiche = courrier.fiche_analyse_sg

        fiche.valide = True
        fiche.date_validation = timezone.now()
        fiche.save(update_fields=['valide', 'date_validation'])

        # Résolution automatique des relances de l'étape Analyse SG
        resoudre_relances_courrier(courrier, etapes=Relance.Etape.ANALYSE_SG)

        creer_historique(
            courrier=courrier,
            utilisateur=request.user,
            action='VALIDATION_ANALYSE_SG',
            description=f"Fiche d'analyse (SG) validée par {request.user.get_full_name() or request.user.username}."
        )

        # Si la fiche DC existe et est validée, on marque l'analyse globale comme validée
        try:
            fiche_dc = courrier.fiche_analyse
        except FicheAnalyse.DoesNotExist:
            fiche_dc = None

        if fiche_dc and fiche_dc.valide:
            courrier.statut = Courrier.Statut.ANALYSE_VALIDE
            courrier.save(update_fields=['statut'])

            notifier_role(
                role=User.Role.SECRETAIRE_MINISTRE,
                courrier=courrier,
                message=f"Nouveau courrier à soumettre au Ministre : {courrier.reference} — {courrier.designation[:60]}."
            )
            messages.success(
                request,
                f"✅ Analyse (SG) validée. Le Secrétariat du Ministre a été notifié pour transmission."
            )
        else:
            messages.success(
                request,
                f"✅ Votre validation a été enregistrée. En attente de la validation complémentaire du DC."
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
                fiche_analyse__valide=True,
                fiche_analyse_sg__valide=True,
                decision__isnull=True,
            ),
            pk=self.kwargs['courrier_id'],
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        courrier = self.get_courrier()
        context['courrier'] = courrier

        try:
            context['fiche_analyse'] = courrier.fiche_analyse
        except FicheAnalyse.DoesNotExist:
            context['fiche_analyse'] = None

        return context

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        if self.request.method != 'POST':
            kwargs['initial'] = {'delai_traitement_jours': self.get_courrier().delai_traitement_jours}
        return kwargs

    def form_valid(self, form):
        try:
            with transaction.atomic():
                courrier = self.get_courrier()
                form.instance.signe_par = self.request.user
                form.instance.courrier = courrier
                form.instance.fiche_analyse = courrier.fiche_analyse

                response = super().form_valid(form)

                courrier.statut = Courrier.Statut.DECIDE
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
# AFFECTATION AUX SERVICES/DIRECTIONS (Phase 10)
# ==============================================================================

class AffectationCreateView(LoginRequiredMixin, RoleRequiredMixin, CreateView):
    """
    Affectation du courrier aux directions/services/agents après la décision du Ministre.
    Peut créer plusieurs affectations pour un même courrier.
    Met le statut du courrier à AFFECTE et notifie les destinataires.
    """
    model = Affectation
    form_class = AffectationForm
    template_name = 'affectation_form.html'
    allowed_roles = [User.Role.MINISTRE, User.Role.DC, User.Role.SECRETARIAT_CENTRAL]

    def get_courrier(self):
        return get_object_or_404(
            Courrier.objects.pour_utilisateur(self.request.user).filter(decision__isnull=False),
            pk=self.kwargs['courrier_id'],
            statut=Courrier.Statut.DECIDE
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        courrier = self.get_courrier()
        context['courrier'] = courrier
        context['affectations_existantes'] = courrier.affectations.select_related('destinataire').order_by('-date_affectation')[:100]
        context['decision'] = courrier.decision
        return context

    def form_valid(self, form):
        with transaction.atomic():
            courrier = self.get_courrier()
            form.instance.affecte_par = self.request.user
            form.instance.courrier = courrier
            form.instance.decision = courrier.decision
            response = super().form_valid(form)
            affectation = self.object

            # La date limite part de l'affectation et du délai propre au courrier.
            if not courrier.delai_traitement_jours:
                raise ValueError("Le délai de traitement doit être défini par le Ministre avant l'affectation.")
            from datetime import timedelta
            affectation.date_limite_traitement = affectation.date_affectation + timedelta(days=courrier.delai_traitement_jours)
            affectation.save(update_fields=['date_limite_traitement'])
            informations_delai = (
                f"Délai fixé par le Ministre : {courrier.delai_traitement_jours} jour(s). "
                f"Date limite : {affectation.date_limite_traitement:%d/%m/%Y %H:%M}."
            )

            courrier.statut = Courrier.Statut.AFFECTE
            courrier.responsable_actuel_role = (
                affectation.destinataire.role if affectation.destinataire else User.Role.DIRECTEUR
            )
            courrier.save(update_fields=['statut', 'responsable_actuel_role'])

            # Résolution automatique de la relance Affectation
            resoudre_relances_courrier(courrier, etapes=Relance.Etape.AFFECTATION)

            destinataire_nom = (
                f"{affectation.destinataire.get_full_name() or affectation.destinataire.username}"
                if affectation.destinataire else "aucun agent"
            )
            service_nom = affectation.service_concerne or "aucun service"

            creer_historique(
                courrier=courrier,
                utilisateur=self.request.user,
                action='AFFECTATION',
                description=f"Courrier affecté à {destinataire_nom} ({service_nom}) par "
                            f"{self.request.user.get_full_name() or self.request.user.username}."
            )

            if affectation.destinataire:
                notifier(
                    destinataire=affectation.destinataire,
                    courrier=courrier,
                    message=f"Nouveau courrier affecté à votre service : {courrier.reference} — {courrier.designation[:60]}. "
                            f"{informations_delai} Décision du Ministre : {courrier.decision.instructions_finales[:80]}..."
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

        # Déterminer le destinataire et le nouveau statut
        if request.user.role in [User.Role.SECRETAIRE_DC, User.Role.SECRETAIRE_SG]:
            # Ne pas permettre une retransmission si le courrier n'est plus à l'état d'arrivée
            if courrier.statut != Courrier.Statut.ARRIVE:
                messages.error(request, "Transmission impossible : le courrier a déjà été transmis ou n'est plus modifiable.")
                return redirect('courrier_detail', pk=courrier_id)

            role_destinataire = User.Role.DC if request.user.role == User.Role.SECRETAIRE_DC else User.Role.SG
            titre_destinataire = "Directeur de Cabinet" if request.user.role == User.Role.SECRETAIRE_DC else "Secrétaire Général"
            nouveau_statut = Courrier.Statut.TRANSMIS_DC
            message_notif = f"Nouveau courrier transmis par votre secrétariat : {courrier.reference} — {courrier.designation[:60]}."

        elif request.user.role == User.Role.SECRETAIRE_MINISTRE:
            # Le Secrétaire du Ministre ne peut transmettre que si l'analyse est validée
            if courrier.statut != Courrier.Statut.ANALYSE_VALIDE:
                messages.error(request, "Transmission impossible : le courrier n'est pas prêt pour transmission au Ministre.")
                return redirect('courrier_detail', pk=courrier_id)

            role_destinataire = User.Role.MINISTRE
            titre_destinataire = "Ministre"
            nouveau_statut = Courrier.Statut.TRANSMIS_MINISTRE
            message_notif = f"Courrier validé transmis pour votre décision : {courrier.reference} — {courrier.designation[:60]}."

        else:
            messages.error(request, "Vous n'êtes pas autorisé à transmettre ce courrier.")
            return redirect('courrier_detail', pk=courrier_id)

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
            description=f"Courrier transmis au {titre_destinataire} par {request.user.get_full_name() or request.user.username}."
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
        return redirect('dashboard')


class RefuserCourrierView(LoginRequiredMixin, RoleRequiredMixin, View):
    """
    Vue permettant à un secrétaire (DC ou SG) de rejeter un courrier (ex: infos manquantes).
    Le courrier retourne au Secrétariat Central.
    """
    allowed_roles = [User.Role.SECRETAIRE_DC, User.Role.SECRETAIRE_SG]

    def post(self, request, courrier_id):
        courrier = get_object_or_404(
            Courrier.objects.pour_utilisateur(request.user),
            pk=courrier_id,
            statut=Courrier.Statut.ARRIVE
        )
        motif = (request.POST.get('motif') or '').strip()

        # Exiger un motif pour les secrétaires
        if request.user.role in [User.Role.SECRETAIRE_DC, User.Role.SECRETAIRE_SG] and not motif:
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
    (ex: RECU -> EN_COURS -> TRAITE). Résout automatiquement les relances à la finalisation.
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
        note = (request.POST.get('note_traitement') or '').strip()

        if nouveau_statut in Affectation.StatutTraitement.values:
            affectation.statut_traitement = nouveau_statut
            if note:
                affectation.note_traitement = note
            
            if nouveau_statut == Affectation.StatutTraitement.TRAITE:
                affectation.date_traitement = timezone.now()
                affectation.traite_par = request.user
                # Résoudre la relance liée au traitement
                resoudre_relances_courrier(affectation.courrier, etapes=Relance.Etape.TRAITEMENT_SERVICE)
                
                # Créer un historique
                creer_historique(
                    courrier=affectation.courrier,
                    utilisateur=request.user,
                    action='TRAITEMENT_FINALISE',
                    description=f"Affectation marquée comme traitée par {request.user.get_full_name() or request.user.username}."
                )

                # Si toutes les affectations sont traitées, marquer le courrier comme TERMINE
                if not affectation.courrier.affectations.exclude(statut_traitement=Affectation.StatutTraitement.TRAITE).exists():
                    affectation.courrier.statut = Courrier.Statut.TERMINE
                    affectation.courrier.save(update_fields=['statut'])
                    resoudre_relances_courrier(affectation.courrier)
                    creer_historique(
                        courrier=affectation.courrier,
                        utilisateur=request.user,
                        action='CLOTURE',
                        description="Toutes les affectations ont été traitées. Courrier clôturé."
                    )
            elif nouveau_statut == Affectation.StatutTraitement.EN_COURS and not affectation.date_reception:
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


