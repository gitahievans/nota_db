# Key-estimation evidence, 2026-10-24

The initial follow-up below is historical. The targeted pitch-class fix in the
final section supersedes its key-estimation restriction; exact octave support
remains unresolved.

## Confirmed local example

Read-only `build_identity` + `key_analysis(converter.parse(path), identity)` on
`output/output_127.xml` reproduces four written three-flat signature records and
`estimate={"status":"unsupported","code":"unknown_sounding_pitch"}` before
this change. `output_39.xml` reproduces the same combination. These are local
recognition outputs, not reviewed references, and neither is confirmed to be the
user's particular score. No persisted application results or records were read
or changed, and recognition was not rerun.

`output_127.xml` SHA-256:
`140f886d10549c7ffb2dd41347613388d022a45b431faa71f343be76246b741d`.
Identity issues are `octave_shift_sounding_unsupported` at `p2:m30`, `p2:m34`,
`p2:m34` (zero-based source order). The XML measure labels are 30 and 34.
Part 3/staff 1 has down/8/number 1 at m30, then down/8/number 1 and up/8/number 2
at m34; there are no octave-shift stop directions. This evidence does not
diagnose recognition quality or prove the directions match the original print.

## Cause and decision

`musical_identity.index_musicxml` records octave-shift directions as unsupported
without tracking spans. Its final safeguard invalidates all pitched sounding
values when octave shifts or doubling transpositions occur. `key_analysis`
correctly blocks a whole-score estimate if any pitched event lacks a sounding
MIDI value. It never reaches music21 analysis in this path. This is independent
of the written signature. The frontend previously followed the unsupported label
with an unconditional sentence claiming an estimate.

Supporting general octave shifts is a separate feature: implement staff/part,
number, direction, size, offset, continue/stop, overlapping and unclosed-span
semantics; compose with instrument transposition; verify the music21 import
pitch basis and downstream harmony/playback contracts against reviewed examples.
The observed repeated/unclosed starts must not be assigned invented boundaries.
Do not use octave invariance as permission to bypass unknown sounding pitches or
claim the remaining notes describe the whole score. Doubling transposition also
remains unsupported. No identity/pitch behavior was changed in this follow-up.

## Implemented backend behavior

Stable broad reason codes remain intact. `unknown_sounding_pitch` now carries
bounded identity `source_codes`; unavailable, failed and absent estimates have
safe messages, with `no_pitched_events` for absence. No raw exception is exposed.
Written signature records remain independent. Ordinary successful estimation,
including concert-pitch instrument transposition, remains unchanged.

## Verification actually run

From the backend root using `.venv-p1/Scripts/python.exe`:

- `manage.py test files.reliability.tonal files.reliability.identity --settings=tests.settings -v 1`: **42 passed**.
- `manage.py test files --settings=tests.settings -v 0`: **164 passed** (159 existing + five new).
- `manage.py test files.reliability.baseline --settings=tests.settings -v 0`: exit 0, **0 tests**, intentionally empty; not extra coverage.

New `UnavailableKeyTests` use checked miniature XML, not recognition output as
musical truth. They reproduce the three-flat octave-shift unsupported path,
assert analysis is not called, retain all pitched events, check doubling reasons,
compare labels and correlation exactly with the unchanged music21 algorithm for
four existing reviewed supplemental references, verify written C / sounding
B-flat for a transposing passage, and cover failure/absence/incomplete identity.
Before and after: the octave-shift example remains unsupported; after: it also
returns the specific source reason and safe explanation.

Tests use standalone settings, temporary artifacts and in-memory SQLite. Existing
injected-failure log traces and dependency deprecation warnings occurred; all
checks exited 0. No application migrations, services, recognition, provider calls,
commits or deployment were used. P2 VERIFY, real recognition/audio, playback and
other phase gates remain unchanged. Frontend checks and wording are recorded in
`../scoreanalyzr/tests/KEY_ESTIMATION_EVIDENCE.md`.


## Targeted octave-invariant key estimation (implemented)

### Installed implementation inspected

The isolated interpreter has **music21 9.1.0**. Inspected local source:

- `music21/analysis/discrete.py`: `KrumhanslSchmuckler.process` flattens the stream,
  excludes unpitched notes, and calls `_likelyKeys`. `_getPitchClassDistribution`
  adds each note's `quarterLength` to each member pitch's `pitchClass` bin.
  Chord members each receive the full chord duration; separate parts add together;
  rests contribute nothing; tied written segments each contribute their duration;
  grace notes contribute zero. Dynamics, octave, simultaneity and exact span
  boundaries are not extra weights. `_getDifference` correlates that histogram
  against the major/minor Krumhansl-Schmuckler profiles. `_bestKeyEnharmonic`
  chooses conventional enharmonics by mode, without consulting octave heights.
- `music21/musicxml/xmlToM21.py`, `MeasureParser.xmlOneSpanner`: octave shifts
  create `Ottava` objects with `transposing=False`; the importer explicitly treats
  encoded MusicXML octaves as sounding octaves. This does not establish the
  correctness of arbitrary recognition output or resolve our identity contract's
  exact pitches. Closed up/8 and down/15 spans and unclosed/repeated up/down
  starts preserve pitch classes in checked miniature XML examples.
- `music21/stream/base.py`, `Stream.toSoundingPitch`: makes a copy, applies
  instrument transposition according to the stream's pitch-basis flag, and calls
  ottava transposition. We retain this exact existing conversion and estimator.
  Independent source-class reconciliation catches skipped or doubled instrument
  transposition instead of trusting those flags universally.

### Eligibility and behavior

`musical_identity` now retains an independent `sounding_pitch_class` observation
for every resolvable pitched event, derived from the explicit XML step/alter plus
current part/staff chromatic transposition, modulo 12. Missing required chromatic
transposition, fractional resulting classes and doubling transposition cannot
supply eligible class metadata. Each octave issue records whether its type and
size establish octave invariance (up/down/continue/stop; 8, 15 or 22; absent size
uses 8). No exact sounding pitch, span boundary or playback mapping is inferred.

Ordinary supported scores use the unchanged conversion, estimator and weighting.
The extra eligibility path is deliberately conservative: complete identity,
nonempty issues consisting exclusively of octave-invariant octave-shift issues,
and known integral classes and nonnegative durations for **every** pitched event.
Other identity issues, including unknown future ones, keep this exception closed.
Older identities without the new independent observations cannot use it.

Before estimation, compare the complete multiset of `(concert pitch class,
quarter-note duration)` members from music21 against the independent source
observations. This includes chord members, all parts and zero-duration grace
members, so missing/duplicated/reweighted content cannot silently disappear into
a partial estimate. Mismatch returns `unsupported/unverified_pitch_class_content`.
Import/conversion/estimation exceptions retain the safe failed result. The check
also avoids changing ordinary scores to accommodate unusual importer semantics.

Permitted results use the existing `status=estimated`, label, method, correlation,
`pitch_space=sounding` and complete pitched `event_ids`. Additive provenance:
`pitch_basis=verified_sounding_pitch_classes`, `exact_octaves=unresolved`,
`source_codes=[octave_shift_sounding_unsupported]` and an explicit limitation.
Written signatures remain independent, including incompatible signatures and
concert-pitch transposing-instrument estimates. The frontend already accepts the
ordinary successful result; no frontend code was changed or required.

### Before and after

- The minimal three-flat/unclosed-shift regression previously returned
  `unsupported/unknown_sounding_pitch`; it now returns a verified-class estimate.
- The reviewed C-major miniature remains C major when moved from octave 4 to
  octaves 3 or 5 or given repeated/unclosed 8/15/22 up/down directions. Its
  correlation is identical. Written C material with -2 chromatic transposition
  estimates B-flat major, with identical correlation to its no-shift control;
  adding octave-change -1 does not change its classes. A transposition change
  between measures is also checked independently.
- Read-only reanalysis of the unchanged `output/output_127.xml` now returns
  **E-flat major** (`E- major` in music21), correlation `0.9440461178439872`, with
  the verified-class provenance. This reproduces the symptom and demonstrates
  the fix on available local output; it is not a reviewed musical truth source.
  Its written three-flat records remain available. Its exact sounding pitches
  remain unsupported and its playback mapping remains unavailable.
- No persisted application result was recomputed or backfilled. Old stored
  responses keep their prior statuses; services were not restarted.

### Verification actually run for this targeted fix

Python `.venv-p1/Scripts/python.exe`, standalone `tests.settings`, in-memory
SQLite and temporary artifacts; no recognition or provider calls:

- `manage.py test files.reliability.tonal files.reliability.identity --settings=tests.settings -v 1`: **51 passed**, exit 0.
- `manage.py test files --settings=tests.settings -v 0`: **173 passed**, exit 0.
- `manage.py test files.reliability.baseline --settings=tests.settings -v 0`: exit 0, intentionally **0 tests**, not additional coverage.

Nine tests added and the previous octave-blocking assertion updated. Coverage
includes actual importer behavior, octave-invariant estimates, independent
histogram arithmetic, chord members/parts/rests/ties/graces, fractional durations,
explicit accidentals, instrument transposition exactly once and changes over
time, unknown/missing/fractional/doubled transposition, nonstandard shift sizes,
unknown issue codes, and imported missing/extra/reweighted/altered pitches.
Existing four ordinary reviewed-reference tests continue comparing labels and
correlations exactly with the previous algorithm. Existing exact pitch, playback,
harmony and signature assertions remain intact.

The initial focused run caught two fixture defects: an undeclared second part
(which the new full-content safeguard correctly rejected) and fractional
transposition that music21 itself rejects at import. The fixtures were corrected
to declare both parts and independently test source eligibility for malformed
input. Final focused and full runs pass. Existing injected failure logs and
third-party dependency warnings occurred as before.

### Still unresolved

No full octave-shift span interpretation, exact octave reconstruction, MIDI
alignment or playback/harmony/interval support was added. Doubling transposition,
unknown pitch classes, unsupported shift sizes and import mismatches stay blocked.
Key estimation remains a whole-written-score profile, not repeat-expanded
performance, local key detection or calibrated confidence. No unrelated phase
or recognition/audio gate is marked complete.
