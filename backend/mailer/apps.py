from django.apps import AppConfig
from django.utils.translation import gettext_lazy as _


class MailerConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "mailer"
    verbose_name = _("Mail (Gmail API)")
