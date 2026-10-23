#!/usr/bin/env bash
set -euo pipefail

APP_DIR="/opt/notadb"
ENV_FILE="${APP_DIR}/secrets/backend.env"
COMPOSE_FILE="${APP_DIR}/compose.prod.yml"

compose=(docker compose --project-name notadb --env-file "${ENV_FILE}" -f "${COMPOSE_FILE}")

"${compose[@]}" config --quiet
"${compose[@]}" pull
"${compose[@]}" up -d --remove-orphans
"${compose[@]}" ps
