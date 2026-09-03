import os

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = "Désactive les comptes dont le mot de passe correspond à un secret compromis."

    def add_arguments(self, parser):
        parser.add_argument(
            "--password-env",
            required=True,
            help="Nom de la variable d'environnement contenant le mot de passe compromis.",
        )
        parser.add_argument(
            "--apply",
            action="store_true",
            help="Applique la correction. Sans cette option, la commande est en mode audit.",
        )

    def handle(self, *args, **options):
        password = os.getenv(options["password_env"])
        if not password:
            raise CommandError("Variable d'environnement introuvable ou vide.")

        User = get_user_model()
        matched_users = []
        for user in User.objects.filter(is_active=True):
            if user.has_usable_password() and user.check_password(password):
                matched_users.append(user)

        if not options["apply"]:
            self.stdout.write(
                self.style.WARNING(
                    f"{len(matched_users)} compte(s) actif(s) utilisent ce mot de passe compromis."
                )
            )
            return

        for user in matched_users:
            user.set_unusable_password()
            user.is_active = False
            user.save(update_fields=["password", "is_active"])

        self.stdout.write(
            self.style.SUCCESS(
                f"{len(matched_users)} compte(s) compromis ont été désactivés et invalidés."
            )
        )
