"""
Services de gestion des alertes et relances automatiques — GEC MTCA.

Règles métier :
1. Détection automatique des courriers sans traitement depuis plus de 3 jours à chaque étape.
2. Éviter toute duplication de relance pour une même étape et un même destinataire.
3. Résolution automatique dès que le courrier est transmis, validé, décidé ou traité.
4. Filtrage :
   - Secrétaires & Superusers : voient toutes les alertes de tout le monde.
   - Autres utilisateurs (Ministre, DC, SG, Directeurs, Agents) : voient uniquement leurs alertes.
"""

from datetime import timedelta
from django.conf import settings
from django.utils import timezone
from django.db.models import Q
from django.db import transaction

from .models import Courrier, User, Relance, Affectation, FicheAnalyse, FicheAnalyseSG, Decision, Historique, ConfigurationDelai


def get_delai_jours():
    """Récupère le délai de traitement fixé par le Ministre (en jours)."""
    return ConfigurationDelai.get_delai_jours()


def date_seuil_relance():
    """Retourne l'horodatage seuil au-delà duquel un courrier est considéré en retard selon la décision du Ministre."""
    return timezone.now() - timedelta(days=get_delai_jours())


def resoudre_relances_courrier(courrier, etapes=None):
    """
    Résout les relances actives d'un courrier.
    Si `etapes` est spécifié (liste ou valeur unique), seules les relances de ces étapes sont résolues.
    """
    qs = Relance.objects.filter(courrier=courrier, est_resolue=False)
    if etapes:
        if isinstance(etapes, (list, tuple, set)):
            qs = qs.filter(etape__in=etapes)
        else:
            qs = qs.filter(etape=etapes)
    
    now = timezone.now()
    qs.update(est_resolue=True, date_resolution=now)


def get_ou_creer_relance(courrier, etape, date_debut_etape, destinataire_role=None, destinataire_user=None, service_concerne=None):
    """
    Crée une relance si elle n'existe pas déjà comme relance active pour ce courrier, cette étape et ce destinataire.
    Évite les doublons.
    """
    if not date_debut_etape:
        return None

    # Vérifier si une relance active existe déjà
    filtre = Q(
        courrier=courrier,
        etape=etape,
        est_resolue=False,
    )
    if destinataire_user:
        filtre &= Q(destinataire_user=destinataire_user)
    elif destinataire_role:
        filtre &= Q(destinataire_role=destinataire_role)
    elif service_concerne:
        filtre &= Q(service_concerne=service_concerne)

    existante = Relance.objects.filter(filtre).first()
    if existante:
        # Met à jour la date_debut_etape si nécessaire
        if existante.date_debut_etape != date_debut_etape:
            existante.date_debut_etape = date_debut_etape
            existante.save(update_fields=['date_debut_etape'])
        return existante

    # Création de la nouvelle relance
    return Relance.objects.create(
        courrier=courrier,
        etape=etape,
        destinataire_user=destinataire_user,
        destinataire_role=destinataire_role,
        service_concerne=service_concerne,
        date_debut_etape=date_debut_etape,
        est_resolue=False,
    )


def synchroniser_relances():
    """
    Examine tous les courriers actifs et génère/résout les relances en fonction
    du temps passé à chaque étape (> 3 jours).
    """
    seuil = date_seuil_relance()
    
    # 1. Courriers ARRIVE (attente de transmission par les secrétariats DC / SG / Central)
    courriers_arrive = Courrier.objects.filter(
        statut=Courrier.Statut.ARRIVE,
        date_arrivee__lte=seuil
    )
    for c in courriers_arrive:
        # Résoudre d'éventuelles relances d'anciennes étapes
        Relance.objects.filter(courrier=c, est_resolue=False).exclude(etape=Relance.Etape.ARRIVE).update(est_resolue=True, date_resolution=timezone.now())
        
        # Relance pour les secrétariats
        for role in [User.Role.SECRETAIRE_DC, User.Role.SECRETAIRE_SG, User.Role.SECRETARIAT_CENTRAL]:
            get_ou_creer_relance(
                courrier=c,
                etape=Relance.Etape.ARRIVE,
                destinataire_role=role,
                date_debut_etape=c.date_arrivee
            )

    # 2. Courriers REJETES (retour au Secrétariat Central)
    courriers_rejet = Courrier.objects.filter(
        statut=Courrier.Statut.REJETE_SECRETAIRE
    )
    for c in courriers_rejet:
        hist_rejet = c.historiques.filter(action='REJET').order_by('-date_action').first()
        date_debut = hist_rejet.date_action if hist_rejet else c.date_arrivee
        if date_debut <= seuil:
            Relance.objects.filter(courrier=c, est_resolue=False).exclude(etape=Relance.Etape.REJET).update(est_resolue=True, date_resolution=timezone.now())
            get_ou_creer_relance(
                courrier=c,
                etape=Relance.Etape.REJET,
                destinataire_role=User.Role.SECRETARIAT_CENTRAL,
                destinataire_user=c.cree_par,
                date_debut_etape=date_debut
            )

    # 3. Courriers TRANSMIS_DC / EN_COURS_DC (analyse DC / SG)
    courriers_dc = Courrier.objects.filter(
        statut__in=[Courrier.Statut.TRANSMIS_DC, Courrier.Statut.EN_COURS_DC]
    ).select_related('fiche_analyse', 'fiche_analyse_sg')
    
    for c in courriers_dc:
        hist_trans = c.historiques.filter(action='TRANSMISSION').order_by('-date_action').first()
        date_debut = hist_trans.date_action if hist_trans else c.date_arrivee
        if date_debut <= seuil:
            # Vérifier si la fiche DC est validée
            try:
                fiche_dc = c.fiche_analyse
                dc_valide = fiche_dc.valide
            except FicheAnalyse.DoesNotExist:
                dc_valide = False

            # Vérifier si la fiche SG est validée
            try:
                fiche_sg = c.fiche_analyse_sg
                sg_valide = fiche_sg.valide
            except FicheAnalyseSG.DoesNotExist:
                sg_valide = False

            if not dc_valide:
                get_ou_creer_relance(
                    courrier=c,
                    etape=Relance.Etape.ANALYSE_DC,
                    destinataire_role=User.Role.DC,
                    date_debut_etape=date_debut
                )
            else:
                Relance.objects.filter(courrier=c, etape=Relance.Etape.ANALYSE_DC, est_resolue=False).update(est_resolue=True, date_resolution=timezone.now())

            if not sg_valide:
                get_ou_creer_relance(
                    courrier=c,
                    etape=Relance.Etape.ANALYSE_SG,
                    destinataire_role=User.Role.SG,
                    date_debut_etape=date_debut
                )
            else:
                Relance.objects.filter(courrier=c, etape=Relance.Etape.ANALYSE_SG, est_resolue=False).update(est_resolue=True, date_resolution=timezone.now())

    # 4. Courriers ANALYSE_VALIDE (attente de transmission au Ministre par le Secrétaire du Ministre)
    courriers_valides = Courrier.objects.filter(
        statut=Courrier.Statut.ANALYSE_VALIDE
    )
    for c in courriers_valides:
        # Résoudre les relances d'analyse DC / SG
        Relance.objects.filter(courrier=c, etape__in=[Relance.Etape.ANALYSE_DC, Relance.Etape.ANALYSE_SG], est_resolue=False).update(est_resolue=True, date_resolution=timezone.now())
        
        hist_val = c.historiques.filter(action__in=['VALIDATION_ANALYSE', 'VALIDATION_ANALYSE_SG']).order_by('-date_action').first()
        date_debut = hist_val.date_action if hist_val else c.date_arrivee
        if date_debut <= seuil:
            get_ou_creer_relance(
                courrier=c,
                etape=Relance.Etape.TRANSMISSION_MINISTRE,
                destinataire_role=User.Role.SECRETAIRE_MINISTRE,
                date_debut_etape=date_debut
            )

    # 5. Courriers TRANSMIS_MINISTRE (attente de décision du Ministre)
    courriers_ministre = Courrier.objects.filter(
        statut=Courrier.Statut.TRANSMIS_MINISTRE
    )
    for c in courriers_ministre:
        # Résoudre relance de transmission
        Relance.objects.filter(courrier=c, etape=Relance.Etape.TRANSMISSION_MINISTRE, est_resolue=False).update(est_resolue=True, date_resolution=timezone.now())
        
        hist_trans_min = c.historiques.filter(action='TRANSMISSION').order_by('-date_action').first()
        date_debut = hist_trans_min.date_action if hist_trans_min else c.date_arrivee
        if date_debut <= seuil:
            get_ou_creer_relance(
                courrier=c,
                etape=Relance.Etape.DECISION,
                destinataire_role=User.Role.MINISTRE,
                date_debut_etape=date_debut
            )

    # 6. Courriers DECIDE (attente d'affectation par le DC ou Secrétariat Central)
    courriers_decides = Courrier.objects.filter(
        statut=Courrier.Statut.DECIDE
    ).select_related('decision')
    for c in courriers_decides:
        Relance.objects.filter(courrier=c, etape=Relance.Etape.DECISION, est_resolue=False).update(est_resolue=True, date_resolution=timezone.now())
        
        try:
            date_debut = c.decision.date_decision
        except Decision.DoesNotExist:
            date_debut = c.date_arrivee

        if date_debut <= seuil:
            get_ou_creer_relance(
                courrier=c,
                etape=Relance.Etape.AFFECTATION,
                destinataire_role=User.Role.DC,
                date_debut_etape=date_debut
            )

    # 7. Courriers AFFECTE (traitement par les services ou agents affectés)
    affectations_en_cours = Affectation.objects.filter(
        courrier__statut=Courrier.Statut.AFFECTE,
        statut_traitement__in=[Affectation.StatutTraitement.RECU, Affectation.StatutTraitement.EN_COURS],
        date_affectation__lte=seuil
    ).select_related('courrier', 'destinataire')
    
    for aff in affectations_en_cours:
        Relance.objects.filter(courrier=aff.courrier, etape=Relance.Etape.AFFECTATION, est_resolue=False).update(est_resolue=True, date_resolution=timezone.now())
        
        get_ou_creer_relance(
            courrier=aff.courrier,
            etape=Relance.Etape.TRAITEMENT_SERVICE,
            destinataire_user=aff.destinataire,
            destinataire_role=User.Role.DIRECTEUR if not aff.destinataire else None,
            service_concerne=aff.service_concerne,
            date_debut_etape=aff.date_affectation
        )

    # 8. Courriers TERMINE (tout doit être résolu)
    courriers_termines = Courrier.objects.filter(statut=Courrier.Statut.TERMINE)
    Relance.objects.filter(courrier__in=courriers_termines, est_resolue=False).update(est_resolue=True, date_resolution=timezone.now())


def get_relances_pour_utilisateur(user):
    """
    Retourne le QuerySet des relances actives pertinentes pour l'utilisateur :
    - Le Ministre, le DC, le SG, les Secrétaires (SG, DC, Ministre, Central) et Superusers ont
      une vue complète sur toutes les relances et alertes de retard à travers le Ministère.
    - Les Directeurs de département et Agents voient les alertes qui les concernent directement
      (leur service ou leurs affectations personnelles).
    """
    if not user.is_authenticated or not user.is_active:
        return Relance.objects.none()

    # Rôles ayant la vue globale de supervision sur toutes les relances
    roles_vue_globale = {
        User.Role.MINISTRE,
        User.Role.DC,
        User.Role.SG,
        User.Role.SECRETARIAT_CENTRAL,
        User.Role.SECRETAIRE_DC,
        User.Role.SECRETAIRE_SG,
        User.Role.SECRETAIRE_MINISTRE,
    }

    base_qs = Relance.objects.filter(est_resolue=False).select_related('courrier', 'destinataire_user', 'courrier__cree_par')

    if user.is_superuser or user.role in roles_vue_globale:
        return base_qs

    # Pour les Directeurs de département et Agents : filtrage par utilisateur, rôle ou direction
    filtres = Q(destinataire_user=user) | Q(destinataire_role=user.role)
    if user.service_direction:
        filtres |= Q(service_concerne=user.service_direction)

    return base_qs.filter(filtres).distinct()
