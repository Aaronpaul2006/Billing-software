#!/bin/sh
# Restore drill: prove the latest backup can be read and restored, without
# touching production. Restores into a throwaway Postgres inside this
# container, checks it, and throws it away.
#
#   docker compose ... run --rm -e AGE_IDENTITY="$(cat key.txt)" backup restore-drill.sh [backup file name]
#
# AGE_IDENTITY is the private key (AGE-SECRET-KEY-1...): bring it for the drill,
# never store it on the server.
set -eu
# shellcheck disable=SC3040  # Alpine's ash (BusyBox) has pipefail
set -o pipefail

: "${AGE_IDENTITY:?give the private key: -e AGE_IDENTITY=...}" "${BACKUP_BUCKET:?}"
name="${1:-$(rclone lsf "backup:${BACKUP_BUCKET}/db" | sort | tail -n 1)}"
[ -n "${name}" ] || { echo "no backups found" >&2; exit 1; }
echo "restoring ${name}"

work=$(mktemp -d)
printf '%s\n' "${AGE_IDENTITY}" > "${work}/key"
chmod 600 "${work}/key"
rclone cat "backup:${BACKUP_BUCKET}/db/${name}" | age -d -i "${work}/key" > "${work}/db.dump"
rm "${work}/key"

data="${work}/pgdata"
mkdir -p "${data}" && chown postgres "${data}" "${work}"
su-exec postgres initdb -D "${data}" -U postgres --auth=trust >/dev/null
su-exec postgres pg_ctl -D "${data}" -o "-k ${work} -c listen_addresses=''" -w start >/dev/null
export PGHOST="${work}" PGUSER=postgres
unset PGPASSWORD PGDATABASE

# The roles the dump refers to (passwords are set by bootstrap_db.py in a real restore).
psql -q -v ON_ERROR_STOP=1 <<SQL
CREATE ROLE billing_owner LOGIN;
CREATE ROLE billing_app NOLOGIN NOBYPASSRLS;
CREATE ROLE billing_app_login LOGIN IN ROLE billing_app;
CREATE DATABASE billing OWNER billing_owner;
SQL
pg_restore --dbname=billing --exit-on-error "${work}/db.dump"

psql -d billing -At -v ON_ERROR_STOP=1 <<'SQL'
SELECT 'migrations ' || count(*) FROM django_migrations;
SELECT 'users ' || count(*) FROM users;
SET row_security = off;
SELECT 'tenants ' || count(*) FROM tenants;
SELECT 'documents ' || count(*) FROM documents;
SELECT 'audit rows ' || count(*) FROM audit_log;
SELECT 'tables with RLS forced ' || count(*) FROM pg_class WHERE relforcerowsecurity;
SQL

su-exec postgres pg_ctl -D "${data}" -m fast stop >/dev/null
rm -rf "${work}"
echo "RESTORE DRILL OK: ${name}"
