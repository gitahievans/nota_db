# syntax=docker/dockerfile:1.7

ARG AUDIVERIS_IMAGE=ghcr.io/example/notadb-audiveris:5.6.3

FROM ${AUDIVERIS_IMAGE} AS audiveris-assets

# Stage 2: Python Dependencies Builder
FROM python:3.13-slim-bookworm AS python-builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# Copy ONLY requirements first - this layer caches unless requirements.txt changes
COPY requirements.txt .

# Install dependencies into a virtualenv we can copy directly into the final image.
RUN --mount=type=cache,target=/root/.cache/pip,sharing=locked \
    python -m venv /opt/venv && \
    /opt/venv/bin/pip install --upgrade pip && \
    /opt/venv/bin/pip install -r requirements.txt

# Stage 3: Final Production Image
FROM python:3.13-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    AUDIVERIS_HOME=/app/audiveris \
    PATH="/opt/venv/bin:/opt/gradle-8.7/bin:/root/.local/bin:$PATH"

WORKDIR /app

# Install Runtime Dependencies
RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
    --mount=type=cache,target=/var/lib/apt/lists,sharing=locked \
    apt-get update && \
    apt-get install -y --no-install-recommends \
    ca-certificates \
    fontconfig fonts-dejavu libfreetype6 \
    tesseract-ocr tesseract-ocr-eng \
    postgresql-client \
    libgl1-mesa-glx \
    libglib2.0-0 \
    libsm6 \
    libxext6 \
    libxrender-dev \
    libgomp1 \
    libfontconfig1 \
    libxcb1 \
    wget && \
# Install Java 21 Runtime (JDK needed for Gradle wrapper)
    mkdir -p /etc/apt/keyrings && \
    wget -q -O /etc/apt/keyrings/adoptium.asc https://packages.adoptium.net/artifactory/api/gpg/key/public && \
    echo "deb [signed-by=/etc/apt/keyrings/adoptium.asc] https://packages.adoptium.net/artifactory/deb bookworm main" | \
    tee /etc/apt/sources.list.d/adoptium.list && \
    apt-get update && \
    apt-get install -y --no-install-recommends temurin-21-jdk && \
    apt-get purge -y wget && \
    apt-get autoremove -y && \
    apt-get clean && rm -rf /var/lib/apt/lists/*

# Copy Gradle (needed for running Audiveris via gradle wrapper/command)
COPY --from=audiveris-assets /opt/gradle-8.7 /opt/gradle-8.7

# Copy Audiveris application and build artifacts/cache
COPY --from=audiveris-assets /app/audiveris /app/audiveris

# Copy the prebuilt Python environment
COPY --from=python-builder /opt/venv /opt/venv

# Copy Application Code LAST (so code changes don't invalidate dependency layers)
COPY . .

# Set permissions
RUN chmod +x entrypoint.web.sh entrypoint.celery.sh entrypoint.prod.sh && \
    mkdir -p /processing/input /processing/output && \
    chmod -R 755 /processing/input /processing/output

ENTRYPOINT ["/app/entrypoint.web.sh"]
