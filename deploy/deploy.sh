#!/bin/sh
# Deploy (or roll back to) one version on the server, from /opt/billing:
#   ./deploy.sh <git sha>
# Pulls the images built by .github/workflows/deploy.yml, runs the migrate job
# (migrations are backwards-compatible: expand -> migrate -> contract), restarts
# the stack and waits until it answers. Rolling back = deploying an older sha.
set -eu

tag="${1:?usage: deploy.sh <git sha>}"
cd "$(dirname "$0")"
registry="${REGISTRY-ghcr.io/aaronpaul2006/}"
export RELEASE="${tag}"
export BACKEND_IMAGE="${registry}billing-backend:${tag}"
export WEB_IMAGE="${registry}billing-web:${tag}"
export BACKUP_IMAGE="${registry}billing-backup:${tag}"
compose="docker compose -f docker-compose.prod.yml --env-file .env"

log() { echo "[deploy $(date -u +%H:%M:%S)] $*"; }

if [ -z "${SKIP_PULL:-}" ]; then
  log "pulling ${tag}"
  ${compose} pull --quiet api caddy backup
fi
log "migrations"
${compose} run --rm migrate
log "starting"
${compose} up -d --no-build --remove-orphans

app_url=$(sed -n 's/^APP_URL=//p' .env | tr -d '"')
for _ in $(seq 1 40); do
  if curl -fsS ${CURL_INSECURE:+-k} -o /dev/null "${app_url}/healthz"; then
    log "up: ${app_url} answers (release ${tag})"
    echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) ${tag}" >> deployed.log
    docker image prune -f --filter "until=168h" > /dev/null
    exit 0
  fi
  sleep 3
done
log "NOT HEALTHY after 2 minutes: check '${compose} logs api caddy'; roll back with ./deploy.sh <previous sha> (see deployed.log)"
exit 1
