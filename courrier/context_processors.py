"""
Context processors pour l'application Courrier (MTCA).
Injecte globalement les alertes / relances et les notifications dans les templates.
"""

from .services import get_relances_pour_utilisateur, synchroniser_relances
from .models import ConfigurationDelai


ROLES_AVEC_ALERTES = {
    'MINISTRE',
    'SECRETAIRE_MINISTRE',
    'SG',
    'DC',
    'DIRECTEUR',
    'AGENT',
}


def alertes_context_processor(request):
    """
    Fournit le nombre et la liste des alertes / relances actives pour l'utilisateur connecté,
    ainsi que le délai réglementaire de traitement actuellement défini par le Ministre.
    """
    delai_actuel = ConfigurationDelai.get_delai_jours()
    alertes_visibles = (
        request.user.is_authenticated
        and request.user.is_active
        and request.user.role in ROLES_AVEC_ALERTES
    )

    if not request.user.is_authenticated or not request.user.is_active:
        return {
            'nb_alertes': 0,
            'alertes_actives_nav': [],
            'alertes_visibles': False,
            'delai_traitement_actuel': delai_actuel,
            'delai_traitement_configure': delai_actuel is not None,
        }

    # Récupérer les relances actives
    relances_qs = get_relances_pour_utilisateur(request.user) if alertes_visibles else None
    
    return {
        'nb_alertes': relances_qs.count() if relances_qs is not None else 0,
        'alertes_actives_nav': relances_qs.order_by('-date_creation')[:5] if relances_qs is not None else [],
        'alertes_visibles': alertes_visibles,
        'delai_traitement_actuel': delai_actuel,
        'delai_traitement_configure': delai_actuel is not None,
    }
