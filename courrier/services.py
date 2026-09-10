"""
Services de gestion des alertes et relances automatiques — GEC MTCA.

Règles métier :
1. Détection automatique des courriers sans traitement au-delà du délai réglementaire fixé par le Ministre.
2. Éviter toute duplication de relance pour une même étape et un même destinataire.
3. Résolution automatique dès que le courrier est transmis, validé, décidé ou traité.
4. Filtrage :
   - Chaque utilisateur ne voit que ses relances, celles de son rôle ou de son service.
   - Les superutilisateurs conservent la vue d'administration globale.
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
    delai = get_delai_jours()
    return timezone.now() - timedelta(days=delai) if delai else None


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


def get_ou_creer_relance(courrier, etape, date_debut_etape, destinataire_role=None, destinataire_user=None, service_concerne=None, nature=None, date_limite=None):
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
    filtre &= Q(nature=nature)
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
        nature=nature,
        date_limite=date_limite,
        date_debut_etape=date_debut_etape,
        est_resolue=False,
    )


def synchroniser_relances():
    """
    Examine tous les courriers actifs et génère/résout les relances en fonction
    du temps passé à chaque étape au-delà du délai fixé par le Ministre.
    """
    seuil = date_seuil_relance()
    # Aucune valeur implicite n'est utilisée : les relances ne démarrent qu'après
    # la configuration explicite du Ministre, enregistrée en base.
    if seuil is None:
        return

    # 0. Résoudre les relances actives devenues prématurées suite à une augmentation du délai par le Ministre
    Relance.objects.filter(est_resolue=False, date_debut_etape__gt=seuil).update(
        est_resolue=True,
        date_resolution=timezone.now()
    )
    
    # 1. Courriers ARRIVE (attente de transmission par le Secrétaire SG)
    courriers_arrive = Courrier.objects.filter(
        statut=Courrier.Statut.ARRIVE,
        date_arrivee__lte=seuil
    )
    for c in courriers_arrive:
        # Résoudre d'éventuelles relances d'anciennes étapes
        Relance.objects.filter(courrier=c, est_resolue=False).exclude(etape=Relance.Etape.ARRIVE).update(est_resolue=True, date_resolution=timezone.now())
        
        # Relance pour les secrétariats
        for role in [User.Role.SECRETAIRE_SG]:
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

    # 3. Courriers en analyse SG puis DC
    courriers_sg = Courrier.objects.filter(
        statut__in=[Courrier.Statut.TRANSMIS_SG, Courrier.Statut.EN_COURS_SG]
    )
    for c in courriers_sg:
        hist_trans = c.historiques.filter(action='TRANSMISSION').order_by('-date_action').first()
        date_debut = hist_trans.date_action if hist_trans else c.date_arrivee
        if date_debut <= seuil:
            get_ou_creer_relance(
                courrier=c,
                etape=Relance.Etape.ANALYSE_SG,
                destinataire_role=User.Role.SG,
                date_debut_etape=date_debut,
            )

    # 4. Courriers TRANSMIS_DC / EN_COURS_DC (analyse DC)
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
            # Sans agent nommé, la relance reste rattachée au seul service ;
            # cibler le rôle DIRECTEUR rendrait l'alerte visible à tous les
            # directeurs, y compris ceux d'une autre direction.
            destinataire_role=None,
            service_concerne=aff.service_concerne,
            date_debut_etape=aff.date_affectation
        )

    # 8. Courriers TERMINE (tout doit être résolu)
    courriers_termines = Courrier.objects.filter(statut=Courrier.Statut.TERMINE)
    Relance.objects.filter(courrier__in=courriers_termines, est_resolue=False).update(est_resolue=True, date_resolution=timezone.now())


def synchroniser_relances():
    """Synchronise les alertes J-2 et de retard des affectations.

    Le seul délai utilisé est ``Courrier.delai_traitement_jours`` : aucune
    configuration globale ni valeur implicite ne participe au calcul.
    """
    now = timezone.now()
    active_affectations = Affectation.objects.filter(
        statut_traitement__in=[Affectation.StatutTraitement.RECU, Affectation.StatutTraitement.EN_COURS],
        courrier__delai_traitement_jours__isnull=False,
        date_limite_traitement__isnull=False,
    ).select_related('courrier', 'destinataire')

    actifs = list(active_affectations)
    actif_ids = {a.courrier_id for a in actifs}
    # Les anciennes relances de workflow ne sont plus des alertes d'échéance.
    Relance.objects.filter(est_resolue=False).exclude(
        courrier_id__in=actif_ids, etape=Relance.Etape.TRAITEMENT_SERVICE
    ).update(est_resolue=True, date_resolution=now)

    roles_suivi = [User.Role.MINISTRE, User.Role.SECRETAIRE_MINISTRE, User.Role.SG, User.Role.DC]
    for aff in actifs:
        courrier = aff.courrier
        reste = aff.date_limite_traitement - now
        if now > aff.date_limite_traitement:
            nature = Relance.Nature.RETARD
            Relance.objects.filter(courrier=courrier, etape=Relance.Etape.TRAITEMENT_SERVICE,
                nature=Relance.Nature.ECHEANCE_PROCHE, est_resolue=False).update(est_resolue=True, date_resolution=now)
        elif reste <= timedelta(days=2):
            nature = Relance.Nature.ECHEANCE_PROCHE
            Relance.objects.filter(courrier=courrier, etape=Relance.Etape.TRAITEMENT_SERVICE,
                nature=Relance.Nature.RETARD, est_resolue=False).update(est_resolue=True, date_resolution=now)
        else:
            Relance.objects.filter(courrier=courrier, etape=Relance.Etape.TRAITEMENT_SERVICE,
                est_resolue=False).update(est_resolue=True, date_resolution=now)
            continue

        for role in roles_suivi:
            get_ou_creer_relance(courrier, Relance.Etape.TRAITEMENT_SERVICE, aff.date_affectation,
                destinataire_role=role, nature=nature, date_limite=aff.date_limite_traitement)
        if aff.destinataire:
            get_ou_creer_relance(courrier, Relance.Etape.TRAITEMENT_SERVICE, aff.date_affectation,
                destinataire_user=aff.destinataire, nature=nature, date_limite=aff.date_limite_traitement)
        elif aff.service_concerne:
            get_ou_creer_relance(courrier, Relance.Etape.TRAITEMENT_SERVICE, aff.date_affectation,
                service_concerne=aff.service_concerne, nature=nature, date_limite=aff.date_limite_traitement)


def get_relances_pour_utilisateur(user):
    """
    Retourne le QuerySet des relances actives pertinentes pour l'utilisateur :
    Chaque utilisateur voit les alertes qui le concernent directement (lui-même,
    son rôle ou son service). Les superutilisateurs ont la vue globale.
    """
    if not user.is_authenticated or not user.is_active:
        return Relance.objects.none()

    base_qs = Relance.objects.filter(est_resolue=False).select_related('courrier', 'destinataire_user', 'courrier__cree_par')

    if user.is_superuser:
        return base_qs

    # Chaque utilisateur voit uniquement les relances adressées à lui, à son rôle
    # ou à son service. Les rôles de supervision ne contournent pas ce filtre.
    filtres = Q(destinataire_user=user) | Q(destinataire_role=user.role)
    if user.service_direction:
        filtres |= Q(service_concerne=user.service_direction)

    return base_qs.filter(filtres).distinct()
