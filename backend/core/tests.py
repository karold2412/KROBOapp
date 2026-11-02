import shutil
import subprocess
import unittest
from unittest import mock

from django.conf import settings
from django.db import OperationalError
from django.test import TestCase, override_settings
from django.utils import translation


def polish(text):
    """The Polish translation of a source string, read from the catalog (not hard-coded)."""
    with translation.override("pl"):
        return translation.gettext(text)


class TranslationCatalogTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which("msgfmt"), "gettext is not installed")
    def test_polish_catalog_has_no_untranslated_or_fuzzy_entries(self):
        catalog = settings.BASE_DIR / "locale" / "pl" / "LC_MESSAGES" / "django.po"
        result = subprocess.run(
            ["msgfmt", "--check", "--statistics", "-o", "/dev/null", str(catalog)],
            capture_output=True,
            text=True,
            env={"LC_ALL": "C", "PATH": "/usr/bin:/bin"},
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("untranslated", result.stderr)
        self.assertNotIn("fuzzy", result.stderr)


class HomePageTests(TestCase):
    def test_polish_is_the_default_ui_language(self):
        expected = polish("System is running.")
        self.assertNotEqual(expected, "System is running.", "missing Polish translation")
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, expected)
        self.assertContains(response, '<html lang="pl">')

    def test_english_from_browser_language(self):
        response = self.client.get("/", HTTP_ACCEPT_LANGUAGE="en")
        self.assertContains(response, "System is running.")
        self.assertContains(response, '<html lang="en">')

    @override_settings(SESSION_COOKIE_SECURE=False, CSRF_COOKIE_SECURE=False)
    def test_language_switch_sets_english(self):
        self.client.post("/i18n/setlang/", {"language": "en", "next": "/"})
        response = self.client.get("/")
        self.assertContains(response, "System is running.")

    def test_shows_database_status(self):
        response = self.client.get("/", HTTP_ACCEPT_LANGUAGE="en")
        self.assertContains(response, 'class="ok">working')


class HealthTests(TestCase):
    def test_ok_when_database_answers(self):
        response = self.client.get("/health/")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["status"], "ok")
        self.assertEqual(data["database"], "ok")
        self.assertFalse(data["https"])

    def test_https_detected_from_trusted_proxy_header(self):
        response = self.client.get("/health/", HTTP_X_FORWARDED_PROTO="https")
        self.assertTrue(response.json()["https"])

    def test_503_when_database_fails(self):
        with mock.patch("core.views.connection.cursor", side_effect=OperationalError("no database")):
            response = self.client.get("/health/")
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()["status"], "error")

    def test_time_is_warsaw(self):
        data = self.client.get("/health/").json()
        self.assertRegex(data["time"], r"\+0[12]:00$")

    def test_public_domain_is_allowed_host(self):
        response = self.client.get("/health/", HTTP_HOST="app.krobo-test.pl")
        self.assertEqual(response.status_code, 200)

    def test_unknown_host_is_rejected(self):
        response = self.client.get("/health/", HTTP_HOST="evil.example.com")
        self.assertEqual(response.status_code, 400)
