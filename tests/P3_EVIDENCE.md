# P3 implementation and handoff evidence

Date: 2026-10-23. Status: DONE for the supported identity/location contract.
P3.1–P3.9 complete. P2 remains VERIFY; its missing recognition/audio gates are
not passed by these symbolic checks. Contract, joins, bounds and API selections:
[IDENTITY_API.md](IDENTITY_API.md). P1/P2 evidence remains historical and intact.

## Changes and checks

New `files/musical_identity.py` indexes canonical source bytes with revision-scoped
deterministic XML ordinals, exact rational positions, actual measure extents,
part/staff/voice/chord-member identity, literal labels, written/sounding pitch,
tie links, written markings and explicitly limited playback occurrences. It
reports missing/unsupported content and bounds without truncating identity lists.
`files/music21_analyzer.py` attaches that index and analytical span references,
repairs global legacy chord/meter positions, removes divide-by-four measure guesses,
reconciles duplicated meter markings and correctly maps split grand staves back
to their source part/staff. P4 key/tempo/harmony algorithms are not completed here.

`files/reliability/identity.py` and `files/tests.py` add passing identity checks;
the resolved P3 meter probe moved out of `files/reliability/baseline.py`.
`tests/osmd_identity.py` supplies a reproducible real installed-library join probe.
Other changed documents: plan, tests README, ARTIFACTS addendum, project guide,
this evidence and IDENTITY_API. Existing uncommitted P1/P2 work was retained.
No migration, source-fixture edit, frontend edit, commit, push or deployment.

Commands below use `.venv-p1/Scripts/python.exe`, Python 3.12.5, isolated test
settings, temporary filesystem copies and SQLite; no production database/services.

| Command | Actual result |
|---|---|
| `manage.py test files --settings=tests.settings -v 1` | 47 discovered, 47 passed, zero skips; exit 0 |
| `manage.py test files.reliability.baseline --settings=tests.settings -v 1` | 4 discovered, 4 ordinary assertion failures, zero errors/skips; nonzero |
| `-m tests.osmd_identity` | PASS: 68/68 written events joined one-to-one across eight passages in installed OSMD **1.9.0**, local headless Chrome |
| `-m tests.integration omr` | UNVERIFIED: required backend Audiveris runtime `/app/audiveris` absent |
| `-m tests.integration audio` | UNVERIFIED: reviewed audio reference and Basic Pitch model/backend dependencies absent |
| `-m compileall -q files tests` | Passed |
| `git diff --check` | Passed |

OSMD counts: melody 8, parts 5, rhythm 5, expression 4, harmony 36, distributed 3,
triplet/voices/repeated-label/transposition passage 5, grand staff 2. The probe uses
literal XML and the actual loaded source model, not mocked OSMD declarations.
The initial sandboxed Chrome launch could not start its GPU/browser processes;
an approved unsandboxed local run succeeded. No frontend dependency was installed
or changed. Chrome uses an isolated temporary profile and a loopback-only server.

New passing coverage includes the resolved meter defect, pickups and 6/8 ties,
3/4→6/8 and dotted-unit tempo locations, chord members with unequal durations,
exact triplet fractions, same-pitch independent voices/parts, repeated nonnumeric
labels, stale revision detection, byte-addressable XML notes, JSON serialization,
deduplicated shared context with retained part scopes, transposition, grand staff
source mapping, repeats reported unsupported, rests/empty/unpitched/missing context,
unresolved ties, ambiguous unison OSMD joins, all index limits, 2,000-event complete
output, anchored later-bar harmony references, and revision equality with actual
served XML and detail API. Existing preservation/MIDI/API/catalog tests still pass.
Fixture fingerprints are checked before/after pipeline cases as in P2.

Remaining defect probes are exactly P4B numeric tempo, P4C full sonority coverage
and cross-part harmony, and P5 nested-error completion. Their failures remain
visible; the logged legacy tempo NameError is not represented as a P3 success.

## Limits and next action

Real Audiveris PDF/image output, actual Basic Pitch short-audio accuracy, full five
primary-score reference equivalence, worker/broker delivery, optional summary
service and expiry/database deletion remain UNVERIFIED. Five PDFs still lack
reviewed full XML counterparts; reviewed short audio is absent. P3's real runtime
claim is limited to the local installed OSMD source-model join. It is not a
browser product UX test or production integration pass.

Repeat/ending/jump traversal is explicitly unavailable, as allowed by P3's gate;
no repeat expansion or second traversal occurrence is invented. Symbolic linear
tie chains work; seconds, universal MIDI alignment, percussion synchronization,
transposing-instrument MIDI equivalence and original-recording alignment are not
claimed. Ambiguous identical notes in one voice cannot be joined individually in
OSMD 1.9.0 without additional support. Grace timing, octave-shift/double-transpose
sounding interpretation and non-controlling navigation are unsupported. Unknown
empty-measure lengths propagate null subsequent global positions.

Next authorized phase would be P4, using this revision/location model to repair
key, tempo and complete harmony semantics. It has not been started. To close P2,
provide its actual recognition/audio runtime and reviewed references and run its
remaining acceptance gate. Frontend selection/playhead controls remain separate
work; existing frontend compatibility was inspected read-only.
