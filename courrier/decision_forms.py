from django import forms
from .models import Decision

class DecisionForm(forms.ModelForm):
    class Meta:
        model = Decision
        fields = ['instructions_finales']
        widgets = {
            'instructions_finales': forms.Textarea(attrs={'rows': 5, 'class': 'form-control', 'placeholder': 'Saisissez la décision finale...'}),
        }
