#!/bin/bash
set -e

echo "Starting collectstatic..."
python manage.py collectstatic --noinput

echo "Starting migrations..."
python manage.py migrate --noinput

echo "Starting gunicorn..."
exec gunicorn nota_db.wsgi:application --bind 0.0.0.0:8000 --workers 9