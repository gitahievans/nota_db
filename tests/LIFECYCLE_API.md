# P6 temporary analysis lifecycle (schema 1)

P6.1-P6.10 apply only to records explicitly created with internal
`retention_kind=analysis`. Input source type does not establish ownership. New
catalog uploads have `catalog`; migration 0013 gives **every existing row** the
conservative `legacy` default, including earlier analysis uploads. Clients cannot
set ownership, timestamps, deletion intent or task association through serializers.
No existing catalog source, shared category, fixture or historical XML is adopted.
Migration 0012 is a prerequisite and was already applied locally; 0013 must be
applied before running this code. No data backfill or local production migration
was performed for P6.

## Deadline, retries and availability

Normal and failed processing atomically record `terminal_at` and
`expires_at = terminal_at + 3600 seconds`. Preprocessing, input-save and dispatch
failures use the same rule. Upload time is not an expiry deadline. Pending work has
null terminal/deadline timestamps. Summary success/failure, repeated reads,
cleanup retries and task redelivery never extend availability. Reprocessing an
input requires a **new upload/session**, not resetting a terminal row. There is no
retry/reprocessing endpoint that reuses an analysis directory. Celery redelivery
returns the stored terminal state; foreign workers cannot overwrite its outputs.

Upload and serialized detail/list payloads add `lifetime`; existing fields retain
P5 types and terminal SUCCESS/FAILURE semantics. P2 artifacts remain version 1,
P3/P4 components remain schema 1, and results remain schema 2 (legacy schema 1
still readable). No musical algorithm, revision or playback role changes.

Pending upload response selection:

```json
{"score_id":42,"task_id":"associated-job",
 "lifetime":{"schema_version":1,"policy":"temporary_analysis",
   "retention_seconds":3600,"terminal_at":null,"expires_at":null,
   "state":"processing",
   "message":"Temporary results are available for one hour after processing finishes, then deleted."}}
```

Terminal detail selection (UTC ISO timestamps):

```json
{"score":{"id":42,"processed":true,
 "lifetime":{"schema_version":1,"policy":"temporary_analysis",
   "retention_seconds":3600,"terminal_at":"2026-10-23T19:00:00+00:00",
   "expires_at":"2026-10-23T20:00:00+00:00","state":"available",
   "message":"Temporary results are available for one hour after processing finishes, then deleted."}},
 "task_status":{"state":"SUCCESS","info":{"stage":"PARTIAL"}}}
```

Catalog/historical lifetime is `{"schema_version":1,"policy":"catalog",
"expires_at":null}` or policy `legacy`. Null does not promise permanent storage
or establish whether a historical record was an analysis. Older result metadata
remains readable without regenerating files; this does not adopt legacy ownership.

At `now >= expires_at`, content is unavailable even if physical deletion is
delayed. Detail, XML, canonical MIDI, raw preview, source audio, summary, download
and update ID routes all return HTTP **404** with the same JSON for expired and
unknown/deleted IDs:

```json
{"code":"analysis_unavailable_or_expired",
 "error":"This score is unavailable or its temporary analysis has expired."}
```

No tombstones are retained. Unknown IDs are never asserted to have expired.
Expired rows are omitted from lists, including rows retained for deletion retry.
No response claims a deleted score is processed or offers its URLs/results.
Missing individual artifacts on an otherwise live record remain 404 without
changing P5's historical terminal outcome. A response admitted before expiry may
already have delivered bytes; cleanup cannot revoke downloaded files or an open
stream. Races at artifact open return 404 rather than leaking server paths.

Summary/update mutations share the session lock with writers/deletion. Contention
returns **409**, `code=analysis_busy`; retry later. The summary provider call has
a 60-second timeout with SDK retries disabled. If it crosses expiry, its generated
text is discarded and the route returns the unavailable response. It neither
extends the deadline nor recreates a deleted row. Analysis update rejects a new
FileField upload; a new input must use the analysis upload flow. Catalog updates
remain compatible.

## Inventory and deletion safety

All newly owned files live beneath `TEMP_STORAGE_DIR/<id>`: uploaded/preprocessed
input (including source audio), OCR JSON and intermediates, raw preview MIDI,
canonical MIDI, MusicXML/MXL, recognizer workspaces/OMR files and other processor
intermediates. Audiveris workspaces now live inside that directory, so process
death cannot leave its workspace outside the session's deletion root. Normal
workspace context exit still removes it immediately. Raw `basic_pitch_raw.mid`
inside an explicitly owned directory is removed along with everything else.

P2 stopped creating `BASE_DIR/output/output_<id>.xml` compatibility copies and
external raw duplicates. **Historical compatibility copies and old OS temporary
workspaces are excluded**, even when filenames match a current ID. Their ownership
is ambiguous; no pattern sweep or retrospective adoption is performed. No new
analysis-owned external copies exist. Historical cleanup needs a separately
reviewed ownership manifest and explicit user decision before any deletion.

Deletion checks explicit ownership and deadline, acquires a per-session OS lock,
then persists `deletion_pending` before changing files. It removes the directory
before deleting the analysis row, summary/results/job fields and category join
rows. Category records survive. Missing files/directories are successful deletion
steps. Filesystem/database failures keep the row and deletion intent for retry;
APIs still hide it. Repetition converges without recreating a session. An unexpected
FileField storage reference blocks deletion for review instead of risking shared
catalog storage. Directory symlinks/escaped paths and roots overlapping repository
tests, output or application source are refused. No catalog/legacy directory is
deleted merely because its name resembles a session ID.

Task result metadata is best-effort forgotten. Redis result TTL is 3600 seconds,
including during forget outages; socket/connect timeouts are two seconds. This
is not retained analysis content or an expiry marker. Fixed striped lock files
under `.locks/` are shared infrastructure with no score IDs/content; they are not
session artifacts. Never unlink/replace that directory while services run.

## Recovery and deployment requirements

`python manage.py cleanup_analyses` runs a broker-independent sweep once;
`--loop --interval 60` repeats every minute. All three Compose configurations now
include an independent `analysis-cleanup` service using the same `nota_tmp` volume
as web and workers and a database dependency. No service was started or deployed.
For other deployments schedule the once command at least once per minute. Run
migrations before starting it; the loop retries database outages rather than
exiting permanently. It streams IDs in batches of 200 and isolates per-row errors.

The sweep recovers explicitly owned jobs with no progress for 3600 seconds only
when no live writer holds their lock, records a conservative P5 terminal outcome,
and starts their one-hour retention at recovery. Recent jobs remain protected.
Polling follows the same lock protection; missing broker metadata alone never
terminalizes a live writer. Processing tasks have a 3540-second soft limit and
3600-second hard limit; after process death the OS releases the lock. Stage/task
conditional writes reject late/stale outcomes. Old cleanup tasks check current
ownership/deadline and, for new associated jobs, the expected task ID. Contending
workers retry after ten seconds (up to 360 retries); terminal redelivery does not
run recognition again. Busy cleanup is retried by the next independent sweep.
Filesystem OSErrors also receive up to eight Celery exponential retries.

With services/storage available, a dead job is recovered within the no-progress
bound plus a sweep interval, then retained for one hour. A terminal session's
files/row normally disappear on its scheduled cleanup or the next sweep. Logical
availability always ends at the recorded deadline; **physical deletion cannot be
guaranteed during database/storage/service outages**. It resumes once those
dependencies return. A sweep takes processing time in addition to its interval;
backlogs are not a hard 60-second wall-clock SLA. Permission failures/unsafe
ownership need operator repair; retry does not bypass those protections.

Locks require one shared local filesystem supporting OS advisory locks across
web, worker and cleaner. The supplied Compose volume meets the intended topology;
separate host-local volumes/NFS without working locks are not supported. Windows
process exclusion/crash release is tested locally; actual Linux container,
PostgreSQL and Celery/Redis crash/restart delivery remain runtime-UNVERIFIED.

Frontend inspection was read-only: context polling still uses SUCCESS/FAILURE,
legacy tempo remains a string, and URL names/types are unchanged. Future frontend
work must render `lifetime.message`/deadline, handle 404/409 and stop presenting
cached results after expiry. No frontend notice, browser UX or playback fix is
claimed here. Evidence: [P6_EVIDENCE.md](P6_EVIDENCE.md).
