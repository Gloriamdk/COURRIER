"""
Formulaires — GEC Ministère.
"""
import re

from django import forms
from .models import Courrier, CourrierSortant, FicheAnalyse, Affectation, User
from .validators import validate_document_upload


class CourrierForm(forms.ModelForm):
    """
    Formulaire d'enregistrement d'un courrier par le Secrétariat Central.
    - Le champ fichier_scan est optionnel et séparé du modèle Courrier.
    """
    fichier_scan = forms.FileField(
        label="Document numérisé",
        required=False,
        widget=forms.FileInput(attrs={
            'class': 'form-control',
            'accept': '.pdf,.docx,.xlsx,.jpg,.jpeg,.png',
            'id': 'id_fichier_scan',
        }),
        help_text="Formats acceptés : PDF, DOCX, XLSX, JPG, PNG. Taille max : 10 Mo."
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

    def clean_expediteur_telephone(self):
        telephone = (self.cleaned_data.get('expediteur_telephone') or '').strip()
        if telephone and not re.fullmatch(r"[\d\s+().-]{6,20}", telephone):
            raise forms.ValidationError("Numéro de téléphone invalide.")
        return telephone


class FicheAnalyseForm(forms.ModelForm):
    """
    Formulaire de rédaction de la fiche d'analyse par le Directeur de Cabinet.
    """
    class Meta:
        model = FicheAnalyse
        fields = ['direction_proposee', 'observations_dc', 'propositions_dc']
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
            'propositions_dc': forms.Textarea(attrs={
                'rows': 3,
                'class': 'form-control',
                'id': 'id_propositions_dc',
                'placeholder': 'Propositions / orientation (optionnel)',
            }),
        }


class FicheAnalyseSGForm(forms.ModelForm):
    """
    Formulaire pour la fiche d'analyse du Secrétaire Général (SG).
    """
    class Meta:
        model = FicheAnalyse
        fields = ['direction_proposee', 'observations_sg', 'propositions_sg']
        widgets = {
            'direction_proposee': forms.Select(attrs={
                'class': 'form-control',
                'id': 'id_direction_proposee_sg',
            }),
            'observations_sg': forms.Textarea(attrs={
                'rows': 4,
                'class': 'form-control',
                'id': 'id_observations_sg',
                'placeholder': 'Observations du Secrétaire Général...',
            }),
            'propositions_sg': forms.Textarea(attrs={
                'rows': 3,
                'class': 'form-control',
                'id': 'id_propositions_sg',
                'placeholder': 'Propositions / orientation (optionnel)',
            }),
        }


def get_affectation_choices():
    """
    Construit la liste groupée des destinataires pour le formulaire d'affectation.
    Groupe par direction/service, et inclut les agents sans département.
    Les directeurs ne sont plus des destinataires internes d’affectation:
    la direction est attribuée par le Ministre, et le Directeur ne peut
    ensuite rattacher qu’un seul agent de sa propre direction.
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
        role=User.Role.AGENT,
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


SERVICE_ALIAS = {
    'DAF': 'DAAF',
}


def normalize_service(service):
    if not service:
        return ''
    value = str(service).strip()
    return SERVICE_ALIAS.get(value, value)


class AffectationForm(forms.ModelForm):
    """
    Formulaire d'affectation d'un courrier à un directeur/agent/service.
    Organisé en liste déroulante groupée par direction (organigramme MTCA).
    Le destinataire est OPTIONNEL (le Ministre peut valider sans préciser d'agent).
    """
    destinataire = forms.ModelChoiceField(
        queryset=User.objects.filter(
            role=User.Role.AGENT,
            is_active=True
        ).order_by('service_direction', 'last_name'),
        label="Destinataire (Agent interne)",
        required=False,
        empty_label="— Sélectionner un agent interne (optionnel) —",
        widget=forms.Select(attrs={
            'class': 'form-control',
            'id': 'id_destinataire',
        }),
        help_text="Choisissez l’agent interne de votre direction. Le directeur ne peut affecter qu’un agent de son département."
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
        request_user = kwargs.pop('request_user', None)
        super().__init__(*args, **kwargs)
        self.request_user = request_user

        # Base de candidats : agents internes uniquement.
        users = User.objects.filter(
            role=User.Role.AGENT,
            is_active=True
        )

        # Règle de sélection de la vue :
        # - Ministre : n’autorise que les agents sans direction.
        # - Directeur : n’autorise que les agents de sa propre direction.
        if request_user and request_user.role == User.Role.MINISTRE:
            users = users.filter(service_direction__in=[None, ''])

        elif request_user and request_user.role == User.Role.DIRECTEUR and request_user.service_direction:
            service = normalize_service(request_user.service_direction)
            aliases = {service}
            if service == 'DAAF':
                aliases.add('DAF')
            elif service == 'DAF':
                aliases.add('DAAF')
            users = users.filter(service_direction__in=list(aliases))

        users = users.order_by('service_direction', 'last_name', 'first_name')
        self.fields['destinataire'].queryset = users

        # Pour le directeur, on cache explicitement le service concerné, parce
        # qu’il ne doit pas réaffecter le courrier à une autre direction
        # que la sienne. Le service est donc implicite / inféré.
        if request_user and request_user.role == User.Role.DIRECTEUR and request_user.service_direction:
            self.fields['service_concerne'].widget = forms.HiddenInput()
            self.fields['service_concerne'].required = False
            self.initial['service_concerne'] = normalize_service(request_user.service_direction)

    def clean(self):
        cleaned_data = super().clean()
        destinataire = cleaned_data.get('destinataire')
        service = normalize_service(cleaned_data.get('service_concerne'))

        # Sécurité de la relation directeur → agent : le directeur ne peut pas
        # rediriger vers une autre direction ni réaffecter un second parcours.
        if self.request_user and self.request_user.role == User.Role.DIRECTEUR and self.request_user.service_direction:
            expected = normalize_service(self.request_user.service_direction)
            if service and normalize_service(service) != expected:
                raise forms.ValidationError("Vous ne pouvez affecter ce courrier qu’à un agent de votre propre direction.")
            if destinataire and getattr(destinataire, 'service_direction', None):
                if normalize_service(destinataire.service_direction) != expected:
                    raise forms.ValidationError("Le destinataire choisi doit appartenir à votre direction.")
            if not service:
                service = expected
                cleaned_data['service_concerne'] = service

        # L’agent sans direction est la cible du ministre ; jamais un agent
        # de direction. Donc l’annonce est totalement exclusive entre service
        # et agent sans rattachement.
        if self.request_user and self.request_user.role == User.Role.MINISTRE:
            if destinataire and service:
                raise forms.ValidationError("Le Ministre choisit soit une direction, soit un agent sans direction.")

        if not destinataire and not service:
            raise forms.ValidationError("Sélectionnez au moins un agent ou une direction/service.")

        # Un agent porte implicitement la direction de son compte ; on l'infère
        # automatiquement au service concerné pour le workflow hiérarchique.
        if destinataire and getattr(destinataire, 'service_direction', None):
            inferred_service = normalize_service(destinataire.service_direction)
            if not service:
                cleaned_data['service_concerne'] = inferred_service
                service = inferred_service

        # Contrôle de cohérence cross-direction côté serveur.
        if destinataire and service:
            agent_service = normalize_service(destinataire.service_direction)
            if agent_service and agent_service != service:
                raise forms.ValidationError("Le destinataire choisi ne correspond pas au service sélectionné.")

        return cleaned_data


class CourrierSortantForm(forms.ModelForm):
    document_signe = forms.FileField(
        required=False, label="Document signé à expédier",
        widget=forms.FileInput(attrs={'class': 'form-control'}),
    )

    class Meta:
        model = CourrierSortant
        fields = ['destinataire', 'objet', 'observation']
        widgets = {
            'destinataire': forms.TextInput(attrs={'class': 'form-control'}),
            'objet': forms.TextInput(attrs={'class': 'form-control'}),
            'observation': forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
        }
