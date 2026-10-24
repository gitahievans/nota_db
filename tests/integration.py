"""Opt-in real recognition boundary. Exit 2 means UNVERIFIED, never a skip/pass."""
import argparse
import importlib.util
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile

from files.reliability.references import FIXTURES, fixture_hashes, inventory


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("kind", choices=["omr", "audio"])
    parser.add_argument("--sample", default="01-simple-melody")
    args = parser.parse_args()
    missing = []
    if not importlib.util.find_spec("django") or not importlib.util.find_spec("music21"):
        missing.append("Install backend Python dependencies")
    if args.kind == "omr":
        if not Path("/app/audiveris").is_dir():
            missing.append("Backend Audiveris runtime at /app/audiveris")
        if not shutil.which("java"):
            missing.append("Java runtime required by Audiveris")
        samples = {s["id"]: s for s in inventory()["primary"]}
        if args.sample not in samples:
            missing.append("Sample identity must be in manifest.json")
        else:
            sample = samples[args.sample]
            expected = sample.get("checked_observations", {}).get("first_measure")
            if not expected:
                missing.append("Reviewed first_measure pitches/quarter_durations in manifest.json")
            if sample.get("checked_observations", {}).get("printed_tempo") != "quarter=80":
                missing.append("This initial integration probe requires reviewed quarter=80 tempo (Sample 1)")
    else:
        # Future reviewed audio uses the same local inventory, never production uploads.
        sample = inventory().get("audio_reference")
        if not sample:
            missing.append("Reviewed audio_reference with source, pitches and quarter_durations in manifest.json")
        elif not all(k in sample for k in ("source", "review", "pitches", "quarter_durations")):
            missing.append("audio_reference requires source, review, pitches and quarter_durations")
        elif not (FIXTURES / sample["source"]).is_file():
            missing.append("Reviewed audio source file is absent")
        if not importlib.util.find_spec("basic_pitch"):
            missing.append("Basic Pitch 0.4.0 plus its model/backend and audio decoding dependencies")
    if missing:
        print(json.dumps({"status": "UNVERIFIED", "layer": "real-recognition", "kind": args.kind, "dependencies": missing}, indent=2))
        return 2

    os.environ["DJANGO_SETTINGS_MODULE"] = "tests.settings"
    import django
    django.setup()
    from django.test import override_settings
    from music21 import converter, note, stream, tempo
    originals = fixture_hashes()
    try:
        with tempfile.TemporaryDirectory(prefix="nota-real-recognition-") as folder:
            root = Path(folder)
            session = root / "sessions" / "1"
            session.mkdir(parents=True)
            with override_settings(BASE_DIR=root, TEMP_STORAGE_DIR=root / "sessions"):
                if args.kind == "omr":
                    from files.audiveris_processor import process_with_audiveris
                    source = FIXTURES / sample["source"]
                    target = session / ("input" + source.suffix)
                    shutil.copyfile(source, target)
                    mxl, xml = process_with_audiveris(1, source.suffix.lstrip("."), str(target))
                    if not xml or not Path(xml).exists():
                        raise AssertionError("Recognizer returned no served XML")
                    recognized = converter.parse(xml, forceSource=True)
                    compressed = converter.parse(mxl, forceSource=True)
                    first = recognized.parts[0].getElementsByClass(stream.Measure).first()
                    events = list(first.notesAndRests)
                    actual = {"pitches": [e.nameWithOctave if isinstance(e, note.Note) else "rest" for e in events], "quarter_durations": [float(e.quarterLength) for e in events]}
                    if actual != expected:
                        raise AssertionError(f"Recognition mismatch: expected {expected}, got {actual}")
                    if [p.nameWithOctave for p in recognized.pitches] != [p.nameWithOctave for p in compressed.pitches]:
                        raise AssertionError("Recognized XML/MXL pitches disagree")
                    marks = recognized.recurse().getElementsByClass(tempo.MetronomeMark)
                    if not marks or marks.first().getQuarterBPM() != 80:
                        raise AssertionError("Reviewed PDF numeric tempo quarter=80 not recognized")
                    coverage = "Sample 1 first measure pitches/durations, numeric tempo and XML/MXL pitch agreement only"
                else:
                    from files.audio_processor import transcribe_audio_to_musicxml
                    source = FIXTURES / sample["source"]
                    if not source.resolve().is_relative_to(FIXTURES.resolve()):
                        raise ValueError("Audio source must stay in local fixture directory")
                    target = session / ("input" + source.suffix)
                    shutil.copyfile(source, target)
                    output, metadata = transcribe_audio_to_musicxml(1, target)
                    draft = converter.parse(output, forceSource=True)
                    events = list(draft.flatten().notes)
                    actual = {"pitches": [n.nameWithOctave for n in events], "quarter_durations": [float(n.quarterLength) for n in events]}
                    expected = {k: sample[k] for k in actual}
                    if actual != expected:
                        raise AssertionError(f"Audio draft mismatch: {actual}; expected {expected}")
                    coverage = "Reviewed monophonic draft pitches/durations only; original recording alignment unverified"
        print(json.dumps({"status": "PASS", "layer": "real-recognition", "kind": args.kind, "coverage": coverage, "unverified": "All other passages, full-score fidelity and end-to-end deployed orchestration"}, indent=2))
        return 0
    except Exception as exc:
        print(json.dumps({"status": "FAIL", "kind": args.kind, "error": str(exc)}, indent=2))
        return 1
    finally:
        if fixture_hashes() != originals:
            raise AssertionError("Integration run modified fixture originals")


if __name__ == "__main__":
    sys.exit(main())
