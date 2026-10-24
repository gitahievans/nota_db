# P2 artifact contract

Decided before dependent P2 work: the served `output.xml` is authoritative for
analysis and default synthesized playback. Preserve recognition XML without
re-export/reconstruction. For MXL, use its declared container root (including
nested `.musicxml` members); replace stale extracted XML with that root. Ambiguous
multiple roots, malformed XML, non-partwise/Opus input fail explicitly. Archive
member paths are never extracted onto the filesystem. XML formatting is retained,
although tests judge notation facts separately through parsing.

| Role | Session path | Lineage and API |
|---|---|---|
| Source upload | `input.<ext>` | Original PDF/image/recording; audio uses existing `source_audio_url` |
| Recognized MusicXML | `output.xml` | Audiveris root; aliases canonical displayed XML |
| Recognition archive | `output.mxl` | Audiveris compressed source; retained in session for traceability |
| Audio draft notation | `output.xml` | Approximate reconstruction of raw MIDI; aliases canonical displayed XML |
| Canonical displayed XML | `output.xml` | `musicxml_url`; analysis parses this exact artifact with source cache bypassed |
| Default playback MIDI | `<id>.mid` | `midi_url` and `playback_midi_url`; export from canonical XML, using a deep copy to isolate export mutations |
| Raw preview | `preview.mid` | Audio only; `raw_preview_midi_url`; approximate comparison, no notation synchronization claim |

`results.artifacts` version 1 contains owner analysis ID, relative storage root,
roles/lineage, canonical digest, quality and synchronization limits. `results.playback`
reports available/failed and canonical lineage. Example export failure:

```json
{"midi_url": null, "playback_midi_url": null,
 "raw_preview_midi_url": "/api/serve-preview-midi/7/",
 "results": {"playback": {"status": "failed",
 "derived_from": "canonical_displayed_xml", "error": "export failure"}}}
```

Default MIDI failure removes stale/partial output and exposes the failure;
it never substitutes raw MIDI. The existing MIDI artifact route then returns 404.
The broader processed/task-completion contract remains P5. Legacy result dictionaries
and JSON strings still serialize. No migration is required; historical analyses
are not retroactively repaired or assigned provenance. Existing audio clients now
receive canonical playback through the same field; clients can adopt the new raw
comparison field separately. Frontend UI wording/controls remain deferred.

Audio normalization is restricted to audio. It applies meter before building
measures, retains its approximate quantization/pruning, and labels staves, piano
synthesis, and meter/tempo choices as inferred MIDI context or fallbacks. It does
not claim to detect recording instruments or written markings. Pitch-range SATB
suggestions no longer replace written part names or assert an ensemble identity.

Ownership for P6: all newly generated analysis files are under
`TEMP_STORAGE_DIR/<id>`: input, preprocessed input/OCR/text results, `output.mxl`,
`output.xml`, `<id>.mid`, `preview.mid`, and recognizer intermediates where retained.
Audiveris working directories use its existing temporary context and are removed
on context exit. New `BASE_DIR/output/output_<id>.xml` compatibility copies and raw
MIDI duplicates are no longer created. Historical compatibility copies, historical
`basic_pitch_raw.mid`, database deletion, retries and complete expiry remain P6;
this phase does not delete ambiguous historical files or catalog sources.

MIDI checks compare literal independently read passage expectations against raw
MIDI note-on/off ticks with tolerance 0.002 quarter notes. Ties are one sounding
attack; simultaneous same pitches in separate parts and independent voices retain
durations in checked passages. XML independently retains spelling, lyrics,
expression, context, instrument/part identities and repeat notation. Repeat/ending,
percussion and transposing-instrument synchronization are explicitly unsupported
pending dedicated validation. Original-recording alignment is unsupported.

## P3 additive identity mapping (2026-10-23)

The P2 artifact contract/version above is unchanged and P2 remains VERIFY.
`results.musical_identity` schema 1 hashes and directly indexes the same served
canonical XML, with separate written-event IDs and symbolic playback occurrences.
`analysis_references` uses that revision for explicit musical spans/source joins.
No rewritten XML, new stored artifact, changed MIDI selection or historical
backfill is introduced. Contract and API examples: [IDENTITY_API.md](IDENTITY_API.md).
Actual source-model OSMD 1.9.0 correspondence and P3 verification/limitations:
[P3_EVIDENCE.md](P3_EVIDENCE.md). Written/sounding transposition is represented in
the index; this does not close P2's transposing-instrument MIDI synchronization
gap. Repeat traversal, seconds and recording alignment remain unavailable.

## P6 ownership and expiry

The inventory above is now enforced for explicitly owned new analysis sessions.
See [LIFECYCLE_API.md](LIFECYCLE_API.md): one hour from terminal processing,
file/record/join deletion, failure retries, active-writer protection and independent
recovery. Audiveris workspaces now also live under the session directory.
Historical external compatibility copies and legacy rows are conservatively
excluded pending a reviewed ownership manifest; filename matches authorize no
deletion. Artifact version, lineage, canonical MIDI and P2 VERIFY are unchanged.
