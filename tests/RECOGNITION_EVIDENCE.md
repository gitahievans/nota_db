# Recognition failure investigation and feedback (2026-10-24)

Follow-up explicitly requested after P6: investigate the failed upload and use
the approved, qualified recognition feedback. The underlying recognition issue
remains unresolved; no engine upgrade, musical repair or reconstruction is claimed.

Local worker logs and database metadata identified analysis 13 as a PDF recognition
failure: Audiveris exited 0 without exported MusicXML. Two isolated reruns using
the existing container runtime reproduced an internal `IllegalStateException`,
`No abscissa computable for StaffBarlineInter`, during rhythm processing. Both
default resolution and an explicit 400-DPI PDF-render option failed. The installed
Java source confirmed that exception originates in barline-position lookup.
Visual inspection found a clear page; poor quality was not established. OCR language
warnings also occurred, but were not established as the cause of the fatal error.

Diagnostic copies/logs stayed under the existing analysis 13 directory, sharing
its expiry boundary and lock. Its terminal outcome was not reset or extended.
No fixture/catalog data was modified. The idle local worker was restarted to load
the diagnostic code; no deployment occurred. The proposed fresh API upload was
interrupted before its execution was confirmed and is not claimed as verified.

Changes: `files/audiveris_processor.py` validates export after an exit-zero process,
uses stable error codes, and preserves up to four 128-KiB log tails privately in
the session's diagnostics directory before removing the recognizer workspace.
No full OMR project is archived by normal failure handling. Diagnostic write
failure preserves the original exception. Success preserves canonical XML and
normal workspace cleanup. `files/tasks.py` persists safe typed recognition outcomes.
`files/outcomes.py` defines the approved feedback; `files/jobs.py` returns it for
PDF/image recognition failures while retaining terminal compatibility, actual
failure stage and machine-readable code. Audio/dispatch messages remain separate.
The existing frontend consumes this message without changes. The current local
container confirmed the approved text in score 13's persisted-status response.

Verification with `.venv-p1/Scripts/python.exe`, isolated test settings:

- `manage.py test files --settings=tests.settings -v 1`: **143 passed**, zero skips,
  exit 0 (134 prior checks plus nine recognition checks).
- `manage.py test files.reliability.baseline --settings=tests.settings -v 1`:
  intentionally zero tests, exit 0.
- `git diff --check`: passed; line-ending normalization notices only.

Nine new checks cover zero-exit/no-export handling, precise barline classification,
incomplete-transcription feedback, bounded logs and P6 expiry deletion, timeout
logs, unchanged successful XML/MXL, pollable safe cause/approved message, existing
generic failure and audio compatibility, and log-storage failure preserving the
original error. A pre-existing Windows process-death check intermittently saw a
busy lock immediately after termination. It now requires release within three
seconds, matching eventual cleanup rather than assuming synchronous OS release;
a permanently held lock still fails the check. Production cleanup behavior is
unchanged. Ignored transcripts: `tests/.runtime/recognition-{passing,baseline,targeted}.log`.

P2 remains VERIFY. These real failing reruns establish a reproduced recognizer
fault, not passing OMR fidelity or general PDF/image/audio acceptance. The approved
message lists possible factors without attributing this specific fault to quality.
No frontend change, commit, push or deployment performed.
