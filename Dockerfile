# Use an official Python runtime
FROM python:3.13-slim

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# Set work directory
WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --upgrade pip && pip install -r requirements.txt

# Copy project files
COPY . .

# Collect static files
RUN python manage.py collectstatic --noinput

# Create input and output directories and set permissions
RUN mkdir -p /processing/input /processing/output

# Make entrypoint scripts executable
RUN chmod +x /app/entrypoint.web.sh /app/entrypoint.celery.sh /app/entrypoint.prod.sh

# Run the Django server (optional for dev; overridden by docker-compose.yml)
CMD ["python", "manage.py", "runserver", "0.0.0.0:8000"]