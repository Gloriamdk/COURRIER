"""
URL patterns — Application courrier (GEC Ministère).
"""
from django.urls import path
from .views import (
    DashboardView,
    CourrierListView,
    CourrierCreateView,
    CourrierDetailView,
    FicheAnalyseCreateView,
    FicheAnalyseValidateView,
    DecisionCreateView,
    AffectationCreateView,
    DocumentDownloadView,
    MarquerNotificationLueView,
)

urlpatterns = [
    # ── Tableau de bord ──────────────────────────────────────────────────────
    path('dashboard/', DashboardView.as_view(), name='dashboard'),

    # ── Courriers ─────────────────────────────────────────────────────────────
    path('liste/', CourrierListView.as_view(), name='courrier_liste'),
    path('nouveau/', CourrierCreateView.as_view(), name='courrier_nouveau'),
    path('<int:pk>/', CourrierDetailView.as_view(), name='courrier_detail'),
    path('document/<int:pk>/telecharger/', DocumentDownloadView.as_view(), name='document_telecharger'),

    # ── Fiche d'analyse (DC) ─────────────────────────────────────────────────
    path('<int:courrier_id>/fiche/nouveau/', FicheAnalyseCreateView.as_view(), name='fiche_nouveau'),
    path('<int:courrier_id>/fiche/valider/', FicheAnalyseValidateView.as_view(), name='fiche_valider'),

    # ── Décision (Ministre) ───────────────────────────────────────────────────
    path('<int:courrier_id>/decision/nouveau/', DecisionCreateView.as_view(), name='decision_nouveau'),

    # ── Affectation (DC / Secrétariat Central) ────────────────────────────────
    path('<int:courrier_id>/affectation/nouveau/', AffectationCreateView.as_view(), name='affectation_nouveau'),

    # ── Notifications (AJAX) ─────────────────────────────────────────────────
    path('notification/<int:pk>/lue/', MarquerNotificationLueView.as_view(), name='notification_lue'),
]
