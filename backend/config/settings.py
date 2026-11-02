"""Django settings for the KROBO system.

All configuration comes from environment variables (the .env file next to
docker-compose.yml), so the same image runs on each of the three laptops.
"""

import os
from pathlib import Path

from django.core.exceptions import ImproperlyConfigured
from django.utils.translation import gettext_lazy as _

BASE_DIR = Path(__file__).resolve().parent.parent


def env(name, default=None, required=False):
    value = os.environ.get(name, default)
    if required and not value:
        raise ImproperlyConfigured(f"Missing required environment variable {name}")
    return value


def env_bool(name, default=False):
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def env_list(name, default=""):
    return [item.strip() for item in env(name, default).split(",") if item.strip()]


DEBUG = env_bool("DJANGO_DEBUG", False)
SECRET_KEY = env("DJANGO_SECRET_KEY", required=True)

PUBLIC_DOMAIN = env("PUBLIC_DOMAIN", "")

# "web" is the service name in docker-compose (used by the Caddy and container health checks).
ALLOWED_HOSTS = ["localhost", "127.0.0.1", "web"] + env_list("DJANGO_EXTRA_ALLOWED_HOSTS")
if PUBLIC_DOMAIN:
    ALLOWED_HOSTS.append(PUBLIC_DOMAIN)

CSRF_TRUSTED_ORIGINS = [f"https://{PUBLIC_DOMAIN}"] if PUBLIC_DOMAIN else []

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "core",
    "mailer",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.locale.LocaleMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.template.context_processors.i18n",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": env("POSTGRES_DB", "krobo"),
        "USER": env("POSTGRES_USER", "krobo"),
        "PASSWORD": env("POSTGRES_PASSWORD", ""),
        "HOST": env("POSTGRES_HOST", "db"),
        "PORT": env("POSTGRES_PORT", "5432"),
        "CONN_MAX_AGE": 60,
        "CONN_HEALTH_CHECKS": True,
    }
}

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator", "OPTIONS": {"min_length": 12}},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

# Specification, section 13: Polish and English from the first release, Europe/Warsaw.
# Source strings are English; Polish comes from locale/pl and is the default for users.
LANGUAGE_CODE = "pl"
LANGUAGES = [("pl", _("Polish")), ("en", _("English"))]
LOCALE_PATHS = [BASE_DIR / "locale"]
TIME_ZONE = "Europe/Warsaw"
USE_I18N = True
USE_TZ = True

# Formal emails between the company and the contractor are written in Polish (specification, section 10).
FORMAL_EMAIL_LANGUAGE = "pl"

STATIC_URL = "/static/"
STATIC_ROOT = Path(env("DJANGO_STATIC_ROOT", "/srv/static"))
MEDIA_URL = "/media/"
MEDIA_ROOT = Path(env("DJANGO_MEDIA_ROOT", "/srv/media"))

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# Internet traffic path: browser -> Cloudflare (HTTPS) -> cloudflared -> Caddy -> Django.
# Caddy forwards X-Forwarded-Proto only from trusted Docker network addresses, so Django
# can rely on it.
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
USE_X_FORWARDED_HOST = False
SESSION_COOKIE_SECURE = env_bool("DJANGO_COOKIE_SECURE", True)
CSRF_COOKIE_SECURE = SESSION_COOKIE_SECURE
SESSION_COOKIE_HTTPONLY = True
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "same-origin"
X_FRAME_OPTIONS = "DENY"
# HSTS and the HTTPS redirect are handled by Cloudflare ("Always Use HTTPS"). Django does
# not enforce them because local access through http://localhost:8080 must keep working.
SECURE_HSTS_SECONDS = int(env("DJANGO_HSTS_SECONDS", "0"))
SILENCED_SYSTEM_CHECKS = ["security.W004", "security.W008"]

# Gmail accounts named in the company <-> contractor agreement as correspondence addresses.
GMAIL_ACCOUNTS = {
    "company": {
        "address": env("GMAIL_COMPANY_ADDRESS", ""),
        "display_name": env("GMAIL_COMPANY_NAME", "KROBO sp. z o.o."),
    },
    "contractor": {
        "address": env("GMAIL_CONTRACTOR_ADDRESS", ""),
        "display_name": env("GMAIL_CONTRACTOR_NAME", "KROBO Karol Duda"),
    },
}
GMAIL_TOKEN_KEY = env("GMAIL_TOKEN_KEY", "")
GMAIL_CLIENT_SECRET_FILE = env("GMAIL_CLIENT_SECRET_FILE", "/app/secrets/google-oauth-client.json")

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {"console": {"class": "logging.StreamHandler"}},
    "root": {"handlers": ["console"], "level": env("DJANGO_LOG_LEVEL", "INFO")},
    # The OAuth library prints the authorization URL and also logs it at INFO level;
    # without this entry the URL would appear twice in the terminal.
    "loggers": {"google_auth_oauthlib": {"level": "WARNING"}},
}
