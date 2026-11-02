from django.contrib import admin

from .models import GmailAccount, SentEmail


@admin.register(GmailAccount)
class GmailAccountAdmin(admin.ModelAdmin):
    list_display = ("role", "address", "authorized_at", "updated_at")
    exclude = ("token_encrypted",)
    readonly_fields = ("role", "address", "authorized_at", "updated_at")

    def has_add_permission(self, request):
        return False


@admin.register(SentEmail)
class SentEmailAdmin(admin.ModelAdmin):
    list_display = ("sent_at", "account", "to_address", "subject", "gmail_message_id")
    readonly_fields = [f.name for f in SentEmail._meta.fields]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
