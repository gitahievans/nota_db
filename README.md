# Nota DB

Nota DB is a Django REST API for cataloguing sheet music and turning uploaded scores into structured musical analysis. It uses Audiveris for optical music recognition (OMR), music21 for analysis and MIDI generation, and Celery for background processing. An optional Gemini integration explains the results in language suitable for music theory beginners.

This repository contains the backend; a frontend is not included.

## Features

- Catalogue scores with a title, composer, year, lyrics, and categories.
- Upload PDFs or images, with image preprocessing to improve recognition.
- Convert sheet music into MusicXML and generate MIDI when possible.
- Analyze keys, time signatures, parts, chords, accidentals, articulations, dynamics, and score structure.
- Extract embedded PDF text or run Tesseract OCR on supported images.
- Track processing through score details and Celery task status.
- Generate an educational summary and clean extracted text using Gemini.
- Manage scores and categories through Django admin.

## How processing works

1. A client uploads a score to `/api/upload/` with `analyze=true`.
2. Django saves the input under `/tmp/nota/<score_id>/`, preprocesses images, and attempts text extraction.
3. A Celery worker runs Audiveris to produce compressed MusicXML, then extracts XML and runs music21 analysis.
4. Analysis results and output URLs are saved in PostgreSQL. Clients can poll the score endpoint and fetch MusicXML or MIDI.
5. A separate summary request sends the analysis and extracted text to Gemini.

The web service and worker must share `/tmp/nota`. The supplied Compose files configure this volume. Cleanup is scheduled one hour after processing reaches the cleanup step; generated download URLs can return `404` after cleanup even though the database record remains.

## Technology

| Component | Repository configuration |
| --- | --- |
| Application | Python 3.13 container, Django 5.2.1, Django REST Framework 3.16.0 |
| Database | PostgreSQL 16 |
| Background jobs | Celery 5.5.2 with Redis 7 as broker and result backend |
| Recognition | Audiveris 5.6.3, Java 21, Gradle 8.7 |
| Analysis | music21 9.1.0 |
| Image and text processing | OpenCV, Pillow, Tesseract, pdfplumber, PyPDF2 |
| Optional summaries | Gemini (`gemini-2.5-flash` in the current implementation) |
| Deployment | Docker Compose, Gunicorn, WhiteNoise, optional Caddy |

## Local development

Docker Compose is the most direct setup because the processing code expects Audiveris and Gradle at fixed Linux paths. Install Docker with Compose v2 and allow enough memory for Java processing: the code requests roughly 1–2.5 GB of Java heap per job, in addition to the other services.

### 1. Configure the environment

Create a `.env` file in the repository root:

```dotenv
SECRET_KEY=replace-with-a-random-development-secret
DEBUG=1
DB_NAME=nota_db
DB_USER=postgres
DB_PASSWORD=replace-with-a-local-database-password
DB_HOST=db
DB_PORT=5432
AUDIVERIS_IMAGE=nota-db-audiveris:5.6.3

# Optional: required only for summary generation
GEMINI_API_KEY=
```

`.env` is ignored by Git. The `postgres` user matches the database health check in the supplied Compose files. Compose creates a database named `nota_db`, so keep `DB_NAME` aligned with it.

### 2. Build the Audiveris base image

```bash
docker build -f Dockerfile.audiveris -t nota-db-audiveris:5.6.3 .
```

This downloads and builds Audiveris, Java, and Gradle, so the first build can take some time. Alternatively, set `AUDIVERIS_IMAGE` to an accessible, compatible prebuilt image containing `/app/audiveris` and `/opt/gradle-8.7`. The Compose files otherwise default to a project-specific registry; the Dockerfile has a placeholder registry default.

### 3. Build and start the development services

```bash
docker compose -f docker-compose.dev.yml build web
docker compose -f docker-compose.dev.yml up -d
docker compose -f docker-compose.dev.yml logs -f web celery
```

The development web entrypoint runs `makemigrations` and `migrate`, then starts Django with automatic reload. Source files are mounted into both application services.

- API: <http://localhost:8000/api/files/>
- Admin: <http://localhost:8000/admin/>

Create an admin account:

```bash
docker compose -f docker-compose.dev.yml exec web python manage.py createsuperuser
```

Verify the API responds:

```bash
curl http://localhost:8000/api/files/
```

An empty database returns `[]`.

## API reference

All paths below are relative to `http://localhost:8000`. The current API views do not configure authentication or permission restrictions; account for that before exposing the service publicly.

| Method | Endpoint | Purpose |
| --- | --- | --- |
| `GET` | `/api/files/` | List scores, newest first; no pagination configured |
| `POST` | `/api/upload/` | Create a score, optionally upload and analyze a file |
| `GET` | `/api/scores/<id>/` | Retrieve a score and optional task status |
| `PUT` | `/api/update/<id>/` | Update score metadata; include required fields |
| `GET` | `/api/categories/` | List categories |
| `GET` | `/api/serve-musicxml/<id>/` | Stream generated MusicXML while it exists |
| `GET` | `/api/serve-midi/<id>/` | Stream generated MIDI while it exists |
| `POST` | `/api/generate-summary/` | Generate a summary for a processed score |
| `GET` | `/api/download/<id>/download` | Legacy PDF download route; currently broken (see limitations) |

### Upload and analyze a score

```bash
curl -X POST http://localhost:8000/api/upload/ \
  -F 'title=Example score' \
  -F 'composer=Anonymous' \
  -F 'year=2026' \
  -F 'analyze=true' \
  -F 'file=@/path/to/score.pdf;type=application/pdf'
```

Accepted upload MIME types are PDF, JPEG, PNG, TIFF, and WebP, with a **10 MiB** limit enforced by the serializer. Use PDF, JPEG, PNG, or TIFF for the most complete processing path; WebP is accepted at upload but is not supported by the text extractor. Clear scans around 300 DPI improve recognition.

An example response (`201 Created`):

```json
{
  "status": "success",
  "score_id": 1,
  "task_id": "<celery-task-id>",
  "message": "PDF uploaded and processing started"
}
```

`analyze` defaults to the string `"false"`. Set it to the string `"true"` to request processing; analysis requires a file. With analysis enabled, the original is kept in temporary storage and the model's `file` field is cleared. File uploads without analysis use the model's S3-compatible storage instead and require storage credentials.

To create metadata without a file, or to set nested categories, use JSON:

```bash
curl -X POST http://localhost:8000/api/upload/ \
  -H 'Content-Type: application/json' \
  -d '{"title":"Example score","composer":"Anonymous","categories":[{"name":"Choral"}],"analyze":"false"}'
```

### Check results and download outputs

Substitute the returned score and task IDs:

```bash
curl 'http://localhost:8000/api/scores/1/?task_id=<celery-task-id>'
curl http://localhost:8000/api/serve-musicxml/1/ -o score.musicxml
curl http://localhost:8000/api/serve-midi/1/ -o score.mid
```

The detail response contains `score` and `task_status`. The score includes `results`, `processed`, `musicxml_url`, and `midi_url`. Without the `task_id` query parameter, `task_status` is `null`.

Check `score.processed` and the analysis contents as well as the Celery state: task completion alone does not guarantee valid musical analysis. MIDI generation can fail independently of an otherwise processed score.

### Generate a summary

Configure `GEMINI_API_KEY`, then request a summary after processing succeeds:

```bash
curl -X POST http://localhost:8000/api/generate-summary/ \
  -H 'Content-Type: application/json' \
  -d '{"score_id":1}'
```

The response contains `status`, `score_id`, and `summary`, plus `cleaned_text` when returned by the model. The summary is saved on the record but is not included in the current score serializer. This request calls Gemini synchronously and sends score metadata, analysis, and extracted text to that service.

## Configuration details

| Setting | Behavior |
| --- | --- |
| `SECRET_KEY` | Django secret; replace the development fallback for deployments |
| `DEBUG` | Accepts `true`, `1`, or `yes`; development Compose forces `1` |
| `DB_NAME`, `DB_USER`, `DB_PASSWORD`, `DB_HOST`, `DB_PORT` | PostgreSQL connection settings |
| `DATABASE_URL` | Overrides individual database settings only when debug is disabled |
| `ALLOWED_HOSTS` | Comma-separated additions to the built-in production hosts; ignored in debug mode |
| `PRODUCTION_URL` | Adds an HTTP(S) frontend origin to CORS only when debug is disabled |
| `GEMINI_API_KEY` | Enables the summary endpoint |
| `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY` | Credentials for file uploads using the model's S3-compatible storage |
| `AWS_STORAGE_BUCKET_NAME` | Used to construct `MEDIA_URL`; the actual storage bucket is hardcoded in settings |
| `AUDIVERIS_IMAGE` | Compose build argument selecting the Audiveris assets image |

Some settings require code changes rather than environment variables: the Redis URLs are fixed at `redis://redis:6379/0`, the processing directory is `/tmp/nota`, the storage bucket and endpoint are project-specific, and development CORS origins are a fixed list. Review [settings.py](nota_db/settings.py) before adapting the service to another environment. `DJANGO_ENV` is supplied by Compose but is not read by the current settings module.

## Development commands

```bash
# Django system checks
docker compose -f docker-compose.dev.yml exec web python manage.py check

# Apply committed migrations
docker compose -f docker-compose.dev.yml exec web python manage.py migrate

# Run Django's test runner
docker compose -f docker-compose.dev.yml exec web python manage.py test files

# Inspect image quality and write a preprocessed copy beside the input
docker compose -f docker-compose.dev.yml exec web \
  python files/test_image_preprocessing.py /app/images/your-score.png

# Stop the development services, retaining named volumes
docker compose -f docker-compose.dev.yml down
```

`files/tests.py` is currently a placeholder. The image preprocessing script is a manual diagnostic, so the repository does not yet provide automated coverage of the complete upload-to-analysis workflow.

For native Python development, create a fresh Python 3.13 virtual environment and install `requirements.txt`; the checked-in `venv/` is not a portable environment. The requirements file is UTF-16 encoded. Native execution also needs PostgreSQL, Redis, Tesseract, Java, Gradle, and Audiveris, plus adjustments to the fixed container paths and service hostnames.

## Production deployment

[docker-compose.yml](docker-compose.yml) runs Gunicorn on host port `8001`, a Celery worker, PostgreSQL, Redis, and Caddy on port `8080`. The web entrypoint applies migrations and collects static files before starting Gunicorn.

The Caddy service references **`Caddyfile.notadb`, which is not included in this repository**. Supply that file before starting the full production stack, or run the application services behind your own proxy:

```bash
# After configuring .env and building the Audiveris base image
docker compose -f docker-compose.yml build web
docker compose -f docker-compose.yml up -d db redis web celery
```

Use `DEBUG=0`, a unique `SECRET_KEY`, deployment database credentials, and suitable host/origin settings. The current settings also contain a hardcoded OpenAI credential fallback; remove it and rotate any exposed credential before deployment. Review permissions, storage configuration, HTTPS, and cookie settings for your environment: several security settings remain disabled regardless of debug mode.

## Troubleshooting and current limitations

| Symptom | What to check |
| --- | --- |
| Audiveris image cannot be pulled | Build `Dockerfile.audiveris` locally and set `AUDIVERIS_IMAGE` as shown above |
| Upload succeeds but processing remains pending | Inspect worker logs, Redis connectivity, and the shared `/tmp/nota` volume |
| Recognition fails or times out | Use a sharper scan around 300 DPI; inspect worker memory and Audiveris logs. The configured subprocess timeout is 450–600 seconds |
| Output endpoint returns `404` | Processing may not have generated that output, or the scheduled cleanup has removed it |
| Summary returns a configuration error | Set `GEMINI_API_KEY` and recreate the application containers |
| Summary reports missing analysis | Confirm `processed` is true and `results` contains analysis |
| Browser reports CORS errors | Check the fixed development origins or production `PRODUCTION_URL` setting |
| Non-analysis file upload fails | Configure credentials and adapt the hardcoded bucket/endpoint in settings |

Additional implementation limitations:

- The legacy PDF download view references the removed `pdf_file` model field. It needs updating before use.
- Text extraction from scanned/image-only PDFs is not implemented; OMR and text extraction are separate steps.
- `DEFAULT_FILE_STORAGE` references a missing `files.storage` module. The score model separately declares its storage class in `files/models.py`; review both when changing storage configuration.
- Production output URLs and host assumptions should be reviewed when deploying under a different domain.

## Repository layout

```text
nota_db/                    Django settings, routing, WSGI/ASGI, and Celery app
files/
  models.py                 Score and category models, file storage class
  serializers.py            API representation and upload validation
  views.py                  Upload, preprocessing, retrieval, and summary endpoints
  tasks.py                  Background processing and delayed cleanup
  audiveris_processor.py    Audiveris invocation and MusicXML extraction
  music21_analyzer.py        Musical analysis and MIDI generation
  text_extraction.py        PDF text extraction and image OCR
  migrations/               Database schema history
  test_image_preprocessing.py  Manual image diagnostic
images/                     Sample image assets
output/                     Generated XML compatibility copies
Dockerfile                  Application image using prebuilt Audiveris assets
Dockerfile.audiveris        Audiveris base image build
docker-compose.dev.yml      Development stack with source mounts
docker-compose.yml          Production stack
entrypoint.*.sh             Service startup scripts
requirements.txt            Python dependencies
manage.py                   Django management CLI
```
