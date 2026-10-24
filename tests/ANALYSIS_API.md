# P4 analysis API (additive component schema 1)

P4 uses the unchanged [P3 identity contract](IDENTITY_API.md). Resolve references
only against `results.musical_identity` with the same `artifact_revision` (SHA-256
of canonical served XML) and schema version. Times in structured components are
rational quarter-note strings; legacy offsets remain numbers. No new endpoints,
migration, backfill, notation rewrite or frontend features are introduced. Older
stored results remain older payloads; absence of a component establishes no facts.
P2 artifact version 1, ownership, lineage, URLs and VERIFY status are unchanged.

## Written signature and estimated tonal key

`key_analysis.signatures` contains literal written values, source marking IDs and
all actual part/staff/measure locations. Missing signatures stay unspecified;
`unspecified_part_ids` lists parts without a signature at the start. Part-wide
signatures apply to every observed staff; `changes` compares written values within
each part/staff, retaining locations and marking references. These are signature
changes, not modulation detections. `signature_conflicts` records incompatible
same-position staff signatures or unknown locations and resets change comparison
there; ambiguous context does not become a chronological change. Nontraditional signatures are explicitly
unsupported for interpretation; their literal indexed fields remain available.
A fifths value alone does not select major/minor. Conflicting parts keep their
separate written facts; no global signature is forced.

`estimate` is separate: whole-score sounding-pitch Krumhansl-Schmuckler analysis
from music21 (including chord members). Its correlation is an algorithm score,
not calibrated confidence. No pitched content produces `absent`; unsupported
pitch-class content or missing identity produces `unsupported`. Exact octave
uncertainty alone can use the verified pitch-class path described below. No local keys, Roman
numerals, functions or modulations are inferred. `signature_origin` labels audio
notation as `inferred_audio_draft`, even if its reconstructed XML contains a key.
Unavailable estimates retain stable `code` values: `unknown_sounding_pitch`,
`identity_unavailable`, `key_estimation_failed`; absent pitched content has
`no_pitched_events`. Safe `message` text is included for these states.
`unknown_sounding_pitch` additionally returns a bounded `source_codes` list from
identity issues, currently `octave_shift_sounding_unsupported` and/or
`double_transposition_unsupported` when present. An empty list establishes no
specific cause. These explanations do not relax exact sounding-pitch safeguards or estimate
from a subset. Successful estimates retain their existing fields and algorithm;
the octave-only path adds provenance as described below.
See [key-estimation evidence](KEY_ESTIMATION_EVIDENCE.md) for the confirmed local
example, isolated regression results and remaining octave-shift feature.

For octave-shift-only identity issues, key estimation can succeed independently
of exact sounding-pitch support. Every pitched event must have an independently
known integral concert pitch class (`musical_identity.events[].sounding_pitch_class`)
and duration. Only standard octave-invariant shift sizes/types are eligible.
The imported concert stream's complete pitch-class/duration multiset must match
those source observations, including chord members and all parts. Instrument
transposition is thus checked exactly once. A mismatch returns
`unsupported/unverified_pitch_class_content`, never a subset estimate. Other
identity issues, unknown/missing class metadata, doubling transposition and
incomplete identity cannot use this exception. Ordinary supported scores keep
the existing algorithm and weights unchanged.

Newly eligible estimates keep the ordinary successful fields and add
`pitch_basis=verified_sounding_pitch_classes`, `exact_octaves=unresolved`,
`source_codes=[octave_shift_sounding_unsupported]` and an explicit limitation.
`pitch_space=sounding` describes concert pitch classes; it does not resolve exact
heights. Exact `sounding_pitch`, playback and harmony limitations remain intact.
Written signatures are independent. No frontend redesign, record backfill,
notation rewrite or MIDI change is required.

Legacy `key` remains a string, e.g. `Estimated tonal key: C major`, or
`Not specified`. It never presents an estimate as an observed signature.

```json
{"schema_version":1,"artifact_revision":"<harmony XML SHA-256>",
 "signatures":[{"marking_id":"mark0","written":{"fifths":"-1"},
   "status":"observed","sources":[{"location":{"part_id":"p0",
   "measure_id":"p0:m0","measure_onset":"0","score_onset":"0"},
   "staff":null,"xml":{"part":0,"measure":0,"child":0}}]}],
 "changes":[{"from_marking_id":"mark0","to_marking_id":"mark2",
   "location":{"part_id":"p0","measure_id":"p0:m2",
   "measure_onset":"0","score_onset":"8"},"staff":"1",
   "interpretation":"written_signature_change_only"}]}
```

These are selected fields, not full response snapshots. The checked harmony
fixture intentionally writes **one flat**, while sounding alternating Bb-major
and C-major triads; do not substitute a presumed Bb-major signature of two flats.

`accidental_observations.observations` enumerates every pitched XML note, including
chord members, with its event ID, `pitch_alter`, literal `accidental` (null if no
XML sign), and accidental attributes such as parentheses/print-object. A pitch
alteration does not establish a printed symbol, nor does an encoded accidental
guarantee the renderer displays it. Written enharmonic spelling stays in P3.
Legacy notable-element accidental counters remain pitch-alteration counts on
standalone music21 notes, not a printed-sign inventory. The new observations are
a complete separate source inventory within P3 bounds.

## Tempo and compatibility

`results.tempo` is now a **display string**: `80 quarter notes/min` or
`Not specified`. This deliberately fixes the current AnalysisResults.getTempo
consumer, which returns successful tempo values directly as a React child.
The full structured response moves to `tempo_analysis`; callers of the former
successful object shape must adopt that field. No new object is passed through
the legacy React-child path. Failed parse responses retain their `.error` path.

`tempo_analysis.tempo_markings` orders actual global onsets, retaining locations,
marking IDs, printed units/dots/per-minute values and normalized quarter-note BPM.
Identical numeric marking/sound-tempo copies at an onset reconcile once across
parts/classes. Conflicting speeds remain separate at `conflicting_positions`;
status is `conflicting`, the ambiguous initial BPM is null, and change comparison
resets there. Unknown positions remain null and report `unsupported_timeline`.
No score position is inferred by division by four. `bpm_changes` compares explicit
numeric values only; duplicate copies do not become chronological changes.
`initial_bpm` is only an unambiguous explicit numeric value at zero. `average_bpm`
is null: no marking-count average is asserted to describe elapsed-time speed.

```json
{"tempo":"80 quarter notes/min",
 "tempo_analysis":{"schema_version":1,"artifact_revision":"<expression XML SHA-256>",
   "initial_bpm":80,"average_bpm":null,
   "tempo_markings":[{"offset":3,"bpm":90,"origin":"explicit_numeric",
     "printed":[{"beat_unit":"quarter","dots":1,"per_minute":"60"}],
     "marking_ids":["mark5"],"locations":[{"part_id":"p0",
       "measure_id":"p0:m1","measure_onset":"0","score_onset":"3"}]}]}}
```

Quarter=80 then dotted-quarter=60 in 6/8 means quarter BPM 80 then **90**, and
the controlled canonical MIDI has those actual speeds at quarter onsets 0 and 3.
The examples select returned fields; clients use actual returned IDs/revisions.
Text-only Allegro stays `bpm=null`, `origin=text_unquantified`; the optional
`interpreted_quarter_bpm` is a separate music21 lexical suggestion (132 here).
It is neither observed speed nor a promise about export. The checked plain-words
Allegro XML exports MIDI at the default 120, not that lexical suggestion.
`playback_default` identifies music21's 120 quarter BPM default, `observed=false`;
`applies_at_start` is null for text/conflicting initial context, true for a known
missing numeric initial context, false for an explicit initial tempo. Actual
export remains distinct; no original-recording speed/alignment is claimed.
Audio `notation_origin` is `inferred_audio_draft`, not an observed recording fact.

## Complete simultaneous sonorities

`harmony` covers the supported written score with `complete=true`, bounded by P3
source/event limits plus **200,000 total output event memberships**. A bound or
unknown timeline/sounding pitch yields explicit `complete=false`, stable code and
no partial sonority list. Unpitched notes are excluded. Unsupported P3 sounding
transposition prevents a complete pitched claim. Grace performance and repeat
unfolding are outside this written-order analysis.

Sweep segmentation uses every positive-duration pitched onset and ending.
Intervals are half-open `[start,end)`; rests-only gaps produce no sonority.
Sustained notes remain active across other onsets, part boundaries do not duplicate
staves, and each independent unison/member retains its own ID. Ties keep source
continuation IDs and written boundaries without asserting new attacks. There is
no merging or filtering of passing tones. Each result is an instantaneous combined
sound over a span, not an inferred underlying harmonic change. Member
`chord_group` identifies written chord grouping separately.

```json
{"schema_version":1,"artifact_revision":"<distributed XML SHA-256>",
 "complete":true,"sonorities":[{"id":"sonority0","start":"0","end":"4",
   "duration":"4","event_ids":["p0:m0:n0","p0:m0:n1","p1:m0:n0"],
   "part_ids":["p0","p1"],"measure_ids":["p0:m0","p1:m0"],
   "sounding_midis":[48.0,64.0,67.0],"bass_midi":48.0,
   "suggestion":{"label":"C-major triad","root":"C","bass":"C3",
     "inversion":0,"status":"suggested"}}]}
```

Full results also include each member's written spelling, sounding pitch,
part/staff/voice, measure, chord group and ties. Root/bass/inversion suggestions
are restricted to complete familiar triads and dominant/diminished sevenths;
other collections, single pitches, octaves/unisons and clusters have null
`suggestion`, with observed collections retained. Even a familiar collection has
only a tentative label, not human-level progression/function certainty. Concert
MIDI pitch collections determine labels after transposition exactly once; original
written spelling remains in members. Labels retain original spelling when the
whole collection is untransposed; transposed label spelling may be normalized by
music21, so it is not an authoritative concert enharmonic engraving.

Legacy `chords` remains a list of objects with string `pitch` and numeric `offset`,
now complete across parts rather than capped at ten per-part results. Unlabelled
collections use `Unlabelled sonority`. It includes `sonority_id`, `event_ids` and
an aggregate span with `part_id=null`; `analysis_references.chords` resolves the
same combined source members. All references share P3's revision; sonority IDs
are only stable inside that component/revision, not across arbitrary edits.

## Read-only frontend handoff and limits

Inspected types.ts, ScoreDataContext, AnalysisResults, AnalysisDisplay and
MidiPlayer read-only. Legacy key/pitch remain strings, offset remains numeric,
artifact URLs stay unchanged, and tempo's successful value is renderable.
No browser UX gate or new frontend features are claimed. The Key Signature heading
still needs wording separating written signatures and estimated key. Structured
changes, accidentals, uncertainty and sonority members require future consumers.
MidiPlayer has its own transport/tempo control; exported MIDI verification does
not validate that player's handling of changing tempos or repeat occurrences.
Optional summary prompts now preserve signature/estimate, sonority/progression,
audio-inference and accidental distinctions. No AI calls are added; live summary
quality is unverified. P5 component outcomes and P6 lifecycle remain separate work.

## P5 orchestration addition

The enclosing results payload now uses schema 2, while every P4 component retains
schema 1 and the musical semantics above. See [PROCESSING_API.md](PROCESSING_API.md)
for component outcomes, partial/failed terminal examples, actual artifact
capabilities, older JSON handling, job association and optional summary behavior.
A failed analysis component no longer discards successful neighboring components
or canonical notation. `processed` means usable notation, not that all analyses
or playback succeeded. No P4 numeric values, references or uncertainty claims
are replaced by the P5 status model.

P6's [lifecycle contract](LIFECYCLE_API.md) now limits new explicitly owned
analysis sessions to one hour after terminal processing. Expired findings and
references are unavailable; no P4 values, units, interpretations or uncertainty
states changed. Historical results are excluded from automatic ownership backfill.

## Articulation-count correction (2026-10-24)

`notable_elements.articulations` retains `staccato`, `accent`, `tenuto`, each with
integer `count` and boolean `has_*`. Counts now include standalone notes and
chords: one marking on a three-pitch chord counts once. Distinct retained member
markings also count; a shared marking object within the chord/member event and
a member visited again by traversal do not count twice. Flags and chart datasets
use the same counts. Existing results are not rewritten.

music21 9.1.0 promotes XML member articulations to chords and collapses repeated
instances of the same class within a chord. Counts reflect that parsed
representation; they cannot recover discarded source multiplicity/placement.
Constructed chords may retain distinct member objects and count them separately.
Legacy standalone-note accidental counts, P4 source accidental observations and
sorted unique dynamic values (chart presence of 1 per value) retain their scope.
See [MARKINGS_EVIDENCE.md](MARKINGS_EVIDENCE.md) for verification and limits.
