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

RUN python manage.py collectstatic --noinput


# *****************
# Create a non-root user 'celeryuser'
RUN addgroup --system celerygroup && adduser --system --ingroup celerygroup celeryuser

# Give ownership of the app folder to celeryuser
RUN chown -R celeryuser:celerygroup /app

# Switch to celeryuser
USER celeryuser
# *****************

# Run the Django server (optional for dev)
CMD ["python", "manage.py", "runserver", "0.0.0.0:8000"]

RUN chmod +x /app/entrypoint.prod.sh

# Set entrypoint
ENTRYPOINT ["/app/entrypoint.prod.sh"]