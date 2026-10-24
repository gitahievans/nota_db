# P6 implementation and handoff evidence

Date: 2026-10-23. Status **DONE for the supported backend lifecycle contract**,
P6.1-P6.10. P2 remains **VERIFY**; P3/P4 musical semantics, source revisions,
artifact roles and P5 partial-success/terminal compatibility remain unchanged.
The earlier phase evidence is historical and preserved. Decisions and API examples:
[LIFECYCLE_API.md](LIFECYCLE_API.md).

## Implementation and ownership boundary

- `files/models.py`, `files/migrations/0013_analysis_lifecycle.py`: explicit
  analysis/catalog/legacy ownership, terminal/deadline timestamps and durable
  deletion intent. 0013 depends on the already locally applied 0012. All prior
  rows default to legacy; no historical adoption, content backfill or deletion.
  Application database migration was **not run**; test databases apply 0013.
- `files/lifecycle.py`: shared-volume OS locks, safe root/ownership checks,
  lifetime schema 1, expired/unknown response gating, file-before-row deletion,
  retry convergence and independent abandoned-job recovery. No tombstone or
  retained content marker. Fixed striped lock files contain no session IDs/data.
- `files/tasks.py`, `files/jobs.py`: atomic terminal timestamps, task/state
  conditional writes, active-writer protection, stale cleanup/task rejection,
  terminal redelivery without reprocessing/retention extension, cleanup retry and
  scheduling-failure compatibility. Worker soft/hard bounds are 3540/3600 seconds.
- `files/views.py`, `files/serializers.py`: explicit ownership at upload, lifetime
  metadata, consistent expired/deleted/unknown ID-route 404s, expired list
  exclusion, analysis no-store responses, summary/update locking and 409 retry
  response, summary deadline recheck and bounded existing provider call. Analysis
  updates cannot put a new source in catalog storage. Catalog upload/update/list
  remain usable; legacy dictionaries/JSON-string results remain readable.
- `files/audiveris_processor.py`: recognition workspaces moved beneath the owned
  session directory; regular context cleanup remains. This closes the interrupted
  recognizer workspace leak without changing recognized MusicXML.
- `files/management/commands/cleanup_analyses.py`, its package initializers,
  `nota_db/settings.py`, `deploy/compose.prod.yml`, `docker-compose.yml`,
  `docker-compose.dev.yml`: broker-independent once/loop recovery, one-minute
  cleaner service, shared artifact volume and database dependency, 3600-second
  result TTL and bounded Redis socket/connect waits. No services started/deployed.
- `files/reliability/lifecycle.py`, `files/tests.py`: 32 new lifecycle checks in
  ordinary passing discovery. Existing P1-P5 tests and defect baseline unchanged.
- Documentation: plan tracker/P6 checkboxes/handoff, tests README, ARTIFACTS,
  IDENTITY_API, ANALYSIS_API, PROCESSING_API, new LIFECYCLE_API, project guide and
  this evidence. Existing uncommitted P1-P5 work was retained. No frontend edits,
  fixture changes, commit, push or deployment.

## Verification actually executed

Interpreter `.venv-p1/Scripts/python.exe`, Python 3.12.5 on Windows. Tests use
standalone settings, disposable SQLite, local storage and isolated artifact
directories. No production database, storage, provider or broker was contacted.

| Command after interpreter | Actual result |
|---|---|
| `manage.py test files --settings=tests.settings -v 1` | **134 tests, 134 passed**, zero skips; exit 0 |
| `manage.py test files.reliability.baseline --settings=tests.settings -v 1` | **0 tests**, intentional `NO TESTS RAN`; exit 0 |
| `-m tests.integration omr` | **UNVERIFIED**, exit 2: backend Audiveris `/app/audiveris` unavailable |
| `-m tests.integration audio` | **UNVERIFIED**, exit 2: no reviewed audio_reference; Basic Pitch/model/backend/decoder dependencies unavailable |
| `manage.py makemigrations --check --dry-run --settings=tests.settings` | No changes detected; exit 0 |
| `-m compileall -q files tests` | Passed; exit 0 |
| PyYAML parse of all three Compose files plus cleaner/web/worker shared-volume and loop assertions | Passed |
| `git diff --check` | Passed; LF/CRLF normalization notices only |

Ignored transcripts: `tests/.runtime/p6-{passing,baseline,omr,audio,migrations,compile}.log`
and `p6-checks.json`. Early checks caught a list UNION ordering incompatibility
with SQLite and a new test helper missing its QUEUED stage; both were corrected.
No requirement/assertion was skipped to pass the suite.

Checks cover terminal/failure/pre-dispatch deadlines; upload ownership resistant
to client overrides; input preprocessing and dispatch failures without scheduled
cleanup; complete input/MIDI/XML/MXL/OCR/workspace/record/join deletion; category
and catalog source/update/list preservation; missing directories; partial rmtree
and database deletion failure followed by successful retry; catalog/legacy and
historical external-copy exclusions; all content/detail/summary/download routes
before/at/after expiry and deletion versus unknown IDs; exact deadline boundary;
list exclusion; active writer and obsolete/newer cleanup protection; independent
stale-job recovery; terminal redelivery without deadline extension; late worker
after deletion; summary crossing expiry without persistence/resurrection;
successful summary without extension; artifact-open race; retry isolation across
sessions; unsafe roots/unexpected catalog references; catalog worker rejection;
cleanup scheduling outage; task-metadata forget and TTL fallback; owned terminal
deadline recovery; and recognition workspace containment.

The OS-lock check launches a **real separate Windows Python process**, acquires
the same shared lock there, verifies parent cleanup reports busy, terminates the
child and verifies cleanup succeeds after OS lock release. This is actual local
process coordination, not a mocked lock. It does not establish Linux container,
Redis/Celery delivery or PostgreSQL concurrency. Other job/provider failures and
races exercise persisted Django state with controlled boundaries. Fixture hashes
are checked before/after every isolated pipeline/API case; all originals survive.
All 102 prior checks continue passing, including P2 canonical XML/MIDI, P3 event
references and P4 literal tempo/key/harmony expectations.

## Runtime limits, migration and next action

Apply migration **0013** before application startup; 0012 is already applied
locally per the user. No local application migration was attempted. Existing
records and historical external compatibility copies/workspaces remain excluded.
Any later historical deletion needs a reviewed ownership manifest and separate
user decision; filename/source type/old timestamps are not sufficient evidence.

Deployments must run `cleanup_analyses --loop --interval 60` (provided Compose
service) or an equivalent minute schedule, using the same filesystem lock/artifact
volume as web/workers. The sweep retries missed scheduling and per-row failures.
One hour is the logical availability deadline, not a guarantee of physical
deletion while database/storage/services are down. Physical cleanup resumes after
recovery; permission/ownership problems need operator repair. Shared locks protect
active writers; worker process death releases them. Unavailable task metadata has
a separate one-hour backend TTL if best-effort forget fails.

**UNVERIFIED:** actual Linux container locks, Celery/Redis hard-kill/restart and
delivery behavior, PostgreSQL concurrency/load, cleaner service startup and outage
recovery in deployed topology, live summary/provider timeout, browser UX and
end-to-end PDF/image/audio upload through real recognition and expiry. Real OMR,
reviewed short audio and full primary-score counterparts remain missing as before.
P3's earlier installed OSMD join was not rerun; P2 VERIFY remains open. No new
claims about repeat/percussion/transposition/recording synchronization are made.

Frontend types, context, AnalysisResults, AnalysisDisplay and MidiPlayer were
inspected read-only. Existing SUCCESS/FAILURE and legacy value/URL types remain
compatible. Displaying lifetime notices, stopping cached results after expiry,
handling 404/409 and improving playback controls remain frontend handoff items.
No notice or browser behavior is claimed implemented.

Next runtime action: after applying 0013 in an authorized backend runtime, start
the cleaner with shared storage and verify an owned PDF/image/audio session through
terminal outcome, deadline and complete deletion, including worker/broker/storage
outage/restart. Close P2 only with reviewed recognition/audio references and its
real acceptance checks. Overall runtime completion gates stay open in the plan.

## Follow-up: local migration applied (2026-10-23)

At the user's explicit request, applied `0013_analysis_lifecycle` through the
running local `nota_db-web-1` container. `python manage.py migrate files 0013
--noinput` exited 0 with `Applying files.0013_analysis_lifecycle... OK`.
`python manage.py showmigrations files --plan` then exited 0 and confirmed
`[X] files.0013_analysis_lifecycle`. Migration 0012 was already applied.
The earlier statements about no application migration describe the initial P6
implementation gate and are superseded locally by this follow-up. No cleanup,
historical backfill, service restart, deployment, commit or push was performed.
