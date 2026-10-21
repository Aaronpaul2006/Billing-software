#!/bin/sh
# Encrypted backups of the database and the uploaded files.
#   backup.sh schedule   every day at BACKUP_HOUR (UTC), forever (the container's job)
#   backup.sh once       one backup now
#
# Database: pg_dump (custom format) | age -r <public key> | rclone rcat: streamed,
# never written unencrypted to disk. Only the holder of the private key can read
# a backup, so a leaked backup bucket leaks nothing.
# Files: the app bucket copied into the backup bucket (copy: nothing is ever
# deleted there), without exports (temporary by design, purged after 7 days).
set -eu
# shellcheck disable=SC3040  # Alpine's ash (BusyBox) has pipefail
set -o pipefail

: "${PGHOST:?}" "${PGUSER:?}" "${PGPASSWORD:?}" "${PGDATABASE:?}" "${AGE_RECIPIENT:?}"
: "${BACKUP_HOUR:=21}" "${KEEP_DAYS:=30}"
# rclone remotes "app" and "backup" come from RCLONE_CONFIG_APP_* / RCLONE_CONFIG_BACKUP_*.
: "${APP_BUCKET:?}" "${BACKUP_BUCKET:?}"

log() { printf '{"time":"%s","level":"%s","logger":"backup","message":"%s"}\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$1" "$2"; }

once() {
  stamp=$(date -u +%Y-%m-%dT%H%M%SZ)
  target="backup:${BACKUP_BUCKET}/db/${PGDATABASE}-${stamp}.dump.age"
  log INFO "database backup started: ${target}"
  pg_dump --format=custom --compress=6 "${PGDATABASE}" | age -r "${AGE_RECIPIENT}" | rclone rcat "${target}"
  size=$(rclone size --json "${target}" | sed -E 's/.*"bytes":([0-9]+).*/\1/')
  log INFO "database backup done: ${size} bytes"

  rclone copy "app:${APP_BUCKET}" "backup:${BACKUP_BUCKET}/files" --exclude "tenants/*/exports/**" --transfers 4
  log INFO "files copied"

  # KEEP_DAYS=0: never delete here (a backup key without delete rights, and a
  # lifecycle rule on the bucket, protect backups even if the server is taken over).
  if [ "${KEEP_DAYS}" -gt 0 ]; then
    rclone delete "backup:${BACKUP_BUCKET}/db" --min-age "${KEEP_DAYS}d"
    log INFO "database backups older than ${KEEP_DAYS} days removed"
  fi

  if [ -n "${BACKUP_PING_URL:-}" ]; then
    wget -q -O /dev/null "${BACKUP_PING_URL}" || log WARNING "ping failed"
  fi
}

case "${1:-schedule}" in
  once)
    once
    ;;
  schedule)
    log INFO "scheduled daily at ${BACKUP_HOUR}:00 UTC"
    last=""
    while true; do
      today=$(date -u +%F)
      if [ "$(date -u +%H)" = "$(printf %02d "${BACKUP_HOUR}")" ] && [ "${last}" != "${today}" ]; then
        if once; then last="${today}"; else log ERROR "backup failed; retrying in 5 minutes"; fi
      fi
      sleep 300
    done
    ;;
  *)
    echo "usage: backup.sh once|schedule" >&2
    exit 2
    ;;
esac
