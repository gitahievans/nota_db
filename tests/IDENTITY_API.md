# P3 musical identity contract (schema 1)

`results.musical_identity` is additive. It indexes the exact canonical `output.xml`
bytes served by `musicxml_url`; it never rewrites them. P2 artifact version 1,
URLs, lineage, default MIDI selection and VERIFY status are unchanged.
No database migration or historical-result backfill is required. Results without
this field have no established identity mapping.

## Scope, units and absence

A reference is the tuple `(schema_version, artifact_revision, id)`.
`artifact_revision` is SHA-256 of the exact served XML bytes, matching P2's
canonical artifact digest. Clients must reject mismatched revisions before
resolving IDs. Identical bytes produce identical IDs across reparses and requests;
any edit, including formatting, changes revision. IDs are not an edit-tracking API.

IDs use zero-based XML order: `p0`, `p0:m0`, `p0:m0:n0`. Each `<note>` has its own
identity, including every chord member, rest, same-pitch unison and tie continuation.
Original XML IDs are optional metadata, never trusted as unique identities.
Part XML IDs/names are retained; staff and voice are part-scoped strings, defaulting
to MusicXML's staff 1 / voice 1 when omitted. A grand staff remains one XML part
with two staff references, even when music21 splits it into two PartStaff streams.

`score_onset`, `measure_onset`, `duration`, `actual_duration`, `aligned_duration`
and occurrence positions use exact rational **quarter-note units** as JSON strings
(`"0"`, `"1/3"`, `"3/2"`). They are never seconds or MIDI ticks. An OSMD whole-note
timestamp is four times smaller. Legacy offsets remain JSON numbers and now use
global positions. Never derive a measure by dividing an offset by four.

Measure `order` is unique within a part; `label` is the literal XML `number`
(including `"0"`, `"A"`, repeated labels, or null). `actual_duration` is maximum
written extent from notes/forward/backup, not the nominal meter length. Source
measures align across parts by XML ordinal, using the greatest extent at that
ordinal. This handles pickups, 3/4, 6/8, tuplets and changing meters. Non-controlling
measures are explicitly unsupported for playback. A wholly empty aligned measure
has unknown elapsed duration: later global positions become null; local identities
remain available and analysis span mapping reports `unknown_measure_timeline`.
Do not treat that null as zero. No key, meter, tempo or pitch is inserted into
the identity index when missing from XML.

`written_pitch` preserves step, alter and octave. `sounding_pitch.midi` is an
exact rational derived from that pitch plus XML chromatic/octave transposition;
it does not assert MIDI-export equivalence. Rests and unpitched notes have null
pitch. Double transposition and octave-shift sounding pitch report unsupported.
An independent additive event field, `sounding_pitch_class`, contains
`{value: "0".."11", status: "derived_from_written_transpose"}` when the explicit
step/alter and instrument transposition establish an integral concert class.
It may remain available when exact octaves are unsupported. Unknown chromatic
transposition, fractional resulting classes, doubling transposition and
non-octave-invariant shift types/sizes cannot supply this exception. Octave issues
carry `pitch_class_invariant`; this records class invariance, not span resolution.
Only key estimation consumes the new exception; see [ANALYSIS_API](ANALYSIS_API.md).
Exact pitch, playback, harmony and interval safeguards are unchanged.

Grace notes retain written zero-duration identity; performed grace timing is
unsupported. Malformed indexing reports `failed/invalid_source_index` without
discarding P2's artifacts. Empty content reports `absent`, not invented events.

## Findings and written versus playback order

`markings` locates written keys, meters, metronomes, sound tempo, words and dynamics
in the source. Identical kind/value/onset/staff markings across parts are reconciled
into one marking with every part's `sources` retained. Conflicting values remain
separate findings with their actual scopes. P4 interprets these facts separately in `key_analysis`, `tempo_analysis` and
`harmony`; see [ANALYSIS_API.md](ANALYSIS_API.md). Metronome unit/dots remain
literal here; normalized quarter BPM is a separate P4 field.

`analysis_references` binds legacy whole-score estimates/counts to explicit written
spans, legacy chord results to source event IDs and part/staff spans, and written
context to marking IDs. It carries the same revision. Source part matching uses
music21 instrument `partId`; unmatched mappings are explicitly unavailable.
Legacy meter changes carry actual part/measure locations and compare chronologically
within each part before reconciling duplicates. Legacy numeric `measure` labels
remain for compatibility; the index's literal label and ID are authoritative.
P4 removes the legacy chord cap and combines pitched parts into simultaneous
sonorities. A legacy chord span now has `part_id=null` for its combined scope,
with contributing source event IDs; individual members retain part/staff/voice.
The identity index itself remains a notation index, not a harmonic-function engine.

`ties`, `tie_previous`, `tie_next` describe written contiguous ties within the same
part/staff/voice/pitch. Ambiguous or unmatched ties report `unresolved_tie`.
For supported linear notation, `playback.status=linear_written_order` supplies
one occurrence per pitched attack, with tied members collected into `event_ids`.
This is a symbolic traversal; `midi_alignment=unverified` and `seconds=unavailable`.
It makes no universal claim about the exporter, original recording or player.

Repeats, endings, segno/coda and jump instructions report
`navigation=unsupported_repeats_endings_jumps`, `status=unavailable`, and an empty
occurrence list. Written identities/locations still work. A revisited event would
require a distinct occurrence ID; no fabricated occurrence or repeat unfolding is
returned. Unpitched content, unknown measure lengths, unresolved ties and grace
timing likewise prevent a claimed complete playback traversal. P2's MIDI file may
still be available independently; its availability is not proof of synchronization.

## Join to served XML and installed OSMD 1.9.0

First validate the fetched XML digest. Resolve `xml.part`, `xml.measure`, `xml.note`
as zero-based positions in the part/measure/direct-note lists. This is exact even
when labels or original note IDs repeat. Marking `xml.child` addresses a direct
measure child; kind identifies nested content. Several markings in one direction
may intentionally share that source child.

OSMD 1.9.0 has no reliable public source XML note-ID field. Use its **source** model:

1. Match `Sheet.Instruments` in XML part order. Match `SourceMeasure.measureListIndex`
   to XML measure order, never `MeasureNumberXML` (numeric and lossy for labels).
2. Traverse `SourceMeasure.VerticalSourceStaffEntryContainers`, `StaffEntries`,
   `VoiceEntries`, `Notes`. Match `ParentStaff.ParentInstrument`, staff `Id` and
   `ParentVoice.VoiceId`; voice IDs are numeric in this OSMD release.
3. Match `VoiceEntry.Timestamp * 4`, `Note.Length * 4`, rest state, written pitch
   step/accidental/octave. OSMD `Pitch.Octave + 3` is MusicXML octave. Use source
   `Pitch`, not `halfTone` or `TransposedPitch`; the latter can represent transposition.
   Use exact fractions or a small numerical tolerance (the probe uses 1e-8).
4. Require exactly one candidate. Identical same-pitch/duration unisons in one
   voice cannot be distinguished this way; backend IDs remain distinct, but
   `osmd_join.status=ambiguous_or_unsupported`. Grace, unpitched and nonnumeric
   voice IDs are also unsupported by this join. `candidate` means the backend
   key is unique, not that every arbitrary score has been tested in OSMD.

`python -m tests.osmd_identity` runs installed OSMD 1.9.0 in local headless Chrome,
loading canonical fixture bytes and checking a one-to-one join for every written
event. It reads frontend dependencies only and writes no frontend files. Missing
browser/package or launch failure exits 2 (UNVERIFIED); mapping mismatch exits 1.
No rendering, SVG coordinates, frontend feature or MIDI playback is involved.

## Minimum future API selections

These are examples of selections within the returned data, not new endpoints.
The revision below stands for the actual digest from the relevant response.

```json
{"schema_version":1,"artifact_revision":"<rhythm XML SHA-256>",
 "selected_note":{"id":"p0:m1:n0","measure_id":"p0:m1",
   "score_onset":"1/2","measure_onset":"0","duration":"3/2",
   "tie_previous":"p0:m0:n0"},
 "selected_rest":{"id":"p0:m1:n3","score_onset":"3","duration":"1/2"},
 "selected_measure":{"id":"p0:m0","label":"0","order":0,
   "actual_duration":"1/2","score_onset":"0"}}
```

```json
{"artifact_revision":"<distributed XML SHA-256>",
 "simultaneous_harmony_selection":{"start":"0","end":"4",
   "event_ids":["p0:m0:n0","p0:m0:n1","p1:m0:n0"]}}
```

That selection includes independent E4/G4/C3 members. P4 suggests C-major triad
with C3 bass and inversion 0; no harmonic function is encoded into their identities.

```json
{"artifact_revision":"<expression XML SHA-256>",
 "tempo_change_selection":{"kind":"metronome",
   "location":{"part_id":"p0","measure_id":"p0:m1",
     "score_onset":"3","measure_onset":"0"},
   "written_value":"dotted-quarter = 60"}}
```

```json
{"artifact_revision":"<XML with repeat SHA-256>",
 "repeat_occurrence_selection":{"event_id":"p0:m0:n0","occurrence_id":null,
   "status":"unavailable","reason":"unsupported_repeats_endings_jumps"}}
```

## Bounds and compatibility

No pagination in schema 1: complete index up to 16 MiB source XML, 50,000 written
events and 10,000 total per-part measures. Exceeding a bound reports
`unsupported`, `complete=false`, a stable `*_limit` code and limits; it returns
no partial arrays or apparently complete truncated index. These bounds cover
identity extraction, not all legacy music21/recognition work. Index storage and
response size grow with written events/markings and can be tens of MiB at the
limit. Consumers should explicitly opt into processing the new arrays. Extraction
is bounded by input/event counts, uses keyed tie lookup, and caches no mutable
stream objects or process-dependent IDs. A 2,000-event completeness check runs
in the passing suite. Whole-score musical analyses remain independently limited.

Frontend read-only inspection: existing types/context preserve legacy `pitch` and
numeric `offset`; additive fields are not consumed. AnalysisDisplay fetches the
same MusicXML URL and canonical playback URL. MidiPlayer controls its own transport
and does not use the identity index. P4 supplies a renderable string in legacy `tempo`, with full normalized data
in `tempo_analysis`. The existing Key Signature heading still needs frontend
wording work; the legacy key value explicitly labels its estimate. Future overlays, selection state, occurrence
navigation and partial-state wording require frontend work separately.

## P5 status envelope

P3 identities remain schema 1, with the same byte revision, complete index bounds,
locations and supported traversal rules. Enclosing results schema 2 adds
`processing.components.events`; an unsupported playback traversal can yield a
partial event capability while the written identity index stays complete.
Identity extraction failure does not erase usable notation or other analysis.
See [PROCESSING_API.md](PROCESSING_API.md) for outcomes, terminal polling, safe
failures and current file capabilities. No frontend join or P3 mapping changed.

P6 lifetime/deletion is an outer session contract: [LIFECYCLE_API.md](LIFECYCLE_API.md).
After expiry these IDs/revisions/results are unavailable, not regenerated. No
identity format or musical coordinate semantics changed.
