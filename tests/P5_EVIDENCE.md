# P5 implementation and handoff evidence

Date: 2026-10-23. Status **DONE** for supported backend orchestration, P5.1-P5.9.
P2 remains **VERIFY**; P3 identity/location and P4 key/tempo/harmony contracts are
unchanged. P6 remains TODO. Historical P1-P4 evidence is retained rather than
rewritten as if earlier checks had passed. New API examples, decisions, terminal
mapping, compatibility and frontend-only follow-ups: [PROCESSING_API.md](PROCESSING_API.md).

## Changed paths and behavior

- `files/outcomes.py`: results schema 2, processing schema 1, recursive nested-error
  detection, safe component codes/messages/output names, partial/absent/unsupported
  distinction, source limitation codes, current file-backed capabilities and
  legacy dictionary/JSON-string normalization. `processed` means usable canonical
  notation at terminal completion, independently of analysis/MIDI completeness.
- `files/music21_analyzer.py`: independent exception boundaries for each musical
  analysis, preservation of completed neighbors, parse-stage failure reporting,
  checkpointed MIDI availability, and database text fallback if an optional OCR
  sidecar could not be written. P4 values/reference algorithms are unchanged.
- `files/tasks.py`: persisted progress and terminal outcomes, canonical notation
  checkpoint before analysis, actual audio callback substages, no unqualified
  COMPLETED for nested/optional failures, preservation of useful outputs, safe
  cleanup-dispatch failures, foreign task rejection, terminal redelivery handling
  and conditional writes protecting recorded recovery from late results.
- `files/models.py`, migration `0012_pdffile_analysis_task_id_pdffile_job_stage_and_more.py`:
  internal task ID, state, stage and last-progress timestamp. Empty/null defaults
  leave historical/catalog ownership and content unchanged. Migration applied in
  isolated test databases only; no production database migration or backfill.
- `files/jobs.py`, `nota_db/settings.py`: score-owned polling, persisted terminal
  state independent of Celery result expiry, conservative failed/revoked/incomplete
  terminal recovery, and configurable 3600-second no-progress recovery on reads.
  This timeout is not content retention. Recent queued jobs are not falsely
  declared dead just because Celery says PENDING; foreign IDs are never queried.
- `files/views.py`: pre-dispatch and optional OCR failure recording, dispatch/task
  association, safe detail responses and optional summary limited to usable
  findings/provenance/uncertainty. Summary failures preserve old summary/findings;
  successful retry can clear only its own limitation. No new model call/provider.
- `files/serializers.py`: old result handling preserved; malformed/non-object JSON
  is handled safely, schema version and live capabilities are additive; stale URL
  advertisements disappear when files are missing. Raw preview never replaces
  default canonical playback. Historical outcomes remain readable after file loss.
- `files/reliability/partial.py`, `files/tests.py`, `files/reliability/baseline.py`:
  final nested-error probe moved to passing discovery; 30 additional P5 tests.
  `preservation.py` now supplies an actual canonical file for its selection check
  and asserts stable failure code instead of raw exception text. XML/MIDI musical
  assertions, fixture originals, P3 source IDs and all P4 checks were preserved.
- Docs: plan tracker/P5 checkboxes/handoff, README, ANALYSIS_API, IDENTITY_API,
  PROCESSING_API, this evidence and project-guide P5 addendum.

Existing uncommitted P1-P4 changes were present at task start and preserved.
No frontend file, recognition/reconstruction algorithm, deletion task or retention
policy was changed. Scope remains P5.

## Verification actually run

Python 3.12.5, `.venv-p1/Scripts/python.exe`. Final exits captured with Python
`subprocess.run(capture_output=True)` to avoid PowerShell treating dependency
stderr warnings as command failure. Tests use independent settings, in-memory
SQLite, isolated temporary artifacts/local storage and controlled services.

| Command after interpreter | Actual result |
|---|---|
| `manage.py test files --settings=tests.settings -v 1` | **102 discovered, 102 passed**, zero skips, exit 0 |
| `manage.py test files.reliability.baseline --settings=tests.settings -v 1` | **0 tests**, `NO TESTS RAN`, exit 0; intentionally empty after moving every resolved probe |
| `-m tests.integration omr` | **UNVERIFIED**, exit 2; backend `/app/audiveris` runtime unavailable |
| `-m tests.integration audio` | **UNVERIFIED**, exit 2; no reviewed audio_reference and no Basic Pitch 0.4.0/model/backend/decoder runtime |
| `manage.py makemigrations --check --dry-run --settings=tests.settings` | No changes detected, exit 0 |
| `-m compileall -q files tests` | Passed, exit 0 |
| `git diff --check` | Passed; pre-existing .gitignore line-ending warning only |

Local ignored transcripts: `tests/.runtime/p5-{passing,baseline,omr,audio,migrations,compile}.log`
and `p5-checks.json`. Persistent evidence is this document, not the ignored logs.
Earlier intermediate failures were corrected: missing real MIDI in a serializer
test, a raw exception-message assertion replaced by safe stable code, and two
new test setup mistakes (incorrect import and overlapping recognizer mocks).
No failed requirement was skipped or weakened to make the final gate pass.

The 31 P5 cases cover nested error dictionaries, an independently raised analysis
exception, real analyzer parse failure with preserved XML, invalid XML total
failure, recognition failure, actual audio callback attribution, MIDI failure
without raw fallback, OCR failure/absence/initialization failure, rest-only absent
key/meter, unsupported repeat traversal, cleanup dispatch failure on both success
and failure, persisted dispatch/input preprocessing failures, foreign task IDs and
foreign worker rejection, recent PENDING metadata, stale/interrupted worker
recovery, late result protection, backend FAILURE/REVOKED/incomplete SUCCESS,
terminal metadata/file loss, old dictionary/string/malformed/non-object payloads,
summary failure/previous summary/retry/provenance/missing text/file-loss behavior,
progress-backend outage, and renderable/list legacy field types under individual failures. Earlier P2 preservation, canonical MIDI export, P3
identity/revision and P4 key/tempo/harmony tests still pass. Fixture fingerprints
are checked around every controlled pipeline/API case; originals remain unchanged.

## Limits and next action

Real worker/broker delivery/restarts, PostgreSQL concurrency, live provider summary
quality, browser UX, and OSMD browser join were **not run** in P5. Restart/late-result
checks exercise real persisted Django state with controlled Celery boundaries;
they are not a live process-kill/load test. Recovery happens on detail reads after
a failed/revoked task or a maximum no-progress interval, not by a background sweep.
An hour without a stage update can also mean a slow worker; configure that bound
for operational workloads. P6 must provide background recovery/cleanup and full
analysis-record deletion. No expiry timestamp or expired-vs-unknown claim is added.

All five PDF originals remain present, but independently reviewed full symbolic
counterparts/full expectations remain missing. Reviewed short audio and production
recognition runtime remain missing. No general synchronization claim is added for
repeats/endings, percussion, transposing instruments or original recordings.
P2 VERIFY and P3/P4 uncertainty/unsupported states are unchanged.

Frontend inspection was read-only across types, context, AnalysisResults,
AnalysisDisplay and MidiPlayer. Terminal SUCCESS/FAILURE, legacy tempo strings and
nullable artifact URLs are compatible. Partial messaging, confidence/provenance
labels, structured findings, expiry display once P6 exists, and playback controller
fixes are handoff items, not implemented features. Next implementation phase: P6.
To close P2, supply reviewed fixtures/runtime and run its real acceptance gate.
No commit, push or deployment performed.
