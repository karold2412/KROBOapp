import logging

from django.db import DatabaseError, connection
from django.http import JsonResponse
from django.shortcuts import render
from django.utils import timezone

logger = logging.getLogger(__name__)

APP_VERSION = "0.1.0 (stage 0)"


def database_ok():
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            return cursor.fetchone() == (1,)
    except DatabaseError:
        logger.exception("Health check: database unavailable")
        return False


def home(request):
    return render(
        request,
        "core/home.html",
        {
            "database_ok": database_ok(),
            "server_time": timezone.localtime(),
            "is_secure": request.is_secure(),
            "version": APP_VERSION,
        },
    )


def health(request):
    """Server state for Docker health checks and the stage 0 acceptance test.

    The "https" field tells whether the request arrived encrypted (through Cloudflare),
    so a check from a phone covers the whole chain: tunnel -> Caddy -> Django.
    """
    db = database_ok()
    payload = {
        "status": "ok" if db else "error",
        "database": "ok" if db else "error",
        "https": request.is_secure(),
        "time": timezone.localtime().isoformat(),
        "version": APP_VERSION,
    }
    return JsonResponse(payload, status=200 if db else 503)
