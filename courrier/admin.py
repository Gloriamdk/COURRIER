from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from .models import User, Courrier, Document, FicheAnalyse, FicheAnalyseSG, Decision, Affectation, Historique, Notification, Relance, ConfigurationDelai


# ==============================================================================
# Admin sécurisé — accès restreint aux superusers uniquement
# ==============================================================================

class SecureAdminSite(admin.AdminSite):
    """AdminSite sécurisé : seuls les superusers ont accès à l'interface d'administration."""
    site_header = "Administration GEC — MTCA"
    site_title = "Admin GEC"

    def has_permission(self, request):
        """Restreint l'accès à l'interface admin aux superusers uniquement."""
        return request.user.is_active and request.user.is_superuser


# Remplace le site admin par défaut par le site sécurisé
secure_admin_site = SecureAdminSite(name='secure_admin')


class SecureModelAdmin(admin.ModelAdmin):
    """ModelAdmin de base sécurisé : lecture seule sauf pour les superusers."""

    def has_add_permission(self, request):
        return request.user.is_superuser

    def has_change_permission(self, request, obj=None):
        return request.user.is_superuser

    def has_delete_permission(self, request, obj=None):
        return request.user.is_superuser

    def has_module_permission(self, request):
        return request.user.is_active and request.user.is_superuser


@admin.register(ConfigurationDelai, site=secure_admin_site)
class ConfigurationDelaiAdmin(SecureModelAdmin):
    list_display = ('delai_jours', 'modifie_par', 'date_modification')


@admin.register(User, site=secure_admin_site)
class CustomUserAdmin(UserAdmin):
    list_display = ('username', 'email', 'role', 'service_direction', 'is_staff')
    list_filter = ('role', 'is_staff', 'is_superuser')
    fieldsets = UserAdmin.fieldsets + (
        (None, {'fields': ('role', 'service_direction')}),
    )

    def has_module_permission(self, request):
        return request.user.is_active and request.user.is_superuser


@admin.register(Courrier, site=secure_admin_site)
class CourrierAdmin(SecureModelAdmin):
    list_display = ('reference', 'designation', 'expediteur_nom', 'statut', 'date_arrivee')
    list_filter = ('statut',)
    search_fields = ('reference', 'designation', 'expediteur_nom', 'expediteur_institution')


@admin.register(Document, site=secure_admin_site)
class DocumentAdmin(SecureModelAdmin):
    list_display = ('nom', 'courrier', 'date_televersement')


@admin.register(FicheAnalyse, site=secure_admin_site)
class FicheAnalyseAdmin(SecureModelAdmin):
    list_display = ('courrier', 'analyse_par', 'valide', 'date_analyse')


@admin.register(FicheAnalyseSG, site=secure_admin_site)
class FicheAnalyseSGAdmin(SecureModelAdmin):
    list_display = ('courrier', 'analyse_par', 'valide', 'date_analyse')


@admin.register(Decision, site=secure_admin_site)
class DecisionAdmin(SecureModelAdmin):
    list_display = ('courrier', 'signe_par', 'date_decision')


@admin.register(Affectation, site=secure_admin_site)
class AffectationAdmin(SecureModelAdmin):
    list_display = ('courrier', 'destinataire', 'service_concerne', 'statut_traitement')


@admin.register(Historique, site=secure_admin_site)
class HistoriqueAdmin(SecureModelAdmin):
    list_display = ('courrier', 'utilisateur', 'action', 'date_action')


@admin.register(Notification, site=secure_admin_site)
class NotificationAdmin(SecureModelAdmin):
    list_display = ('destinataire', 'message', 'lu', 'date_notification')


@admin.register(Relance, site=secure_admin_site)
class RelanceAdmin(SecureModelAdmin):
    list_display = ('courrier', 'etape', 'destinataire_role', 'destinataire_user', 'service_concerne', 'date_debut_etape', 'est_resolue', 'date_resolution')
    list_filter = ('est_resolue', 'etape', 'destinataire_role')
    search_fields = ('courrier__reference', 'courrier__designation')
