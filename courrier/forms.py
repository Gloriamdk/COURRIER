"""
Formulaires — GEC Ministère.
"""
from django import forms
from .models import Courrier, FicheAnalyse, Affectation, User
from .validators import validate_document_upload


class CourrierForm(forms.ModelForm):
    """
    Formulaire d'enregistrement d'un courrier par le Secrétariat Central.
    - Le champ fichier_scan est optionnel et séparé du modèle Courrier.
    """
    fichier_scan = forms.FileField(
        label="Document numérisé (PDF)",
        required=False,
        widget=forms.FileInput(attrs={
            'class': 'form-control',
            'accept': 'application/pdf,image/*',
            'id': 'id_fichier_scan',
        }),
        help_text="Formats acceptés : PDF, JPG, PNG. Taille max : 10 Mo."
    )


    class Meta:
        model = Courrier
        fields = [
            'designation', 'resume',
            'expediteur_nom', 'expediteur_institution', 'expediteur_telephone',
            'priorite', 'date_arrivee',
        ]
        widgets = {
            'designation': forms.TextInput(attrs={
                'class': 'form-control',
                'id': 'id_designation',
                'placeholder': "Objet du courrier"
            }),
            'resume': forms.Textarea(attrs={
                'rows': 4,
                'class': 'form-control',
                'id': 'id_resume',
                'placeholder': "Résumé analytique du contenu du courrier..."
            }),
            'expediteur_nom': forms.TextInput(attrs={
                'class': 'form-control',
                'id': 'id_expediteur_nom',
                'placeholder': "Nom de l'expéditeur ou de l'organisation"
            }),
            'expediteur_institution': forms.TextInput(attrs={
                'class': 'form-control',
                'id': 'id_expediteur_institution',
                'placeholder': "Ex: Ministère de la Santé (Laisser vide si particulier)"
            }),
            'expediteur_telephone': forms.TextInput(attrs={
                'class': 'form-control',
                'id': 'id_expediteur_telephone',
                'placeholder': "+228 XX XX XX XX (optionnel)"
            }),
            'priorite': forms.Select(attrs={
                'class': 'form-control',
                'id': 'id_priorite',
            }),
            'date_arrivee': forms.DateTimeInput(attrs={
                'class': 'form-control',
                'id': 'id_date_arrivee',
                'type': 'datetime-local',
            }, format='%Y-%m-%dT%H:%M'),
        }

    def clean_fichier_scan(self):
        fichier = self.cleaned_data.get('fichier_scan')
        if fichier:
            validate_document_upload(fichier)
        return fichier


class FicheAnalyseForm(forms.ModelForm):
    """
    Formulaire de rédaction de la fiche d'analyse par le Directeur de Cabinet.
    """
    class Meta:
        model = FicheAnalyse
        fields = ['direction_proposee', 'observations_dc']
        widgets = {
            'direction_proposee': forms.Select(attrs={
                'class': 'form-control',
                'id': 'id_direction_proposee',
            }),
            'observations_dc': forms.Textarea(attrs={
                'rows': 4,
                'class': 'form-control',
                'id': 'id_observations_dc',
                'placeholder': 'Observations du Directeur de Cabinet sur le contenu du courrier...',
            }),
        }


def get_affectation_choices():
    """
    Construit la liste groupée des destinataires pour le formulaire d'affectation.
    Groupe par direction/service, et inclut les agents sans département.
    """
    # Ordre d'affichage des groupes (correspondant à service_direction)
    GROUPES_ORDRE = [
        "Cabinet du Ministre",
        "Secrétariat Général",
        "DAAF",
        "DPDT",
        "DPT",
        "DRICEHB",
        "DLPL",
        "DPAC",
        "CNCIA",
        "DERPC",
        "DPC",
        "CENALAC",
        "DRAC Grand-Lomé",
        "DRAC Maritime",
        "DRAC Plateaux",
        "DRAC Centrale",
        "DRAC Kara",
        "DRAC Savanes",
        "PRMP",
        "CPMP",
        "CCMP",
        "Agent Comptable",
        "FPDT",
        "FNPC",
        "CNACET",
        "IRES-RDEC",
        "BUTODRA",
        "CNPC",
        "CRFTH",
        "CCT",
    ]

    users = User.objects.filter(
        role__in=[User.Role.DIRECTEUR, User.Role.AGENT],
        is_active=True
    ).order_by('service_direction', 'last_name', 'first_name')

    # Groupement par service_direction
    groupes = {}
    sans_service = []

    for user in users:
        service = user.service_direction or ""
        if service:
            if service not in groupes:
                groupes[service] = []
            groupes[service].append((user.pk, user.get_full_name() or user.username))
        else:
            sans_service.append((user.pk, user.get_full_name() or user.username))

    # Construction des choix groupés
    choices = [('', '— Sélectionner un destinataire —')]

    for groupe in GROUPES_ORDRE:
        if groupe in groupes:
            choices.append((groupe, groupes[groupe]))

    # Groupes non listés dans l'ordre par défaut
    for service, membres in groupes.items():
        if service not in GROUPES_ORDRE:
            choices.append((service, membres))

    # Agents sans département (optionnel, en dernier)
    if sans_service:
        choices.append(("Agents (sans département)", sans_service))

    return choices


class AffectationForm(forms.ModelForm):
    """
    Formulaire d'affectation d'un courrier à un directeur/agent/service.
    Organisé en liste déroulante groupée par direction (organigramme MTCA).
    Le destinataire est OPTIONNEL (le Ministre peut valider sans préciser d'agent).
    """
    destinataire = forms.ModelChoiceField(
        queryset=User.objects.filter(
            role__in=[User.Role.DIRECTEUR, User.Role.AGENT],
            is_active=True
        ).order_by('service_direction', 'last_name'),
        label="Destinataire (Direction ou Agent)",
        required=False,   # <-- NON OBLIGATOIRE
        empty_label="— Sélectionner un destinataire (optionnel) —",
        widget=forms.Select(attrs={
            'class': 'form-control',
            'id': 'id_destinataire',
        }),
        help_text="Choisissez la direction ou l'agent concerné. Ce champ est optionnel."
    )

    class Meta:
        model = Affectation
        fields = ['destinataire', 'service_concerne', 'note_traitement']
        widgets = {
            'service_concerne': forms.Select(attrs={
                'class': 'form-control',
                'id': 'id_service_concerne',
            }),
            'note_traitement': forms.Textarea(attrs={
                'rows': 3,
                'class': 'form-control',
                'id': 'id_note_traitement',
                'placeholder': 'Instructions complémentaires pour ce service (optionnel)...',
            }),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Rebuild the queryset with grouped choices using optgroup
        users = User.objects.filter(
            role__in=[User.Role.DIRECTEUR, User.Role.AGENT],
            is_active=True
        ).order_by('service_direction', 'last_name', 'first_name')
        self.fields['destinataire'].queryset = users

    def clean(self):
        cleaned_data = super().clean()
        destinataire = cleaned_data.get('destinataire')
        service = cleaned_data.get('service_concerne')

        if not destinataire and not service:
            raise forms.ValidationError("Sélectionnez au moins un agent ou une direction/service.")

        if destinataire and service and destinataire.service_direction != service:
            raise forms.ValidationError("Le destinataire choisi ne correspond pas au service sélectionné.")

        return cleaned_data
