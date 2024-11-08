#!/bin/bash

# Exit on error
set -e

# Run gunicorn with recommended settings
gunicorn nota_db.wsgi:application \
    --bind 0.0.0.0:$PORT \
    --workers $GUNICORN_WORKERS \
    --threads $GUNICORN_THREADS \
    --worker-class=gthread \
    --worker-tmp-dir /dev/shm \
    --timeout 120 \
    --keep-alive 5 \
    --access-logfile - \
    --error-logfile - \
    --log-level info \
    --max-requests 1000 \
    --max-requests-jitter 50