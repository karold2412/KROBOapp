from cryptography.fernet import Fernet, InvalidToken
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured


class TokenDecryptionError(Exception):
    pass


def _fernet():
    key = settings.GMAIL_TOKEN_KEY
    if not key:
        raise ImproperlyConfigured("GMAIL_TOKEN_KEY is missing from .env (run scripts/init-env.py).")
    try:
        return Fernet(key.encode())
    except ValueError as exc:
        raise ImproperlyConfigured("GMAIL_TOKEN_KEY has an invalid format.") from exc


def encrypt(plaintext: str) -> str:
    return _fernet().encrypt(plaintext.encode()).decode()


def decrypt(ciphertext: str) -> str:
    try:
        return _fernet().decrypt(ciphertext.encode()).decode()
    except InvalidToken as exc:
        raise TokenDecryptionError(
            "Cannot decrypt the Gmail token: GMAIL_TOKEN_KEY differs from the key used during authorization."
        ) from exc
