#!/bin/sh
# Disaster recovery: restore a backup into the production database.
# Refuses unless the database is empty, so it can never overwrite live data.
# The full procedure (new server, roles first, files, start) is in
# docs/03-operations.md, "Disaster recovery".
#
#   docker compose ... run --rm -e AGE_IDENTITY="$(cat key.txt)" backup restore.sh [backup file name]
set -eu
# shellcheck disable=SC3040  # Alpine's ash (BusyBox) has pipefail
set -o pipefail

: "${AGE_IDENTITY:?give the private key: -e AGE_IDENTITY=...}" "${BACKUP_BUCKET:?}" "${PGDATABASE:?}"
name="${1:-$(rclone lsf "backup:${BACKUP_BUCKET}/db" | sort | tail -n 1)}"
[ -n "${name}" ] || { echo "no backups found" >&2; exit 1; }

tables=$(psql -At -c "SELECT count(*) FROM pg_tables WHERE schemaname = 'public'")
if [ "${tables}" != "0" ]; then
  echo "database ${PGDATABASE} is not empty (${tables} tables): refusing to restore over it" >&2
  exit 1
fi
for role in billing_owner billing_app; do
  exists=$(psql -At -c "SELECT count(*) FROM pg_roles WHERE rolname = '${role}'")
  [ "${exists}" = "1" ] || { echo "role ${role} missing: run bootstrap_db.py first" >&2; exit 1; }
done

echo "restoring ${name} into ${PGDATABASE}"
work=$(mktemp -d)
printf '%s\n' "${AGE_IDENTITY}" > "${work}/key"
chmod 600 "${work}/key"
rclone cat "backup:${BACKUP_BUCKET}/db/${name}" | age -d -i "${work}/key" > "${work}/db.dump"
rm "${work}/key"
pg_restore --dbname="${PGDATABASE}" --exit-on-error "${work}/db.dump"
rm -rf "${work}"
psql -At -c "SELECT 'restored: ' || count(*) || ' migrations' FROM django_migrations"
echo "RESTORE OK: ${name}. Next: copy the files back, run the migrate job, start the stack."
