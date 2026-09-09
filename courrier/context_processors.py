"""
Context processors pour l'application Courrier (MTCA).
Injecte globalement les alertes / relances et les notifications dans les templates.
"""

from .services import get_relances_pour_utilisateur, synchroniser_relances


def alertes_context_processor(request):
    """
    Fournit le nombre et la liste des alertes / relances actives pour l'utilisateur connecté.
    """
    if not request.user.is_authenticated or not request.user.is_active:
        return {
            'nb_alertes': 0,
            'alertes_actives_nav': [],
        }

    # Récupérer les relances actives
    relances_qs = get_relances_pour_utilisateur(request.user)
    
    return {
        'nb_alertes': relances_qs.count(),
        'alertes_actives_nav': relances_qs.order_by('-date_creation')[:5],
    }
