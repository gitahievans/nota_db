# Missing printed tempo investigation — 2026-10-24

Confirmed cause in the local running worker: Audiveris OCR has no usable language
data configured. This loses tempo markings before musical analysis or frontend
rendering. No application code, saved results, or persistent container configuration
was changed during this investigation.

## Evidence

- Current worker: `nota_db-celery-1`; current exported XML identifies Audiveris 5.6.2.
- Existing sessions 47, 48, 49 and 51 contain no `metronome`, direction `words`,
  or `credit-words` elements. Worker logs report zero tempo markings.
- Session 48's input PDF is **Canon in D**, matching screenshot 1: quarter=70
  and “Graceful, with feeling”. Its embedded PDF text contains both; its original
  recognition XML contains neither.
- `TESSDATA_PREFIX` is unset. Audiveris's `TesseractOCR.findOcrFolder()` falls
  back to its user configuration `tessdata` directory, which is empty. It does
  not automatically select Debian's system Tesseract language directory.
- Retained session 50 recognition diagnostics explicitly report:
  `TESSDATA_PREFIX: null`, `No installed OCR languages`,
  `The collection of supported languages is empty`, and
  `Missing support for 'eng' language(s)`.
- The Dockerfile installs `tesseract-ocr-eng` but does not configure
  `TESSDATA_PREFIX`. Compose files do not configure it either.

## Controlled recognition experiments

Each run used an existing PDF input, a separate temporary output folder, and a
process-local environment override. Temporary outputs were removed automatically;
original inputs, served XML, database results and worker settings were untouched.

1. Set `TESSDATA_PREFIX=/usr/share/tesseract-ocr/5/tessdata` for session 49.
   Audiveris finds English, but recognition still fails: Debian's English data
   lacks legacy engine components. Logs report
   `Could not initialize TessBaseAPI languages: eng in legacy mode` and
   `Tesseract (legacy) engine requested, but components are not present`.
   No tempo or score text is exported, despite process exit 0.
2. Set `TESSDATA_PREFIX=/app/audiveris/app/dev/tessdata` for the same session 49
   input. This directory contains the bundled compatible English data
   (`eng.traineddata`, 23,466,654 bytes). Recognition exports quarter=82 and
   `sound tempo="82"`, plus title/composer text, previously absent.
3. Use the same bundled-data override on session 48, **Canon in D**.
   Recognition exports quarter=70, “Graceful, with feeling”, “With passion”,
   and “rit.”. Passing that newly recognized XML to the existing
   `index_musicxml` → `tempo_analysis` functions returns `status="present"`,
   `initial_bpm=70.0`, and the printed quarter=70 marking. This reproduces and
   resolves the first screenshot's missing tempo at the recognition boundary.

## Data flow and misleading wording

`files/musical_identity.py` indexes tempo from recognized MusicXML directions.
`files/tonal_analysis.py::tempo_analysis` returns `status="absent"` when that
index contains no tempo entries. Separate PDF/image text extraction is not a
tempo recovery step. `scoreanalyzr/src/components/AnalysisResults.tsx` displays
“No tempo marking specified.” for an absent result with no entries. Thus a
recognition omission is presented as a statement about the original score.

## Recommended implementation

- Configure the final application image to give Audiveris a stable path to
  compatible legacy-capable English language data. The bundled directory above
  is verified in the current worker. Verify its existence in the actual built
  image; do not assume system `tesseract-ocr-eng` is compatible.
- Add a recognition preflight or smoke check that actually exercises Audiveris
  OCR. Process exit 0 and `tesseract --list-langs` alone both missed this failure.
- Report absent recognized tempo as “No tempo marking detected in the recognized
  notation.” rather than asserting the source has no marking.
- Reprocess affected inputs after the runtime correction; existing saved results
  will not acquire the missing markings merely by changing configuration.
- Verify the other two screenshot originals once available. They were not among
  the current session inputs; their exact recognition outcomes remain untested.

## Validation

- Existing backend `files.reliability.tonal` suite in the Linux worker:
  **29 passed**, using isolated `tests.settings`.
- Existing frontend `tests/reliability.test.tsx`: **15 passed**.
- Local Windows focused backend symbolic tests: **15 passed**. A broader local
  run had 8 pipeline errors because the sandbox-compatible temporary directory
  under `tests/.runtime` is intentionally rejected by lifecycle storage guards;
  the Linux worker run above passed all 29 without that workaround.
- Two successful real Audiveris reruns recovered tempos 82 and 70; the latter
  also passed through the existing production tempo-analysis functions.
