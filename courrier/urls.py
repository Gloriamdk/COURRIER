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
    FicheAnalyseCorrectionView,
    SGTransmettreDCView,
    DCTransmettreMinistreView,
    DecisionCreateView,
    AffectationCreateView,
    DocumentDownloadView,
    TransmettreCourrierView,
    RefuserCourrierView,
    MarquerNotificationLueView,
    AffectationStatutUpdateView,
    ConfigurationDelaiUpdateView,
    ReponseCourrierCreateView,
    ReponseCourrierValidateView,
    DirecteurTransmettreSGView,
    CourrierSortantCreateView,
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
    path('<int:courrier_id>/fiche/correction/', FicheAnalyseCorrectionView.as_view(), name='fiche_correction'),
    path('<int:courrier_id>/sg/transmettre-dc/', SGTransmettreDCView.as_view(), name='sg_transmettre_dc'),
    path('<int:courrier_id>/dc/transmettre-ministre/', DCTransmettreMinistreView.as_view(), name='dc_transmettre_ministre'),

    # ── Décision (Ministre) ───────────────────────────────────────────────────
    path('<int:courrier_id>/decision/nouveau/', DecisionCreateView.as_view(), name='decision_nouveau'),
    path('<int:courrier_id>/sortant/nouveau/', CourrierSortantCreateView.as_view(), name='courrier_sortant_nouveau'),

    # ── Affectation (DC / Secrétariat Central) ────────────────────────────────
    path('<int:courrier_id>/affectation/nouveau/', AffectationCreateView.as_view(), name='affectation_nouveau'),
    path('affectation/<int:pk>/statut/', AffectationStatutUpdateView.as_view(), name='affectation_statut_update'),

    # ── Transmission & Rejet (Secrétaires) ───────────────────────────────────
    path('<int:courrier_id>/transmettre/', TransmettreCourrierView.as_view(), name='courrier_transmettre'),
    path('<int:courrier_id>/refuser/', RefuserCourrierView.as_view(), name='courrier_refuser'),
    path('<int:pk>/editer/', CourrierUpdateView.as_view(), name='courrier_editer'),

    # ── Réponse écrite de l’agent / validation du directeur ────────────────
    path('<int:courrier_id>/reponse/nouveau/', ReponseCourrierCreateView.as_view(), name='reponse_nouveau'),
    path('<int:courrier_id>/reponse/<int:pk>/valider/', ReponseCourrierValidateView.as_view(), name='reponse_valider'),
    path('<int:courrier_id>/transmettre-secretaire-sg/', DirecteurTransmettreSGView.as_view(), name='directeur_transmettre_sg'),

    # ── Notifications (AJAX) ─────────────────────────────────────────────────
    path('notification/<int:pk>/lue/', MarquerNotificationLueView.as_view(), name='notification_lue'),
]
