#!/usr/bin/env bash
# Stage 0 acceptance test (specification, section 15):
#   1) services are running, 2) the site answers on the domain over HTTPS,
#   3) the server sends a test email from both Gmail accounts.
#
# Run on the primary server, in the repository directory:
#   ./scripts/acceptance-stage0.sh                  # address from PUBLIC_DOMAIN in .env
#   ./scripts/acceptance-stage0.sh --url URL        # a different address
#   ./scripts/acceptance-stage0.sh --skip-mail      # without sending emails
#
# Also check condition 2 from a phone (mobile data, Wi-Fi off): open
# https://YOUR-DOMAIN/ and look for the status card with "HTTPS".

set -euo pipefail
cd "$(dirname "$0")/.."
COMPOSE="${COMPOSE:-docker compose}"

url=""; send_mail=1
while [ $# -gt 0 ]; do
    case "$1" in
        --url) url="$2"; shift 2 ;;
        --skip-mail) send_mail=0; shift ;;
        *) echo "Unknown option: $1" >&2; exit 2 ;;
    esac
done

if [ -z "$url" ]; then
    domain="$(grep -E '^PUBLIC_DOMAIN=' .env 2>/dev/null | head -n1 | cut -d= -f2-)"
    if [ -z "$domain" ]; then
        echo "PUBLIC_DOMAIN is missing from .env; pass an address: --url https://..." >&2
        exit 1
    fi
    url="https://$domain"
fi
url="${url%/}"
failed=0

echo "== 1/3 Services"
$COMPOSE --profile tunnel ps --format '{{.Service}}: {{.State}} {{.Health}}'

echo
echo "== 2/3 Site: $url/health/"
if body="$(curl -fsS --max-time 20 "$url/health/")"; then
    echo "$body"
    if ! python3 - "$body" "$url" <<'EOF'
import json, sys
data, url = json.loads(sys.argv[1]), sys.argv[2]
problems = []
if data.get("status") != "ok":
    problems.append("the server reports a database error")
if url.startswith("https://") and data.get("https") is not True:
    problems.append("Django does not see HTTPS: check the tunnel and trusted_proxies in Caddy")
for p in problems:
    print("ERROR:", p)
sys.exit(1 if problems else 0)
EOF
    then
        failed=1
    else
        echo "OK"
    fi
else
    echo "ERROR: no answer from $url/health/ (tunnel, DNS or the web service)"
    failed=1
fi

echo
echo "== 3/3 Test emails from both accounts"
if [ "$send_mail" -eq 1 ]; then
    if $COMPOSE exec -T web python manage.py gmail_send_test --from both; then
        echo "OK: check both mailboxes (inbox and \"Sent\")."
    else
        failed=1
    fi
else
    echo "skipped (--skip-mail)"
fi

echo
if [ "$failed" -eq 0 ]; then
    echo "Stage 0: acceptance test PASSED."
else
    echo "Stage 0: acceptance test FAILED (details above)."
fi
exit "$failed"
