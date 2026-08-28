"""
Formulaires — GEC Ministère.
"""
from django import forms
from .models import Courrier, FicheAnalyse, Affectation, User


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
            'destinataire_initial': forms.TextInput(attrs={
                'class': 'form-control',
                'id': 'id_destinataire_initial',
                'placeholder': "Orientation initiale du courrier (optionnel)"
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
        """Valide l'extension et la taille du fichier scanné."""
        fichier = self.cleaned_data.get('fichier_scan')
        if fichier:
            # Vérification de la taille (max 10 Mo)
            taille_max = 10 * 1024 * 1024  # 10 Mo en octets
            if fichier.size > taille_max:
                raise forms.ValidationError(
                    f"Le fichier est trop volumineux ({fichier.size // (1024*1024)} Mo). Maximum : 10 Mo."
                )
            # Vérification de l'extension
            extensions_autorisees = ['.pdf', '.jpg', '.jpeg', '.png']
            import os
            ext = os.path.splitext(fichier.name)[1].lower()
            if ext not in extensions_autorisees:
                raise forms.ValidationError(
                    f"Extension '{ext}' non autorisée. Formats acceptés : PDF, JPG, PNG."
                )
        return fichier


class FicheAnalyseForm(forms.ModelForm):
    """
    Formulaire de rédaction de la fiche d'analyse par le Directeur de Cabinet.
    """
    class Meta:
        model = FicheAnalyse
        fields = ['observations_dc', 'propositions_dc']
        widgets = {
            'observations_dc': forms.Textarea(attrs={
                'rows': 6,
                'class': 'form-control',
                'id': 'id_observations_dc',
                'placeholder': 'Observations du Directeur de Cabinet sur le contenu du courrier...',
            }),
            'propositions_dc': forms.Textarea(attrs={
                'rows': 6,
                'class': 'form-control',
                'id': 'id_propositions_dc',
                'placeholder': 'Propositions d\'orientation : direction, service ou action recommandée...',
            }),
        }


class AffectationForm(forms.ModelForm):
    """
    Formulaire d'affectation d'un courrier à un directeur/agent/service.
    Filtré pour n'afficher que les utilisateurs DIRECTEUR et AGENT actifs.
    """
    destinataire = forms.ModelChoiceField(
        queryset=User.objects.filter(
            role__in=[User.Role.DIRECTEUR, User.Role.AGENT],
            is_active=True
        ).order_by('role', 'service_direction', 'last_name'),
        label="Sélectionnez l'acteur concerné :",
        widget=forms.RadioSelect(attrs={'class': 'actor-radio'}),
        empty_label=None,
        help_text="Cliquez sur l'acteur à qui vous souhaitez affecter ce courrier."
    )

    class Meta:
        model = Affectation
        fields = ['destinataire', 'service_concerne', 'note_traitement']
        widgets = {
            'service_concerne': forms.TextInput(attrs={
                'class': 'form-control',
                'id': 'id_service_concerne',
                'placeholder': 'Ex: DAF, DEC, DGM, DAAF...',
            }),
            'note_traitement': forms.Textarea(attrs={
                'rows': 3,
                'class': 'form-control',
                'id': 'id_note_traitement',
                'placeholder': 'Instructions complémentaires pour ce service (optionnel)...',
            }),
        }
