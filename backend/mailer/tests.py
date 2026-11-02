import base64
import email
import json
from email import policy
from io import StringIO
from unittest import mock

from cryptography.fernet import Fernet
from django.core.management import CommandError, call_command
from django.test import TestCase, override_settings
from django.utils import translation

from . import crypto, gmail
from .models import GmailAccount, SentEmail

COMPANY = "company.test@gmail.com"
CONTRACTOR = "contractor.test@gmail.com"
DIACRITICS = "\u0105\u0107\u0119\u0142\u0144\u00f3\u015b\u017a\u017c"  # the nine Polish letters outside ASCII


def fake_id_token(address, verified=True):
    def part(data):
        return base64.urlsafe_b64encode(json.dumps(data).encode()).decode().rstrip("=")

    return f"{part({'alg': 'RS256'})}.{part({'email': address, 'email_verified': verified})}.signature"


class FakeCredentials:
    def __init__(self, address, refresh_token="1//refresh-secret", scopes=None):
        self.id_token = fake_id_token(address)
        self.refresh_token = refresh_token
        self.scopes = gmail.SCOPES if scopes is None else scopes

    def to_json(self):
        return json.dumps(
            {
                "refresh_token": self.refresh_token,
                "client_id": "id.apps.googleusercontent.com",
                "client_secret": "client-secret",
                "token": "access-token",
                "scopes": self.scopes,
                "token_uri": "https://oauth2.googleapis.com/token",
            }
        )


class FakeGmailService:
    """Stand-in for the Gmail service: records messages instead of sending them."""

    def __init__(self):
        self.sent = []

    def users(self):
        return self

    def messages(self):
        return self

    def send(self, userId, body):
        self.sent.append((userId, body))
        number = len(self.sent)
        return mock.Mock(execute=lambda: {"id": f"msg{number}", "threadId": f"thr{number}"})


def decode_raw(body):
    return email.message_from_bytes(base64.urlsafe_b64decode(body["raw"]), policy=policy.default)


def sender(message):
    address = message["From"].addresses[0]
    return address.display_name, address.addr_spec


class CryptoTests(TestCase):
    def test_roundtrip(self):
        token = crypto.encrypt("secret token")
        self.assertNotIn("secret", token)
        self.assertEqual(crypto.decrypt(token), "secret token")

    def test_other_key_cannot_decrypt(self):
        token = crypto.encrypt("secret token")
        with override_settings(GMAIL_TOKEN_KEY=Fernet.generate_key().decode()):
            with self.assertRaises(crypto.TokenDecryptionError):
                crypto.decrypt(token)


class StoreCredentialsTests(TestCase):
    def test_stores_encrypted_token_for_matching_account(self):
        account = gmail.store_credentials("company", FakeCredentials(COMPANY))
        self.assertEqual(account.address, COMPANY)
        self.assertNotIn("refresh-secret", account.token_encrypted)
        self.assertIn("refresh-secret", crypto.decrypt(account.token_encrypted))

    def test_address_comparison_ignores_case(self):
        account = gmail.store_credentials("contractor", FakeCredentials(CONTRACTOR.upper()))
        self.assertEqual(account.address, CONTRACTOR)

    def test_rejects_wrong_account(self):
        with self.assertRaisesMessage(gmail.GmailError, "Nothing was saved"):
            gmail.store_credentials("company", FakeCredentials(CONTRACTOR))
        self.assertFalse(GmailAccount.objects.exists())

    def test_rejects_missing_refresh_token(self):
        with self.assertRaisesMessage(gmail.GmailError, "no refresh token"):
            gmail.store_credentials("company", FakeCredentials(COMPANY, refresh_token=None))

    def test_rejects_missing_send_scope(self):
        creds = FakeCredentials(COMPANY, scopes=["openid", "https://www.googleapis.com/auth/userinfo.email"])
        with self.assertRaisesMessage(gmail.GmailError, "gmail.send"):
            gmail.store_credentials("company", creds)

    def test_rejects_unverified_email(self):
        creds = FakeCredentials(COMPANY)
        creds.id_token = fake_id_token(COMPANY, verified=False)
        with self.assertRaisesMessage(gmail.GmailError, "not verified"):
            gmail.store_credentials("company", creds)

    @override_settings(
        GMAIL_ACCOUNTS={
            "company": {"address": "", "display_name": "X"},
            "contractor": {"address": CONTRACTOR, "display_name": "Y"},
        }
    )
    def test_requires_address_in_env(self):
        with self.assertRaisesMessage(gmail.GmailError, "GMAIL_COMPANY_ADDRESS"):
            gmail.store_credentials("company", FakeCredentials(COMPANY))

    def test_reauthorization_replaces_token(self):
        gmail.store_credentials("company", FakeCredentials(COMPANY, refresh_token="old"))
        gmail.store_credentials("company", FakeCredentials(COMPANY, refresh_token="new"))
        self.assertEqual(GmailAccount.objects.count(), 1)
        self.assertIn("new", crypto.decrypt(GmailAccount.objects.get().token_encrypted))

    def test_stored_token_loads_as_google_credentials(self):
        account = gmail.store_credentials("company", FakeCredentials(COMPANY))
        creds = gmail.load_credentials(account)
        self.assertEqual(creds.refresh_token, "1//refresh-secret")


class SendEmailTests(TestCase):
    def setUp(self):
        gmail.store_credentials("company", FakeCredentials(COMPANY))
        gmail.store_credentials("contractor", FakeCredentials(CONTRACTOR))
        self.service = FakeGmailService()

    def test_message_headers_and_non_ascii_text(self):
        # Polish diacritics must survive MIME encoding: formal emails are written in Polish.
        sent = gmail.send_email(
            "company", CONTRACTOR, f"Order ZL-2026-0001 – {DIACRITICS}", f"Body: {DIACRITICS.upper()}", self.service
        )
        user_id, body = self.service.sent[0]
        self.assertEqual(user_id, "me")
        message = decode_raw(body)
        self.assertEqual(sender(message), ("KROBO sp. z o.o.", COMPANY))
        self.assertEqual(message["To"], CONTRACTOR)
        self.assertEqual(message["Subject"], f"Order ZL-2026-0001 – {DIACRITICS}")
        self.assertIn(DIACRITICS.upper(), message.get_content())
        self.assertTrue(message["Message-ID"].endswith("@gmail.com>"))
        self.assertEqual(sent.gmail_message_id, "msg1")
        self.assertEqual(sent.gmail_thread_id, "thr1")
        self.assertEqual(sent.rfc822_message_id, message["Message-ID"])

    def test_unauthorized_role_is_reported(self):
        GmailAccount.objects.filter(role="contractor").delete()
        with self.assertRaisesMessage(gmail.GmailError, "gmail_authorize --role contractor"):
            gmail.send_email("contractor", COMPANY, "Test", "Test", self.service)

    def test_request_through_real_google_client(self):
        """The real Google library (bundled API description) with a substituted HTTP layer:
        checks the URL, method and body of the request that would go to Gmail."""
        from googleapiclient.discovery import build
        from googleapiclient.http import HttpMockSequence

        http = HttpMockSequence([({"status": "200"}, json.dumps({"id": "g-id", "threadId": "g-thread"}))])
        service = build("gmail", "v1", http=http, cache_discovery=False)
        sent = gmail.send_email("contractor", COMPANY, "Timesheet 10/2026", "Body", service)

        uri, method, body, _headers = http.request_sequence[0]
        self.assertEqual(method, "POST")
        self.assertTrue(uri.startswith("https://gmail.googleapis.com/gmail/v1/users/me/messages/send"), uri)
        message = decode_raw(json.loads(body))
        self.assertEqual(sender(message), ("KROBO Karol Duda", CONTRACTOR))
        self.assertEqual(sent.gmail_message_id, "g-id")

    def test_http_error_from_gmail_is_reported(self):
        from googleapiclient.discovery import build
        from googleapiclient.http import HttpMockSequence

        http = HttpMockSequence([({"status": "403"}, json.dumps({"error": {"message": "Insufficient Permission"}}))])
        service = build("gmail", "v1", http=http, cache_discovery=False)
        with self.assertRaisesMessage(gmail.GmailError, "Gmail rejected sending"):
            gmail.send_email("company", CONTRACTOR, "Test", "Test", service)
        self.assertFalse(SentEmail.objects.exists())

    def test_revoked_token_gives_clear_message(self):
        from google.auth.exceptions import RefreshError

        broken = mock.Mock()
        broken.users.return_value.messages.return_value.send.return_value.execute.side_effect = RefreshError(
            "invalid_grant"
        )
        with self.assertRaisesMessage(gmail.GmailError, "revoked or has expired"):
            gmail.send_email("company", CONTRACTOR, "Test", "Test", broken)
        self.assertFalse(SentEmail.objects.exists())


class SendTestCommandTests(TestCase):
    def setUp(self):
        gmail.store_credentials("company", FakeCredentials(COMPANY))
        gmail.store_credentials("contractor", FakeCredentials(CONTRACTOR))
        self.service = FakeGmailService()
        patcher = mock.patch("mailer.gmail.build_service", return_value=self.service)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_both_directions(self):
        out = StringIO()
        call_command("gmail_send_test", stdout=out)
        pairs = [(sender(decode_raw(body)), decode_raw(body)["To"]) for _, body in self.service.sent]
        self.assertEqual(
            pairs,
            [(("KROBO sp. z o.o.", COMPANY), CONTRACTOR), (("KROBO Karol Duda", CONTRACTOR), COMPANY)],
        )
        self.assertEqual(SentEmail.objects.count(), 2)
        self.assertIn("OK company", out.getvalue())
        self.assertIn("OK contractor", out.getvalue())

    def test_test_email_is_written_in_the_formal_email_language(self):
        source = "[KROBO] Delivery test, stage 0, %(time)s"
        with translation.override("pl"):
            expected_prefix = translation.gettext(source).split("%(")[0]
        self.assertNotEqual(expected_prefix, source.split("%(")[0], "missing Polish translation")
        call_command("gmail_send_test", "--from", "company", stdout=StringIO())
        message = decode_raw(self.service.sent[0][1])
        self.assertTrue(message["Subject"].startswith(expected_prefix), message["Subject"])
        self.assertIn("KROBO sp. z o.o.", message.get_content())
        self.assertNotIn("This is a test message", message.get_content())

    @override_settings(FORMAL_EMAIL_LANGUAGE="en")
    def test_formal_email_language_can_be_english(self):
        call_command("gmail_send_test", "--from", "company", stdout=StringIO())
        message = decode_raw(self.service.sent[0][1])
        self.assertTrue(message["Subject"].startswith("[KROBO] Delivery test, stage 0, "), message["Subject"])

    def test_single_direction(self):
        call_command("gmail_send_test", "--from", "contractor", stdout=StringIO())
        self.assertEqual(len(self.service.sent), 1)
        self.assertEqual(decode_raw(self.service.sent[0][1])["To"], COMPANY)

    def test_failure_of_one_account_still_tries_other_and_fails_command(self):
        GmailAccount.objects.filter(role="company").delete()
        with self.assertRaises(CommandError):
            call_command("gmail_send_test", stdout=StringIO(), stderr=StringIO())
        self.assertEqual(len(self.service.sent), 1)


class AuthorizeCommandTests(TestCase):
    def patched(self, **kwargs):
        flow = mock.patch("mailer.gmail.run_authorization_flow", **kwargs)
        is_file = mock.patch("mailer.management.commands.gmail_authorize.Path.is_file", return_value=True)
        return flow, is_file

    def test_missing_client_secret_file(self):
        with self.assertRaisesMessage(CommandError, "google-oauth-client.json"):
            call_command("gmail_authorize", "--role", "company", "--client-secret", "/no/such/file.json")

    def test_successful_flow_stores_account(self):
        flow, is_file = self.patched(return_value=FakeCredentials(CONTRACTOR))
        with flow, is_file:
            out = StringIO()
            call_command("gmail_authorize", "--role", "contractor", stdout=out)
        self.assertIn("Authorization saved", out.getvalue())
        self.assertTrue(GmailAccount.objects.filter(role="contractor", address=CONTRACTOR).exists())

    def test_denied_consent_gives_clear_message(self):
        from oauthlib.oauth2.rfc6749.errors import AccessDeniedError

        flow, is_file = self.patched(side_effect=AccessDeniedError())
        with flow, is_file:
            with self.assertRaisesMessage(CommandError, "Google aborted the authorization (access_denied)"):
                call_command("gmail_authorize", "--role", "company", stdout=StringIO())
        self.assertFalse(GmailAccount.objects.exists())

    def test_wrong_account_in_browser_is_rejected(self):
        flow, is_file = self.patched(return_value=FakeCredentials("someone@gmail.com"))
        with flow, is_file:
            with self.assertRaisesMessage(CommandError, "someone@gmail.com"):
                call_command("gmail_authorize", "--role", "contractor", stdout=StringIO())


class StatusCommandTests(TestCase):
    def test_reports_authorized_and_missing(self):
        gmail.store_credentials("company", FakeCredentials(COMPANY))
        out = StringIO()
        call_command("gmail_status", stdout=out)
        text = out.getvalue()
        self.assertIn(f"{COMPANY}: authorized", text)
        self.assertIn("token OK", text)
        self.assertIn(f"{CONTRACTOR}: NOT AUTHORIZED", text)

    def test_reports_wrong_key(self):
        gmail.store_credentials("company", FakeCredentials(COMPANY))
        out = StringIO()
        with override_settings(GMAIL_TOKEN_KEY=Fernet.generate_key().decode()):
            call_command("gmail_status", stdout=out)
        self.assertIn("GMAIL_TOKEN_KEY differs", out.getvalue())
