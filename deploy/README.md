# VPS deployment

`setup_vps.sh` bootstraps TimorMart on a fresh Ubuntu 22.04/24.04 VPS: system
packages, a brand-new empty Postgres database, the app itself under a
dedicated system user, gunicorn as a systemd service, and (if you set a
domain) Nginx + a Let's Encrypt certificate.

No data is imported or migrated — `manage.py migrate` builds an empty
schema from scratch. The only account that exists afterward is the
superuser you fill in below.

## Two files, same relationship as `.env` / `.env.example`

- **`setup_vps.sh`** — the committed template. No real credentials in it,
  safe to commit/push. `SUPERUSER_USERNAME`/`PASSWORD`/`EMAIL` are all
  `"CHANGE_ME"`; the script refuses to run until you change them.
- **`setup_vps.local.sh`** — your actual copy with real values filled in.
  Already in `.gitignore` — it will never be committed, the same way
  `.env` never is.

## Usage

1. Copy the template: `cp setup_vps.sh setup_vps.local.sh`, then edit
   `setup_vps.local.sh` and fill in `SUPERUSER_USERNAME`/`PASSWORD`/`EMAIL`
   (and `DOMAIN`, `REPO_URL`, `APP_DIR` if you want anything other than
   the defaults).
2. Point your domain's DNS `A` record at the new server's IP (skip this if
   you just want to test on the bare IP first — leave `DOMAIN` blank in
   that case).
3. Copy `setup_vps.local.sh` to the server and run it as root:
   ```
   sudo bash setup_vps.local.sh
   ```
4. Read the summary it prints at the end — it lists exactly which
   `.env` values (Stripe, Cloudinary, Resend/Gmail, Firebase) still need
   filling in by hand, since those are your own external accounts and
   nothing here can generate them. Edit `/srv/timormart/.env`, then:
   ```
   systemctl restart timormart
   ```
5. Log in at `/accounts/login/` with the superuser account and change
   that password immediately — it was sitting in `setup_vps.local.sh` in
   plain text.

Everything else — payment instructions, commission rate, platform bank
accounts, courier delivery fee, and so on — is configured from the app's
own `/dashboard/` once it's running, not from the server.

## After a domain/IP change

The courier Flutter app has the API's base URL baked in at build time
(`--dart-define=API_BASE_URL=...`, defaults to the Render URL — see
`courier_app/lib/api_client.dart`). Moving to a new domain means a new
release build pointed at it; the existing installed app will keep talking
to the old host until that happens.
