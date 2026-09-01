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
from django.views.generic import CreateView, TemplateView, ListView, DetailView, View
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.auth import logout
from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect
from django.http import FileResponse, Http404, JsonResponse
from django.utils import timezone
from django.db import IntegrityError, transaction
from pathlib import Path

from .models import Courrier, User, FicheAnalyse, Decision, Document, Historique, Notification, Affectation
from .forms import CourrierForm, FicheAnalyseForm, AffectationForm
from .decision_forms import DecisionForm
from .utils import RoleRequiredMixin
from .validators import validate_document_upload


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
    Notification.objects.create(
        destinataire=destinataire,
        courrier=courrier,
        message=message,
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

        # Notifications non lues (commun à tous les rôles)
        context['notifications_non_lues'] = user.notifications.filter(lu=False).order_by('-date_notification')[:5]
        context['nb_notifications'] = user.notifications.filter(lu=False).count()

        if user.role == User.Role.SECRETARIAT_CENTRAL:
            context['courriers_recents'] = Courrier.objects.filter(cree_par=user).order_by('-date_enregistrement')[:10]
            context['total_courriers'] = Courrier.objects.filter(cree_par=user).count()
            context['courriers_en_attente'] = Courrier.objects.filter(statut=Courrier.Statut.ARRIVE).count()

        elif user.role in [User.Role.DC, User.Role.SECRETAIRE_DC]:
            context['courriers_a_analyser'] = Courrier.objects.filter(statut=Courrier.Statut.ARRIVE).order_by('-date_arrivee')[:10]
            context['analyses_faites'] = FicheAnalyse.objects.filter(analyse_par=user).order_by('-date_analyse')[:10]
            context['total_a_analyser'] = Courrier.objects.filter(statut=Courrier.Statut.ARRIVE).count()
            context['en_cours'] = Courrier.objects.filter(statut=Courrier.Statut.EN_COURS_DC).count()

        elif user.role in [User.Role.MINISTRE, User.Role.SECRETAIRE_MINISTRE]:
            context['courriers_a_decider'] = Courrier.objects.filter(statut=Courrier.Statut.ANALYSE_VALIDE).order_by('-date_arrivee')[:10]
            context['decisions_prises'] = Decision.objects.filter(signe_par=user).order_by('-date_decision')[:10]
            context['total_a_decider'] = Courrier.objects.filter(statut=Courrier.Statut.ANALYSE_VALIDE).count()
            context['total_decides'] = Decision.objects.filter(signe_par=user).count()

        elif user.role in [User.Role.DIRECTEUR, User.Role.AGENT]:
            # Les directeurs/agents voient les courriers qui leur ont été affectés
            context['mes_affectations'] = Affectation.objects.filter(
                destinataire=user
            ).select_related('courrier', 'decision').order_by('-date_affectation')[:10]
            context['affectations_en_cours'] = Affectation.objects.filter(
                destinataire=user,
                statut_traitement=Affectation.StatutTraitement.EN_COURS
            ).count()
            context['affectations_recues'] = Affectation.objects.filter(
                destinataire=user,
                statut_traitement=Affectation.StatutTraitement.RECU
            ).count()

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
        return Courrier.objects.pour_utilisateur(self.request.user)

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
            user.role == User.Role.DC
            and context['fiche_analyse'] is None
            and courrier.statut in [Courrier.Statut.ARRIVE, Courrier.Statut.EN_COURS_DC]
        )
        context['peut_valider_fiche'] = (
            user.role == User.Role.DC
            and context['fiche_analyse'] is not None
            and not context['fiche_analyse'].valide
            and context['fiche_analyse'].analyse_par_id == user.id
            and courrier.statut == Courrier.Statut.EN_COURS_DC
        )
        context['peut_decider'] = (
            user.role == User.Role.MINISTRE
            and context['fiche_analyse'] is not None
            and context['fiche_analyse'].valide
            and context['decision'] is None
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

        extension = Path(document.fichier.name).suffix.lower()
        filename = f"document-{document.pk}{extension}"
        return FileResponse(file_handle, as_attachment=True, filename=filename)


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
                statut=Courrier.Statut.ARRIVE,
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

        # Mise à jour du statut du courrier
        courrier.statut = Courrier.Statut.ANALYSE_VALIDE
        courrier.save(update_fields=['statut'])

        # Journal d'audit
        creer_historique(
            courrier=courrier,
            utilisateur=request.user,
            action='VALIDATION_ANALYSE',
            description=f"Fiche d'analyse validée par le DC {request.user.get_full_name() or request.user.username}. "
                        f"Courrier transmis au Ministre pour décision."
        )

        # Notification au Ministre
        notifier_role(
            role=User.Role.MINISTRE,
            courrier=courrier,
            message=f"Courrier {courrier.reference} prêt pour votre décision. "
                    f"Analyse du DC disponible : {courrier.designation[:60]}."
        )
        notifier_role(
            role=User.Role.SECRETAIRE_MINISTRE,
            courrier=courrier,
            message=f"Nouveau courrier à soumettre au Ministre : {courrier.reference} — {courrier.designation[:60]}."
        )

        messages.success(
            request,
            f"✅ Analyse validée. Le Ministre a été notifié pour la décision sur {courrier.reference}."
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
                statut=Courrier.Statut.ANALYSE_VALIDE,
                fiche_analyse__valide=True,
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

    def form_valid(self, form):
        try:
            with transaction.atomic():
                courrier = self.get_courrier()
                form.instance.signe_par = self.request.user
                form.instance.courrier = courrier
                form.instance.fiche_analyse = courrier.fiche_analyse

                response = super().form_valid(form)

                courrier.statut = Courrier.Statut.DECIDE
                courrier.save(update_fields=['statut'])

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

            courrier.statut = Courrier.Statut.AFFECTE
            courrier.save(update_fields=['statut'])

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
                            f"Décision du Ministre : {courrier.decision.instructions_finales[:80]}..."
                )

        messages.success(
            self.request,
            f"✅ Courrier {courrier.reference} affecté à {affectation.service_concerne}. Le destinataire a été notifié."
        )
        return response

    def get_success_url(self):
        return reverse('courrier_detail', kwargs={'pk': self.kwargs['courrier_id']})


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
