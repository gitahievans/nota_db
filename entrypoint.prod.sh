#!/bin/bash
set -e

echo "Applying migrations..."
python manage.py migrate --noinput

echo "Collecting static files..."
python manage.py collectstatic --noinput

echo "Starting Gunicorn..."
exec gunicorn nota_db.wsgi:application --bind 0.0.0.0:8000
