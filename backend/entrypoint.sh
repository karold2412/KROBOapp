#!/bin/sh
# When the application server starts: database migrations and static files.
# Other commands (e.g. manage.py gmail_authorize) run without these steps.
set -eu

if [ "${1:-}" = "gunicorn" ]; then
    python manage.py migrate --noinput
    python manage.py collectstatic --noinput --verbosity 0
fi

exec "$@"
