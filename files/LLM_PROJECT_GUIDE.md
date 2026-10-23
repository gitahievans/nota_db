# NotaDB LLM Guide

Purpose: fast orientation for LLMs editing this repo. Prefer this file over stale READMEs.

## 1. Repo Map

- `nota_db/`: Django backend
- `scoreanalyzr/`: Next.js frontend

Primary product: upload sheet-music files, run OMR + music analysis, then show results, MusicXML, MIDI, and an AI summary.

There are **2 product flows** sharing one backend model:

- `analysis flow`: upload score for Audiveris/music21 processing
- `catalog flow`: upload/edit score metadata without analysis

## 2. Backend Shape

Root API:

- `nota_db/nota_db/urls.py`
  - mounts `files.urls` at `/api/`

Core app:

- `nota_db/files`

Important files:

- `models.py`: `Category`, `PDFFile`
- `serializers.py`: DRF serializer for list/upload/update/detail
- `views.py`: upload, list, detail, update, MusicXML, MIDI, AI summary
- `tasks.py`: Celery orchestration
- `audiveris_processor.py`: runs Audiveris and extracts MusicXML
- `music21_analyzer.py`: parses `.mxl`, creates analysis JSON, writes MIDI
- `text_extraction.py`: PDF/image text extraction

Infrastructure/config:

- `nota_db/nota_db/settings.py`
  - Postgres
  - Redis/Celery
  - temp storage: `/tmp/nota`
  - S3/R2-backed file storage

## 3. Data Model

### `Category`

- `name`

### `PDFFile`

Despite the name, this model stores both PDFs and images.

Key fields:

- `title`
- `lyrics`
- `file`
- `composer`
- `year`
- `categories`
- `results`
- `processed`
- `musicxml_url`
- `midi_url`
- `summary`

Semantics:

- `results` is a `JSONField`, but code still sometimes stores a JSON string
- `processed=True` means core analysis succeeded enough for the app
- backend currently treats MIDI failure as non-fatal for `processed`
- `summary` is generated later via a separate endpoint

## 4. API Contract

Defined in `nota_db/files/urls.py`:

- `GET /api/files/`
- `POST /api/upload/`
- `GET /api/download/<pk>/download`
- `GET /api/categories/`
- `PUT /api/update/<pk>/`
- `GET /api/scores/<pk>/?task_id=...`
- `GET /api/serve-musicxml/<score_id>/`
- `GET /api/serve-midi/<score_id>/`
- `POST /api/generate-summary/`

Frontend-critical response fields:

- upload response:
  - `status`
  - `score_id`
  - `task_id`
  - `message`
- score detail response:
  - `score`
  - `task_status`
- serialized score fields used by frontend:
  - `id`
  - `title`
  - `lyrics`
  - `composer`
  - `year`
  - `categories`
  - `results`
  - `processed`
  - `musicxml_url`
  - `midi_url`

If these shapes change, update frontend callers too.

## 5. Main Backend Flows

### A. Analysis upload

Entry point:

- `views.py` -> `FileUploadView.post()`

Current behavior:

1. Validate request via `FileSerializer`
2. Read `analyze=true`
3. Create `PDFFile` with `file=None`
4. Save uploaded file to `/tmp/nota/<score_id>/input.<ext>`
5. If image:
   - preprocess image for Audiveris in-request
6. Run `TextExtractor.extract_from_file(...)` **in-request**
7. Save `text_results.json` into temp dir
8. Queue Celery task: `process_score.delay(score.id, file_ext=file_ext)`
9. Return `score_id` and `task_id`

Important: text extraction is synchronous before the task is queued. This increases perceived upload latency.

### B. Worker processing

Entry point:

- `tasks.py` -> `process_score`

Current behavior:

1. Load `/tmp/nota/<id>/input.<ext>`
2. Run `process_with_audiveris(...)`
3. Run `analyze_with_music21(...)`
4. Save `results`
5. Set `processed`
6. Schedule temp cleanup after `CLEANUP_DELAY_SECONDS`

### C. MusicXML/MIDI serving

Entries:

- `ServeMusicXMLView`
- `ServeMIDIView`

These serve files from `/tmp/nota/<score_id>/...`, not from permanent object storage.

Important: temp cleanup runs after 1 hour by default, so old analysis artifacts disappear.

### D. AI summary

Entry:

- `GenerateSummaryView.post()`

Current behavior:

1. Load `PDFFile.results`
2. Parse to dict if stored as string
3. Call Gemini `gemini-2.5-flash`
4. Save `summary`
5. Optionally save cleaned OCR text back into `results["text_content"]["cleaned_text"]`

## 6. Worker / Analysis Internals

### `audiveris_processor.py`

Responsibilities:

- dynamic memory sizing
- concurrent job tracking via Django cache
- temp workspace creation
- build Gradle/Audiveris command
- validate file size
- move generated `.mxl`
- extract `.xml`
- copy XML into `nota_db/output/`

Current notable behavior:

- image-specific Audiveris OCR is enabled:
  - `org.audiveris.omr.text.tesseract.TesseractOCR.useOCR=true`
- timeout is adaptive but still large:
  - minimum `450s`, maximum `600s`

### `music21_analyzer.py`

Responsibilities:

- parse MusicXML/MXL with `music21.converter.parse`
- generate MIDI
- build analysis JSON
- merge earlier text extraction results

Main analysis keys:

- `key`
- `parts`
- `chords`
- `time_signature`
- `notable_elements`
- `score_structure`
- `measures`
- `instrumentation`
- `meter_changes`
- `tempo`
- `text_content`

### `text_extraction.py`

Current behavior:

- PDFs:
  - direct text extraction only
  - image-based PDFs are effectively not OCR'd
- images:
  - OpenCV preprocessing
  - Tesseract OCR
  - heuristic cleanup/classification

This means PDF text extraction is limited unless the PDF already contains embedded text.

## 7. Frontend Shape

Primary routes:

- `/` -> analysis app
- `/notadb` -> catalog/listing view
- `/upload` -> metadata upload form

Important files:

- `src/app/page.tsx`: holds `scoreId`, `taskId`, `isProcessing`
- `src/components/UploadArea.tsx`: analysis upload UI
- `src/contexts/ScoreDataContext.tsx`: polling logic
- `src/components/AnalysisDisplay.tsx`: tabs for results / MusicXML / MIDI / summary
- `src/components/Upload.tsx`: non-analysis upload form
- `src/components/Home.tsx`: catalog list page

## 8. Frontend Flows

### A. Analysis UI

1. User uploads PDF/image in `UploadArea.tsx`
2. Frontend posts:
   - `file`
   - `title=file.name`
   - `composer=Anonymous`
   - `analyze=true`
3. Frontend stores `scoreId` + `taskId`
4. `ScoreDataContext` polls `/api/scores/<id>/?task_id=<task_id>`
5. `AnalysisDisplay` renders:
   - result cards
   - MusicXML viewer
   - MIDI player/download
   - AI summary

### B. Catalog UI

`Home.tsx` fetches `/api/files/` and filters to:

- `!file.processed`
- `file.composer !== "Anonymous"`

Meaning: catalog page is intentionally showing mostly non-analysis records, not analyzed anonymous uploads.

### C. Metadata upload UI

`Upload.tsx` posts with:

- title
- composer
- lyrics
- file
- year
- categories
- `analyze=false`

This is a different use case from the main `/` upload.

## 9. Polling / State Rules

`ScoreDataContext.tsx`:

- polls every 3 seconds while:
  - task state is `PENDING`
  - score is not `processed`
- stops polling on:
  - server errors
  - too many consecutive errors

This context is the single most important frontend file for analysis-status behavior.

## 10. Current Bottlenecks

These are real code-path bottlenecks, not generic guesses:

- synchronous text extraction during upload in `views.py`
- Audiveris OMR itself
- image preprocessing before Audiveris
- MIDI generation during music21 analysis
- full-PDF processing with no page-range support

For large PDFs, end-to-end time is not just Audiveris; the request thread already does non-trivial work before the task starts.

## 11. Known Inconsistencies / Risks

- `PDFFile` name is misleading: model stores PDFs and images
- `results` handling is mixed dict/string
- `PDFDownloadView` looks broken:
  - uses `pdf.pdf_file`
  - model field is `file`
- frontend expects MIDI as a core UX feature
- backend treats MIDI failure as non-fatal for `processed`
- `MusicTheoryContent .tsx` filename includes a trailing space before `.tsx`
- frontend has some mojibake/copy artifacts in strings
- `settings.py` still contains risky defaults and hardcoded-looking fallback secrets/API key values

## 12. Edit Guide

If changing upload behavior:

- backend:
  - `files/views.py`
  - `files/serializers.py`
- frontend:
  - `components/UploadArea.tsx`
  - `components/Upload.tsx`

If changing analysis contents:

- `files/music21_analyzer.py`
- `components/AnalysisResults.tsx`
- `src/lib/types.ts`

If changing processing performance:

- `files/views.py`
- `files/tasks.py`
- `files/audiveris_processor.py`
- `files/text_extraction.py`

If changing status/polling UX:

- `contexts/ScoreDataContext.tsx`
- `components/AnalysisDisplay.tsx`

If changing catalog behavior:

- `components/Home.tsx`
- `components/PDFCard.tsx`
- `components/UpdateForm.tsx`

## 13. LLM Working Rules

Before editing:

1. Decide whether the change affects:
   - analysis flow
   - catalog flow
   - both
2. Verify serializer + response shape first
3. Then verify frontend assumptions
4. Preserve existing API field names unless intentionally updating both sides

Mental model:

- Django = API + persistence + orchestration
- Celery = heavy background work
- Audiveris = OMR conversion
- music21 = structured music analysis
- Next.js = upload, polling, rendering
