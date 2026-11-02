# Operations runbook

How the production system is set up, deployed, backed up and recovered.
Everything here was rehearsed on a development PC on 2026-10-22 (production
stack under `https://localhost:8443`, a full backup → wipe → restore cycle).

## 1. What runs where

```
 browser / phone ──HTTPS──▶  Caddy (TLS, headers, web app)  ──▶  api (gunicorn, Django)
                                                                   │
                     worker (Celery: PDFs, emails, upload checks, exports)
                     beat   (housekeeping; reminders 09:30 IST)    │
                     backup (nightly, encrypted)                   │
                                                                   ▼
          one server ── Postgres 17 · Redis · ClamAV  (Docker volumes)
          outside    ── object storage (files) · backup bucket · SMTP email · Sentry (optional)
```

Files: `deploy/docker-compose.prod.yml` (the stack, project name `billing-prod`),
`deploy/.env.production.example` (every setting), `deploy/deploy.sh` (one
deploy), `deploy/backup/` (backups, restore drill, restore),
`.github/workflows/deploy.yml` (build and deploy).

## 2. What to buy or sign up for

Keep everything in India where possible (DPDP Act; customers expect it).

| Item | Suggested | Notes |
|---|---|---|
| Server | Ubuntu 24.04 LTS, 4 vCPU, 8 GB RAM, 80 GB SSD, in Mumbai or another Indian region (AWS EC2 / Lightsail `ap-south-1`, DigitalOcean `BLR1`, …) | ClamAV alone needs about 1.5 GB of memory. A static public IP. |
| Domain | e.g. `app.<yourcompany>.in` | DNS `A` record → the server's IP. |
| File storage | AWS S3 bucket in `ap-south-1` (or Cloudflare R2) | Private bucket; an access key that can use only this bucket. |
| Backup storage | A second bucket in another region (`ap-south-2` Hyderabad), ideally another account | Versioning on, lifecycle rule (delete after 35 days), a key that can write but not delete. |
| Email | Amazon SES in `ap-south-1`, or another transactional provider (ZeptoMail, Postmark…) | Verify the sending domain: SPF, DKIM and DMARC records. SES starts in a sandbox: request production access. |
| Error alerts (optional) | sentry.io project | Put its DSN in `SENTRY_DSN`. |
| Backup alert (optional) | healthchecks.io check, period 1 day | Its ping URL in `BACKUP_PING_URL`: you get an email if a night's backup does not happen. |
| Uptime alert (optional) | any uptime monitor | Watch `https://<domain>/healthz` every minute. |

App bucket policy (AWS IAM), replacing `BUCKET`:

```json
{"Version": "2012-10-17", "Statement": [
  {"Effect": "Allow", "Action": ["s3:GetObject", "s3:PutObject", "s3:DeleteObject"], "Resource": "arn:aws:s3:::BUCKET/*"},
  {"Effect": "Allow", "Action": ["s3:ListBucket", "s3:GetBucketCORS", "s3:PutBucketCORS"], "Resource": "arn:aws:s3:::BUCKET"}
]}
```

Backup bucket policy: `s3:PutObject`, `s3:GetObject`, `s3:ListBucket` only (no
delete), and set `BACKUP_KEEP_DAYS=0` so the backup job never tries to delete;
the lifecycle rule removes old backups. Then even someone who takes over the
server cannot erase the backups.

## 3. One-time server setup

As root on the new server:

```bash
# Updates, firewall, automatic security updates
apt update && apt -y upgrade
apt -y install ufw unattended-upgrades
ufw allow OpenSSH && ufw allow 80/tcp && ufw allow 443/tcp && ufw allow 443/udp && ufw --force enable
dpkg-reconfigure -plow unattended-upgrades

# SSH: keys only, no root login (first copy your own key to a sudo user!)
cat > /etc/ssh/sshd_config.d/90-hardening.conf <<'EOF'
PasswordAuthentication no
PermitRootLogin no
EOF
systemctl reload ssh

# Docker Engine + compose plugin: https://docs.docker.com/engine/install/ubuntu/

# A user for deploys (docker group = can run containers: keep its key safe)
adduser --disabled-password --gecos "" deploy
usermod -aG docker deploy
mkdir -p /opt/billing && chown deploy:deploy /opt/billing
# Put the deploy key's public half in /home/deploy/.ssh/authorized_keys
```

On your own PC, make the keys that never live on the server:

```bash
ssh-keygen -t ed25519 -f billing-deploy -C "github deploy"   # deploy key pair
age-keygen -o billing-backup-key.txt                          # backup key pair (winget install FiloSottile.age)
```

Store `billing-backup-key.txt` (the private backup key) in a password manager
**and** an offline copy. Without it no backup can be restored; with it,
anyone can read them. Only its public line (`age1…`) goes on the server.

## 4. Settings

On the server, as `deploy`: copy `deploy/.env.production.example` to
`/opt/billing/.env`, `chmod 600 /opt/billing/.env`, and fill every value.

```bash
openssl rand -base64 48   # DJANGO_SECRET_KEY, JWT_SIGNING_KEY, the passwords
openssl rand -base64 32   # MFA_ENCRYPTION_KEY (exactly 32 bytes)
```

Never change `MFA_ENCRYPTION_KEY` later (two-step verification secrets are
encrypted with it), and keep a copy of `.env` in the password manager.

## 5. GitHub

Repository → Settings:

* **Environments → New environment `production`**: add yourself as a required
  reviewer (every deploy then waits for your click), and these secrets:
  * `DEPLOY_HOST` – the server's IP or name
  * `DEPLOY_USER` – `deploy`
  * `DEPLOY_SSH_KEY` – the contents of `billing-deploy` (private key)
  * `DEPLOY_KNOWN_HOSTS` – the output of `ssh-keyscan -t ed25519 <server>`,
    after checking the fingerprint against the provider's console
* **Variables → `AUTO_DEPLOY` = `true`** (optional): deploy after every green
  CI run on `main`. Without it, deploys run only by hand.

## 6. First deploy

1. Actions → **Deploy** → Run workflow (or push to `main` with `AUTO_DEPLOY`).
   It builds the images, pushes them to `ghcr.io/aaronpaul2006/…`, copies
   the compose file and `deploy.sh` to `/opt/billing` and runs
   `./deploy.sh <sha>`: pull, migrate job (roles, migrations, bucket CORS),
   start, wait for `https://<domain>/healthz`.
2. Open `https://<domain>/signup`, create the owner account, confirm the
   email (checks email works), set up two-step verification.
3. Check `docker compose -f docker-compose.prod.yml --env-file .env ps`: every
   service up, `api`/`postgres`/`redis`/`clamav` healthy.
4. Run a backup now and the restore drill (section 8) to prove both work.

## 7. Deploying and rolling back

* Deploy: the workflow (above). On the server it is `./deploy.sh <sha>`.
* Every deploy is appended to `/opt/billing/deployed.log`.
* Roll back: `./deploy.sh <previous sha>` (from `deployed.log`) after a
  `docker login ghcr.io`, or re-run an older successful workflow run.
  Migrations are written backwards-compatible (expand → migrate → contract),
  so the previous version runs on the newer schema.
* `deploy.sh` exits non-zero and says so if the site does not answer within
  two minutes.

Useful commands on the server (`cd /opt/billing`, `C="docker compose -f docker-compose.prod.yml --env-file .env"`):

```bash
$C ps                         # what runs, health
$C logs -f --since 10m api    # logs (one JSON object per line, with request_id)
$C logs -f worker caddy
$C restart api worker         # restart
df -h; docker system df       # disk
```

A user who reports an error can quote the `request_id` shown in the error; it
appears in the `api` log lines of that request.

### Database statistics and the speed check (W.7)

Report pages rely on PostgreSQL's table statistics. Autovacuum keeps them
current (leave it on, the default). After a bulk import or restore, run
`ANALYZE` as the table owner (`billing_owner`); as the app role it is silently
skipped. Without statistics the planner guesses one row per table and a
report on a large company takes seconds instead of milliseconds.

To check speed against a large company (500 clients, about 11,000 bills,
8,000 payments): `PERF=1 uv run pytest tests/perf -s` in `backend/`
(`PERF_EXPLAIN=1` also prints the plan of any slow page's slowest query).
Budget: 500 ms and 25 queries per request.

## 8. Backups

* Nightly at `BACKUP_HOUR` (UTC; default 21:00 = 02:30 IST): the database is
  dumped, encrypted with the backup public key and streamed to the backup
  bucket (`db/billing-<time>.dump.age`); uploaded files and PDFs are copied
  to `files/` (exports are left out: they are temporary by design).
* Logs: `$C logs backup`. Alert: the `BACKUP_PING_URL` check.
* A backup now: `$C run --rm backup backup.sh once`.
* **Restore drill — every quarter, and after the first deploy.** On the
  server, with the private key brought along (never stored there):

  ```bash
  $C run --rm -e AGE_IDENTITY="$(cat billing-backup-key.txt)" backup restore-drill.sh
  rm billing-backup-key.txt
  ```

  It restores the latest backup into a throwaway database inside the
  container, prints the counts (migrations, users, tenants, documents, audit
  rows, tables with row-level security forced) and ends with
  `RESTORE DRILL OK`. Production is not touched. Compare the counts with the
  live system; write the date in `deployed.log` or your notes.

## 9. Disaster recovery

Database lost or server gone. Rehearsed on 2026-10-22: database volume and a
stored PDF deleted, restored, the same owner signed in (password + code) and
saw their data.

1. New server: sections 3–5 (same `.env`: same secrets, same buckets).
2. `cd /opt/billing; docker login ghcr.io` and start only the databases:
   `$C up -d postgres redis`
3. Roles and an empty database:
   `$C run --rm migrate sh -c "python scripts/bootstrap_db.py --production"`
4. Restore the latest backup (or name one: `restore.sh billing-<time>.dump.age`):
   `$C run --rm -e AGE_IDENTITY="$(cat billing-backup-key.txt)" backup restore.sh`
   It refuses to run on a database that already has tables.
5. Files back (only if the app bucket was lost too):
   `$C run --rm backup rclone copy backup:<BACKUP_S3_BUCKET>/files app:<S3_BUCKET>`
6. Start: `./deploy.sh <sha of the last deploy>` (runs migrations, starts all).
7. Delete the key file from the server; run a backup; tell users. Data
   entered after the last backup (at most a day) must be entered again.

## 10. Security checklist

* Only ports 22, 80, 443 open; SSH keys only; automatic security updates.
* `.env` is `chmod 600`, owned by `deploy`, copied in the password manager.
* The backup private key and the deploy private key never live on the server.
* Containers: app containers read-only, no Linux capabilities, logs rotated
  (10 MB × 5 per service). Postgres, Redis and ClamAV are not reachable from
  outside; Caddy is the only door.
* HTTPS certificates renew by themselves (Caddy, Let's Encrypt); the
  `caddy-data` volume keeps them across restarts.
* Rotate a leaked secret: change it in `.env` and `./deploy.sh <current sha>`.
  `DJANGO_SECRET_KEY` / `JWT_SIGNING_KEY`: everyone signs in again.
  Database passwords: also run the migrate job (it re-applies them).
* Upgrade the server OS once a year (Ubuntu LTS) and Postgres between major
  versions with a dump and restore (section 9), never in place.

## 11. Owner mobile app

Android test builds come from Expo's cloud (EAS) and talk to this server's
API (`https://<domain>`): see `mobile/README.md`, "Android test build". The
build refuses an address that is not `https://`. Nothing on the server
changes for the app: it uses the same API and the same accounts.
