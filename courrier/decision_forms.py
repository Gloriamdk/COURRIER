from django import forms
from .models import Decision

class DecisionForm(forms.ModelForm):
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
