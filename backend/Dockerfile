FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    TZ=Europe/Warsaw

# gettext compiles the Polish translations while building the image. The package version is
# not pinned: it follows the base image, and a pinned version disappears from the Debian
# repository after an update.
# hadolint ignore=DL3008
RUN apt-get update \
    && apt-get install -y --no-install-recommends gettext \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --uid 1000 krobo

WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt

COPY . .
RUN DJANGO_SECRET_KEY=build-only python manage.py compilemessages \
    && mkdir -p /srv/static /srv/media /app/secrets \
    && chown -R krobo:krobo /srv /app \
    && chmod +x /app/entrypoint.sh

# Gunicorn trusts forwarded headers from any address because only Caddy can reach this
# container; Caddy itself accepts them only from private networks.
USER 1000:1000
EXPOSE 8000
ENTRYPOINT ["/app/entrypoint.sh"]
CMD ["gunicorn", "config.wsgi", "--bind", "0.0.0.0:8000", "--workers", "3", "--access-logfile", "-", "--forwarded-allow-ips", "*"]
