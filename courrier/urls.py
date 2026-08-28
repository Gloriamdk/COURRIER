from django.urls import path
from .views import DashboardView, CourrierCreateView, FicheAnalyseCreateView, CourrierListView, CourrierDetailView, DecisionCreateView

urlpatterns = [
    path('dashboard/', DashboardView.as_view(), name='dashboard'),
    path('courrier/liste/', CourrierListView.as_view(), name='courrier_liste'),
    path('courrier/nouveau/', CourrierCreateView.as_view(), name='courrier_nouveau'),
    path('courrier/<int:pk>/', CourrierDetailView.as_view(), name='courrier_detail'),
    path('courrier/<int:courrier_id>/fiche/nouveau/', FicheAnalyseCreateView.as_view(), name='fiche_nouveau'),
    path('courrier/<int:courrier_id>/decision/nouveau/', DecisionCreateView.as_view(), name='decision_nouveau'),
]
