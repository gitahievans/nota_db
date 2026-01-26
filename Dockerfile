# Stage 1: Audiveris Builder
FROM python:3.13-slim-bookworm as audiveris-builder

# Install build dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    git wget unzip java-common \
    && rm -rf /var/lib/apt/lists/*

# Install Java 21 (Temurin)
RUN mkdir -p /etc/apt/keyrings && \
    wget -q -O /etc/apt/keyrings/adoptium.asc https://packages.adoptium.net/artifactory/api/gpg/key/public && \
    echo "deb [signed-by=/etc/apt/keyrings/adoptium.asc] https://packages.adoptium.net/artifactory/deb bookworm main" | \
    tee /etc/apt/sources.list.d/adoptium.list && \
    apt-get update && \
    apt-get install -y --no-install-recommends temurin-21-jdk

# Install Gradle 8.7
RUN wget -q https://services.gradle.org/distributions/gradle-8.7-bin.zip -O /tmp/gradle.zip && \
    unzip -d /opt /tmp/gradle.zip && \
    rm /tmp/gradle.zip
ENV PATH="/opt/gradle-8.7/bin:${PATH}"

# Clone and build Audiveris
WORKDIR /app
RUN git clone https://github.com/Audiveris/audiveris.git && \
    cd audiveris && \
    git checkout 5.6.3

WORKDIR /app/audiveris
# Build and run help to populate Gradle cache
RUN ./gradlew clean build --no-daemon && \
    ./gradlew run --args="-help" --no-daemon

# Stage 2: Python Dependencies Builder
FROM python:3.13-bookworm as python-builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# Copy ONLY requirements first - this layer caches unless requirements.txt changes
COPY requirements.txt .

# Build wheels for all dependencies - much faster to install later
RUN pip install --upgrade pip && \
    pip wheel --no-cache-dir --no-deps --wheel-dir /app/wheels -r requirements.txt

# Stage 3: Final Production Image
FROM python:3.13-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    AUDIVERIS_HOME=/app/audiveris \
    PATH="/opt/gradle-8.7/bin:/root/.local/bin:$PATH"

WORKDIR /app

# Install Runtime Dependencies
RUN apt-get update && \
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
COPY --from=audiveris-builder /opt/gradle-8.7 /opt/gradle-8.7

# Copy Audiveris application and build artifacts/cache
COPY --from=audiveris-builder /app/audiveris /app/audiveris
COPY --from=audiveris-builder /root/.gradle /root/.gradle

# Install Python packages from pre-built wheels (MUCH faster)
COPY --from=python-builder /app/wheels /wheels
RUN pip install --no-cache /wheels/* && rm -rf /wheels

# Copy Application Code LAST (so code changes don't invalidate dependency layers)
COPY . .

# Set permissions
RUN chmod +x entrypoint.web.sh entrypoint.celery.sh entrypoint.prod.sh && \
    mkdir -p /processing/input /processing/output && \
    chmod -R 755 /processing/input /processing/output

ENTRYPOINT ["/app/entrypoint.web.sh"]