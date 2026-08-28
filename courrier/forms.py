from django import forms
from .models import Courrier, FicheAnalyse

class CourrierForm(forms.ModelForm):
    # Restreindre le choix à NORMAL uniquement au niveau du formulaire
    confidentialite = forms.ChoiceField(
        choices=[('NORMAL', 'Normal')],
        widget=forms.Select(attrs={'class': 'form-control'})
    )

    class Meta:
        model = Courrier
        fields = [
            'designation', 'resume', 
            'expediteur_nom', 'expediteur_institution', 'expediteur_telephone',
            'destinataire_initial', 'confidentialite', 'priorite'
        ]
        widgets = {
            'designation': forms.TextInput(attrs={'class': 'form-control'}),
            'resume': forms.Textarea(attrs={'rows': 4, 'class': 'form-control'}),
            'expediteur_nom': forms.TextInput(attrs={'class': 'form-control'}),
            'expediteur_institution': forms.TextInput(attrs={'class': 'form-control'}),
            'expediteur_telephone': forms.TextInput(attrs={'class': 'form-control'}),
            'destinataire_initial': forms.TextInput(attrs={'class': 'form-control'}),
            'priorite': forms.Select(attrs={'class': 'form-control'}),
        }

class FicheAnalyseForm(forms.ModelForm):
    class Meta:
        model = FicheAnalyse
        fields = ['observations_dc', 'propositions_dc']
        widgets = {
            'observations_dc': forms.Textarea(attrs={'rows': 5, 'placeholder': 'Ajouter les observations ici...'}),
            'propositions_dc': forms.Textarea(attrs={'rows': 5, 'placeholder': 'Ajouter les propositions ici...'}),
        }
