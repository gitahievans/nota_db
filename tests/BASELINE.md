# Phase 1 baseline evidence

Historical P1 snapshot. Current P2 results and resolved probes:
[P2_EVIDENCE.md](P2_EVIDENCE.md). The three P2 probes below now pass in the
default suite; the five P3-P5 probes remain in the separate defect suite.

Date: 2026-10-23. Application baseline: `6f87a6a` (main).
Status: P1 framework and limited acceptance gate complete; real recognition and
full primary-score musical verification remain explicitly unverified. No application
behavior, migrations, deployment, frontend code, commit, or push changed.

## Executed checks

Host: Windows, Python 3.12.5, isolated `.venv-p1`; Django 5.2.1, music21 9.1.0,
DRF 3.16.0, Celery 5.5.2, NumPy 1.26.4, Pillow 12.1.0.
Installed `tests/requirements.txt`; `pip check` reports no broken requirements.
This is a local baseline, not validation of the production Linux/ML dependency set.
Repeatable commands and boundaries are in [README.md](README.md).

| Command (using `.venv-p1` Python where applicable) | Result |
|---|---|
| `python -m unittest files.reliability.inventory -v` | 3 passed; all five PDF hashes and sizes match |
| `python manage.py test files --settings=tests.settings -v 1` | 20 discovered, 20 passed; zero skips; SQLite test DB created/destroyed |
| `python manage.py test --settings=tests.settings -v 1` | Default discovery also finds and passes the same 20 checks |
| `python manage.py test files.reliability.baseline --settings=tests.settings -v 1` | 8 discovered, 8 ordinary assertion failures; zero errors/skips; exit 1 |
| `python -m tests.integration omr` | UNVERIFIED, exit 2; `/app/audiveris` backend runtime absent |
| `python -m tests.integration audio` | UNVERIFIED, exit 2; Basic Pitch/model backend and reviewed audio absent |
| `python -m pip check` | Passed |
| `python -m compileall -q files/reliability tests` | Passed |
| `git diff --check` | Passed (only Git LF/CRLF notices) |

Passing checks include: fixture inventory; checked symbolic pitch/duration/counts,
pickup/tie positions, part independence, signature spelling, dynamics/articulations,
lyrics, meter/tempo source facts and parser/export sanity; malformed XML reporting;
controlled PDF/image/audio upload dispatch; separate audio task branch; real PDF
task through controlled OMR, analysis, MIDI export, detail and streamed artifacts;
recognition failure staging and cleanup scheduling; missing artifact 404s; local
catalog upload/list without task dispatch; dictionary/JSON-string result compatibility.
Passing orchestration only proves the specific assertions: a completed job is not
thereby musically correct. Tempo errors are logged even in successful task cases.

## Reproduced failures (not passing requirements)

Each row corresponds to an ordinary test in `files/reliability/baseline.py`.
These probes describe desired musical/observable behavior; future phase contract
decisions may refine response assertions without suppressing the underlying defect.

| Probe | Expected reference behavior | Observed current behavior | Owner |
|---|---|---|---|
| `test_P2_recognized_parts_preserved` | Upper/Lower identities survive controlled recognition -> served analysis | Rebuilt as one `Recognized Part` | P2 |
| `test_P2_recognized_expression_preserved` | Written lyric `la` remains in served XML; subsequent spelling assertion also defined | First assertion fails: lyric becomes `None`; spelling assertion not reached | P2 |
| `test_P2_audio_default_uses_canonical_midi` | Default points to canonical MIDI role | Preview URL wins whenever `preview.mid` exists | P2 |
| `test_P3_meter_change_global_location` | 3/4 -> 6/8 at score quarter offset 3, measure 2 | Offset 0; measure assertion not reached | P3 |
| `test_P4B_explicit_numeric_tempo` | Explicit quarter=96 extraction works | Error dictionary: `name 'tempo' is not defined`; BPM assertion not reached | P4B |
| `test_P4C_all_twelve_sonorities` | All 12 alternating quarter-note sonorities covered | Only 10 returned; offsets restart each measure | P4C/P3 |
| `test_P4C_distributed_initial_triad` | Simultaneous E4/G4 above independent C3 yields combined C-major triad | Separate `Minor Third above E` and `C` findings | P4C |
| `test_P5_nested_analysis_error_is_not_unqualified_completion` | Nested component/MIDI failure is qualified in task outcome | `COMPLETED` returned despite nested failure and missing MIDI; row may remain processed | P5 |

No failures were repaired. No expected-failure or skip decorator hides them. Run
both passing and failing suites at each subsequent phase gate.

## Recognition, limitations and infrastructure

All five primary PDFs are present and fingerprinted. They have no MusicXML/image
counterparts or reviewed audio. The manifest records actual visible coverage,
reviewed pages and uncertainty independently of intended filename categories.
Sample 1's first measure/tempo is visually checked and available for the initial
real OMR comparison; complete-score reference counts are not established.
Seven supplemental files (six valid, one malformed) supply checked symbolic inputs
without depending on generated output or production database records.

The direct checked XML boundary distinguishes downstream backend errors from
recognition errors; the actual Audiveris/Basic Pitch boundary has **not** run.
Integration preflight produces structured UNVERIFIED output instead of a test skip
or success. Docker daemon access is unavailable here; no production service was
started or contacted. Java is on PATH but does not substitute for Audiveris assets.
Optional AI packages emit existing import-time deprecation warnings; no AI request
or summary generation was made.

Unverified: full PDF/image recognition fidelity; later pages of samples 2/4;
complete MIDI pitch/onset/duration/tie equivalence; actual image preprocessing/OCR;
real audio transcription; broker/worker delivery/restarts; optional summary calls;
expiry/deletion semantics and catalog survival across actual cleanup. Additional
musical gaps are listed in README.md. These are coverage limits, not passes and
not additional observed failures.

## Handoff

Completed IDs: P1.1-P1.7. Changed paths: `files/tests.py`, `files/reliability/`,
`tests/` (settings, integration runner, requirements, inventory, supplemental XML,
documentation), `.gitignore`, and `BACKEND_RELIABILITY_PLAN.md`. Original user PDFs
were read only and all original hashes match. The plan and five PDFs were already
untracked when work began; they remain uncommitted.

P1 acceptance is limited to the framework and checked supplemental/sample passages:
intended checks are demonstrably discovered, test paths/records are isolated, and
incomplete integration is visible, as the plan permits with partial references.
This does not complete later phase gates. Next action: use the checked passages
for P2's artifact contract/preservation work **only when separately instructed**.
For real integration, provide the backend Linux Audiveris runtime, reviewed XML
counterparts/full expectations for the primary scores, and a short reviewed audio
fixture with Basic Pitch runtime/model assets. Do not treat recognition output as
truth without reviewing it against the PDF or recording.

## P3 follow-up (2026-10-23)

The original evidence above is historical. P3's meter-location defect is now in
the passing suite; four P4/P5 ordinary defects remain. Current exact results and
supported/unsupported coverage: [P3_EVIDENCE.md](P3_EVIDENCE.md). P2 remains VERIFY;
real recognition/audio and full primary-score equivalence are still UNVERIFIED.
