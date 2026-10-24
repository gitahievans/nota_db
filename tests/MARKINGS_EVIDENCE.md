# Articulation-count follow-up (2026-10-24)

Status: implemented and verified for supported symbolic markings. Existing P1-P6
work and uncommitted changes preserved; no recognition, frontend, preprocessing,
transcription, migration, service restart, deployment, commit or push performed.

## Cause and scope

`get_all_notes()` filters cached recursive elements to `music21.note.Note`.
`music21.chord.Chord` is a separate event; recursion does not descend into its
member notes. The old articulation loop therefore missed chord articulations.
One C/E/G chord with one staccato produced count **0**, flag **false**, chart **0**;
the corrected outputs are **1**, **true**, **1**. No pitch multiplication occurs.

Repository-wide consumer inspection found `get_all_notes()` used only by
`analyze_notable_elements()`. `get_all_elements()` serves that helper and notable
element scans. Both helpers retain their behavior. A dedicated read-only
`_iter_articulations()` handles notes, chords and separately retained members;
pitch-range/ensemble and instrumentation paths are unchanged.

The existing supported types remain Staccato, Accent and Tenuto (including their
existing `isinstance` subclass handling). Counts are integer notation-marking
counts; `has_*` values are booleans derived from counts. Visualization datasets
continue to read those same counts. No API field names or value types change.

## Representation and counting decisions

Checked against installed **music21 9.1.0**, Python **3.12.5**, Windows, including
its `musicxml/xmlToM21.py::MeasureParser.xmlToChord` implementation and small
hand-authored MusicXML passages (not music21-generated expectations):

- A chord-level marking counts once regardless of pitch count.
- Constructed chords can retain distinct member articulation instances. Each
  counts separately, even if another member/chord carries the same type.
- An identical marking object shared by a chord and its members counts once
  within that chord event. A member also encountered through stream traversal
  is excluded as an independent event, regardless of traversal order.
- Separate note/chord events count independently, even when callers reuse the
  same articulation instance. Deduplication is scoped to the musical event.
- XML markings on the first or subsequent chord note nodes are promoted onto
  the parsed Chord; member articulation lists are cleared. Different supported
  types survive. **Repeated markings of the same class within one XML chord
  collapse to one in this parser**, before analysis. We count the surviving
  representation; literal XML multiplicity and member placement cannot be
  recovered here. Supporting those distinctions would require separate source
  extraction and a future contract decision, outside this focused fix.

Legacy accidentals still count pitch alterations on standalone notes, excluding
chord members; they are not printed-sign counts. P4 `accidental_observations`
continues to provide source evidence including chord members. Dynamics still
return sorted unique values and a presence flag; their chart values are **1 per
distinct dynamic value**, not occurrence counts. Neither semantic is redefined.

## Changed files

- `files/music21_analyzer.py`: dedicated articulation traversal, counts and flags.
- `files/reliability/markings.py`: 16 focused regression tests, including one
  isolated pipeline case; literal XML, object/member and traversal checks.
- `files/tests.py`: register the new classes in existing default discovery.
- `tests/ANALYSIS_API.md`, `tests/README.md`, `BACKEND_RELIABILITY_PLAN.md`:
  contract and current verification pointers; historical evidence retained.
- This evidence record.

## Checks actually run

All Django commands use `.\.venv-p1\Scripts\python.exe manage.py test` with
`--settings=tests.settings -v 2`; no application database or live providers.

| Test labels / command | Discovered and result |
|---|---|
| `files.reliability.markings` before implementation | 16 tests; FAILED, 14 failure entries including subtests; chord omission reproduced |
| `files.reliability.markings` after implementation | 16 discovered, 16 passed, exit 0 |
| `files` full reliability suite | **159 discovered, 159 passed**, exit 0; 143 existing plus 16 new |
| `files.reliability.baseline` | 0 discovered, intentionally empty, exit 0 / NO TESTS RAN |
| `git diff --check` | exit 0; existing CRLF normalization notices only |

Coverage includes standalone and chord staccato/accent/tenuto, mixed/unmarked/rest
and empty passages, multiple types per event, one marking on several pitches,
distinct member markings, shared object aliases, duplicate member traversal in
both orders, independent events sharing an articulation instance, counts/flags/
charts, unchanged accidentals and unique dynamics, real file parsing, parser
promotion/collapse, and a controlled pipeline verifying canonical XML bytes,
three pitch identities and MIDI availability. Existing assertions remain intact.
Tests use temporary XML/storage, in-memory SQLite and controlled recognition;
fixture fingerprints and existing P2-P6 checks pass. Ignored transcripts:
`tests/.runtime/markings-{before,focused,full,baseline}.log`.

## Remaining limits and handoff

Fresh analyses receive corrected values; stored historical results are not
rewritten or reprocessed. Consumers may observe higher chord articulation counts,
with unchanged payload shapes. No new articulation types, raw-XML marking counter
or recognition claims are introduced. Canonical XML, identity construction, MIDI
export, partial-success and expiry implementations are unchanged.

The existing deprecated Google generative-AI import warning appears during test
startup; no provider is called. Recognition investigations/reruns are explicitly
deferred and were not performed. P2 remains VERIFY; real recognition/audio,
reviewed full primary-score counterparts, live worker/broker/PostgreSQL/Linux
outage and browser acceptance gates remain UNVERIFIED. Earlier phase results are
historical; these 159 passing tests do not close those runtime gates.
