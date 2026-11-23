import getpass
import os

from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError

from apps.common import tenancy


class Command(BaseCommand):
    help = "Create a platform super admin. Password from --password-env (env var name) or an interactive prompt."

    def add_arguments(self, parser):
        parser.add_argument("--email", required=True)
        parser.add_argument("--first-name", default="Platform")
        parser.add_argument("--last-name", default="Admin")
        parser.add_argument("--password-env", help="Name of an environment variable holding the password")

    def handle(self, *args, email, first_name, last_name, password_env, **options):
        from apps.accounts.models import User
        from apps.accounts.services.platform import create_super_admin

        password = os.environ.get(password_env, "") if password_env else getpass.getpass("Password: ")
        if not password:
            raise CommandError("A password is required.")
        try:
            validate_password(password)
        except ValidationError as exc:
            raise CommandError(" ".join(exc.messages)) from exc
        with tenancy.platform_context():
            if User.objects.filter(email__iexact=email).exists():
                raise CommandError("A user with this email already exists.")
            create_super_admin(email=email, password=password, first_name=first_name, last_name=last_name)
        self.stdout.write(self.style.SUCCESS(f"Super admin {email} created."))
