#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="${ENV_FILE:-$ROOT_DIR/.env.prod}"
export APP_ENV_FILE="$ENV_FILE"
COMPOSE=(docker compose -f "$ROOT_DIR/docker_compose.yml" --env-file "$ENV_FILE")

cd "$ROOT_DIR"
test -f "$ENV_FILE" || { echo "Copiez .env.prod.example vers .env.prod et renseignez les secrets." >&2; exit 1; }

"${COMPOSE[@]}" config --quiet

if "${COMPOSE[@]}" ps --status running --services 2>/dev/null | grep -qx db; then
  ENV_FILE="$ENV_FILE" "$ROOT_DIR/deploy/backup.sh"
fi

"${COMPOSE[@]}" build --pull
"${COMPOSE[@]}" up -d db redis
"${COMPOSE[@]}" up --abort-on-container-exit --exit-code-from release release
"${COMPOSE[@]}" up -d --remove-orphans traefik web worker beat flower

for attempt in $(seq 1 30); do
  if "${COMPOSE[@]}" exec -T web curl -fsS http://127.0.0.1:8000/health/ready/ >/dev/null; then
    "${COMPOSE[@]}" ps
    echo "Déploiement Lyneci terminé. Le trading live reste piloté par FEATURE_TRADING_ENABLED."
    exit 0
  fi
  sleep 5
done

"${COMPOSE[@]}" logs --tail=100 web
echo "Le service web n'est pas devenu prêt dans le délai imparti." >&2
exit 1
