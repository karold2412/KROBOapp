# KROBO

Order, working-time and booking system for KROBO sp. z o.o. and its contractors.
Requirements live in the "KROBO system specification" document. This repository is at stage 0:
the server skeleton, internet access through a Cloudflare tunnel, and mail sending through the Gmail API.

## Contents

| Path | Purpose |
| --- | --- |
| `docker-compose.yml` | services: PostgreSQL 17, Django (Gunicorn), Caddy, cloudflared (`tunnel` profile) |
| `backend/` | Django 5.2 LTS application: status page, `/health/`, `mailer` module (Gmail API) |
| `backend/locale/pl/` | Polish translation of the user interface and formal emails |
| `caddy/Caddyfile` | web server: static files, proxy to Django, forwarded headers trusted only from private networks |
| `scripts/init-env.py` | creates `.env` with generated passwords and keys |
| `scripts/check-server-laptop.sh` | checks whether a laptop can serve as the primary server (read-only) |
| `scripts/acceptance-stage0.sh` | stage 0 acceptance test |
| `docs/stage-0.md` | step-by-step guide: laptop, domain, Cloudflare, Google Cloud |
| `secrets/` | Google OAuth client file (kept out of git) |

## Quick start on the server

The full guide, including the Cloudflare and Google dashboard steps, is in [docs/stage-0.md](docs/stage-0.md).

```bash
sudo ./scripts/check-server-laptop.sh          # is the laptop suitable
python3 scripts/init-env.py                    # creates .env
# paste CLOUDFLARE_TUNNEL_TOKEN into .env, save the OAuth client file in secrets/
docker compose --profile tunnel up -d --build
docker compose run --rm -p 127.0.0.1:8765:8765 web python manage.py gmail_authorize --role company
docker compose run --rm -p 127.0.0.1:8765:8765 web python manage.py gmail_authorize --role contractor
./scripts/acceptance-stage0.sh
```

On the other laptops (no tunnel): `docker compose up -d --build`, then open http://localhost:8080.

## Tests

```bash
# application tests (need PostgreSQL; run them in Docker):
docker compose run --rm web python manage.py test
# laptop check script tests:
python3 -m unittest discover -s scripts/tests
```

## Conventions

- Code, comments, documentation and commit messages are in English. Only user-facing texts
  are translated: source strings are English, Polish comes from `backend/locale/pl` and is
  the default interface language.
- After changing user-facing strings: `python manage.py makemessages -l pl`, translate the new
  entries, then `python manage.py compilemessages` (the Docker build compiles them as well).
- Configuration comes only from `.env`; the same file sits on each of the three laptops and is
  copied by hand.
- Only the tunnel is reachable from the internet; the Caddy (8080) and database ports stay on `localhost`.
- Gmail tokens are stored in the database encrypted with `GMAIL_TOKEN_KEY` from `.env`.
- Time zone Europe/Warsaw; interface languages: Polish (default) and English.
