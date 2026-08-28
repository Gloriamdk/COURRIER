from django.urls import reverse_lazy
from django.views.generic import CreateView, TemplateView, ListView, DetailView
from django.contrib.auth.mixins import LoginRequiredMixin
from .models import Courrier, User, FicheAnalyse, Decision
from .forms import CourrierForm, FicheAnalyseForm
from .decision_forms import DecisionForm
from .utils import RoleRequiredMixin

# ... (les autres classes vues restent inchangées)

class DecisionCreateView(LoginRequiredMixin, RoleRequiredMixin, CreateView):
    model = Decision
    form_class = DecisionForm
    template_name = 'decision_form.html'
    success_url = reverse_lazy('courrier_liste')
    allowed_roles = [User.Role.MINISTRE]

    def form_valid(self, form):
        form.instance.signe_par = self.request.user
        form.instance.courrier_id = self.kwargs['courrier_id']
        return super().form_valid(form)

class DashboardView(LoginRequiredMixin, TemplateView):
    template_name = 'dashboard.html'
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        user = self.request.user
        
        if user.role == User.Role.SECRETARIAT_CENTRAL:
            context['courriers_recents'] = Courrier.objects.filter(cree_par=user)[:10]
        elif user.role == User.Role.DC:
            # Courriers arrivés en attente d'analyse
            context['courriers_a_analyser'] = Courrier.objects.filter(statut=Courrier.Statut.ARRIVE)
            context['analyses_faites'] = FicheAnalyse.objects.filter(analyse_par=user)[:10]
        elif user.role == User.Role.MINISTRE:
            # Courriers ayant une fiche d'analyse validée, en attente de décision finale
            context['courriers_a_decider'] = Courrier.objects.filter(statut=Courrier.Statut.ANALYSE_VALIDE)
            context['decisions_prises'] = Decision.objects.filter(signe_par=user)[:10]
            
        return context

class CourrierListView(LoginRequiredMixin, RoleRequiredMixin, ListView):
    model = Courrier
    template_name = 'courrier_list.html'
    context_object_name = 'courriers'
    allowed_roles = [User.Role.SECRETARIAT_CENTRAL, User.Role.DC, User.Role.MINISTRE]

    def get_queryset(self):
        return Courrier.objects.pour_utilisateur(self.request.user)

class CourrierDetailView(LoginRequiredMixin, DetailView):
    model = Courrier
    template_name = 'courrier_detail.html'
    context_object_name = 'courrier'

    def get_queryset(self):
        return Courrier.objects.pour_utilisateur(self.request.user)

class CourrierCreateView(LoginRequiredMixin, RoleRequiredMixin, CreateView):
    model = Courrier
    form_class = CourrierForm
    template_name = 'courrier_form.html'
    success_url = reverse_lazy('courrier_liste')
    allowed_roles = [User.Role.SECRETARIAT_CENTRAL]

    def form_valid(self, form):
        form.instance.cree_par = self.request.user
        return super().form_valid(form)

class FicheAnalyseCreateView(LoginRequiredMixin, RoleRequiredMixin, CreateView):
    model = FicheAnalyse
    form_class = FicheAnalyseForm
    template_name = 'fiche_analyse_form.html'
    success_url = reverse_lazy('dashboard')
    allowed_roles = [User.Role.DC]

    def form_valid(self, form):
        form.instance.analyse_par = self.request.user
        form.instance.courrier_id = self.kwargs['courrier_id']
        return super().form_valid(form)


