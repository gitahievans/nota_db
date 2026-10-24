# P2 implementation and handoff evidence

Date: 2026-10-23. Status: VERIFY. P2.1-P2.8 implemented and checked at the
symbolic/controlled pipeline boundary. Full phase acceptance remains open for
real short audio and recognition verification. P1 history stays in BASELINE.md.
No P3-P6 repairs, migrations, frontend changes, commits, pushes or deployments.

## Contract and changed behavior

Artifact decision: [ARTIFACTS.md](ARTIFACTS.md). One canonical displayed XML
supplies analysis and default MIDI for PDF, image and audio. PDF/image preserve
Audiveris's notation root rather than reconstructing notes. MXL and served XML
cannot diverge: canonical XML is materialized from the declared compressed root.
Audio alone retains approximate reconstruction, with meter inserted before
measure construction and guessed layout/instrument/context explicitly identified.
Raw preview and original recording remain separate comparison URLs. MIDI export
failure produces null default playback and a structured failure, never raw fallback;
stale/partial canonical MIDI is removed. Inferred SATB roles no longer overwrite
written names. Recognition quality is not equated with downstream success.

Changed application paths: `files/artifacts.py`, `files/tasks.py`,
`files/audiveris_processor.py`, `files/audio_processor.py`, `files/score_cleanup.py`,
`files/music21_analyzer.py`, `files/serializers.py`. Documentation/discovery:
`files/LLM_PROJECT_GUIDE.md`, `files/tests.py`, `files/reliability/baseline.py`,
`files/reliability/orchestration.py`, `files/reliability/preservation.py`,
`tests/README.md`, `tests/BASELINE.md`, `tests/ARTIFACTS.md`, this evidence and the plan.
P1's pre-existing uncommitted files and original PDFs were retained. No fixture
original was modified; each isolated pipeline case checks fixture fingerprints.

## Executed verification

Same Windows/Python 3.12.5 `.venv-p1` and dependency set as P1; no services or
production database were contacted. Commands use `.venv-p1/Scripts/python.exe`.

| Command | Result |
|---|---|
| `manage.py test files --settings=tests.settings -v 1` | 34 discovered, 34 passed, zero skips; exit 0 |
| `manage.py test files.reliability.baseline --settings=tests.settings -v 1` | 5 discovered, 5 ordinary assertion failures, zero errors/skips; exit 1 |
| `-m tests.integration omr` | UNVERIFIED, exit 2: backend Audiveris runtime `/app/audiveris` absent |
| `-m tests.integration audio` | UNVERIFIED, exit 2: Basic Pitch/model/backend and reviewed audio reference absent |
| `-m compileall -q files tests` | Passed |
| `git diff --check` | Passed; existing LF/CRLF notice only |

The three original P2 defect probes now live in `PreservationTests`, imported by
`files/tests.py`. They test written part identity, lyric/spelling preservation and
audio canonical-default selection. Eleven additional P2 checks exercise:
served bytes and canonical analysis input across four reviewed reference passages;
nested compressed roots over stale XML; safe declared-root extraction; controlled
image with two independent voices, triplets and retained repeat notation;
literal MIDI pitches/onsets/durations for independent same pitches, a pickup tie
(single sounding attack), dotted durations, and triplet voices without navigation;
actual audio wrapper/reconstruction with only Basic Pitch inference controlled,
including all four artifact URLs; MIDI failure with raw comparison retained and
stale output removed; 3/4 audio measure boundaries; and separate inferred SATB roles.
MIDI timing tolerance is 0.002 quarter notes. Expectations come from literal checked
MusicXML/arithmetic, not another export of the score under test. Original P1
symbolic checks still independently inspect expression, spelling, parts and context.
XML exact-byte checks are an additional preservation guarantee, not a replacement
for those semantic observations. Controlled inference proves orchestration and
draft construction only, never real transcription accuracy.

Remaining defect suite: P3 global meter locations; P4B numeric tempo (`tempo` import
error); P4C truncation and cross-part sonority; P5 unqualified nested-error
completion. These remain ordinary failures. Existing tempo errors appear in logs
of otherwise passing P2 tasks and were deliberately left for P4B. P2's MIDI status
is explicit even though broader task/component qualification remains P5.

## Acceptance limits and next action

UNVERIFIED: real Audiveris PDF/image output, actual image preprocessing/OCR,
real short-audio transcription, full five primary-score reference equivalence,
worker/broker delivery, optional summary service, full expiry and database deletion.
The five PDFs have no reviewed full XML/image counterparts; short reviewed audio
is absent. Controlled catalog upload/list, optional-summary-compatible results
serialization and existing artifact routes remain covered; real optional AI calls
and catalog survival across cleanup are not claimed.

Repeat notation is preserved in XML, but repeat/ending synchronization is unsupported
pending validation. Percussion and transposing-instrument synchronization and
original-recording alignment are also explicitly unsupported; this phase does not
claim a universal notation-to-playback event map. Basic Pitch's approximation,
quantization/pruning and piano synthesis remain declared limitations. No wholesale
audio-model changes were made. Additional empty/unpitched/context cases remain
for later phase gates. Historical artifacts are not rewritten or deleted.

To close P2 acceptance: run the real recognition commands in the backend runtime
with reviewed primary counterparts/full expectations and a reviewed short audio
reference, then check notation and canonical MIDI against those references.
P3 can use the documented artifact contract for independent work when instructed;
do not change P2 to DONE on the strength of mocked recognition. P6 must address
historical external compatibility copies and complete session/database ownership
cleanup as documented in ARTIFACTS.md.
