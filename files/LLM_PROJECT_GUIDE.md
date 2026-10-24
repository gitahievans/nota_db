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
- `music21_analyzer.py`: parses canonical `output.xml`, creates analysis JSON, writes default MIDI
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
2. PDF/image: run Audiveris and preserve its declared MusicXML root; audio: run Basic Pitch and reconstruct an explicitly approximate draft
3. Materialize canonical `output.xml`; analyze this served file and export MIDI from a separate parse/deep copy
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
- retain session-owned MXL/XML under `/tmp/nota/<id>/`; no new compatibility XML copies in `output/`

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


## P2 artifact contract (2026-10-23)

`results.artifacts` version 1 declares ownership, lineage, notation quality, paths
relative to `TEMP_STORAGE_DIR/<analysis_id>`, canonical SHA-256, and playback limits.
Recognized XML and displayed XML share `output.xml`; audio draft notation and
displayed XML also share this location. Default MIDI `<id>.mid` always derives
from that file. `playback_midi_url` now selects canonical MIDI for audio too.
`raw_preview_midi_url` is an additive, separately labelled audio comparison URL;
`source_audio_url` still serves the original recording. `preview.mid` contains the
raw Basic Pitch transcription; no duplicate `basic_pitch_raw.mid` is created.
On export failure, `midi_url` and default playback are null, `results.playback`
contains status/error, and stale/partial canonical MIDI is removed. Raw preview is
never a fallback. Broader component outcomes/completion semantics remain P5.

OMR `score_cleanup.applied` is false; recognition quality remains unverified.
Audio staves, synthesis instrument, meter/tempo context are inferred choices,
not written facts from a recording. Pitch-based SATB suggestions live separately
in `inferred_part_roles`; written part names are preserved. No universal playback
synchronization is promised; repeat/ending, percussion, transposing-instrument
synchronization and recording alignment are unsupported pending validation.
See `tests/P2_EVIDENCE.md` and `tests/ARTIFACTS.md` for evidence and ownership.

## P3 musical identity contract (2026-10-23)

`results.musical_identity` schema 1 indexes exact canonical XML with deterministic
part/measure/direct-note ordinals scoped to its SHA-256 artifact revision. Positions
are rational quarter-note strings; measure labels remain separate from identity.
Written pitches, chromatic/octave sounding transposition, independent voices/staves,
chord members, tie links and anchored context are explicit. Analytical legacy
findings have revision-scoped spans in `analysis_references`. Grand-staff music21
PartStaff streams map back to the source XML part and staff.

Linear tie occurrences are symbolic; repeats/endings/jumps and ambiguous OSMD joins
report unavailable/unsupported. No universal MIDI or original-audio synchronization
is promised. Bounds fail explicitly without partial identity arrays. Missing
context is not replaced by guessed key/meter/tempo in the new index. Legacy tempo,
key and full harmony corrections remain P4; component completion remains P5.
See `tests/IDENTITY_API.md` for the exact XML/OSMD 1.9.0 join, scope, bounds and API
examples; `tests/P3_EVIDENCE.md` for actual checks and remaining runtime gaps. P2
remains VERIFY. Frontend inspection was read-only; no selection/playhead feature
or migration was introduced.


## P4 key, tempo and harmony (2026-10-23)

P4 is implemented using P3 revision-scoped references. This supersedes the P3
handoff's deferred P4 statements above. `key_analysis` separates written signatures
(and scoped changes) from a whole-score Krumhansl-Schmuckler estimate; correlation
is not calibrated confidence. Legacy `key` explicitly labels an estimate. Audio
notation's key/tempo context is inferred draft metadata, not recording facts.
`accidental_observations` includes chord members and distinguishes XML signs from
pitch alteration; older notable-element counts are not printed-symbol counts.

Legacy `tempo` is a display string for AnalysisResults' direct React child.
`tempo_analysis` retains units/dots/numbers, normalized quarter BPM, marking IDs,
locations, conflicts and separate lexical text suggestions/export default.
`harmony` reports complete simultaneous sounding collections with event members,
spans, observed spelling and tentative triad/seventh root/bass/inversion. Legacy
`chords` retains string `pitch`/numeric `offset`, now combined across parts and
uncapped within explicit resource bounds. No harmonic-function/progression engine
or repeat expansion is implied. Summary prompts preserve these distinctions.

API examples and frontend wording/transport follow-ups: `tests/ANALYSIS_API.md`.
Checks, runtime gaps and next action: `tests/P4_EVIDENCE.md`. P2 remains VERIFY;
P5/P6 remain unimplemented. No frontend changes or deployment were performed.

### P5 reliability addendum (2026-10-23)

P5.1-P5.9 completed for the supported backend orchestration contract. New results
schema 2 adds component outcomes without changing P2 artifact version 1, P3
identity/location schema 1 or P4 tonal semantics. `processed` means usable notation;
consult component outcomes and live capabilities for analyses/default MIDI.
Persisted task association/terminal metadata make polling safe across missing
Celery results; foreign task IDs are ignored. Optional failures preserve valid
outputs and never become musical values or expose server exception paths.

See `tests/PROCESSING_API.md` and `tests/P5_EVIDENCE.md` for exact behavior,
compatibility, migration 0012, controlled checks and frontend-only handoff.
102 passing checks; known-defect suite intentionally empty after moving the final
nested-error probe into passing discovery. Recognition/audio/runtime/browser
limits remain explicit; P2 VERIFY, P6 TODO. No frontend changes or deployment.

### P6 reliability addendum (2026-10-23)

P6.1-P6.10 implement explicitly owned ephemeral analysis sessions. Migration 0013
adds conservative legacy ownership defaults, terminal/deadline timestamps and
deletion intent; it performs no historical adoption or data deletion. Availability
ends one hour after terminal processing. Complete directory/row/join deletion is
idempotent, retains retry intent on failure and protects shared catalog/categories.
Audiveris workspaces are now within the session root. Historical external copies
and unowned rows remain excluded; never sweep fixtures or output filename patterns.

`cleanup_analyses` supplies broker-independent recovery and cleanup, with a
one-minute loop service in Compose. OS locks on the shared artifact volume protect
upload, processing, summary and deletion. Workers have a one-hour hard bound;
terminal redelivery/summary never extend the session. No tombstones: deleted and
unknown IDs share honest unavailable-or-expired 404 responses. Lifetime metadata
is additive; musical results and P5 partial/terminal types are unchanged.

Contract, examples, runtime/topology requirements and exclusions:
`tests/LIFECYCLE_API.md`. Verification/handoff: `tests/P6_EVIDENCE.md`. Apply 0013
before startup; it was tested only in isolated test databases. Linux worker/broker,
PostgreSQL outage delivery, real recognition/audio and browser UX remain unverified.
P2 stays VERIFY. Frontend remains read-only; no commit, push or deployment.
