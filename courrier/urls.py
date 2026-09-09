"""
URL patterns — Application courrier (GEC Ministère).
"""
from django.urls import path
from .views import (
    DashboardView,
    CourrierListView,
    CourrierCreateView,
    CourrierUpdateView,
    CourrierDetailView,
    FicheAnalyseCreateView,
    FicheAnalyseSGCreateView,
    FicheAnalyseValidateView,
    FicheAnalyseSGValidateView,
    DecisionCreateView,
    AffectationCreateView,
    DocumentDownloadView,
    TransmettreCourrierView,
    RefuserCourrierView,
    MarquerNotificationLueView,
    AffectationStatutUpdateView,
    ConfigurationDelaiUpdateView,
)

urlpatterns = [
    # ── Configuration du délai (Ministre) ────────────────────────────────────
    path('configuration-delai/', ConfigurationDelaiUpdateView.as_view(), name='configuration_delai_update'),
    # ── Tableau de bord ──────────────────────────────────────────────────────
    path('dashboard/', DashboardView.as_view(), name='dashboard'),

    # ── Courriers ─────────────────────────────────────────────────────────────
    path('liste/', CourrierListView.as_view(), name='courrier_liste'),
    path('nouveau/', CourrierCreateView.as_view(), name='courrier_nouveau'),
    path('<int:pk>/', CourrierDetailView.as_view(), name='courrier_detail'),
    path('document/<int:pk>/telecharger/', DocumentDownloadView.as_view(), name='document_telecharger'),

    # ── Fiche d'analyse (DC) ─────────────────────────────────────────────────
    path('<int:courrier_id>/fiche/nouveau/', FicheAnalyseCreateView.as_view(), name='fiche_nouveau'),
    path('<int:courrier_id>/fiche-sg/nouveau/', FicheAnalyseSGCreateView.as_view(), name='fiche_sg_nouveau'),
    path('<int:courrier_id>/fiche/valider/', FicheAnalyseValidateView.as_view(), name='fiche_valider'),
    path('<int:courrier_id>/fiche-sg/valider/', FicheAnalyseSGValidateView.as_view(), name='fiche_sg_valider'),

    # ── Décision (Ministre) ───────────────────────────────────────────────────
    path('<int:courrier_id>/decision/nouveau/', DecisionCreateView.as_view(), name='decision_nouveau'),

    # ── Affectation (DC / Secrétariat Central) ────────────────────────────────
    path('<int:courrier_id>/affectation/nouveau/', AffectationCreateView.as_view(), name='affectation_nouveau'),
    path('affectation/<int:pk>/statut/', AffectationStatutUpdateView.as_view(), name='affectation_statut_update'),

    # ── Transmission & Rejet (Secrétaires) ───────────────────────────────────
    path('<int:courrier_id>/transmettre/', TransmettreCourrierView.as_view(), name='courrier_transmettre'),
    path('<int:courrier_id>/refuser/', RefuserCourrierView.as_view(), name='courrier_refuser'),
    path('<int:pk>/editer/', CourrierUpdateView.as_view(), name='courrier_editer'),

    # ── Notifications (AJAX) ─────────────────────────────────────────────────
    path('notification/<int:pk>/lue/', MarquerNotificationLueView.as_view(), name='notification_lue'),
]
