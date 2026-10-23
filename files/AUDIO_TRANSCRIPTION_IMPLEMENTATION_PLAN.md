# Audio Transcription Feature Plan

## Summary
Goal: add audio upload support to the existing score-analysis app with this path:

`audio -> Basic Pitch -> MIDI -> Music21 normalize -> MusicXML -> existing analysis -> existing summary/UI`

Design rule: keep one shared downstream pipeline. Source-specific logic ends once canonical MusicXML exists.

V1 defaults:
- Accept `mp3`, `wav`, `m4a`
- Best-effort transcription for all audio
- UI warns that clean solo recordings are most reliable
- Stage-by-stage progress is required
- OCR/text extraction is skipped for audio

## Phase 1: Backend Foundation
Purpose: make the backend source-aware without changing the current PDF/image behavior.

### Deliverables
- Add `source_type` to the score model with values: `pdf`, `image`, `audio`
- Expose `source_type` in serializer/detail API responses
- Keep existing upload and score-detail routes unchanged
- Unify upload validation rules across backend/frontend targets:
  - supported score files remain supported
  - add audio MIME/extension support for `mp3`, `wav`, `m4a`
  - align one file-size limit across the stack
- Update upload handling so source type is derived once and persisted
- Skip text extraction for audio and write a placeholder in results data:
  - `text_content.status = "not_applicable"`

### API / Type changes
- Score response adds `source_type`
- Task status payload should support structured progress info later:
  - `stage`
  - `message`
  - optional `progress_percent`

### Acceptance
- Existing PDF/image uploads still validate and queue correctly
- Audio uploads are accepted and stored as `source_type=audio`
- Audio uploads do not attempt OCR/text extraction

## Phase 2: Audio Transcription Pipeline
Purpose: create the new audio-only path that produces MusicXML and MIDI artifacts compatible with the existing app.

### Deliverables
- Add backend dependency support for Basic Pitch and required audio decoding/runtime packages
- Add a dedicated audio transcription module responsible for:
  - loading temp audio input
  - validating readable audio
  - running Basic Pitch
  - saving raw MIDI
  - parsing MIDI with Music21
  - applying normalization/quantization for downstream analysis
  - writing canonical `output.xml`
  - writing final MIDI artifact in the existing temp artifact layout
- Refactor Celery processing into source-aware branching:
  - `pdf/image -> Audiveris -> MusicXML`
  - `audio -> Basic Pitch -> MIDI -> Music21 normalize -> MusicXML`
  - then both paths call shared Music21 analysis
- Keep artifact-serving endpoints unchanged:
  - `/api/serve-musicxml/<id>/`
  - `/api/serve-midi/<id>/`

### Non-goals
- No new public endpoint for audio-only transcription
- No separate audio analysis UI path
- No permanent artifact persistence change in v1

### Acceptance
- Audio job produces MusicXML at the same path the frontend already uses
- Audio job produces MIDI at the same path the frontend already uses
- Shared `analyze_with_music21(...)` runs on the audio-derived score
- Existing PDF/image worker path still works unchanged

## Phase 3: Progress, Errors, and Summary Compatibility
Purpose: make long-running audio jobs understandable and keep the summary pipeline safe.

### Deliverables
- Add Celery stage reporting via task state updates with stable stages:
  - `VALIDATING`
  - `TRANSCRIBING_AUDIO`
  - `NORMALIZING_MIDI`
  - `GENERATING_MUSICXML`
  - `ANALYZING_SCORE`
  - `COMPLETED`
  - `FAILED`
- Standardize failure categories:
  - upload validation failure
  - audio decode/transcription failure
  - MIDI-to-MusicXML conversion failure
  - music21 analysis failure
- Update summary generation to tolerate missing OCR text:
  - if `text_content.status == "not_applicable"`, generate music-only summary
  - do not include cleaned-text prompt section for audio
- Ensure result JSON shape remains compatible with the current frontend renderers

### Acceptance
- Polling clients can read stage + message from task info
- Audio failures surface specific error categories instead of generic processing errors
- Summary generation succeeds for audio-derived scores
- Existing summary behavior for PDF/image remains intact

## Phase 4: Frontend Upload and Progress UX
Purpose: add audio support to the current upload flow without splitting the product experience.

### Deliverables
- Extend the existing analysis upload component to accept:
  - PDF/image formats already supported
  - `mp3`, `wav`, `m4a`
- Update upload copy to reflect mixed-source support and audio caveats
- Add audio-aware client validation matching backend rules
- Update frontend score/task types to include:
  - `source_type`
  - structured task progress info
- Show stage-by-stage progress in the analysis flow using task status info
- Tailor messages by source type:
  - upload success copy
  - `transcribing audio` progress copy
  - audio-specific failure guidance
- Reuse the existing post-processing views unchanged:
  - analysis results
  - MusicXML viewer
  - MIDI player
  - summary display

### UX defaults
- One upload area for all supported source types
- Best-effort warning for audio appears before upload or in helper copy
- No separate audio page in v1

### Acceptance
- User can drag/drop or select audio files from the main upload area
- Audio jobs show stage-by-stage status
- Completed audio jobs render in the same results tabs as current uploads
- Existing PDF/image UX remains functional

## Phase 5: Verification and Regression Pass
Purpose: prove the feature works end-to-end and does not break the existing app.

### Backend test cases
- Valid `mp3`, `wav`, `m4a` uploads are accepted
- Unsupported audio formats are rejected
- Oversize files are rejected consistently
- Audio uploads skip OCR/text extraction
- Audio jobs produce MIDI + MusicXML artifacts in expected temp paths
- Audio jobs save analysis results and mark processed correctly
- Summary generation works for audio scores without OCR text
- Stage transitions appear in expected order
- Existing PDF/image processing still passes

### Frontend test cases
- Upload area accepts audio files and rejects unsupported ones
- Stage-by-stage progress renders during audio processing
- Audio completion loads analysis, MusicXML, MIDI, and summary views
- Clear source-aware error messages appear for audio failures
- Existing PDF/image upload flow still behaves correctly

## Implementation Notes
- Preferred doc location: `nota_db/files/AUDIO_TRANSCRIPTION_IMPLEMENTATION_PLAN.md`
- Keep route shapes stable; extend payloads instead of replacing them
- Keep downstream analysis shared; do not fork result rendering by source
- Treat MusicXML as the normalization boundary for all ingest types
- Minimize new persisted fields beyond `source_type` unless implementation proves another field is necessary

## Assumptions
- V1 supports broad audio input on a best-effort basis
- Quality parity with PDF/image is not guaranteed
- Temp artifact retention remains unchanged in v1
- Frontend and backend will use one aligned max file size
- The implementation may add dependency/runtime changes to the backend container for audio decoding and Basic Pitch
