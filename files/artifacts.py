"""P2 artifact boundary: preserve XML bytes; analyze/export only the served file."""
from pathlib import Path
import hashlib
import zipfile
from xml.etree import ElementTree as ET
from django.conf import settings


def notation_bytes(path):
    path = Path(path)
    if zipfile.is_zipfile(path):
        with zipfile.ZipFile(path) as archive:
            container = ET.fromstring(archive.read("META-INF/container.xml"))
            roots = container.findall(".//{*}rootfile")
            roots = [r for r in roots if r.get("media-type") == "application/vnd.recordare.musicxml+xml"] or roots
            if len(roots) != 1:
                raise ValueError("MXL must declare exactly one score root")
            data = archive.read(roots[0].attrib["full-path"])
    else:
        data = path.read_bytes()
    if ET.fromstring(data).tag != "score-partwise":
        raise ValueError("Only a single partwise MusicXML score is supported")
    return data


def canonicalize_notation(path, score_id):
    data = notation_bytes(path)
    target = Path(settings.TEMP_STORAGE_DIR) / str(score_id) / "output.xml"
    # The compressed root is authoritative; replace any stale extracted copy.
    target.write_bytes(data)
    return str(target)


def artifact_metadata(score, file_ext, source_type):
    root = Path(settings.TEMP_STORAGE_DIR) / str(score.id)
    audio = source_type == "audio"
    roles = {
        "source_upload": {"path": f"input.{file_ext}", "label": "Original recording" if audio else "Uploaded score"},
        "canonical_displayed_xml": {"path": "output.xml", "url": score.musicxml_url,
            "also_roles": ["audio_draft_notation" if audio else "recognized_musicxml"],
            "sha256": hashlib.sha256((root / "output.xml").read_bytes()).hexdigest(),
            "derived_from": "raw_preview" if audio else "source_upload"},
        "default_playback_midi": {"path": f"{score.id}.mid", "url": score.midi_url if score.midi_url and not score.midi_url.startswith("Error:") else None,
            "derived_from": "canonical_displayed_xml", "status": "available" if score.midi_url and not score.midi_url.startswith("Error:") else "failed"},
    }
    if (root / "output.mxl").exists():
        roles["recognition_archive"] = {"path": "output.mxl", "derived_from": "source_upload"}
    if audio and (root / "preview.mid").exists():
        roles["raw_preview"] = {"path": "preview.mid", "url": f"/api/serve-preview-midi/{score.id}/",
            "label": "Raw approximate transcription; not synchronized to displayed notation", "derived_from": "source_upload"}
    return {"version": 1, "owner": {"analysis_id": score.id}, "storage_root": "TEMP_STORAGE_DIR/<analysis_id>",
        "notation_quality": "approximate_audio_draft" if audio else "unverified_recognition",
        "roles": roles,
        "synchronization": {"validated_scope": "checked pitched passages with ties, tuplets and independent parts/voices",
            "unsupported": ["repeat/ending synchronization", "percussion synchronization", "transposing-instrument synchronization", "original recording alignment"]},
        "playback_limits": "Music21 export; synchronization outside checked passages is unverified"}
