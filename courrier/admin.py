from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from .models import User, Courrier, Document, FicheAnalyse, Decision, Affectation, Historique, Notification

@admin.register(User)
class CustomUserAdmin(UserAdmin):
    list_display = ('username', 'email', 'role', 'service_direction', 'is_staff')
    list_filter = ('role', 'is_staff', 'is_superuser')
    fieldsets = UserAdmin.fieldsets + (
        (None, {'fields': ('role', 'service_direction')}),
    )

@admin.register(Courrier)
class CourrierAdmin(admin.ModelAdmin):
    list_display = ('reference', 'designation', 'expediteur_nom', 'confidentialite', 'statut', 'date_arrivee')
    list_filter = ('confidentialite', 'statut')
    search_fields = ('reference', 'designation', 'expediteur_nom', 'expediteur_institution')

@admin.register(Document)
class DocumentAdmin(admin.ModelAdmin):
    list_display = ('nom', 'courrier', 'date_televersement')

@admin.register(FicheAnalyse)
class FicheAnalyseAdmin(admin.ModelAdmin):
    list_display = ('courrier', 'analyse_par', 'valide', 'date_analyse')

@admin.register(Decision)
class DecisionAdmin(admin.ModelAdmin):
    list_display = ('courrier', 'signe_par', 'date_decision')

@admin.register(Affectation)
class AffectationAdmin(admin.ModelAdmin):
    list_display = ('courrier', 'destinataire', 'service_concerne', 'statut_traitement')

@admin.register(Historique)
class HistoriqueAdmin(admin.ModelAdmin):
    list_display = ('courrier', 'utilisateur', 'action', 'date_action')

@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    list_display = ('destinataire', 'message', 'lu', 'date_notification')
