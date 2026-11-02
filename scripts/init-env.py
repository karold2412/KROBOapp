#!/usr/bin/env python3
"""Creates the .env file from .env.example and generates passwords and keys.

Usage (in the repository directory):
    python3 scripts/init-env.py                      # asks for the domain and Gmail addresses
    python3 scripts/init-env.py --domain app.company.pl \\
        --gmail-company company@gmail.com --gmail-contractor contractor@gmail.com

An existing .env is never overwritten (this protects the Gmail token encryption key).
Uses only the standard library, so it runs on a clean system.
"""

import argparse
import base64
import os
import re
import secrets
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
DOMAIN_RE = re.compile(r"^(?=.{1,253}$)([a-z0-9-]{1,63}\.)+[a-z]{2,63}$")


def fernet_key():
    return base64.urlsafe_b64encode(os.urandom(32)).decode()


def ask(prompt, validator, current):
    value = current if current else input(prompt).strip()
    if not validator(value):
        sys.exit(f"Invalid value: {value!r}")
    return value


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--domain")
    parser.add_argument("--gmail-company")
    parser.add_argument("--gmail-contractor")
    parser.add_argument("--env-file", default=str(ROOT / ".env"))
    args = parser.parse_args(argv)

    target = Path(args.env_file)
    if target.exists():
        sys.exit(f"{target} already exists; nothing changed. Delete it by hand if you really want a new one.")

    domain = ask("Public hostname (e.g. app.company.pl): ", lambda v: bool(DOMAIN_RE.match(v.lower())), args.domain)
    company = ask("Company Gmail address: ", lambda v: bool(EMAIL_RE.match(v)), args.gmail_company)
    contractor = ask("Contractor Gmail address: ", lambda v: bool(EMAIL_RE.match(v)), args.gmail_contractor)
    if company.lower() == contractor.lower():
        sys.exit("The company and contractor addresses must differ.")

    values = {
        "PUBLIC_DOMAIN": domain.lower(),
        "DJANGO_SECRET_KEY": secrets.token_urlsafe(50),
        "POSTGRES_PASSWORD": secrets.token_urlsafe(32),
        "GMAIL_COMPANY_ADDRESS": company,
        "GMAIL_CONTRACTOR_ADDRESS": contractor,
        "GMAIL_TOKEN_KEY": fernet_key(),
    }

    lines = []
    for line in (ROOT / ".env.example").read_text(encoding="utf-8").splitlines():
        key = line.split("=", 1)[0]
        if not line.startswith("#") and "=" in line and key in values:
            line = f"{key}={values[key]}"
        lines.append(line)

    target.write_text("\n".join(lines) + "\n", encoding="utf-8")
    target.chmod(0o600)
    print(f"Created {target} (permissions 600).")
    print("CLOUDFLARE_TUNNEL_TOKEN is still empty: paste it in after creating the tunnel.")


if __name__ == "__main__":
    main()
