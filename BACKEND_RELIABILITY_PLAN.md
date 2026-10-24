# Scorelearn backend reliability plan

Status: P1 verification framework DONE (2026-10-23); P2.1-P2.8 implemented; P2 VERIFY pending real recognition/audio gate; P3.1-P3.9 DONE for the supported identity/location contract; P4A-P4C DONE for the supported symbolic contract; P5.1-P5.9 DONE for the supported backend orchestration contract; P6.1-P6.10 DONE for the supported backend lifecycle contract. Real recognition/full-primary-score checks remain UNVERIFIED; see `tests/BASELINE.md`.
Baseline: main at 6f87a6a, inspected 2026-10-23. Revalidate paths/behavior before implementation.
Audience: Codex implementation agents. Paths below are relative to this backend repository unless prefixed `../scoreanalyzr/`.

## 0. Scope, decisions, execution contract

Objective: correct existing backend outputs and establish trustworthy musical identities/locations for later interactive score features. Deliver in six phases; phase 4 has three independently tracked work packages.

Accepted decisions:
- Backend first. No frontend feature implementation, visual redesign, authentication, saved-score library, or project renaming in this work.
- PDF/image: remove destructive musical reconstruction; preserve Audiveris-recognized MusicXML. This is recognized notation, not a guarantee of fidelity to the uploaded image.
- Audio: retain a separate, explicitly approximate transcription/reconstruction path. Do not remove audio support or assume raw MIDI is already readable notation.
- Default synthesized playback must represent the displayed notation. Original recording/raw transcription may remain separate comparison artifacts.
- Analysis is ephemeral: retain the one-hour policy, then delete analysis files AND their analysis database records. Do not convert this into permanent storage.
- The existing non-analysis catalog upload is a separate flow. Do not apply ephemeral analysis deletion to catalog records or their stored source files.
- AI interpretation is deferred. Keep existing optional summary support compatible; do not introduce Workers AI, new model calls, or AI-generated musical facts.
- Five local verification samples are being collected by the user. Samples/reference expectations must outlive application cleanup and must not depend on production database uploads.

Out of scope: automatic phrase/cadence/motif/modulation detection; Roman-numeral/harmonic-function/non-chord-tone engines; moving playhead UI; original-recording alignment; wholesale audio model upgrades. This plan prepares their foundations, not their full implementation. Future work must distinguish observed notation from analytical interpretation.

Execution protocol:
1. Read this section, tracker, and current phase. Inspect relevant current code; historical READMEs/plans may describe superseded behavior.
2. Work in phase order. Narrow prerequisite repairs may move earlier, but record the reason. Do not expand into deferred features.
3. Resolve contract choices using the constraints here; document the chosen behavior before dependent work. Escalate only product choices that materially change accepted scope.
4. Preserve useful working behavior and existing upload/catalog routes. Prefer compatible API additions; explicitly account for changes to existing values and types.
5. Test externally meaningful musical/API behavior, not copies of implementation logic. Record expected limitations and actual failures separately.
6. Update checkboxes and tracker after each completed work package. Mark a phase done only after its acceptance gate passes; never mark missing verification as passed.
7. Handoff entry: status, completed IDs, changed paths, checks/results, unresolved issues, next action. Store detailed evidence once and link it; avoid repeated full logs.
8. This document authorizes planning only. Implementation occurs when the user instructs it; do not infer permission to deploy, commit, or push from the existence of this plan.

### Progress tracker

Allowed status: TODO / ACTIVE / VERIFY / DONE / BLOCKED. BLOCKED requires a concrete dependency and an unblock action. Initial fixture availability is UNCONFIRMED, not assumed absent.

| Phase | Original issue(s) | Status | Evidence / remaining dependency |
|---|---|---|---|
| P1 Verification baseline | 9 | DONE | P1.1-P1.7 complete; 20 passing checks, 8 separately reproduced defects. Five PDFs inventoried; checked supplemental passages available. Real OMR/audio and full primary-score verification UNVERIFIED. Evidence: `tests/BASELINE.md`; execution: `tests/README.md` |
| P2 Preserve notation; align artifacts | 1, 4 | VERIFY | P2.1-P2.8 implemented and controlled checks pass; real short audio/OMR and full primary-score verification UNVERIFIED. See `tests/P2_EVIDENCE.md` |
| P3 Musical identity and locations | 3 | DONE | P3.1-P3.9 complete; 47 passing checks and actual OSMD 1.9.0 source-model join (68 events). Unsupported traversal explicit; recognition/audio remain UNVERIFIED. See `tests/P3_EVIDENCE.md` and `tests/IDENTITY_API.md` |
| P4 Key, tempo, harmony correctness | 5, 6, 2 | DONE | P4A-P4C supported symbolic gates pass using P3 revisions/locations; runtime/primary-reference limits remain UNVERIFIED. See `tests/P4_EVIDENCE.md` and `tests/ANALYSIS_API.md` |
| P5 Partial success and compatibility | 8 | DONE | P5.1-P5.9 complete; 102 passing checks; final nested-error probe moved to passing suite; zero unresolved defect probes. Real worker/recognition/audio and browser UX remain UNVERIFIED. See `tests/P5_EVIDENCE.md` and `tests/PROCESSING_API.md` |
| P6 Expiry and complete deletion | 7 | DONE | P6.1-P6.10 complete for the supported lifecycle contract; one-hour terminal deadline, explicit ownership, deletion/retry/recovery and honest unavailable responses. Live Linux worker/broker/PostgreSQL outage gate UNVERIFIED. See `tests/P6_EVIDENCE.md` and `tests/LIFECYCLE_API.md` |

### Repository anchors

| Concern | Current locations |
|---|---|
| Upload, summary, detail, artifact responses | `files/views.py`, `files/urls.py` |
| Source types, analysis record, serialization | `files/models.py`, `files/serializers.py`, `files/migrations/` |
| Pipeline, completion checks, cleanup scheduling/deletion | `files/tasks.py` |
| Audiveris recognition/extraction, extra XML copies | `files/audiveris_processor.py` |
| Audio transcription and raw preview | `files/audio_processor.py` |
| Destructive event-based rebuilding | `files/score_cleanup.py` |
| Key/chord/meter/tempo/structure analysis; MIDI export | `files/music21_analyzer.py` |
| Temporary lifetime/storage, Celery | `nota_db/settings.py`, `deploy/compose.prod.yml` |
| Existing checks | `files/tests.py` is a placeholder; `files/test_image_preprocessing.py` is a manual diagnostic |
| Frontend compatibility references, read-only | `../scoreanalyzr/src/lib/types.ts`, `src/contexts/ScoreDataContext.tsx`, `src/components/AnalysisDisplay.tsx`, `src/components/AnalysisResults.tsx`, `src/components/MidiPlayer.tsx` |

For the last row, all `src/...` paths belong under `../scoreanalyzr/`.

## P1. Establish verification baseline [issue 9]

Problem/location:
- No meaningful automated regression coverage currently establishes that notation is preserved or musical results are correct.
- A successful request/task does not establish musical correctness. Generated `output/*.xml` files have not been established as trusted references.
- Recognition errors and backend processing errors currently have no separate verification boundary.

Target outcome: small reusable local examples, independently checked expectations, and separate checks for recognition, symbolic analysis, and API orchestration.

Work:
- [x] P1.1 Inventory `tests/fixtures/scores/`; preserve user files and identify missing coverage. Keep test discovery compatible with existing `files/tests.py`.
- [x] P1.2 Record five primary fixture identities: `01-simple-melody`, `02-rhythm-and-meter`, `03-multiple-parts`, `04-keys-and-chords`, `05-expression-and-changes`. Accept equivalent filenames with an explicit mapping.
- [x] P1.3 For each fixture record source, available PDF/image/MusicXML counterparts, expected observations, reference-review status, and uncertainty. Unreviewed output is not a truth source.
- [x] P1.4 Separate three layers: direct checked-MusicXML analysis; pipeline/API checks with controlled external dependencies; real Audiveris/Basic Pitch integration checks requiring their actual runtime. Mocked checks cannot establish recognition accuracy.
- [x] P1.5 Capture current failures as baseline evidence. Keep explicit known limitations separate from passing requirements; avoid permanent skips that conceal regressions.
- [x] P1.6 Add small supplemental reference passages where the five scores leave gaps. Expected answers must be independently checked, not generated by the same analyzer being verified.
- [x] P1.7 Document repeatable execution, required services/tools, and which checks need network/model downloads. Core symbolic checks should not require Gemini or repeated OMR runs.

Coverage inventory:
- Sample 1: one staff, simple 4/4 notes/rests, explicit numeric tempo, known note/rest/measure counts.
- Sample 2: 3/4 or 6/8, dotted duration, tied notes, preferably pickup; verify onset/duration and actual measure boundaries.
- Sample 3: two named parts, overlapping unequal-length notes, harmony distributed across parts; preserve part/voice/instrument identity.
- Sample 4: written key signature, accidentals, simple chords, explicit pitch spelling; distinguish signature from estimated key.
- Sample 5: dynamics, articulations, optional lyrics, tempo/meter change; retain markings and correct change locations.
- Supplemental as needed: tuplets; multiple voices on one staff; same-pitch simultaneous notes in different parts; repeated measure labels; repeats/endings; transposing instrument; >10 harmony events; empty/unpitched content; missing key/meter/tempo; malformed input; short reviewed audio.

Acceptance:
- Trusted inputs and checked expectations exist for the behavior a phase changes. Partial fixture availability permits independent work with reviewed supplemental examples; incomplete integration coverage remains visible.
- Originals survive test runs and application expiry. Tests operate on isolated temporary copies/records, never production records.
- Baseline distinguishes recognition fidelity, notation preservation, analytical interpretation, and infrastructure failure.
- Test discovery demonstrably runs the intended checks; unavailable runtimes are reported as unverified, not successful.

### P1 handoff (2026-10-23)

Framework acceptance is complete with partial reviewed references, as permitted above.
Completed P1.1-P1.7; no application behavior fixed. The five PDF originals exist,
are fingerprinted, and remain unchanged. The manifest maps identities, counterparts,
checked observations and review limits. Six valid hand-checked supplemental MusicXML
passages plus malformed input cover independent core checks; no generated output
is a truth source. Django discovery runs 20 passing checks. A separate ordinary
assertion suite reproduces eight existing failures; zero skips conceal missing work.

Detailed results, changed paths, isolation guarantees, remaining dependencies and
next action are recorded once in `tests/BASELINE.md`. Use `tests/README.md` for
execution. Real Audiveris and Basic Pitch checks report UNVERIFIED, not success:
requires backend recognition runtimes, reviewed primary-score counterparts/full
expectations and reviewed short audio. Full-score recognition, MIDI equivalence
and further musical edge cases remain unverified. P2-P6 and completion checkboxes
remain open. No commit, push, deployment or frontend change was performed.

## P2. Preserve recognized notation and align playback [issues 1, 4]

Problem/location:
- `files/tasks.py::process_score` routes PDF/image recognition through `normalize_score_stream` before analysis and overwrites the served XML.
- `files/score_cleanup.py` flattens parts/voices to MIDI-pitch events, quantizes offsets/durations, prunes overlaps and simultaneous notes, groups unequal durations, rebuilds piano parts, and guesses staff allocation from pitch range.
- Reconstruction loses original spelling, parts, markings, lyrics, repeat/tie context, key changes, and measure identity. Time signature is applied after initial measure construction, creating another meter risk in the reconstructed audio path.
- `files/audio_processor.py` saves raw Basic Pitch MIDI as `preview.mid`; `FileSerializer.get_playback_midi_url` prefers it, while displayed XML is reconstructed. The artifacts need not represent the same notes/timing.

Target outcome: one authoritative notation artifact per analysis; analysis and default MIDI derive from it; source-specific transformations/provenance remain explicit.

Work:
- [x] P2.1 Define artifact roles and lineage: source upload, recognized MusicXML, audio draft notation, canonical displayed XML, default playback MIDI, optional raw preview. Preserve distinct roles without redundant long-term storage.
- [x] P2.2 Remove event-based reconstruction from PDF/image processing. Preserve Audiveris note spelling, durations, rests, ties, voices, parts, instruments, key/meter/tempo changes, lyrics, dynamics, articulations, and repeat notation where recognized.
- [x] P2.3 Ensure analysis consumes the notation actually served. Validate uncompressed/compressed XML consistency; do not silently analyze one artifact and display another.
- [x] P2.4 Keep audio reconstruction explicitly separate. Check its measure/meter correctness and prevent unlabelled claims that guessed staves/instruments/tempo were detected from the original recording.
- [x] P2.5 Default playback must come from canonical displayed notation for every source type. Keep original audio and raw MIDI distinct and labelled in backend metadata/URLs; do not remove comparison capability accidentally.
- [x] P2.6 Define fallback behavior: if canonical MIDI generation fails, expose that failure without silently substituting a different musical version as synchronized playback.
- [x] P2.7 Make provenance describe what really occurred; no OMR 'repaired' flag for reconstruction that no longer runs. Distinguish recognition quality from downstream processing success.
- [x] P2.8 Verify known parts/markings currently affected by reconstruction. Avoid silently assigning SATB labels, piano identity, or changed score structure from a heuristic; inferred labels must remain separate from written/source labels.

Acceptance:
- Checked MusicXML preserves musical meaning through the backend. Harmless formatting differences are acceptable; compare semantics, not byte snapshots.
- Two voices/parts retain independent identities/durations, including repeated/simultaneous same pitches. Dotted/triplet rhythms and ties survive PDF/image downstream handling.
- Displayed XML and default MIDI agree on sounding pitches/onsets/durations within documented export tolerances. MIDI cannot prove preservation of spelling/lyrics/articulations; check XML separately.
- Tie continuations do not become repeated attacks; percussion/transposition/repeat handling is either validated or explicitly unsupported rather than silently misleading.
- Real short audio still produces a labelled draft and usable outputs. Existing PDF/image/catalog/summary paths remain usable.
- Generated artifacts have declared ownership and locations for P6 deletion, including recognition compatibility copies outside `/tmp/nota`.

### P2 handoff (2026-10-23)

Status VERIFY: P2.1-P2.8 implementation and controlled verification complete;
full acceptance is not marked DONE because real short audio and recognition/full
primary-score checks remain UNVERIFIED. Artifact choices and lineage are documented
in `tests/ARTIFACTS.md`. Detailed changed paths, checks/results, remaining musical
limits and next actions: `tests/P2_EVIDENCE.md`. All three P2 defect probes moved
into the passing suite; the five P3-P5 failures remain separately reproducible.
No P3-P6 work, migration, frontend change, commit, push or deployment performed.


## P3. Establish musical identities and accurate locations [issue 3]

Problem/location:
- Chord results contain only `pitch` and `offset`; most summary outputs cannot reference individual notes/measures.
- `analyze_chords`, `analyze_meter_changes`, and `analyze_tempo` use element-local offsets as if they located events in the complete score.
- `_offset_to_measure` assumes four quarter notes per measure; pickups, changing meters, and irregular numbering invalidate that assumption.
- Multi-part traversal can mistake a repeated marking in another part for a chronological change.

Target outcome: a versioned, documented event/location contract that analysis, notation, and future frontend interaction can share.

Work:
- [x] P3.1 Decide/document time units and coordinate spaces: score-relative and measure-relative positions in quarter-note units; performed seconds are separate. Retain sufficient precision for tuplets; never infer measure identity by dividing by four.
- [x] P3.2 Preserve displayed measure labels separately from unique measure identity/order; support pickups, nonnumeric/repeated labels, actual measure lengths, and per-part/voice context.
- [x] P3.3 Represent notes/rests and individual chord members with deterministic identities, part/staff/voice references, pitch spelling/octave, written duration/onset, and tie relationships. Distinguish written from sounding pitch where transposition applies.
- [x] P3.4 Define identity scope: stable for repeated requests/reparses of the same artifact revision, not a promise of identity across arbitrary score edits. Include schema/artifact revision information sufficient to detect stale mappings.
- [x] P3.5 Demonstrate that identity/location references can be associated with the served MusicXML and installed OSMD 1.9.0 model. Document the join rules and ambiguities; a backend-only index with no reliable XML correspondence is insufficient. No frontend product changes required for this feasibility check.
- [x] P3.6 Anchor analysis findings to events or explicit musical spans. Key/meter/tempo changes use score positions and relevant part scopes, with duplicate shared markings reconciled.
- [x] P3.7 Separate notation order from playback order. Repeats/endings may revisit a written event; ties may connect multiple written events to one sounding note. Specify/test supported traversal behavior and report unsupported navigation explicitly.
- [x] P3.8 Ensure empty/unpitched content and missing context produce explicit absence/unsupported states, not invented pitches, keys, or measure numbers.
- [x] P3.9 Bound response size/performance for larger scores; no silent data truncation. Define explicit limits or pagination if needed, preserving complete identities within the supported range.

Acceptance:
- Later-measure events have correct global and local positions across 3/4, 6/8, pickups, tuplets, and meter changes.
- Simultaneous notes in different voices/parts remain distinct; repeated requests retain identities; revision changes are detectable.
- All returned references resolve to actual events/measures/spans in the same artifact revision.
- Duplicated markings across parts do not generate fictitious global changes.
- Written-to-playback correspondence is demonstrated for supported repeats/ties, or explicitly labelled unavailable for unsupported navigation. Never assert universal synchronization.
- Document the minimum future API examples: selected note/rest, measure, simultaneous harmony, tempo change, and repeat occurrence. No SVG/pixel coordinates in backend musical data.

### P3 handoff (2026-10-23)

Status DONE for the supported P3 gate: P3.1-P3.9 implemented and verified with
checked supplemental XML, controlled served-artifact/API checks, and the real
installed OSMD 1.9.0 source model (68/68 written-event joins). Repeat/ending/jump
playback traversal is explicitly unavailable; supported linear tie chains have
separate symbolic occurrences. No universal MIDI/recording synchronization claim.
P2 remains VERIFY; missing recognition/audio/full-primary-score verification is
unchanged. Detailed changed paths, actual commands/results, limitations and next
action: `tests/P3_EVIDENCE.md`. Revision/units/XML/OSMD join contract and minimum
API examples: `tests/IDENTITY_API.md`. The P3 defect probe moved to the passing
suite; four P4/P5 defect probes still fail separately. No P4-P6 implementation,
frontend change, migration, commit, push or deployment performed.

## P4. Correct key, tempo, and harmony analysis [issues 5, 6, 2]

Dependency: P3. These work packages share its identity/location conventions; each has an independent completion gate.

### P4A. Written key signature versus estimated key [issue 5]

Problem: `analyze_key` returns one overall estimate; current UI/summary labels it as a written key signature. Written signatures/changes and uncertainty are not separately represented.

- [x] P4A.1 Extract actual written key signatures and locations/scopes, including changes and missing/ambiguous context. A signature alone does not uniquely identify major versus minor.
- [x] P4A.2 Return overall tonal-key estimation separately, labelled with method/evidence limits. Do not present numeric algorithm scores as calibrated probability.
- [x] P4A.3 Preserve written accidentals/enharmonic spelling. Distinguish pitch alteration from explicitly displayed accidental signs; current notable-element counts do not necessarily count printed symbols and omit notes embedded in chord objects.
- [x] P4A.4 Keep audio estimates/injected defaults identifiable as inferred. No false claim that a written signature came from the recording.
- [x] P4A.5 Keep existing summary generation grounded in the distinction. Record frontend wording work as deferred; backend alone cannot change the current UI label.

Gate: reviewed signatures and changes match XML; absent signatures remain absent/unspecified; estimated keys remain distinct and are checked against suitable reference examples. All locations use P3.

### P4B. Tempo extraction and timing semantics [issue 6]

Problem: `analyze_tempo` references an unimported module, double-traverses overlapping tempo classes, uses local offsets, and mixes raw printed beat values with quarter-note BPM. Defaults/text interpretations can be mistaken for observed speed.

- [x] P4B.1 Restore functioning tempo analysis for explicit numeric markings and tempo text.
- [x] P4B.2 Preserve printed beat unit/dots and numerical value; separately express normalized playback speed. A dotted-quarter marking in 6/8 is not the same as that numerical value in quarter notes per minute.
- [x] P4B.3 Order changes globally, reconcile duplicates across parts/classes, and preserve locations. Text such as 'Allegro' without a number is not an exact measured BPM.
- [x] P4B.4 Separate explicit tempo, interpreted text, and playback default. If a default is needed for MIDI, it must not become a discovered score fact.
- [x] P4B.5 Clarify any average tempo statistic; do not present an unweighted average of duplicate markings as representative elapsed-time speed.
- [x] P4B.6 Resolve the known API compatibility trap before release: `../scoreanalyzr/src/components/AnalysisResults.tsx::getTempo` returns a successful `results.tempo` object directly as a React child. Restoring successful backend extraction can therefore break the current page. Document a compatible legacy projection or versioned response strategy while exposing full structured data separately; do not assume additive fields alone fix this.

Gate: explicit quarter/dotted-quarter examples, multiple changes, duplicate part markings, text-only/no-tempo examples all behave correctly; canonical MIDI timing agrees with the declared tempo map; current frontend consumer does not receive an unusable value.

### P4C. Full-score simultaneous harmony [issue 2]

Problem: `analyze_chords(max_chords=10)` stops early, chordifies each part independently, and returns a name/local offset without members, duration, bass, inversion, or uncertainty.

- [x] P4C.1 Cover the supported score completely. If resource limits apply, explicitly report limits/incompleteness; do not silently return the first ten events.
- [x] P4C.2 Analyze notes actually sounding together across pitched parts, including notes sustained from earlier onsets. Avoid duplicating shared staves/parts or treating percussion as pitched harmony.
- [x] P4C.3 Return observed pitch collections separately from suggested chord labels. Distinguish a written chord object, an instantaneous combined sound, and an inferred underlying harmony.
- [x] P4C.4 Include locations/spans, contributing event references, spelled pitches, and supported root/bass/inversion results. Ambiguous/unsupported sonorities need no forced chord name.
- [x] P4C.5 Define/document segmentation and merging rules so passing notes do not automatically become asserted harmonic changes. For this phase, transparent simultaneous-sonority analysis is acceptable; do not imply a complete human-level progression interpretation.
- [x] P4C.6 Preserve multi-part context, transposition correctness, tie durations, and spelling. Evaluate simple known harmonies plus ambiguous/non-chord-tone examples.

Gate: >10 events covered; distributed triad recognized from multiple parts; sustained notes included; unison/octave-only/ambiguous passages not given misleading certainty; all references resolve; existing clients can still consume the agreed legacy chord representation.

### P4 handoff (2026-10-23)

Status DONE for the supported symbolic P4A-P4C gates. Written signatures, scoped
changes and tonal estimates are distinct; explicit tempo uses normalized quarter
BPM and a React-renderable legacy string; complete cross-part sonorities retain
P3 event references. No underlying harmony/function/modulation detection added.
Detailed contracts, compatible projections, limitations and API examples:
`tests/ANALYSIS_API.md`. Changes, checks/results, unresolved dependencies and next
action: `tests/P4_EVIDENCE.md`. P2 remains VERIFY; real recognition/audio and full
primary-score reference verification remain UNVERIFIED. P5's nested-error defect
remains separately reproduced. No frontend features, migration, commit, push or
deployment performed. Existing P1-P3 work was preserved.

## P5. Report capabilities and partial success honestly [issue 8]

Problem/location:
- `process_score` checks truthy values and searches strings for 'Error'; nested failures can pass broad validity checks.
- A task can announce COMPLETED despite `processed=False` or unavailable MIDI; hard errors can overwrite useful results.
- Custom progress states and Celery terminal SUCCESS/FAILURE have different meanings; current polling depends on terminal states and `processed`.
- Artifact URLs can exist without files. Audio substage failures can be attributed to the outer transcription stage instead of the real failing step.

Target outcome: callers can distinguish completion from musical validity and discover which outputs are usable without losing partial results.

Work:
- [x] P5.1 Define outcomes for recognition/transcription, notation availability, event extraction, individual analyses, MIDI generation, and optional text/AI summary. Support success, partial, failure, absent/not-applicable as appropriate.
- [x] P5.2 Each failed/limited component reports a stable code, actual stage, useful message, and available outputs. Do not expose traceback/server paths or use error strings as musical values in the new contract.
- [x] P5.3 Define `processed` compatibility semantics alongside the new status model; missing key/meter estimates are not automatically total failure when notation is usable.
- [x] P5.4 Preserve valid notation/analysis when a later optional component fails. Only advertise default playback/artifact capability when its artifact is available.
- [x] P5.5 Ensure every job reaches a consistent terminal outcome; detail/polling behavior remains correct for total failure, partial success, missing/expired task metadata, and worker restarts.
- [x] P5.6 Associate job metadata with the correct score rather than trusting an unrelated client-supplied task ID. No authentication redesign required.
- [x] P5.7 Define results schema/version and backwards handling for existing JSON-string or older dictionary results. Never require reprocessing already-expired artifacts to read available status metadata.
- [x] P5.8 Keep summary generation optional and grounded in usable findings, their uncertainty, and input provenance. Handle missing text as not-applicable, not a transcription failure.
- [x] P5.9 Capture frontend-only work as a handoff: labels, partial-state messaging, expiry display, and eventual playback controller fixes. Do not silently edit frontend code under this backend plan.

Acceptance:
- Failure scenarios cover recognition, parse/invalid XML, one analysis component, MIDI, optional OCR/summary, and cleanup scheduling. Each reports actual impact and retains valid outputs.
- Empty/unsupported musical content is distinguishable from an internal exception.
- Existing upload/detail/serializer consumers retain usable contracts; tempo compatibility is explicitly exercised.
- All completed jobs stop being represented as actively processing; terminal state and component outcomes agree.
- An unrelated task identifier cannot misrepresent another score's progress.

### P5 handoff (2026-10-23)

Status DONE for the supported backend contract; completed P5.1-P5.9. Versioned
component outcomes separate usable notation, analysis limitations and actual
playback capability. Nested errors/individual exceptions, optional OCR/summary,
MIDI and cleanup scheduling failures preserve valid outputs and report safe
stages/codes. Persisted score/task association and terminal states survive missing
Celery metadata; conditional recovery prevents late task results replacing a
terminal outcome. Legacy dictionaries/JSON strings remain readable without
artifact regeneration. Migration 0012 adds internal job metadata with conservative
empty defaults; no historical success/backfill or production migration was run.

Detailed changed paths, command results, test moves, frontend handoff and limits:
`tests/P5_EVIDENCE.md`. Contract/examples: `tests/PROCESSING_API.md`, linked from
ANALYSIS_API and IDENTITY_API. Both verification suites ran: 102 passing checks,
zero remaining defect probes (exit 0, intentionally empty baseline, no skips).
Real OMR/audio preflights exit 2 UNVERIFIED; full primary-score references,
concurrent worker/broker delivery, live summary and browser UX remain unverified.
P2 stays VERIFY; P3/P4 musical contracts and fixture fingerprints are preserved.
Frontend inspected read-only. P6 remains TODO; its deletion task and one-hour
retention policy are unchanged. No commit, push or deployment performed.


## P6. Enforce temporary lifetime and complete deletion [issue 7]

Problem/location:
- `CLEANUP_DELAY_SECONDS` is one hour and `cleanup_temp_files` deletes `/tmp/nota/<id>` only. The analysis database record survives.
- Audiveris also writes `output/output_<id>.xml`; copies may survive normal temporary deletion. Database URLs can outlive artifacts.
- Failed uploads before Celery dispatch and interrupted/scheduling-failed jobs can leave records/files without a cleanup task.
- Deleting records removes the evidence needed to distinguish expired analyses from IDs that never existed. Existing catalog records must not be swept into cleanup.

Target outcome: analyses expire predictably, all owned transient data and analysis records are removed, and APIs provide useful temporary-session information.

Work:
- [x] P6.1 Define lifecycle timestamps and policy: active processing is protected; normal availability ends one hour after processing reaches a terminal outcome. Failed/pre-dispatch/abandoned work has a bounded cleanup policy too. Document retry/reprocessing behavior explicitly.
- [x] P6.2 Mark analysis-session ownership/lifecycle unambiguously; do not infer deletion eligibility from source type alone. PDF/audio/image types describe input, not catalog-versus-analysis retention.
- [x] P6.3 Return machine-readable lifetime information and a concise temporary-results message while the record exists. Future frontend can display it without inferring dates from upload time.
- [x] P6.4 Inventory all session-owned data: input, raw and processed MIDI, XML/MXL, OCR/other intermediate files, recognition workspaces, compatibility output copies, results/summary/record, and job metadata where applicable.
- [x] P6.5 Delete transient files and the analysis record, including its relationships, without deleting shared categories or catalog data. Never delete test fixtures or tracked historical XML by filename pattern alone; verify ownership and cleanup roots.
- [x] P6.6 Cleanup must tolerate repeated execution, missing files/rows, partial failures, and retries. A missing directory must not prevent eligible database deletion. Preserve enough retry information to finish remaining deletion if one step fails.
- [x] P6.7 Prevent an obsolete cleanup job from deleting an active/newer processing attempt. Handle reads/summary requests racing expiry without recreating expired records or leaving new orphan files.
- [x] P6.8 Provide bounded recovery for jobs/files missed because of worker/broker downtime or failures before cleanup scheduling. Scheduling errors must not conceal the original processing error. Explain expiry deadline versus eventual physical deletion under outages.
- [x] P6.9 Define post-deletion response semantics for detail/XML/MIDI/audio/summary routes. If distinguishing expired from never-existing IDs, retain only short-lived minimal non-content expiry metadata, not the deleted analysis record/results. Without such evidence, use an honest unavailable-or-expired response; never claim every unknown ID expired.
- [x] P6.10 Specify existing-record migration/backfill handling conservatively. Do not bulk-delete ambiguous historical/catalog records; document exclusions and any user decision needed.

Acceptance:
- Before expiry, available artifacts remain accessible and lifetime metadata is accurate. After expiry, session-owned files and the analysis row are removed; no full analysis survives in an expiry marker.
- All artifact/detail routes give consistent unavailable/expired behavior; they do not imply that a deleted analysis is still processed and available.
- Repeated/partially failed cleanup converges safely; catalog records, shared categories, test fixtures, and unrelated files remain unchanged.
- Realistic worker outage/retry/stale-task scenarios do not delete active sessions and eventually remove abandoned data.
- Backend response contracts support the agreed future user notice. Rendering that notice remains a tracked frontend follow-up, not a claimed backend accomplishment.

### P6 handoff (2026-10-23)

Status DONE for the supported backend lifecycle contract; completed P6.1-P6.10.
Explicit analysis ownership and atomic terminal/deadline timestamps retain the
one-hour policy. Expired records are inaccessible even during deletion failures;
owned directories, records and joins are deleted with durable retry intent.
Shared categories, catalog sources, ambiguous historical rows/copies and fixtures
are excluded. OS locks protect active writers; stale tasks cannot recreate a
deleted session. Independent recovery handles abandoned and unscheduled jobs.
No expiry tombstones are retained; unknown/deleted IDs honestly share unavailable
or expired responses. Migration 0013 defaults existing rows to legacy; 0012 was
already applied locally. P6 did not migrate the local application database.

Exact checks/results, changed paths, conservative exclusions, deployment/runtime
requirements and next actions: `tests/P6_EVIDENCE.md`. Decisions and API examples:
`tests/LIFECYCLE_API.md`, linked from artifact/processing/identity/analysis contracts.
P2 remains VERIFY; P3/P4 musical semantics and P5 partial/terminal compatibility
are preserved. Real OMR/audio/full primary references and live Linux/container,
Celery/Redis/PostgreSQL outage delivery remain UNVERIFIED. Frontend inspection
was read-only; expiry rendering and cached-result handling remain frontend work.
No commit, push or deployment performed. Overall C1-C7 gates below remain open
where their representative runtime/product verification has not been completed.

### Focused articulation follow-up (2026-10-24)

Fixed note-only notable-element traversal omitting chord staccato/accent/tenuto.
One chord marking counts once; distinct retained member markings count, with
object/traversal aliases deduplicated within each event. Shared note helpers,
accidental/dynamic semantics, canonical artifacts, identities, playback, partial
outcomes and expiry are preserved. Parser representation limits and exact checks:
`tests/MARKINGS_EVIDENCE.md`. Focused discovery: 16 passed; full existing backend
suite: 159 discovered/passed; separate baseline: zero tests, exit 0. Historical
phase evidence is unchanged. Recognition work is deferred, P2 remains VERIFY,
and real-runtime/full-primary-score acceptance gates remain UNVERIFIED.

## Completion and handoff

The nine fixes are complete only when all phase gates pass with evidence. Report remaining runtime/fixture limitations explicitly.

- [ ] C1 All original issues mapped to verified outcomes: 1=P2, 2=P4C, 3=P3, 4=P2, 5=P4A, 6=P4B, 7=P6, 8=P5, 9=P1 plus continued regression checks.
- [ ] C2 End-to-end representative PDF, image, and short audio runs: upload -> terminal outcome -> detail -> XML/MIDI -> expiry. Independently verify symbolic correctness against reviewed references.
- [ ] C3 Catalog upload/list/update remains functional and survives analysis expiry. Optional summary remains compatible and is not required for core tests.
- [x] C4 API contract/handoff documents include provenance, event identities/units/revision, key/tempo/harmony semantics, component outcomes, artifact roles, and lifecycle/errors, with small representative payloads.
- [x] C5 Existing frontend contract constraints are exercised; unresolved frontend wording/controls work is listed without claiming it fixed. No new frontend features delivered under this plan.
- [ ] C6 `files/LLM_PROJECT_GUIDE.md` and relevant backend docs reflect final behavior; superseded audio plans are labelled historical where conflicting. No AI integration implied.
- [x] C7 Record exact checks/results, residual musical limitations, migration/runtime requirements, and follow-up decisions. No deployment, commit, or push without user instruction.

Future-feature readiness after these fixes: trustworthy notation, same-source playback, stable musical references, complete bounded sonority data, explicit uncertainty, and versioned partial outcomes. Still separate work: interval/scale-degree teaching endpoints, Roman numerals/functions, phrase/cadence/motif inference, recording alignment, frontend overlays/playhead, and evaluated optional AI interpretation.
