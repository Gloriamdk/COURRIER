from django.db import models, router, transaction
from django.db.models import Q
from django.contrib.auth.models import AbstractUser
from django.conf import settings
from django.utils import timezone
from django.utils.text import get_valid_filename
from pathlib import Path
import uuid

from .validators import validate_document_upload

# ==============================================================================
# CONSTANTES GLOBALES
# ==============================================================================

DIRECTIONS_CHOICES = [
    ("Cabinet du Ministre", "Cabinet du Ministre"),
    ("Secrétariat Général", "Secrétariat Général"),
    ("DAAF", "DAAF"),
    ("DPDT", "DPDT"),
    ("DPT", "DPT"),
    ("DRICEHB", "DRICEHB"),
    ("DLPL", "DLPL"),
    ("DPAC", "DPAC"),
    ("CNCIA", "CNCIA"),
    ("DERPC", "DERPC"),
    ("DPC", "DPC"),
    ("CENALAC", "CENALAC"),
    ("DRAC Grand-Lomé", "DRAC Grand-Lomé"),
    ("DRAC Maritime", "DRAC Maritime"),
    ("DRAC Plateaux", "DRAC Plateaux"),
    ("DRAC Centrale", "DRAC Centrale"),
    ("DRAC Kara", "DRAC Kara"),
    ("DRAC Savanes", "DRAC Savanes"),
    ("PRMP", "PRMP"),
    ("CPMP", "CPMP"),
    ("CCMP", "CCMP"),
    ("Agent Comptable", "Agent Comptable"),
    ("FPDT", "FPDT"),
    ("FNPC", "FNPC"),
    ("CNACET", "CNACET"),
    ("IRES-RDEC", "IRES-RDEC"),
    ("BUTODRA", "BUTODRA"),
    ("CNPC", "CNPC"),
    ("CRFTH", "CRFTH"),
    ("CCT", "CCT"),
    ("Autre", "Autre (à préciser)")
]

INSTRUCTIONS_STANDARD = [
    ('MEN_PARLER', "M'en parler avant traitement"),
    ('EN_INSTANCE', "En instance"),
    ('POUR_ATTRIBUTION', "Pour attribution / À traiter"),
    ('A_CLASSER', "À classer"),
    ('AUTRE', "Autre (voir instructions finales)")
]

# ==============================================================================
# 1. MODÈLE UTILISATEUR & RÔLES
# ==============================================================================

def normalize_service_label(service):
    """Normalise l’alias de service métier historique DAF -> DAAF pour les
    filtres de sécurité et la cohérence des affectations aux services.
    """
    if not service:
        return ''
    value = str(service).strip()
    return {'DAF': 'DAAF'}.get(value, value)


class User(AbstractUser):
    """
    Modèle utilisateur personnalisé intégrant les rôles administratifs du ministère.
    """
    class Role(models.TextChoices):
        SECRETARIAT_CENTRAL = 'SECRETARIAT_CENTRAL', 'Secrétariat Central'
        SECRETAIRE_DC = 'SECRETAIRE_DC', 'Secrétaire du Directeur de Cabinet (DC)'
        DC = 'DC', 'Directeur de Cabinet (DC)'
        SECRETAIRE_MINISTRE = 'SECRETAIRE_MINISTRE', 'Secrétaire Particulier du Ministre'
        MINISTRE = 'MINISTRE', 'Ministre'
        SECRETAIRE_SG = 'SECRETAIRE_SG', 'Secrétaire du Secrétaire Général (SG)'
        SG = 'SG', 'Secrétaire Général (SG)'
        DIRECTEUR = 'DIRECTEUR', 'Directeur de Département'
        AGENT = 'AGENT', 'Agent'

    role = models.CharField(
        max_length=50,
        choices=Role.choices,
        default=Role.AGENT,
        verbose_name="Rôle au sein du Ministère"
    )
    service_direction = models.CharField(
        max_length=150,
        blank=True,
        null=True,
        verbose_name="Service / Direction d'appartenance",
        help_text="Pour les directeurs et agents, indique la direction (ex: DAF, DEC, etc.)"
    )

    class Meta:
        verbose_name = "Utilisateur"
        verbose_name_plural = "Utilisateurs"

    def __str__(self):
        return f"{self.get_full_name() or self.username} ({self.get_role_display()})"


# ==============================================================================
# 2. MODÈLE COURRIER & MANAGERS
# ==============================================================================

class CourrierQuerySet(models.QuerySet):
    """
    QuerySet personnalisé pour implémenter la sécurité au niveau de l'ORM (Risque 1).
    Contrôle strict des accès aux courriers en fonction du rôle de l'utilisateur.
    """
    def pour_utilisateur(self, user):
        if not user.is_authenticated or not user.is_active:
            return self.none()

        if user.is_superuser:
            return self

        # Le Ministre, le DC, le SG et leurs secrétariats, ainsi que le Secrétariat Central ont un accès total.
        if user.role in [
            User.Role.MINISTRE, User.Role.DC,
            User.Role.SECRETAIRE_MINISTRE, User.Role.SECRETAIRE_DC,
            User.Role.SECRETARIAT_CENTRAL,
            User.Role.SG, User.Role.SECRETAIRE_SG,
        ]:
            return self

        # Le Directeur voit les courriers affectés à sa personne
        # ou affectés à sa direction par un service non nominatif.
        if user.role == User.Role.DIRECTEUR:
            if user.service_direction:
                raw_service = str(user.service_direction).strip()
                service_ref = normalize_service_label(raw_service)
                service_aliases = {raw_service, service_ref}
                # Compatibilité historique : l’ancien libellé DAF doit matcher
                # l’officialisation métier DAAF et vice-versa.
                if raw_service == 'DAAF':
                    service_aliases.add('DAF')
                elif raw_service == 'DAF':
                    service_aliases.add('DAAF')

                filters = Q(affectations__destinataire=user)
                filters |= Q(
                    affectations__destinataire__isnull=True,
                    affectations__service_concerne__in=list(service_aliases),
                )
                filters |= Q(
                    affectations__destinataire__role=User.Role.AGENT,
                    affectations__destinataire__service_direction__in=list(service_aliases),
                )
                return self.filter(filters).distinct()
            return self.filter(affectations__destinataire=user).distinct()

        # L'Agent voit uniquement les courriers explicitement affectés à son compte,
        # jamais par la simple appartenance à une direction/service.
        if user.role == User.Role.AGENT:
            return self.filter(affectations__destinataire=user).distinct()

        return self.none()


class CourrierManager(models.Manager):
    def get_queryset(self):
        return CourrierQuerySet(self.model, using=self._db)

    def pour_utilisateur(self, user):
        return self.get_queryset().pour_utilisateur(user)


class Courrier(models.Model):
    """
    Modèle principal de gestion d'un courrier enregistré au Secrétariat Central.
    """
    class Statut(models.TextChoices):
        ARRIVE = 'ARRIVE', 'Enregistré (Secrétariat Central)'
        REJETE_SECRETAIRE = 'REJETE_SECRETAIRE', 'Rejeté par Secrétariat pour correction'
        TRANSMIS_SG = 'TRANSMIS_SG', 'Transmis au SG'
        EN_COURS_SG = 'EN_COURS_SG', "En cours d'analyse (SG)"
        TRANSMIS_DC = 'TRANSMIS_DC', 'Transmis au Secrétaire du DC'
        EN_COURS_DC = 'EN_COURS_DC', "En cours d'analyse (DC)"
        ANALYSE_VALIDE = 'ANALYSE_VALIDE', 'Analyse validée (DC/SG)'
        TRANSMIS_MINISTRE = 'TRANSMIS_MINISTRE', 'Transmis au Ministre'
        DECIDE = 'DECIDE', 'Décidé (En attente d\'affectation)'
        SIGNE_PAR_MINISTRE = 'SIGNE_PAR_MINISTRE', 'Signé par le Ministre'
        COURRIER_SORTANT = 'COURRIER_SORTANT', 'Courrier sortant enregistré'
        AFFECTE = 'AFFECTE', 'Affecté aux services'
        SOUMIS_DIRECTEUR = 'SOUMIS_DIRECTEUR', 'Soumis au Directeur pour validation'
        CORRECTION_DEMANDEE = 'CORRECTION_DEMANDEE', 'Correction demandée'
        VALIDE_DIRECTEUR = 'VALIDE_DIRECTEUR', 'Validé par le Directeur'
        TERMINE = 'TERMINE', 'Traité'

    reference = models.CharField(
        max_length=100,
        unique=True,
        verbose_name="Référence / Numéro d'enregistrement",
        help_text="Généré automatiquement ou saisi manuellement"
    )
    designation = models.CharField(
        max_length=255,
        verbose_name="Désignation / Objet du courrier"
    )
    resume = models.TextField(
        verbose_name="Résumé analytique",
        blank=True
    )
    expediteur_nom = models.CharField(
        max_length=200,
        verbose_name="Nom de l'expéditeur"
    )
    expediteur_institution = models.CharField(
        max_length=200,
        blank=True,
        verbose_name="Institution de l'expéditeur"
    )
    expediteur_telephone = models.CharField(
        max_length=20,
        blank=True,
        verbose_name="Téléphone de l'expéditeur"
    )

    class Priorite(models.TextChoices):
        NORMAL = 'NORMAL', 'Normal'
        URGENT = 'URGENT', 'Urgent'
        TRES_URGENT = 'TRES_URGENT', 'Très Urgent'

    priorite = models.CharField(
        max_length=50,
        choices=Priorite.choices,
        default=Priorite.NORMAL,
        verbose_name="Niveau de priorité"
    )

    statut = models.CharField(
        max_length=50,
        choices=Statut.choices,
        default=Statut.ARRIVE,
        verbose_name="Statut du traitement"
    )
    # Le statut EN_COURS_DC est commun au circuit DC et SG. Ce rôle conserve
    # donc le détenteur réel afin de cibler la relance sans ambiguïté.
    responsable_actuel_role = models.CharField(
        max_length=50,
        choices=User.Role.choices,
        blank=True,
        null=True,
        verbose_name="Rôle actuellement détenteur du courrier",
    )
    delai_traitement_jours = models.PositiveIntegerField(
        null=True, blank=True,
        verbose_name="Délai de traitement fixé par le Ministre (jours)",
    )
    # Motif de rejet renseigné par un secrétaire lorsqu'il renvoie le courrier
    motif_rejet = models.TextField(
        verbose_name="Motif de rejet par le secrétariat",
        blank=True,
        null=True,
    )

    # Notes ou compte-rendu du comité à chaque étape (champ libre)
    comite = models.TextField(
        verbose_name="Compte-rendu / Comité",
        blank=True,
        null=True,
    )
    
    # Traçabilité de création
    cree_par = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="courriers_enregistres",
        verbose_name="Enregistré par"
    )
    reponse_requise = models.BooleanField(
        default=True,
        verbose_name="Une réponse écrite est requise pour ce courrier"
    )
    date_arrivee = models.DateTimeField(
        default=timezone.now,
        verbose_name="Date et heure de réception physique"
    )
    date_enregistrement = models.DateTimeField(
        auto_now_add=True,
        verbose_name="Date d'enregistrement dans le système"
    )

    objects = CourrierManager()

    class Meta:
        verbose_name = "Courrier"
        verbose_name_plural = "Courriers"
        ordering = ['-date_arrivee']

    def save(self, *args, **kwargs):
        if not self.reference:
            last = Courrier.objects.order_by('-id').first()
            new_id = (last.id + 1) if last else 1
            self.reference = f"CR-{timezone.now().year}-{new_id:04d}"
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.reference} - {self.designation[:40]}"


# ==============================================================================
# 3. MODÈLE DOCUMENT (PIÈCES JOINTES ET NUMÉRISATIONS)
# ==============================================================================

def secure_file_upload_path(instance, filename):
    """
    Génère un chemin de stockage non prévisible pour les documents.
    """
    now = timezone.now()
    extension = Path(get_valid_filename(filename)).suffix.lower()
    return f"courriers_scans/{now.year}/{now.month:02d}/{uuid.uuid4().hex}{extension}"


class Document(models.Model):
    """
    Pièces jointes ou documents scannés rattachés à un courrier.
    """
    courrier = models.ForeignKey(
        Courrier,
        on_delete=models.CASCADE,
        related_name="documents",
        verbose_name="Courrier associé"
    )
    nom = models.CharField(
        max_length=255,
        verbose_name="Nom de la pièce jointe"
    )
    fichier = models.FileField(
        validators=[validate_document_upload],
        upload_to=secure_file_upload_path,
        verbose_name="Fichier PDF numérisé"
    )
    taille_octets = models.PositiveIntegerField(
        verbose_name="Taille du fichier (en octets)",
        default=0
    )
    date_televersement = models.DateTimeField(
        auto_now_add=True,
        verbose_name="Date d'ajout"
    )

    class Meta:
        verbose_name = "Document joint"
        verbose_name_plural = "Documents joints"

    def __str__(self):
        return f"{self.nom} (Courrier: {self.courrier.reference})"

    def clean(self):
        super().clean()
        # La validation du fichier est assurée par le validateur déclaré sur
        # le FileField (validators=[validate_document_upload]).  Ne pas
        # ré-appeler validate_document_upload ici pour éviter une double
        # lecture coûteuse du contenu du fichier.

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)


# ==============================================================================
# 4. MODÈLE FICHE D'ANALYSE (DC)
# ==============================================================================

class FicheAnalyse(models.Model):
    """
    Fiche analytique rédigée par le Directeur de Cabinet (DC).
    Accompagne le courrier pour éclairer la décision du Ministre (Étape 2 & 3).
    """
    courrier = models.OneToOneField(
        Courrier,
        on_delete=models.CASCADE,
        related_name="fiche_analyse",
        verbose_name="Courrier"
    )
    analyse_par = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="analyses_redigees",
        verbose_name="Analysé par"
    )
    analyse_sg_par = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True,
        related_name="analyses_sg_sur_fiches",
        verbose_name="Analysé par le SG",
    )
    observations_sg = models.TextField(blank=True, verbose_name="Observations du SG")
    propositions_sg = models.TextField(blank=True, verbose_name="Propositions du SG")
    valide_sg = models.BooleanField(default=False, verbose_name="Analyse SG validée")
    date_analyse_sg = models.DateTimeField(null=True, blank=True)
    date_validation_sg = models.DateTimeField(null=True, blank=True)
    observations_dc = models.TextField(
        verbose_name="Observations du Directeur de Cabinet",
        blank=True
    )
    propositions_dc = models.TextField(
        verbose_name="Propositions d'orientation supplémentaires",
        blank=True
    )
    direction_proposee = models.CharField(
        max_length=150,
        choices=DIRECTIONS_CHOICES,
        blank=True,
        null=True,
        verbose_name="Direction / Service proposé (Optionnel)"
    )
    valide = models.BooleanField(
        default=False,
        verbose_name="Analyse validée par le DC"
    )
    date_analyse = models.DateTimeField(
        auto_now_add=True,
        verbose_name="Date de rédaction de l'analyse"
    )
    date_validation = models.DateTimeField(
        blank=True,
        null=True,
        verbose_name="Date de validation de l'analyse"
    )

    class Meta:
        verbose_name = "Fiche d'analyse"
        verbose_name_plural = "Fiches d'analyse"

    def __str__(self):
        return f"Fiche d'analyse - {self.courrier.reference}"


# Fiche d'analyse rédigée par le Secrétaire Général (SG)
class FicheAnalyseSG(models.Model):
    """
    Fiche rédigée par le Secrétaire Général (SG). Même structure que la fiche DC
    mais séparée pour garder les deux avis distincts.
    """
    courrier = models.OneToOneField(
        Courrier,
        on_delete=models.CASCADE,
        related_name="fiche_analyse_sg",
        verbose_name="Courrier"
    )
    analyse_par = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="analyses_sg_redigees",
        verbose_name="Analysé par"
    )
    observations_sg = models.TextField(
        verbose_name="Observations du Secrétaire Général",
        blank=True
    )
    propositions_sg = models.TextField(
        verbose_name="Propositions du Secrétaire Général",
        blank=True
    )
    direction_proposee = models.CharField(
        max_length=150,
        choices=DIRECTIONS_CHOICES,
        blank=True,
        null=True,
        verbose_name="Direction / Service proposé (Optionnel)"
    )
    valide = models.BooleanField(
        default=False,
        verbose_name="Analyse validée par le SG"
    )
    date_analyse = models.DateTimeField(
        auto_now_add=True,
        verbose_name="Date de rédaction de l'analyse"
    )
    date_validation = models.DateTimeField(
        blank=True,
        null=True,
        verbose_name="Date de validation de l'analyse"
    )

    class Meta:
        verbose_name = "Fiche d'analyse (SG)"
        verbose_name_plural = "Fiches d'analyse (SG)"

    def __str__(self):
        return f"Fiche d'analyse (SG) - {self.courrier.reference}"


# ==============================================================================
# 5. MODÈLE DÉCISION (MINISTRE)
# ==============================================================================

class Decision(models.Model):
    """
    Décision ou instruction finale formulée par le Ministre sur un courrier (Étape 4).
    """
    courrier = models.OneToOneField(
        Courrier,
        on_delete=models.CASCADE,
        related_name="decision",
        verbose_name="Courrier"
    )
    fiche_analyse = models.OneToOneField(
        FicheAnalyse,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="decision_associee",
        verbose_name="Fiche d'analyse d'appui"
    )
    signe_par = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="decisions_prises",
        verbose_name="Signé / Décidé par"
    )
    instruction_standard = models.CharField(
        max_length=50,
        choices=INSTRUCTIONS_STANDARD,
        default='POUR_ATTRIBUTION',
        verbose_name="Action rapide / Instruction standard"
    )
    instructions_finales = models.TextField(
        verbose_name="Décisions et Instructions finales (Commentaire libre)",
        blank=True,
        null=True
    )
    document_signe = models.ForeignKey(
        'Document',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='decisions_signees',
        verbose_name="Document signé par le Ministre",
    )
    date_decision = models.DateTimeField(
        auto_now_add=True,
        verbose_name="Date et heure de la décision"
    )

    class Meta:
        verbose_name = "Décision finale"
        verbose_name_plural = "Décisions finales"

    def __str__(self):
        return f"Décision Ministre - {self.courrier.reference}"


class DecisionFinale(models.Model):
    """Décision rendue après le traitement départemental et la validation SG/DC."""
    courrier = models.OneToOneField(
        Courrier, on_delete=models.CASCADE, related_name='decision_finale'
    )
    signe_par = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
        related_name='decisions_finales'
    )
    instructions_finales = models.TextField(blank=True)
    document_signe = models.ForeignKey(
        Document, on_delete=models.PROTECT, related_name='decisions_finales_signees'
    )
    date_decision = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Décision finale après traitement"
        verbose_name_plural = "Décisions finales après traitement"

    def __str__(self):
        return f"Décision finale - {self.courrier.reference}"


class CompteurCourrierSortant(models.Model):
    """Dernier numéro attribué par année, conservé même après une suppression."""
    annee = models.PositiveIntegerField(primary_key=True)
    dernier_numero = models.PositiveIntegerField(default=0)


class CourrierSortant(models.Model):
    """Enregistrement de l'expédition d'une décision signée par le Ministre."""
    courrier = models.OneToOneField(
        Courrier, on_delete=models.CASCADE, related_name='courrier_sortant'
    )
    enregistre_par = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
        related_name='courriers_sortants_enregistres'
    )
    destinataire = models.CharField(max_length=255)
    objet = models.CharField(max_length=255, blank=True)
    document = models.ForeignKey(
        Document, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='courriers_sortants'
    )
    reference_sortie = models.CharField(max_length=100, unique=True, blank=True)
    date_expedition = models.DateTimeField(
        default=timezone.now,
        verbose_name="Date d'expédition",
        null=True, blank=True,
    )
    date_enregistrement = models.DateTimeField(auto_now_add=True)
    observation = models.TextField(blank=True)

    def save(self, *args, **kwargs):
        if self.reference_sortie:
            return super().save(*args, **kwargs)
        using = kwargs.get('using') or router.db_for_write(type(self), instance=self)
        with transaction.atomic(using=using):
            annee = timezone.now().year
            compteur, _ = CompteurCourrierSortant.objects.using(using).get_or_create(annee=annee)
            # L'incrément verrouille le compteur jusqu'à l'enregistrement du courrier.
            while True:
                CompteurCourrierSortant.objects.using(using).filter(pk=annee).update(
                    dernier_numero=models.F('dernier_numero') + 1,
                )
                compteur.refresh_from_db(using=using)
                reference = f"SO-{annee}-{compteur.dernier_numero:04d}"
                if not type(self).objects.using(using).filter(reference_sortie=reference).exists():
                    break
            self.reference_sortie = reference
            kwargs['using'] = using
            return super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.reference_sortie} — {self.courrier.reference}"


# ==============================================================================
# 6. MODÈLE AFFECTATION & SUIVI
# ==============================================================================

class Affectation(models.Model):
    """
    Transmission et affectation du courrier aux directions pour exécution (Étape 5).
    """
    class StatutTraitement(models.TextChoices):
        RECU = 'RECU', 'Reçu par le service'
        EN_COURS = 'EN_COURS', 'En cours de traitement'
        TRAITE = 'TRAITE', 'Traité / Classé'

    courrier = models.ForeignKey(
        Courrier,
        on_delete=models.CASCADE,
        related_name="affectations",
        verbose_name="Courrier"
    )
    decision = models.ForeignKey(
        Decision,
        on_delete=models.PROTECT,
        related_name="affectations_generees",
        verbose_name="Décision d'appui"
    )
    affecte_par = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="affectations_ordonnees",
        verbose_name="Affecté par"
    )
    destinataire = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="affectations_recues",
        verbose_name="Agent destinataire (Optionnel)",
        null=True,
        blank=True
    )
    service_concerne = models.CharField(
        max_length=150,
        choices=DIRECTIONS_CHOICES,
        verbose_name="Direction / Service concerné (Optionnel)",
        null=True,
        blank=True
    )
    statut_traitement = models.CharField(
        max_length=50,
        choices=StatutTraitement.choices,
        default=StatutTraitement.RECU,
        verbose_name="Statut d'exécution"
    )
    date_affectation = models.DateTimeField(
        auto_now_add=True,
        verbose_name="Date d'affectation"
    )
    date_reception = models.DateTimeField(
        blank=True,
        null=True,
        verbose_name="Date de lecture / Réception"
    )
    date_traitement = models.DateTimeField(
        blank=True,
        null=True,
        verbose_name="Date de finalisation"
    )
    date_limite_traitement = models.DateTimeField(
        blank=True, null=True,
        verbose_name="Date limite de traitement",
    )
    traite_par = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name="affectations_traitees",
        verbose_name="Traitement confirmé par",
    )
    note_traitement = models.TextField(
        blank=True,
        verbose_name="Commentaire d'exécution ou rapport de traitement"
    )

    class Meta:
        verbose_name = "Affectation"
        verbose_name_plural = "Affectations"

    def __str__(self):
        return f"Affectation {self.courrier.reference} -> {self.service_concerne}"


# ==============================================================================
# 7. MODÈLE HISTORIQUE / AUDIT (TRAÇABILITÉ)
# ==============================================================================

class Historique(models.Model):
    """
    Journal d'audit immuable (Traçabilité complète du traitement : Risque 4).
    Enregistre 'Qui a fait quoi, sur quel courrier et à quel moment ?'.
    Les champs structurés complémentaires conservent le rôle, la direction,
    les statuts de transition et l'observation liée à l'action.
    """
    courrier = models.ForeignKey(
        Courrier,
        on_delete=models.CASCADE,
        related_name="historiques",
        verbose_name="Courrier concerné"
    )
    utilisateur = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        verbose_name="Auteur de l'action"
    )
    role = models.CharField(
        max_length=50,
        choices=User.Role.choices,
        blank=True,
        null=True,
        verbose_name="Rôle de l'utilisateur"
    )
    direction = models.CharField(
        max_length=150,
        blank=True,
        null=True,
        verbose_name="Direction concernée"
    )
    ancien_statut = models.CharField(
        max_length=50,
        choices=Courrier.Statut.choices,
        blank=True,
        null=True,
        verbose_name="Ancien statut"
    )
    nouveau_statut = models.CharField(
        max_length=50,
        choices=Courrier.Statut.choices,
        blank=True,
        null=True,
        verbose_name="Nouveau statut"
    )
    observation = models.TextField(
        blank=True,
        null=True,
        verbose_name="Observation éventuelle"
    )
    document = models.ForeignKey(
        Document,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="historiques_associes",
        verbose_name="Document associé"
    )
    action = models.CharField(
        max_length=100,
        verbose_name="Action réalisée",
        help_text="ex: ENREGISTREMENT, VALIDATION_ANALYSE, DECISION, AFFECTATION"
    )
    description = models.TextField(
        verbose_name="Description détaillée de l'action"
    )
    date_action = models.DateTimeField(
        auto_now_add=True,
        verbose_name="Date et heure de l'action"
    )

    class Meta:
        verbose_name = "Historique d'audit"
        verbose_name_plural = "Historiques d'audit"
        ordering = ['-date_action']

    def __str__(self):
        return f"[{self.date_action.strftime('%d/%m/%Y %H:%M')}] {self.utilisateur} - {self.action}"


class ReponseCourrier(models.Model):
    """Réponse écrite préparée par l'agent et soumise au directeur puis au circuit.
    Cette table permet de versionner progressivement la réponse après correction.
    """
    class Statut(models.TextChoices):
        BROUILLON = 'BROUILLON', 'Brouillon'
        ENVOYE_DIRECTEUR = 'ENVOYE_DIRECTEUR', 'Envoyée au Directeur'
        CORRECTION = 'CORRECTION', 'Retour pour correction'
        VALIDE = 'VALIDE', 'Validée'

    courrier = models.ForeignKey(
        Courrier,
        on_delete=models.CASCADE,
        related_name='reponses_courrier',
        verbose_name='Courrier concerné'
    )
    auteur = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='reponses_courrier_redigees',
        verbose_name='Auteur de la réponse'
    )
    date_preparation = models.DateTimeField(
        auto_now_add=True,
        verbose_name='Date de préparation'
    )
    document = models.ForeignKey(
        Document,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='reponses_associees',
        verbose_name='Document de réponse'
    )
    version = models.PositiveIntegerField(
        default=1,
        verbose_name='Version de la réponse'
    )
    statut_traitement = models.CharField(
        max_length=40,
        choices=Statut.choices,
        default=Statut.BROUILLON,
        verbose_name='Statut de la réponse'
    )
    observation = models.TextField(
        blank=True,
        null=True,
        verbose_name='Observation de correction'
    )

    class Meta:
        verbose_name = 'Réponse du courrier'
        verbose_name_plural = 'Réponses du courrier'
        ordering = ['-version', '-date_preparation']

    def __str__(self):
        return f"Réponse V{self.version} — {self.courrier.reference}"


# ==============================================================================
# 8. MODÈLE NOTIFICATION
# ==============================================================================

class Notification(models.Model):
    """
    Système de notification interne à l'application.
    """
    destinataire = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="notifications",
        verbose_name="Destinataire"
    )
    courrier = models.ForeignKey(
        Courrier,
        on_delete=models.CASCADE,
        related_name="notifications_associees",
        null=True,
        blank=True,
        verbose_name="Courrier concerné"
    )
    message = models.TextField(
        verbose_name="Contenu de la notification"
    )
    lu = models.BooleanField(
        default=False,
        verbose_name="Marqué comme lu"
    )
    date_notification = models.DateTimeField(
        auto_now_add=True,
        verbose_name="Date d'envoi"
    )

    class Meta:
        verbose_name = "Notification"
        verbose_name_plural = "Notifications"
        ordering = ['-date_notification']

    def __str__(self):
        status = "Lu" if self.lu else "Non lu"
        return f"Notif -> {self.destinataire.username} ({status})"


# ==============================================================================
# 9. MODÈLE RELANCE / ALERTE DE RETARD (TRAÇABILITÉ DES RELANCES)
# ==============================================================================

class Relance(models.Model):
    """
    Modèle représentant une alerte / relance automatique lorsqu'un courrier
    reste sans traitement, transfert ou clôture au-delà du délai fixé par le Ministre.
    """
    class Etape(models.TextChoices):
        ARRIVE = 'ARRIVE', 'Enregistrement / Secrétariat'
        REJET = 'REJET', 'Rejeté pour correction'
        ANALYSE_DC = 'ANALYSE_DC', 'Analyse par le Directeur de Cabinet (DC)'
        ANALYSE_SG = 'ANALYSE_SG', 'Analyse par le Secrétaire Général (SG)'
        TRANSMISSION_MINISTRE = 'TRANSMISSION_MINISTRE', 'Transmission au Ministre'
        DECISION = 'DECISION', 'Décision du Ministre'
        AFFECTATION = 'AFFECTATION', 'Affectation aux services'
        TRAITEMENT_SERVICE = 'TRAITEMENT_SERVICE', 'Traitement par le service / agent'

    class Nature(models.TextChoices):
        ECHEANCE_PROCHE = 'ECHEANCE_PROCHE', 'Échéance proche'
        RETARD = 'RETARD', 'Courrier en retard'

    courrier = models.ForeignKey(
        Courrier,
        on_delete=models.CASCADE,
        related_name="relances",
        verbose_name="Courrier concerné"
    )
    destinataire_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="relances_recues",
        verbose_name="Utilisateur ciblé"
    )
    destinataire_role = models.CharField(
        max_length=50,
        choices=User.Role.choices,
        null=True,
        blank=True,
        verbose_name="Rôle ciblé"
    )
    service_concerne = models.CharField(
        max_length=150,
        choices=DIRECTIONS_CHOICES,
        null=True,
        blank=True,
        verbose_name="Direction / Service concerné"
    )
    etape = models.CharField(
        max_length=50,
        choices=Etape.choices,
        default=Etape.ARRIVE,
        verbose_name="Étape administrative"
    )
    nature = models.CharField(
        max_length=30, choices=Nature.choices, blank=True, null=True,
        verbose_name="Nature de l'alerte",
    )
    date_limite = models.DateTimeField(
        blank=True, null=True, verbose_name="Date limite concernée",
    )
    date_debut_etape = models.DateTimeField(
        verbose_name="Date d'entrée à cette étape (réception / transmission)"
    )
    date_creation = models.DateTimeField(
        default=timezone.now,
        verbose_name="Date de génération de l'alerte"
    )
    est_resolue = models.BooleanField(
        default=False,
        verbose_name="Alerte résolue"
    )
    date_resolution = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name="Date de résolution"
    )

    class Meta:
        verbose_name = "Alerte / Relance"
        verbose_name_plural = "Alertes et Relances"
        ordering = ['-date_creation']
        indexes = [
            models.Index(fields=['est_resolue', 'destinataire_role']),
            models.Index(fields=['est_resolue', 'destinataire_user']),
            models.Index(fields=['courrier', 'est_resolue']),
        ]

    def __str__(self):
        dest = self.destinataire_user or self.get_destinataire_role_display() or self.service_concerne or "Tous"
        status = "Résolue" if self.est_resolue else f"En retard ({self.jours_sans_traitement}j)"
        return f"Relance [{self.courrier.reference}] -> {dest} ({status})"

    @property
    def jours_sans_traitement(self):
        """Nombre de jours sans traitement depuis la date d'entrée dans l'étape."""
        if not self.date_debut_etape:
            return 0
        fin = self.date_resolution if (self.est_resolue and self.date_resolution) else timezone.now()
        delta = fin - self.date_debut_etape
        return max(0, delta.days)

    @property
    def jours_restants(self):
        if not self.date_limite:
            return None
        return max(0, (self.date_limite - timezone.now()).days)

    def resoudre(self):
        """Marque la relance comme résolue."""
        if not self.est_resolue:
            self.est_resolue = True
            self.date_resolution = timezone.now()
            self.save(update_fields=['est_resolue', 'date_resolution'])


# ==============================================================================
# 10. MODÈLE CONFIGURATION DU DÉLAI DE TRAITEMENT (MINISTRE)
# ==============================================================================

class ConfigurationDelai(models.Model):
    """
    Configuration globale du délai de traitement des courriers (en jours).
    Règle de sécurité : Seul le Ministre a le droit de définir ou modifier ce délai.
    """
    delai_jours = models.PositiveIntegerField(
        verbose_name="Délai limite de traitement (en jours)",
        help_text="Nombre de jours sans traitement avant déclenchement d'une alerte et relance automatique."
    )
    modifie_par = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        verbose_name="Dernière modification par"
    )
    date_modification = models.DateTimeField(
        auto_now=True,
        verbose_name="Date de dernière mise à jour"
    )

    class Meta:
        verbose_name = "Configuration du délai de traitement"
        verbose_name_plural = "Configuration du délai de traitement"

    def __str__(self):
        return f"Délai fixé : {self.delai_jours} jour(s) (par {self.modifie_par or 'Système'})"

    @classmethod
    def get_delai_jours(cls):
        """Retourne le délai défini en base par le Ministre, ou ``None`` s'il ne l'a pas encore fixé."""
        config = cls.objects.first()
        if config and config.delai_jours:
            return config.delai_jours
        return None
