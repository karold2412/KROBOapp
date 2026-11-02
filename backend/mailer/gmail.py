"""Sending mail through the Gmail API from the two accounts named in the company <-> contractor agreement.

OAuth scopes: sending only (gmail.send) plus openid and email. The latter two are used solely
to verify that the right account was authorized; gmail.send alone cannot even read the
mailbox address.
"""

import base64
import json
from email.message import EmailMessage
from email.utils import formataddr, formatdate, make_msgid

from django.conf import settings
from django.utils import timezone

from . import crypto
from .models import GmailAccount, SentEmail

SCOPES = [
    "openid",
    "https://www.googleapis.com/auth/userinfo.email",
    "https://www.googleapis.com/auth/gmail.send",
]

ENV_ADDRESS_VARIABLES = {
    GmailAccount.ROLE_COMPANY: "GMAIL_COMPANY_ADDRESS",
    GmailAccount.ROLE_CONTRACTOR: "GMAIL_CONTRACTOR_ADDRESS",
}


class GmailError(Exception):
    pass


def account_config(role):
    try:
        config = settings.GMAIL_ACCOUNTS[role]
    except KeyError as exc:
        raise GmailError(f"Unknown account role: {role}") from exc
    if not config["address"]:
        raise GmailError(f"Account address is missing from .env ({ENV_ADDRESS_VARIABLES[role]}).")
    return config


def email_from_id_token(id_token):
    """Reads the address from the ID token. The token comes straight from Google's token
    endpoint over TLS, so OpenID Connect does not require verifying its signature."""
    if not id_token:
        raise GmailError("Google returned no ID token; check the openid and email scopes in the project.")
    try:
        payload = id_token.split(".")[1]
        payload += "=" * (-len(payload) % 4)
        claims = json.loads(base64.urlsafe_b64decode(payload))
    except (IndexError, ValueError) as exc:
        raise GmailError("Invalid ID token from Google.") from exc
    if not claims.get("email_verified", False):
        raise GmailError("The Google account address is not verified.")
    return claims.get("email", "")


def run_authorization_flow(client_secret_file, port, login_hint):  # pragma: no cover - needs a browser
    from google_auth_oauthlib.flow import InstalledAppFlow

    flow = InstalledAppFlow.from_client_secrets_file(client_secret_file, scopes=SCOPES)
    return flow.run_local_server(
        host="localhost",
        bind_addr="0.0.0.0",
        port=port,
        open_browser=False,
        authorization_prompt_message=(
            f"\nOpen this address in a browser ON THIS LAPTOP and sign in as {login_hint}:\n\n{{url}}\n"
        ),
        success_message="Authorization complete. You can close this tab and return to the terminal.",
        access_type="offline",
        prompt="consent",
        login_hint=login_hint,
    )


def store_credentials(role, credentials):
    """Verifies that the authorized account matches .env and stores the encrypted token."""
    config = account_config(role)
    expected = config["address"].strip().lower()
    actual = email_from_id_token(getattr(credentials, "id_token", None)).strip().lower()
    if actual != expected:
        raise GmailError(
            f"Authorized account {actual}, but .env sets {expected} for role '{role}'. Nothing was saved."
        )
    if not credentials.refresh_token:
        raise GmailError(
            "Google returned no refresh token. Remove the app's access at "
            "https://myaccount.google.com/permissions and authorize again."
        )
    missing = set(SCOPES) - set(credentials.scopes or [])
    if "https://www.googleapis.com/auth/gmail.send" in missing:
        raise GmailError("Permission to send mail (gmail.send) was not granted. Nothing was saved.")

    account, _ = GmailAccount.objects.update_or_create(
        role=role,
        defaults={
            "address": expected,
            "token_encrypted": crypto.encrypt(credentials.to_json()),
            "authorized_at": timezone.now(),
        },
    )
    return account


def load_credentials(account):
    from google.oauth2.credentials import Credentials

    info = json.loads(crypto.decrypt(account.token_encrypted))
    return Credentials.from_authorized_user_info(info, scopes=SCOPES)


def build_service(credentials):
    from googleapiclient.discovery import build

    # The API discovery document ships with the library, so nothing is fetched from the network.
    return build("gmail", "v1", credentials=credentials, cache_discovery=False)


def get_account(role):
    try:
        return GmailAccount.objects.get(role=role)
    except GmailAccount.DoesNotExist as exc:
        raise GmailError(
            f"Account '{role}' is not authorized. Run: python manage.py gmail_authorize --role {role} "
            "(full Docker command: docs/stage-0.md, step 6)"
        ) from exc


def build_message(role, to_address, subject, body):
    config = account_config(role)
    sender = config["address"]
    message = EmailMessage()
    message["From"] = formataddr((config["display_name"], sender))
    message["To"] = to_address
    message["Subject"] = subject
    message["Date"] = formatdate(localtime=True)
    message["Message-ID"] = make_msgid(idstring="krobo", domain=sender.split("@")[-1])
    message.set_content(body, charset="utf-8")
    return message


def send_email(role, to_address, subject, body, service=None):
    from google.auth.exceptions import RefreshError
    from googleapiclient.errors import HttpError

    account = get_account(role)
    message = build_message(role, to_address, subject, body)
    raw = base64.urlsafe_b64encode(message.as_bytes()).decode()
    try:
        if service is None:
            service = build_service(load_credentials(account))
        result = service.users().messages().send(userId="me", body={"raw": raw}).execute()
    except RefreshError as exc:
        raise GmailError(
            f"The token for account '{role}' was revoked or has expired. "
            f"Run again: python manage.py gmail_authorize --role {role} (docs/stage-0.md, step 6)"
        ) from exc
    except HttpError as exc:
        raise GmailError(f"Gmail rejected sending from account '{role}': {exc}") from exc

    return SentEmail.objects.create(
        account=account,
        to_address=to_address,
        subject=subject,
        gmail_message_id=result.get("id", ""),
        gmail_thread_id=result.get("threadId", ""),
        rfc822_message_id=message["Message-ID"],
    )
