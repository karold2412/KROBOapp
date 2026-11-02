from django.db import models
from django.utils.translation import gettext_lazy as _


class GmailAccount(models.Model):
    """Gmail account of one of the two parties (company or contractor), authorized to send.

    The OAuth token is encrypted with GMAIL_TOKEN_KEY from .env, which never reaches the
    database, snapshots or backups. A copy of the database alone cannot send mail on
    behalf of the business.
    """

    ROLE_COMPANY = "company"
    ROLE_CONTRACTOR = "contractor"
    ROLE_CHOICES = [
        (ROLE_COMPANY, _("Company (KROBO sp. z o.o.)")),
        (ROLE_CONTRACTOR, _("Contractor (KROBO Karol Duda)")),
    ]

    role = models.CharField(_("role"), max_length=16, choices=ROLE_CHOICES, unique=True)
    address = models.EmailField(_("address"))
    token_encrypted = models.TextField(_("encrypted token"))
    authorized_at = models.DateTimeField(_("authorized at"))
    updated_at = models.DateTimeField(_("updated at"), auto_now=True)

    class Meta:
        verbose_name = _("Gmail account")
        verbose_name_plural = _("Gmail accounts")

    def __str__(self):
        return f"{self.get_role_display()} <{self.address}>"


class SentEmail(models.Model):
    """Record of every sent message. The Gmail ID locates it in the "Sent" folder and
    links it to the audit log in later stages."""

    account = models.ForeignKey(
        GmailAccount, on_delete=models.PROTECT, related_name="sent", verbose_name=_("account")
    )
    to_address = models.EmailField(_("recipient"))
    subject = models.CharField(_("subject"), max_length=255)
    gmail_message_id = models.CharField(_("Gmail message ID"), max_length=64)
    gmail_thread_id = models.CharField(_("Gmail thread ID"), max_length=64)
    rfc822_message_id = models.CharField(_("Message-ID header"), max_length=255)
    sent_at = models.DateTimeField(_("sent at"), auto_now_add=True)

    class Meta:
        ordering = ["-sent_at"]
        verbose_name = _("sent email")
        verbose_name_plural = _("sent emails")

    def __str__(self):
        return f"{self.sent_at:%Y-%m-%d %H:%M} {self.account.role} -> {self.to_address}: {self.subject}"
