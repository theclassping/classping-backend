#!/usr/bin/env bash
# Production deploy, run on the VPS from the repo checkout by the
# "Deploy production" GitHub workflow. Follows the update steps in
# PRODUCTION_DEPLOYMENT.md: back up, build, stop app, migrate, restart.
set -euo pipefail

cd "$(dirname "$0")/.."

BACKUP_DIR="${BACKUP_DIR:-$HOME/classping-backups}"
HEALTH_TIMEOUT="${HEALTH_TIMEOUT:-180}"

compose() {
  docker compose --env-file .env.production -f docker-compose.prod.yml "$@"
}

if [ ! -f .env.production ]; then
  echo "ERROR: .env.production is missing in $(pwd)" >&2
  exit 1
fi

echo "==> Validating compose config"
compose config --quiet

echo "==> Starting database and Redis"
compose up -d --wait db redis

echo "==> Backing up database to ${BACKUP_DIR}"
mkdir -p "$BACKUP_DIR"
backup_file="${BACKUP_DIR}/classping-$(date +%Y%m%d-%H%M%S)-$(git rev-parse --short HEAD).sql.gz"
compose exec -T db sh -c 'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB"' | gzip > "$backup_file"
echo "    saved ${backup_file}"

echo "==> Building image"
compose build

echo "==> Stopping web and scheduler"
compose stop web scheduler

echo "==> Running migrations"
if ! compose run --rm release; then
  echo "ERROR: migrations failed. web and scheduler are left stopped." >&2
  echo "       Inspect the logs, recover, then start them manually." >&2
  echo "       Pre-deploy backup: ${backup_file}" >&2
  exit 1
fi

echo "==> Starting web and scheduler"
compose up -d --force-recreate web scheduler

echo "==> Waiting for web to become healthy"
web_container=$(compose ps -q web)
deadline=$((SECONDS + HEALTH_TIMEOUT))
while true; do
  status=$(docker inspect --format '{{.State.Health.Status}}' "$web_container")
  echo "    web: ${status}"
  [ "$status" = "healthy" ] && break
  if [ "$status" = "unhealthy" ] || [ "$SECONDS" -ge "$deadline" ]; then
    echo "ERROR: web did not become healthy" >&2
    compose logs --tail 100 web >&2
    exit 1
  fi
  sleep 5
done

echo "==> Deployed $(git rev-parse --short HEAD)"
