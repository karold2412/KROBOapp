from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone, translation
from django.utils.translation import gettext

from mailer import gmail
from mailer.models import GmailAccount

OTHER = {
    GmailAccount.ROLE_COMPANY: GmailAccount.ROLE_CONTRACTOR,
    GmailAccount.ROLE_CONTRACTOR: GmailAccount.ROLE_COMPANY,
}


def build_test_message(sender_role, stamp):
    """Subject and body of the test email, in the language used for formal emails."""
    recipient_role = OTHER[sender_role]
    with translation.override(settings.FORMAL_EMAIL_LANGUAGE):
        subject = gettext("[KROBO] Delivery test, stage 0, %(time)s") % {"time": stamp}
        body = gettext(
            "This is a test message from the KROBO system (stage 0).\n\n"
            "Sender: %(sender)s\n"
            "Recipient: %(recipient)s\n"
            "Sent at: %(time)s (Europe/Warsaw)\n\n"
            "This message confirms that the server sends mail through the Gmail API. "
            "No reply is needed.\n"
        ) % {
            "sender": gmail.account_config(sender_role)["display_name"],
            "recipient": gmail.account_config(recipient_role)["display_name"],
            "time": stamp,
        }
    return subject, body


class Command(BaseCommand):
    help = "Sends a test email from the company to the contractor and/or from the contractor to the company."

    def add_arguments(self, parser):
        parser.add_argument("--from", dest="sender", default="both", choices=["company", "contractor", "both"])

    def handle(self, *args, sender, **options):
        roles = [GmailAccount.ROLE_COMPANY, GmailAccount.ROLE_CONTRACTOR] if sender == "both" else [sender]
        stamp = timezone.localtime().strftime("%Y-%m-%d %H:%M:%S")
        failures = []
        for role in roles:
            try:
                recipient = gmail.account_config(OTHER[role])["address"]
                subject, body = build_test_message(role, stamp)
                sent = gmail.send_email(role, recipient, subject, body)
            except gmail.GmailError as exc:
                failures.append(f"{role}: {exc}")
                self.stderr.write(self.style.ERROR(f"ERROR {role}: {exc}"))
                continue
            self.stdout.write(self.style.SUCCESS(f"OK {role} -> {recipient} (Gmail id {sent.gmail_message_id})"))
        if failures:
            raise CommandError("Not all test emails were sent.")
