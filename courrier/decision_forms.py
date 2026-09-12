from django import forms
from .models import Decision

class DecisionForm(forms.ModelForm):
    action_finale = forms.ChoiceField(
        choices=(('valider', 'Valider et signer'), ('corriger', 'Demander une correction')),
        widget=forms.RadioSelect,
        initial='valider',
        required=False,
        label="Action du Ministre",
    )
    observation_correction = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={'rows': 3, 'class': 'form-control'}),
        label="Observation / motif de correction",
    )
    document_signe = forms.FileField(
        required=False,
        label="Document signé (optionnel)",
        help_text="Joindre la décision signée par le Ministre.",
    )
    delai_traitement_jours = forms.IntegerField(
        min_value=1, max_value=365, required=False,
        label="Délai de traitement (jours)",
        help_text="Délai propre à ce courrier, fixé par le Ministre.",
        widget=forms.NumberInput(attrs={'class': 'form-control', 'min': 1, 'max': 365}),
    )
    class Meta:
        model = Decision
        fields = ['instruction_standard', 'instructions_finales']
        widgets = {
            'instruction_standard': forms.RadioSelect(attrs={'class': 'radio-action'}),
            'instructions_finales': forms.Textarea(attrs={
                'rows': 4,
                'class': 'form-control',
                'placeholder': 'Commentaire ou consigne détaillée supplémentaire (optionnel)...'
            }),
        }
