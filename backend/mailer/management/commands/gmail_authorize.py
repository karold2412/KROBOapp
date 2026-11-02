from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from oauthlib.oauth2.rfc6749.errors import OAuth2Error

from mailer import gmail
from mailer.models import GmailAccount


class Command(BaseCommand):
    help = "Authorizes the company or contractor Gmail account to send mail (once per role)."

    def add_arguments(self, parser):
        parser.add_argument("--role", required=True, choices=[c[0] for c in GmailAccount.ROLE_CHOICES])
        parser.add_argument("--client-secret", default=settings.GMAIL_CLIENT_SECRET_FILE)
        parser.add_argument("--port", type=int, default=8765)

    def handle(self, *args, role, client_secret, port, **options):
        try:
            config = gmail.account_config(role)
        except gmail.GmailError as exc:
            raise CommandError(str(exc)) from exc
        if not Path(client_secret).is_file():
            raise CommandError(
                f"OAuth client file not found: {client_secret}. Download it from Google Cloud "
                "(Clients -> Desktop app) and save it as secrets/google-oauth-client.json."
            )
        try:
            credentials = gmail.run_authorization_flow(client_secret, port, config["address"])
        except OAuth2Error as exc:
            raise CommandError(
                f"Google aborted the authorization ({exc.error}). If you clicked \"Cancel\" or did not "
                "tick the permission to send mail, run the command again."
            ) from exc
        try:
            account = gmail.store_credentials(role, credentials)
        except gmail.GmailError as exc:
            raise CommandError(str(exc)) from exc
        self.stdout.write(self.style.SUCCESS(f"Authorization saved: {account.role} <{account.address}>"))
