from django.core.management.base import BaseCommand

from mailer import crypto, gmail
from mailer.models import GmailAccount


class Command(BaseCommand):
    help = "Shows which Gmail accounts are authorized and whether their tokens can be decrypted."

    def handle(self, *args, **options):
        for role, _label in GmailAccount.ROLE_CHOICES:
            configured = gmail.account_config(role)["address"] if self._has_address(role) else "(missing from .env)"
            account = GmailAccount.objects.filter(role=role).first()
            if account is None:
                self.stdout.write(f"{role}: {configured}: NOT AUTHORIZED")
                continue
            try:
                gmail.load_credentials(account)
                state = self.style.SUCCESS("token OK")
            except crypto.TokenDecryptionError as exc:
                state = self.style.ERROR(str(exc))
            self.stdout.write(f"{role}: {account.address}: authorized {account.authorized_at:%Y-%m-%d %H:%M}, {state}")

    @staticmethod
    def _has_address(role):
        try:
            gmail.account_config(role)
            return True
        except gmail.GmailError:
            return False
