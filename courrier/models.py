from django.db import models
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
        if user.is_superuser:
            return self
        
        # Le Ministre, le DC, le SG et leurs secrétariats, ainsi que le Secrétariat Central ont un accès total
        if user.role in [
            User.Role.MINISTRE, User.Role.DC, 
            User.Role.SECRETAIRE_MINISTRE, User.Role.SECRETAIRE_DC, 
            User.Role.SECRETARIAT_CENTRAL,
            User.Role.SG, User.Role.SECRETAIRE_SG
        ]:
            return self
            
        # Les directeurs et agents voient les courriers affectés directement à leur compte
        # ou affectés au service/direction dont ils relèvent.
        return self.filter(
            Q(affectations__destinataire=user)
            | Q(affectations__service_concerne=user.service_direction)
        ).distinct()


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
        EN_COURS_DC = 'EN_COURS_DC', 'En cours d\'analyse (DC)'
        ANALYSE_VALIDE = 'ANALYSE_VALIDE', 'Analyse validée (En attente décision)'
        DECIDE = 'DECIDE', 'Décidé (En attente d\'affectation)'
        AFFECTE = 'AFFECTE', 'Affecté aux services'
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
    
    # Traçabilité de création
    cree_par = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="courriers_enregistres",
        verbose_name="Enregistré par"
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
        validate_document_upload(self.fichier)

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
    date_decision = models.DateTimeField(
        auto_now_add=True,
        verbose_name="Date et heure de la décision"
    )

    class Meta:
        verbose_name = "Décision finale"
        verbose_name_plural = "Décisions finales"

    def __str__(self):
        return f"Décision Ministre - {self.courrier.reference}"


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
