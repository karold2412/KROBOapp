# Stage 0: server preparation

Stage 0 is complete when a phone on mobile data opens `https://YOUR-DOMAIN/` and shows the
status card with "HTTPS", and the server sends a test email from both Gmail accounts.
Steps 1–2 and 6–7 happen on the server laptop; steps 3–5 in a browser on any computer.

## 1. Choosing the laptop

Copy the repository to the candidate laptop and run the check (it changes nothing):

```bash
sudo apt install smartmontools        # to check disk health
sudo ./scripts/check-server-laptop.sh
```

Every `[FAIL]` item needs a change. Step 2 shows how to fix most of them.
The hardest ones to fix are a missing TPM 2.0, a spinning disk and an unencrypted disk.
LUKS encryption usually means reinstalling the system with the encryption option selected,
so if no laptop has it, choose the one whose reinstallation hurts least.

## 2. Configuring the laptop

Commands for Linux Mint and Ubuntu. After all changes, reboot the laptop and run
`sudo ./scripts/check-server-laptop.sh` again.

**Closed lid and sleep**

```bash
sudo mkdir -p /etc/systemd/logind.conf.d
printf '[Login]\nHandleLidSwitch=ignore\nHandleLidSwitchExternalPower=ignore\nHandleLidSwitchDocked=ignore\n' \
  | sudo tee /etc/systemd/logind.conf.d/krobo-server.conf
sudo systemctl mask sleep.target suspend.target hibernate.target hybrid-sleep.target
```

In the desktop environment's power settings (Cinnamon: System Settings → Power Management)
also choose "do nothing" when the lid is closed and disable suspend on inactivity.

**Battery charge limit (80%)**

```bash
sudo apt install tlp
printf 'START_CHARGE_THRESH_BAT0=75\nSTOP_CHARGE_THRESH_BAT0=80\n' | sudo tee /etc/tlp.d/90-krobo.conf
sudo tlp start
sudo tlp-stat -b      # check that the limit is active
```

Threshold support depends on the vendor; `tlp-stat -b` shows what the laptop supports.
Some laptops (e.g. LG gram) allow only 80% or 100%.

**Clock and time zone**

```bash
sudo timedatectl set-ntp true
sudo timedatectl set-timezone Europe/Warsaw
```

**BIOS (manual):** enable the TPM (TPM / PTT / fTPM) and the option to power on when mains
power is connected (Power On AC, Wake on AC, AC Power Recovery). Not every laptop has the latter.

**Unlocking the disk with TPM 2.0.** On Mint and Ubuntu this is done with clevis. Your disk
passphrase stays as a fallback. Before you start, keep a keyboard and the passphrase at hand.

```bash
lsblk -o NAME,TYPE,FSTYPE        # find the crypto_LUKS partition, e.g. nvme0n1p3
sudo apt install clevis clevis-tpm2 clevis-luks clevis-initramfs
sudo clevis luks bind -d /dev/nvme0n1p3 tpm2 '{"pcr_ids":"7"}'
sudo update-initramfs -u -k all
```

After a reboot the disk should unlock by itself. A BIOS settings change or a firmware update
may require typing the passphrase once; then repeat `clevis luks bind`.

**Docker**

```bash
sudo apt install ca-certificates curl
sudo install -m 0755 -d /etc/apt/keyrings
sudo curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
. /etc/os-release
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu ${UBUNTU_CODENAME:-$VERSION_CODENAME} stable" \
  | sudo tee /etc/apt/sources.list.d/docker.list
sudo apt update
sudo apt install docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
sudo systemctl enable --now docker
sudo usermod -aG docker "$USER"      # log out and back in
```

## 3. Domain

Buy a domain from any registrar. The system will live on a subdomain, e.g. `app.yourdomain.pl`;
the rest of the domain stays free for a future company website. Keep the registrar's panel
open: step 4 changes its DNS servers.

## 4. Cloudflare and the tunnel

1. Create a free account at cloudflare.com and add the domain (Free plan).
2. Cloudflare shows two name servers. Enter them at the registrar instead of the current ones
   and wait until Cloudflare shows the domain as active (from minutes to a day).
3. In the domain's SSL/TLS settings, turn on **Always Use HTTPS**.
4. Go to **Networking → Tunnels**, click **Create Tunnel** and name it `krobo-server`.
5. Choose **Docker** as the environment. From the command shown, copy the long string after
   `--token` and paste it into `.env` as `CLOUDFLARE_TUNNEL_TOKEN=` (step 6 creates `.env`).
6. In the tunnel: **Routes → Add route → Published application**. Hostname: `app` and your
   domain. Service URL: `http://caddy:80`. Save.

The tunnel token is the key to publishing under your domain: keep it only in `.env`.

## 5. Google Cloud and the Gmail API

Sign in to console.cloud.google.com with the company Gmail account.

1. Create a project named `krobo`.
2. Find **Gmail API** in the API library and click **Enable**.
3. Open **Google Auth Platform** and click **Get started**:
   - **Branding:** app name `KROBO`, support and contact email: the company Gmail address;
   - **Audience:** type **External**.
4. **Data Access → Add or remove scopes:** select `.../auth/gmail.send`, `openid`
   and `.../auth/userinfo.email`. Save.
5. **Clients → Create client:** type **Desktop app**, name `krobo-server`. Download the JSON file
   and save it on the server as `secrets/google-oauth-client.json`. The container reads it as
   the user with UID 1000; if authorization reports that it cannot read the file, run
   `chmod 644 secrets/google-oauth-client.json`.
6. **Audience → Publish app**. Without this (status "Testing") tokens expire after 7 days and
   sending stops working. The app stays unverified; during authorization Google shows a warning
   that you pass with "Advanced → Go to KROBO".

## 6. Start-up and account authorization

```bash
python3 scripts/init-env.py               # enter the hostname (e.g. app.yourdomain.pl) and both Gmail addresses
nano .env                                  # paste CLOUDFLARE_TUNNEL_TOKEN from step 4
docker compose --profile tunnel up -d --build
docker compose --profile tunnel ps         # all services "running", web and caddy "healthy"
```

Authorization: each account separately, on the server laptop. The command prints an address;
open it in a private browser window and sign in with the account it asks for. Tick the
permission to send mail. The command rejects the authorization if you sign in with a different
account than the one in `.env`.

```bash
docker compose run --rm -p 127.0.0.1:8765:8765 web python manage.py gmail_authorize --role company
docker compose run --rm -p 127.0.0.1:8765:8765 web python manage.py gmail_authorize --role contractor
docker compose exec web python manage.py gmail_status
```

## 7. Acceptance test

```bash
./scripts/acceptance-stage0.sh
```

The script checks the services and the site on the domain over HTTPS, and sends an email
company → contractor and contractor → company. Then:

- find both emails in the inboxes and in the "Sent" folders;
- on a phone, turn off Wi-Fi, open `https://app.yourdomain.pl/` and check that the status card
  shows "HTTPS".

## Copying `.env` to the other laptops

The same `.env` must be on every laptop that may take over the server role (stage 2).
Copy it with a USB stick, not through messengers or cloud storage: it holds the key to the
Gmail tokens and the tunnel token.
