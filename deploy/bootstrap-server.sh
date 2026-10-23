#!/usr/bin/env bash
set -euo pipefail

APP_DIR="/opt/notadb"
ENV_FILE="${APP_DIR}/secrets/backend.env"

install -d -m 0755 "${APP_DIR}" "${APP_DIR}/scripts"
install -d -m 0700 "${APP_DIR}/secrets"

if [[ ! -f "${ENV_FILE}" ]]; then
    db_password="$(openssl rand -hex 32)"
    django_secret="$(openssl rand -hex 48)"

    umask 077
    printf '%s\n' \
        'NOTADB_IMAGE=gitahikamau/nota-api:latest' \
        'DEBUG=0' \
        "SECRET_KEY=${django_secret}" \
        'ALLOWED_HOSTS=api.scorelearn.site,web' \
        'PRODUCTION_URL=https://scorelearn.site' \
        'DB_NAME=nota_db' \
        'DB_USER=nota' \
        "DB_PASSWORD=${db_password}" \
        'DB_HOST=db' \
        'DB_PORT=5432' \
        "DATABASE_URL=postgresql://nota:${db_password}@db:5432/nota_db" \
        'OPENAI_API_KEY=' \
        'GEMINI_API_KEY=' \
        'AWS_ACCESS_KEY_ID=' \
        'AWS_SECRET_ACCESS_KEY=' \
        'AWS_STORAGE_BUCKET_NAME=nota-pdfs' \
        > "${ENV_FILE}"
fi

chmod 0600 "${ENV_FILE}"
chmod 0755 "${APP_DIR}/scripts/release.sh"

install -m 0644 \
    "${APP_DIR}/api.scorelearn.site.nginx" \
    /etc/nginx/sites-available/api.scorelearn.site

echo "Nota DB deployment files installed. TLS vhost is staged but not enabled."
