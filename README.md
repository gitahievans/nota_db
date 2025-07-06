# NotaDB

NotaDB is a Django-based web application designed for uploading, processing, analyzing, and managing music score files. It leverages Optical Music Recognition (OMR) to convert sheet music (from PDF or image files) into digital formats like MusicXML and MIDI, and utilizes AI to generate insightful summaries of the musical content.

## Features

*   **Multi-Format Score Upload:** Supports PDF, JPG, PNG, and TIFF image files.
*   **Optical Music Recognition (OMR):** Integrates Audiveris for accurate conversion of scores.
*   **Digital Format Conversion:** Outputs MusicXML and MIDI files from processed scores.
*   **Text Extraction:** Extracts lyrical and textual content from sheet music.
*   **AI-Powered Summaries:** Uses Google Gemini to generate descriptive summaries of musical characteristics, key signatures, time signatures, and notable elements.
*   **Asynchronous Processing:** Employs Celery and Redis for background processing of computationally intensive tasks (OMR, AI analysis), ensuring a responsive user experience.
*   **Cloud Storage:** Utilizes Cloudflare R2 for scalable and reliable storage of uploaded and generated files.
*   **RESTful API:** Provides API endpoints for programmatic interaction, file management, and data retrieval.
*   **Image Preprocessing:** Includes advanced image preprocessing steps to enhance OMR accuracy.

## Tech Stack

*   **Backend:** Python, Django, Django REST Framework
*   **Database:** PostgreSQL
*   **Task Queue & Message Broker:** Celery, Redis
*   **OMR Engine:** Audiveris
*   **AI Model:** Google Gemini
*   **Musicology Toolkit:** music21
*   **File Processing:** OpenCV, Pytesseract, PyPDF2, pdfplumber
*   **Containerization:** Docker, Docker Compose
*   **File Storage:** Cloudflare R2 (S3-compatible)
*   **Web Server/Reverse Proxy:** Gunicorn, Caddy (as per `docker-compose.yml`)

## Getting Started

### Prerequisites

*   Docker Engine and Docker Compose installed on your system.
*   Git (for cloning the repository).
*   An environment file (`.env.prod`) to store sensitive credentials and configuration.

### Environment Variables

Create a file named `.env.prod` in the root directory of the project. This file is crucial for the application to run correctly. Populate it with the following variables:

```env
# Django Settings
SECRET_KEY=your_strong_secret_key_here
DEBUG=False # Set to True for development, False for production
ALLOWED_HOSTS=your_domain.com,localhost,127.0.0.1 # Comma-separated list of allowed hosts

# Database Configuration (PostgreSQL)
DB_ENGINE=django.db.backends.postgresql
DB_NAME=nota_db
DB_USER=your_db_user
DB_PASSWORD=your_db_password
DB_HOST=db # Docker service name for the database
DB_PORT=5432

# Celery Configuration (Redis)
CELERY_BROKER_URL=redis://redis:6379/0
CELERY_RESULT_BACKEND=redis://redis:6379/0

# Cloudflare R2 Storage (S3-compatible)
AWS_ACCESS_KEY_ID=your_r2_access_key_id
AWS_SECRET_ACCESS_KEY=your_r2_secret_access_key
AWS_STORAGE_BUCKET_NAME=your_r2_bucket_name
AWS_S3_ENDPOINT_URL=https://your_r2_account_id.r2.cloudflarestorage.com
AWS_S3_REGION_NAME=auto # Or your specific region
AWS_S3_FILE_OVERWRITE=False
DEFAULT_FILE_STORAGE=files.storage.PDFFileStorage # Custom storage backend

# AI Service API Keys
# For Google Gemini (used in GenerateSummaryView)
GOOGLE_GEMINI_API_KEY=your_google_gemini_api_key
# OPENAI_API_KEY=your_openai_api_key # This might be legacy or used in other parts of a larger system.

# Production URL (if applicable for CORS)
# PRODUCTION_URL=https://your_production_domain.com
```

**Important Note on API Keys:**
*   The `GOOGLE_GEMINI_API_KEY` is currently hardcoded in `files/views.py` (look for `genai.configure(api_key="AIzaSy...")`).
*   **It is strongly recommended to modify `files/views.py` to load this key from the `GOOGLE_GEMINI_API_KEY` environment variable.** This improves security and flexibility. For example:
    ```python
    # In files/views.py, instead of:
    # genai.configure(api_key="AIzaSy...")
    # Use:
    # import os
    # genai.configure(api_key=os.environ.get("GOOGLE_GEMINI_API_KEY"))
    ```

### Installation and Running (Docker)

1.  **Clone the repository:**
    ```bash
    git clone <repository-url>
    cd <repository-name>
    ```

2.  **Create and populate `.env.prod`:**
    Copy the template above into `.env.prod` in the project root and fill in your actual credentials and settings.

3.  **Build and run the application using Docker Compose:**
    ```bash
    docker-compose up --build -d
    ```
    The `-d` flag runs the containers in detached mode.

4.  **Accessing the application:**
    *   The application API should be accessible via the Caddy reverse proxy. Based on the `docker-compose.yml`, this would be `http://localhost:8080` and `https://localhost:8443`.
    *   The Django development server (if run directly without Caddy or if Caddy is bypassed) would be on port `8001` (e.g., `http://localhost:8001`).

5.  **To stop the application:**
    ```bash
    docker-compose down
    ```

## API Endpoints

The application provides several API endpoints for interaction. Key endpoints include:

*   `POST /api/files/upload/`: Upload new score files. Include `title`, `composer` (optional), and the `file` itself. Set `analyze=true` in form data to trigger OMR processing.
*   `GET /api/files/`: List all uploaded and processed PDF files.
*   `GET /api/files/<id>/`: Retrieve details of a specific score, including processing status if a `task_id` is provided.
*   `POST /api/files/generate-summary/`: Generate an AI summary for a processed score (requires `score_id`).
*   `GET /api/files/musicxml/<score_id>/`: Serve the generated MusicXML file.
*   `GET /api/files/midi/<score_id>/`: Serve the generated MIDI file.
*   `GET /api/categories/`: List available categories.

Refer to `files/urls.py` for a complete list of URL patterns and `files/views.py` for their implementation details.

## Project Structure

```
.
├── Dockerfile                # Defines the Docker image for the application
├── docker-compose.yml        # Defines services, networks, and volumes for Docker
├── manage.py                 # Django's command-line utility
├── requirements.txt          # Python package dependencies
├── .env.prod.example         # Example environment variables (you should create .env.prod)
├── nota_db/                  # Main Django project directory
│   ├── settings.py           # Django settings
│   ├── urls.py               # Root URL configurations
│   ├── wsgi.py               # WSGI entry point
│   └── celery.py             # Celery application definition
├── files/                    # Django app for file handling and music processing
│   ├── models.py             # Database models (PDFFile, Category)
│   ├── views.py              # API views for file operations and analysis
│   ├── serializers.py        # Data serializers for API responses
│   ├── tasks.py              # Celery tasks for background processing (OMR, etc.)
│   ├── urls.py               # URL configurations for the 'files' app
│   ├── admin.py              # Django admin configurations
│   ├── apps.py               # App configuration
│   ├── text_extraction.py    # Logic for extracting text from files
│   └── storage.py            # Custom file storage backend (e.g., for R2)
├── entrypoint.celery.sh      # Entrypoint script for Celery worker container
├── entrypoint.prod.sh        # Main entrypoint script for production web container
├── entrypoint.web.sh         # Entrypoint script for web service (used by prod)
└── ... (other files and directories)
```

## Contributing

Contributions are welcome! Please feel free to submit pull requests or open issues for bugs, feature requests, or improvements.

(Further details can be added here, e.g., coding standards, development setup without Docker if applicable, running tests.)

## License

This project is currently unlicensed. Consider adding an open-source license like MIT if applicable.

```
