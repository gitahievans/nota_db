# P5 job, component and compatibility API

P5 adds results schema **2** and `results.processing` schema **1**. P2 artifacts
remain version 1; P3 identities and P4 musical components remain schema 1 with
unchanged revisions, locations, key/tempo/harmony semantics. P2 remains VERIFY.

## Outcomes and compatibility

`processing.status` is `success`, `partial`, or `failed`; `terminal` is false in
the canonical-notation checkpoint and true in a recorded terminal outcome.
Components use `success`, `partial`, `failed`, `absent`, or `not_applicable`.
Every component supplies a stable `code`, actual logical `stage`, safe `message`
and `available_outputs` names. Limited components also expose `source_codes`
from the existing structured musical contract. Recognition success means a
conversion produced notation, never that its musical fidelity was verified.

Components cover `recognition` (OMR or approximate audio), `notation`, `events`,
each independent analysis, `midi`, `text`, and optional `summary`. Exceptional
pipeline/job/cleanup-scheduling outcomes are separate components. Stages include
VALIDATING, TRANSCRIBING_AUDIO, CLEANING_TRANSCRIPTION, SPLITTING_HANDS,
GENERATING_MUSICXML, PARSING_MUSICXML, EXTRACTING_EVENTS, ANALYZING_SCORE,
GENERATING_MIDI, EXTRACTING_TEXT, GENERATING_SUMMARY and SCHEDULING_CLEANUP.
Audio callbacks update the actual failing substage rather than attributing every
failure to the outer transcription call. Missing text and unrequested summary
are not applicable, not transcription failures. Absence of key/meter/pitches is
not an exception. Unsupported traversal/interpretation can coexist with complete
written events and usable notation.

`processed=true` for new terminal jobs means canonical notation is available,
including partial analysis/playback failures. It does not certify musical
correctness, MIDI availability, or synchronization. A total failure has
`processed=false`. Legacy fields retain their types: key/tempo strings,
chords with string pitch and numeric offset, and `.error` handling on failed
legacy objects. Failed legacy parts/chords stay lists and time signature stays a
renderable string; safe `analysis_errors` metadata preserves their failure outcomes
without passing an object to a React child. Error values are sanitized; raw exceptions/paths stay in server
logs. New outcomes never put error strings into musical values.

Example selections from a MIDI/component failure response (not a full snapshot):

```json
{"score":{"processed":true,"results_schema_version":2,
 "musicxml_url":"/api/serve-musicxml/42/","midi_url":null,"playback_midi_url":null,
 "capabilities":{"notation":true,"default_playback":false},
 "results":{"schema_version":2,"tempo":"80 quarter notes/min",
  "processing":{"schema_version":1,"status":"partial","terminal":true,
   "components":{
    "midi":{"status":"failed","stage":"GENERATING_MIDI","code":"midi_unavailable",
     "message":"Output is unavailable.","available_outputs":[]},
    "notable_elements":{"status":"failed","stage":"ANALYZING_SCORE",
     "code":"notable_elements_failed","message":"notable elements could not be completed.","available_outputs":[]}}}}},
 "task_status":{"state":"SUCCESS","info":{"stage":"PARTIAL","status":"partial","progress_percent":100}}}
```

Current `score.capabilities` and URL fields check actual files. Terminal outcomes,
`processed`, artifact lineage and their availability snapshot are historical:
file loss does not rewrite a completed job as active or regenerate its artifacts.
Clients should use current capabilities before fetching. No fallback swaps raw
preview MIDI into default playback. Source/raw-preview URLs retain P2 roles.

## Job ownership, terminal polling and recovery

Migration 0012 adds internal `analysis_task_id`, `job_state`, `job_stage`, and
`job_updated_at`. Upload records queued/pre-dispatch work and saves its dispatched
Celery ID; a worker also records its own request ID. Catalog uploads do neither.
A foreign worker task cannot process the score or schedule its cleanup. Terminal
redelivery returns the persisted outcome instead of reprocessing.

Detail always uses the score's stored task association, with or without a query
parameter. A mismatched `?task_id=` is ignored and reports
`info.task_id_status=unassociated_ignored`; that foreign ID is never queried.
Legacy IDs with no established association are never trusted. This is association
checking, not authentication or authorization.

Persisted terminal state wins over unavailable/expired Celery metadata. Polling
uses **SUCCESS** for usable complete/partial outcomes and **FAILURE** for total
failure; `info.stage` distinguishes COMPLETED, PARTIAL and FAILED. These states
stop the existing frontend poller. Celery SUCCESS itself only means the function
returned; clients should read persisted status and component outcomes.

Recent queued/running jobs remain pending/active if the backend reports PENDING
or is unavailable. FAILURE/REVOKED, or SUCCESS without a persisted terminal
outcome, trigger conservative recovery. A no-progress interval greater than
`ANALYSIS_JOB_STALE_SECONDS` (default 3600) becomes a terminal
`job_progress_timeout` on the next detail read. This is a maximum tolerated
interval between stage updates, **not proof a worker died** and not an expiry
policy. Tune it for long recognition workloads. Conditional writes prevent a
late worker or stale recovery read from replacing an already recorded outcome.
Canonical notation and exported MIDI URLs are checkpointed before later analyses;
recovery preserves those available outputs. It does not reconstruct unfinished
findings. Actual concurrent worker/broker behavior remains runtime-unverified.
P6 now adds independent recovery and live-writer protection; see
[LIFECYCLE_API.md](LIFECYCLE_API.md). For explicitly owned analysis sessions a live
writer's OS lock prevents premature recovery even when metadata is missing/stale.

Recognition/invalid-XML failures preserve a safe terminal outcome; component,
MIDI/OCR/summary failures retain other outputs. Cleanup dispatch failure records
`cleanup_schedule_failed`, cannot conceal the original exception, and turns an
otherwise complete usable job into PARTIAL. P6 preserves this behavior and adds
durable deletion/recovery independent of scheduled task delivery. Availability
ends one hour after the persisted terminal outcome, including failure.

## Older results and optional summary

Older dictionaries and JSON-string dictionaries remain readable as schema 1.
No migration/backfill of their content or unverified component success is invented.
Malformed JSON returns `invalid_stored_results`; non-object JSON safely becomes
an empty object. Legacy processed/error status remains conservative, and metadata
reads do not need artifact regeneration, even after files disappear. Missing old
job metadata is not proof of an expired task or analysis.

Summary is still an explicit optional request to the existing endpoint/provider.
Only usable findings plus uncertainty, component outcomes and source provenance
enter the prompt. Missing OCR omits text cleaning. No usable findings returns
400; provider/configuration/empty-response failure returns 503 with `summary_failed`,
preserving findings, notation and a previous summary. A successful retry updates
only summary outcome/text and can restore COMPLETED when no other limitation
remains. Summary metadata remains readable without the original artifact files.
No new AI service, automatic summary call, or musical inference was added.

## Frontend handoff (read-only inspection)

The existing ScoreDataContext and AnalysisDisplay recognize only SUCCESS/FAILURE
as terminal and use `processed` to display notation. The compatible terminal mapping
above stops polling for both partial and failed work. Existing tempo rendering is
still a string; artifact URLs retain their names and types, now nullable when the
file is unavailable. Types/context/AnalysisResults/AnalysisDisplay/MidiPlayer were
inspected read-only; no frontend files changed and no browser UX gate was run.

Future frontend work: distinguish partial completion from analysis validity;
show failed/limited component codes and current capabilities; distinguish written
signatures from estimated key and label approximate audio/raw preview; consume
structured identities/locations/sonorities; display expiry only once P6 supplies
an authoritative lifetime contract (now provided in [LIFECYCLE_API.md](LIFECYCLE_API.md)). Playback controllers still need separate
transport/tempo-change/repeat handling and cannot assume original-audio alignment.
Do not invent an expiry timestamp from upload time or processing timeout.

P6 lifecycle examples, ownership, deadline/recovery/deletion semantics and 404/409 responses are authoritative in [LIFECYCLE_API.md](LIFECYCLE_API.md).

## Recognition failure feedback follow-up (2026-10-24)

For failed PDF/image recognition, `task_status.info.message` now supplies the
approved user feedback, including for existing generic recognition failures:

> We couldn’t recognize this score. Image quality or complex notation may contribute. Try a different PDF export or a clear scan.

This identifies possible contributing factors, not a confirmed quality diagnosis.
`state=FAILURE` and `info.stage=FAILED` remain compatible; additive `failure_stage`
and `code` identify the failed component. Components preserve stable causes such
as `recognition_barline_error`, `recognition_incomplete`, `recognition_no_output`
or the earlier `recognition_failed`. Audio, dispatch and other failures keep their
own messages. Existing frontend displays `info.message`; no frontend edit needed.
Private failure logs are bounded and expire with their owning session. Runtime
findings and verification: [RECOGNITION_EVIDENCE.md](RECOGNITION_EVIDENCE.md).
