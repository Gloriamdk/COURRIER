from django.contrib.auth.mixins import UserPassesTestMixin
from django.core.exceptions import PermissionDenied

class RoleRequiredMixin(UserPassesTestMixin):
    """
    Mixin pour restreindre l'accès à une vue selon le rôle de l'utilisateur.
    """
    allowed_roles = []

    def test_func(self):
        # L'utilisateur doit être connecté et avoir le rôle autorisé
        return (
            self.request.user.is_authenticated
            and self.request.user.is_active
            and self.request.user.role in self.allowed_roles
        )

    def handle_no_permission(self):
        # Si l'utilisateur n'a pas les droits, on lève une erreur 403
        raise PermissionDenied("Vous n'avez pas la permission d'accéder à cette ressource.")
