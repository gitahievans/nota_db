# Base Python image
FROM python:3.13-slim-bookworm

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# Set work directory
WORKDIR /app

# Install core system dependencies (frequently updated)
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    git wget unzip zip ca-certificates \
    fontconfig fonts-dejavu libfreetype6 \
    tesseract-ocr tesseract-ocr-eng \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

# Install PostgreSQL client separately for better cache isolation
RUN apt-get update && \
    apt-get install -y --no-install-recommends postgresql-client && \
    apt-get clean && rm -rf /var/lib/apt/lists/*

# Install system dependencies for OpenCV
RUN apt-get update && apt-get install -y \
    libgl1-mesa-glx \
    libglib2.0-0 \
    libsm6 \
    libxext6 \
    libxrender-dev \
    libgomp1 \
    libfontconfig1 \
    libxcb1 \
    && rm -rf /var/lib/apt/lists/*

# Install Java 21 (Temurin)
RUN mkdir -p /etc/apt/keyrings && \
    wget -q -O /etc/apt/keyrings/adoptium.asc https://packages.adoptium.net/artifactory/api/gpg/key/public && \
    echo "deb [signed-by=/etc/apt/keyrings/adoptium.asc] https://packages.adoptium.net/artifactory/deb bookworm main" | \
    tee /etc/apt/sources.list.d/adoptium.list && \
    apt-get update && \
    apt-get install -y --no-install-recommends temurin-21-jdk && \
    java -version && \
    apt-get clean && rm -rf /var/lib/apt/lists/*

# Install Gradle 8.7
RUN wget -q https://services.gradle.org/distributions/gradle-8.7-bin.zip -O /tmp/gradle.zip && \
    unzip -d /opt /tmp/gradle.zip && \
    rm /tmp/gradle.zip
ENV PATH="/opt/gradle-8.7/bin:${PATH}"

# Clone and build Audiveris from official repository (pinned for reproducibility)
WORKDIR /app
RUN git clone https://github.com/Audiveris/audiveris.git && \
    cd audiveris && \
    git checkout 5.6.3
WORKDIR /app/audiveris
RUN ./gradlew clean build --no-daemon && \
    ./gradlew run --args="-help" --no-daemon

ENV AUDIVERIS_HOME=/app/audiveris

# Copy Python requirements early to leverage cache
WORKDIR /app
COPY requirements.txt .
RUN pip install --upgrade pip && pip install -r requirements.txt

# # Explicitly install music21 if not in requirements.txt
# RUN pip install music21

# Install Docker CLI (optional, for debugging)
RUN apt-get update && \
    apt-get install -y --no-install-recommends docker.io && \
    apt-get clean && rm -rf /var/lib/apt/lists/*

# Now copy the rest of the app (after dependencies so they cache better)
COPY . .

# Copy entrypoint scripts and set permissions
COPY entrypoint.web.sh entrypoint.web.sh
COPY entrypoint.celery.sh entrypoint.celery.sh
COPY entrypoint.prod.sh entrypoint.prod.sh
RUN chmod +x entrypoint.web.sh entrypoint.celery.sh entrypoint.prod.sh

# Create processing directories and set permissions
RUN mkdir -p /processing/input /processing/output && \
    chmod -R 755 /processing/input /processing/output

ENTRYPOINT ["/app/entrypoint.web.sh"]