"""P5 outcomes: operational availability, independent of musical interpretation."""
import json
import re
from pathlib import Path
from django.conf import settings

RECOGNITION_FAILURE_MESSAGE = (
    "We couldn’t recognize this score. Image quality or complex notation may contribute. "
    "Try a different PDF export or a clear scan."
)

ANALYSES = ("parts", "chords", "time_signature", "notable_elements", "score_structure",
            "measures", "instrumentation", "meter_changes", "tempo_analysis",
            "key_analysis", "harmony", "accidental_observations", "analysis_references")


def read_results(value):
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except (ValueError, TypeError):
            return {"error": "Stored results are unreadable", "code": "invalid_stored_results"}
    return value if isinstance(value, dict) else {}


def has_error(value):
    if isinstance(value, dict):
        return bool(value.get("error")) or value.get("status") == "failed" or any(has_error(v) for v in value.values())
    if isinstance(value, list):
        return any(has_error(v) for v in value)
    return isinstance(value, str) and (value == "Error" or value.startswith("Error:"))


def redact_errors(value):
    if isinstance(value, dict):
        return {k: "Component could not be completed." if k == "error" and v else redact_errors(v) for k, v in value.items()}
    if isinstance(value, list):
        return [redact_errors(v) for v in value]
    if isinstance(value, str) and (value == "Error" or value.startswith("Error:")):
        return "Error: Component unavailable"
    return value


def limited(value):
    if isinstance(value, dict):
        return (value.get("complete") is False or value.get("status") in
                {"unsupported", "unavailable", "conflicting", "unsupported_timeline"}
                or any(limited(v) for v in value.values()))
    if isinstance(value, list):
        return any(limited(v) for v in value)
    return False


def outcome(status, stage, code, message, outputs=()):
    return dict(status=status, stage=stage, code=code, message=message, available_outputs=list(outputs))


def source_codes(value):
    codes = set()
    def visit(item):
        if isinstance(item, dict):
            for key, child in item.items():
                if key in {"code", "navigation"} and isinstance(child, str) and child != "none" and re.fullmatch(r"[a-z][a-z0-9_]{0,79}", child):
                    codes.add(child)
                visit(child)
        elif isinstance(item, list):
            for child in item:
                visit(child)
    visit(value)
    return sorted(codes)


def component(name, value, stage="ANALYZING_SCORE"):
    if has_error(value):
        return outcome("failed", stage, name + "_failed", name.replace("_", " ") + " could not be completed.")
    if limited(value):
        result = outcome("partial", stage, name + "_limited", name.replace("_", " ") + " has incomplete or unsupported findings; consult its source codes and structured output.", [name])
        result["source_codes"] = source_codes(value)
        return result
    if value is None or value == [] or value == {} or value in ("Not specified", "No time signature found") or (isinstance(value, dict) and value.get("status") == "absent"):
        return outcome("absent", stage, name + "_absent", "No applicable finding is available.")
    return outcome("success", stage, name + "_available", "Output is available.", [name])


def available(score, name):
    root = Path(settings.TEMP_STORAGE_DIR) / str(score.id)
    path = root / ("output.xml" if name == "notation" else f"{score.id}.mid")
    url = score.musicxml_url if name == "notation" else score.midi_url
    try:
        return bool(url and not has_error(url) and path.is_file() and path.stat().st_size)
    except OSError:
        return False


def finalize(score, results, recognition=None, failure_stage=None, refresh_artifacts=True):
    """Keep legacy values; new outcomes contain only safe messages and output names."""
    results = read_results(results)
    comps = dict(results.get("processing", {}).get("components", {}))
    if recognition:
        comps["recognition"] = recognition
    comps.setdefault("recognition", outcome("absent", "VALIDATING", "recognition_unknown", "Recognition outcome is unavailable."))
    notation = available(score, "notation") if refresh_artifacts else score.processed
    midi = available(score, "midi") if refresh_artifacts else comps.get("midi", {}).get("status") == "success"
    for name, present, stage in (("notation", notation, "GENERATING_MUSICXML"), ("midi", midi, "GENERATING_MIDI")):
        if not refresh_artifacts:
            continue
        comps[name] = outcome("success" if present else "failed", stage, name + ("_available" if present else "_unavailable"),
                              "Output is available." if present else "Output is unavailable.", [name] if present else [])
    comps["events"] = component("musical_identity", results.get("musical_identity"), "EXTRACTING_EVENTS")
    for name in ANALYSES:
        comps[name] = component(name, results.get("analysis_errors", {}).get(name, results.get(name)))
    text = results.get("text_content")
    if not text or (isinstance(text, dict) and (text.get("status") == "not_applicable" or set(text) == {"message"})):
        comps["text"] = outcome("not_applicable", "EXTRACTING_TEXT", "text_not_applicable", "No extracted text is available.")
    else:
        comps["text"] = component("text_content", text, "EXTRACTING_TEXT")
    comps.setdefault("summary", outcome("not_applicable", "GENERATING_SUMMARY", "summary_not_requested", "Optional summary has not been requested."))
    if results.get("error") and not failure_stage:
        failure_stage = results.get("failure_stage", "ANALYZING_SCORE")
    if failure_stage:
        comps["pipeline"] = outcome("failed", failure_stage, "pipeline_failed", "Processing stopped at this stage.")
    bad = any(c["status"] in {"failed", "partial"} for c in comps.values())
    status = "failed" if not notation else "partial" if bad else "success"
    score.processed = notation
    results["schema_version"] = 2
    results["processing"] = dict(schema_version=1, status=status, terminal=True, components=comps,
        available_outputs=[n for n, c in comps.items() if c["available_outputs"]],
        processed_semantics="Canonical notation is usable; consult components for analysis and playback availability.")
    return redact_errors(results)
