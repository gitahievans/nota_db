#!/bin/bash
set -e

echo "Starting collectstatic..."
python manage.py collectstatic --noinput

echo "Starting migrations..."
python manage.py migrate --noinput

echo "Starting Celery worker..."
celery -A nota_db worker --loglevel=info
# echo "Starting gunicorn..."
# exec gunicorn soundleaf.wsgi:application --bind 0.0.0.0:8000 --workers 9