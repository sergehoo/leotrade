#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="${ENV_FILE:-$ROOT_DIR/.env.prod}"
export APP_ENV_FILE="$ENV_FILE"
BACKUP_DIR="${BACKUP_DIR:-$ROOT_DIR/backups}"
RETENTION_DAYS="${BACKUP_RETENTION_DAYS:-14}"

cd "$ROOT_DIR"
test -f "$ENV_FILE" || { echo "Fichier de configuration introuvable: $ENV_FILE" >&2; exit 1; }
mkdir -p "$BACKUP_DIR"

COMPOSE=(docker compose -f "$ROOT_DIR/docker_compose.yml" --env-file "$ENV_FILE")

timestamp="$(date -u +%Y%m%dT%H%M%SZ)"
destination="$BACKUP_DIR/leotrade-$timestamp.dump"

"${COMPOSE[@]}" exec -T leotrade-db \
  sh -c 'pg_dump --format=custom --no-owner --no-privileges -U "$POSTGRES_USER" "$POSTGRES_DB"' \
  > "$destination"

test -s "$destination" || { rm -f "$destination"; echo "Sauvegarde vide." >&2; exit 1; }
find "$BACKUP_DIR" -type f -name 'leotrade-*.dump' -mtime "+$RETENTION_DAYS" -delete
echo "$destination"
