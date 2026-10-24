# Backend reliability verification (P1-P6)

Run from the backend repository root. P2 implementation and verification limits:
[P2_EVIDENCE.md](P2_EVIDENCE.md); artifact contract: [ARTIFACTS.md](ARTIFACTS.md).
P3 identity contract/API examples: [IDENTITY_API.md](IDENTITY_API.md); results and
remaining runtime limits: [P3_EVIDENCE.md](P3_EVIDENCE.md).
P4 contracts and checks: [ANALYSIS_API.md](ANALYSIS_API.md), [P4_EVIDENCE.md](P4_EVIDENCE.md).
P5 job/component contract: [PROCESSING_API.md](PROCESSING_API.md); verification and
frontend handoff: [P5_EVIDENCE.md](P5_EVIDENCE.md).
Evidence and historical defects: [BASELINE.md](BASELINE.md). Fixture identities,
SHA-256 fingerprints, counterparts, review scope, and literal expectations:
[fixtures/scores/manifest.json](fixtures/scores/manifest.json).

## Setup and execution

Use Python 3.11 (backend Docker runtime) or 3.12 (this local baseline).
Create a separate environment; do not point tests at production settings:

```powershell
python -m venv .venv-p1
.\.venv-p1\Scripts\python.exe -m pip install -r tests/requirements.txt
```

Dependency installation needs network access once. The core suite needs no
Gemini/OpenAI credentials, model downloads, Java, Tesseract executable, Redis,
Celery worker, PostgreSQL, R2, Docker, or OMR reruns. Existing view imports require
the Python AI/OCR packages even though those services are never called.

```powershell
# Dependency-free fixture inventory (also included in the default suite):
python -m unittest files.reliability.inventory -v

# Passing suite: direct checked XML + controlled pipeline/API + inventory:
.\.venv-p1\Scripts\python.exe manage.py test files --settings=tests.settings -v 2

# Separate known-defect suite: now intentionally empty after all probes resolved; exits 0:
.\.venv-p1\Scripts\python.exe manage.py test files.reliability.baseline --settings=tests.settings -v 2

# Installed OSMD 1.9.0 model join (read-only frontend dependencies, local Chrome):
.\.venv-p1\Scripts\python.exe -m tests.osmd_identity

# Real integration preflights/runs; exit 2 = UNVERIFIED, 1 = FAIL, 0 = PASS within stated coverage:
.\.venv-p1\Scripts\python.exe -m tests.integration omr
.\.venv-p1\Scripts\python.exe -m tests.integration audio
```

On Linux use `.venv-p1/bin/python` in place of the Windows interpreter path.
`files/tests.py` imports the passing classes, preserving Django discovery without
turning `files/tests.py` into a conflicting `files/tests/` package. The historical
`files/test_image_preprocessing.py` remains a manual diagnostic, not an OMR accuracy
test. Baseline tests have no skips/expected-failure decorators. Run both suites
at every phase gate; as behavior is fixed, move each satisfied probe into the
passing suite and update evidence. A new baseline pass is a change to review,
not a reason to keep a defect permanently tolerated.

## Three verification layers

1. **Symbolic:** hand-authored MusicXML passages, expected spelling, durations,
   ties, part independence and markings checked directly from XML and arithmetic.
   `MusicAnalysisOptimizer` outputs are checked where a suitable current contract
   exists. Parser/export sanity is explicitly distinguished from the application
   pipeline. No generated `output/*.xml` is accepted as a trusted source.
2. **Controlled pipeline/API:** real Django views, serializer, SQLite test records,
   synchronous task, canonical XML handling, audio-only reconstruction, analyzer, MIDI export, and artifact serving.
   Audiveris, OCR, dispatch, task-state writes and scheduled cleanup are controlled
   boundaries. Failures are injected at recognition and nested-analysis boundaries.
   This demonstrates orchestration, never recognition fidelity or real worker delivery.
3. **Real recognition:** `tests.integration` calls the actual Audiveris or Basic
   Pitch wrapper, without recognition mocks, using temporary input copies. OMR
   currently supports reviewed assertions for Sample 1's first measure and tempo;
   other samples require more reviewed expectations before executable comparisons.
   The backend Linux runtime needs `/app/audiveris`, Java/Gradle and its existing
   build/model assets. First Gradle/model setup may require network. Audio needs
   Basic Pitch 0.4.0, its inference backend/model and audio decoders (backend image
   provides ffmpeg/libsndfile). No reviewed audio is supplied, so it remains
   UNVERIFIED. To enable it, add `audio_reference` to the manifest with `source`,
   `review`, `pitches` and `quarter_durations` for a short monophonic draft; this
   checks draft output only, not raw audio alignment or universal accuracy.

## Fixture review and coverage

All five originals exist as PDFs. No image, MusicXML, or audio counterpart exists.
Page counts/titles and limited visual observations are inventoried; a filename is
not evidence of musical coverage. Sample 1's first measure has checked E4 D4 C4 D4
quarters, 4/4, quarter=80. Full score counts have not been approved. Samples 2 and
4 span multiple pages; only page 1 was visually inspected in this baseline.
Samples 3 and 5 are grand staves; this does not prove named instrumental identities
or changing tempo/meter. Original provenance beyond visible credits is unconfirmed.

Supplemental passages are independent miniature examples, **not transcriptions**
of the PDFs: melody (2 bars, 7 notes/1 rest, quarter=96); rhythm (6/8, pickup,
dotting and tie); parts (simultaneous same-pitch notes with independent durations);
harmony (12 alternating Bb-major/C-major chords and a written signature change);
distributed harmony (E4/G4 dyad above independent C3; no part contains the triad); expression
(spelling, lyric, staccato/tenuto, dynamics, 3/4 to 6/8 at quarter offset 3,
quarter=80 then dotted-quarter=60); malformed XML (parse failure).
Expected overall tonal-key estimates are intentionally not asserted from signatures.

P2 adds a hand-authored inline one-quarter measure with two voices: C4/D4/E4
triplet thirds over an independent C4 quarter, plus repeat notation. The triplets
sum to one quarter; MIDI traversal is checked separately without repeats. It also
checks literal MIDI timing/durations for the checked parts and pickup/tie passages.
P3 adds checked inline transposition, unpitched/empty/absent-context, exact triplet,
repeated/non-numeric label, grand-staff, OSMD ambiguity and response-bound cases.
Repeat/ending playback is explicitly unavailable; real recognition, full primary
references, transposing-instrument MIDI equivalence and reviewed audio remain gaps.
The PDFs visibly include repeats/endings, but no checked symbolic traversal exists.
Add reviewed passages before later phases claim these behaviors are verified.

## Isolation

`tests.settings` is independent; it never imports production settings or `.env`.
It uses an in-memory SQLite database and local-memory cache/broker configuration.
Each API/task case further overrides paths with a fresh temporary directory and
replaces the model field's explicit S3 storage with local filesystem storage.
Integration also overrides `BASE_DIR`, so Audiveris compatibility XML copies stay
in its temporary directory. No test calls the deletion task on fixture paths or
production records. Fixture fingerprints are checked before/after pipeline/API
and integration runs, and originals have recorded hashes checked by inventory.
Temporary test files are removed on teardown; production expiry cannot reach
the repository fixtures. Runtime previews under `tests/.runtime/` are ignored.

Current passing suite: 102 checks. Separate known-defect suite: **zero probes**,
exit 0 and `NO TESTS RAN`, intentionally empty after moving the final P5 nested-error
probe into PartialSuccessTests. No skips or expected failures hide missing work.
P5 adds 31 passing cases (the moved probe plus 30 new checks) covering component,
recognition/parse/MIDI/OCR/summary failures, persisted terminal outcomes, job-ID
association, missing task metadata, worker interruption/late return, safe errors,
cleanup scheduling, optional summary retry, file loss and older result payloads.
P2's serializer selection test now creates a canonical MIDI artifact; its failure
assertion uses a stable code instead of leaking raw exporter exception text.
P2 remains VERIFY. Existing P3/P4 symbolic checks remain in passing discovery.
OSMD's 68-event probe is separate because it needs installed frontend/browser
runtime; it was not rerun in P5. Missing real recognition/audio verification is
UNVERIFIED, never a skipped success. See P5_EVIDENCE for exact command exits.

## P6 lifecycle gate

Current passing suite: **134 checks**, including 32 P6 lifecycle checks. Earlier
counts above record their phase gates. The separate baseline suite remains
intentionally empty (exit 0, no skips). See [P6_EVIDENCE.md](P6_EVIDENCE.md) and
[LIFECYCLE_API.md](LIFECYCLE_API.md) for expiry, ownership, recovery, conservative
migration/exclusions and API examples. P2 remains VERIFY.

P6 tests add actual Windows cross-process OS lock exclusion/death release,
isolated directory/record/join deletion, partial filesystem/database failure and
retry, catalog/category/fixture preservation, expired/unknown route consistency,
terminal and abandoned deadlines, late workers/cleanup/summary races and P5
scheduling/summary compatibility. Celery/broker/provider boundaries remain
controlled: this is not a Linux/PostgreSQL/process-kill integration gate.

Migration 0013 is applied automatically to disposable test databases; no local
application migration was run. Once applied in an application runtime, schedule
`python manage.py cleanup_analyses` every minute or use its `--loop --interval 60`
mode (already configured as a new Compose service). Do not run the production
command using test fixture/catalog roots. Real OMR/audio preflights still report
UNVERIFIED, exit 2. Frontend remains read-only; expiry rendering is deferred.

Recognition-failure follow-up: the current suite has **143 passing checks**,
including nine additional recognition/feedback cases. The earlier 134 count is
the P6 gate. See [RECOGNITION_EVIDENCE.md](RECOGNITION_EVIDENCE.md) for reproduced
Audiveris failures, bounded expiring diagnostics and approved user messaging.

## Articulation-count follow-up (2026-10-24)

Current discovery is **159 tests, all passing** (143 existing plus 16 new).
Focused checks: `.\.venv-p1\Scripts\python.exe manage.py test
files.reliability.markings --settings=tests.settings -v 2` (16 passed).
Full suite and intentionally empty baseline commands above both exited 0.
See [MARKINGS_EVIDENCE.md](MARKINGS_EVIDENCE.md) for cause, exact results,
member/chord counting semantics and music21's repeated-class XML limitation.
Earlier counts record their historical gates. Recognition is deferred; P2 VERIFY
and all remaining real-runtime acceptance limits stay open.
