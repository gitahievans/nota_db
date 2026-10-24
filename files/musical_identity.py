"""Lossless source addressing for canonical, partwise MusicXML (schema 1).

This index does not rewrite XML or infer analytical facts. Fractions are exact
quarter-note units; XML ordinals, never displayed labels, form identities.
"""
import hashlib
from fractions import Fraction
from pathlib import Path
from xml.etree import ElementTree as ET

MAX_XML_BYTES = 16 * 1024 * 1024
MAX_EVENTS = 50000
MAX_MEASURES = 10000  # per-part measures in total


def rational(value):
    return str(Fraction(value))


def build_identity(path):
    path = Path(path)
    if path.stat().st_size > MAX_XML_BYTES:
        return {"schema_version": 1, "status": "unsupported", "code": "xml_size_limit",
                "complete": False, "limits": limits()}
    return index_musicxml(path.read_bytes())


def limits():
    return {"xml_bytes": MAX_XML_BYTES, "events": MAX_EVENTS, "part_measures": MAX_MEASURES}


def anchor_analysis(analysis, identity):
    """Explicit written spans; legacy analytical algorithms remain P4 concerns."""
    measures, events = identity["measures"], identity["events"]
    if any(m["score_onset"] is None for m in measures):
        return {"artifact_revision": identity["artifact_revision"], "status": "unavailable",
                "code": "unknown_measure_timeline"}
    duration = max((Fraction(m["score_onset"]) + Fraction(m["aligned_duration"])
                    for m in measures), default=Fraction(0))
    refs = {"artifact_revision": identity["artifact_revision"],
            "key": {"kind": "whole_score_estimate", "start": "0", "end": rational(duration),
                    "measure_ids": [m["id"] for m in measures]}, "chords": []}
    for i, c in enumerate(analysis.get("chords", [])):
        if not isinstance(c, dict) or "span" not in c:
            continue
        span = c["span"]
        if "start" not in span:
            refs["chords"].append({"legacy_index": i, "status": "unavailable"})
            continue
        if "event_ids" in c:
            start = Fraction(span["start"])
            refs["chords"].append({"legacy_index": i, "part_id": span["part_id"],
                "start": rational(start), "end": rational(start + Fraction(span["duration"])),
                "event_ids": c["event_ids"]})
            continue
        start = Fraction(span["start"])
        end = start + Fraction(span["duration"])
        members = [e["id"] for e in events if (span["part_id"] is None or e["part_id"] == span["part_id"])
                   and (span.get("staff") is None or e["staff"] == span["staff"])
                   and e["kind"] == "pitched" and Fraction(e["score_onset"]) < end
                   and Fraction(e["score_onset"]) + Fraction(e["duration"]) > start]
        refs["chords"].append({"legacy_index": i, "part_id": span["part_id"],
                                "start": rational(start), "end": rational(end), "event_ids": members})
    refs["written_context_marking_ids"] = [m["id"] for m in identity["markings"]
                                            if m["kind"] in ("key", "time", "metronome", "sound_tempo")]
    refs["aggregate_scope"] = {"kind": "whole_written_score", "start": "0", "end": rational(duration),
                               "applies_to": ["parts", "measures", "notable_elements", "instrumentation", "score_structure"]}
    if not any(e["written_pitch"] for e in events):
        refs["key"] = {"kind": "absent", "reason": "no_pitched_events"}
    return refs


def index_musicxml(data):
    revision = hashlib.sha256(data).hexdigest()
    base = {"schema_version": 1, "artifact_revision": revision,
            "revision_algorithm": "sha256_exact_served_xml", "units": "quarter_notes",
            "limits": limits(), "complete": False}
    if len(data) > MAX_XML_BYTES:
        return dict(base, status="unsupported", code="xml_size_limit")
    root = ET.fromstring(data)
    # Permit a default MusicXML namespace, retaining original bytes for revision.
    for el in root.iter():
        el.tag = el.tag.rsplit("}", 1)[-1]
    if root.tag != "score-partwise":
        return dict(base, status="unsupported", code="partwise_required")
    parts, measures, events, markings, issues = [], [], [], [], []
    navigation = any(el.tag in ("repeat", "ending", "segno", "coda") or
                     (el.tag == "sound" and any(k in el.attrib for k in
                      ("dacapo", "dalsegno", "tocoda", "fine"))) for el in root.iter())
    names = {p.get("id"): p.findtext("part-name") for p in root.findall("part-list/score-part")}
    for pi, part in enumerate(root.findall("part")):
        pid = f"p{pi}"
        parts.append({"id": pid, "xml_id": part.get("id"), "order": pi,
                      "name": names.get(part.get("id"))})
        divisions, transpositions, pitch_class_transpositions = None, {}, {}
        for mi, measure in enumerate(part.findall("measure")):
            if len(measures) >= MAX_MEASURES:
                return dict(base, status="unsupported", code="measure_limit")
            mid = f"{pid}:m{mi}"
            m = {"id": mid, "part_id": pid, "order": mi,
                 "label": measure.get("number"), "implicit": measure.get("implicit") == "yes",
                 "xml": {"part": pi, "measure": mi}}
            measures.append(m)
            if measure.get("non-controlling") == "yes":
                issues.append({"code": "non_controlling_measure_unsupported", "measure_id": mid})
            cursor, extent, previous_onset, group = Fraction(0), Fraction(0), None, None
            ni = 0
            for ci, el in enumerate(measure):
                loc = {"part_id": pid, "measure_id": mid, "measure_onset": rational(cursor)}
                if el.tag == "attributes":
                    if el.find("divisions") is not None:
                        divisions = Fraction(el.findtext("divisions"))
                        if divisions <= 0:
                            raise ValueError("MusicXML divisions must be positive")
                    for tr in el.findall("transpose"):
                        transpositions[tr.get("number", "*")] = (
                            Fraction(tr.findtext("chromatic", "0")) +
                            12 * int(tr.findtext("octave-change", "0")))
                        # Key estimation needs an independently known chromatic
                        # transposition, even when exact octaves remain unsupported.
                        pitch_class_transpositions[tr.get("number", "*")] = (
                            transpositions[tr.get("number", "*")]
                            if tr.findtext("chromatic") is not None and tr.find("double") is None else None)
                        if tr.find("double") is not None:
                            issues.append({"code": "double_transposition_unsupported", "measure_id": mid})
                    for kind in ("key", "time"):
                        for context in el.findall(kind):
                            markings.append({"kind": kind, "location": dict(loc),
                                "staff": context.get("number"),
                                "value": {c.tag: c.text for c in context},
                                "xml": {"part": pi, "measure": mi, "child": ci}})
                elif el.tag in ("backup", "forward"):
                    if divisions is None:
                        raise ValueError("Duration without divisions")
                    delta = Fraction(el.findtext("duration", "0")) / divisions
                    cursor += -delta if el.tag == "backup" else delta
                    if cursor < 0:
                        raise ValueError("MusicXML backup before measure start")
                    extent = max(extent, cursor)
                elif el.tag == "direction":
                    if el.find("offset") is not None and divisions is None:
                        raise ValueError("Direction offset without divisions")
                    offset = Fraction(el.findtext("offset", "0")) / (divisions or 1)
                    for dt in el.findall("direction-type"):
                        for mark in dt:
                            if mark.tag == "octave-shift":
                                issues.append({"code": "octave_shift_sounding_unsupported", "measure_id": mid,
                                    "pitch_class_invariant": mark.get("size", "8") in ("8", "15", "22")
                                        and mark.get("type") in ("up", "down", "continue", "stop")})
                            if mark.tag in ("metronome", "words", "dynamics"):
                                markings.append({"kind": mark.tag,
                                    "value": ET.tostring(mark, encoding="unicode"),
                                    "location": dict(loc, measure_onset=rational(cursor + offset)),
                                    "staff": el.findtext("staff"),
                                    "xml": {"part": pi, "measure": mi, "child": ci}})
                    if el.find("sound") is not None and el.find("sound").get("tempo"):
                        markings.append({"kind": "sound_tempo", "value": el.find("sound").get("tempo"),
                                         "location": dict(loc, measure_onset=rational(cursor + offset)),
                                         "staff": el.findtext("staff"),
                                         "xml": {"part": pi, "measure": mi, "child": ci}})
                elif el.tag == "note":
                    if len(events) >= MAX_EVENTS:
                        return dict(base, status="unsupported", code="event_limit")
                    eid = f"{mid}:n{ni}"
                    is_chord = el.find("chord") is not None
                    grace = el.find("grace") is not None
                    if not grace and divisions is None:
                        raise ValueError("Note duration without divisions")
                    if not grace and el.find("duration") is None:
                        raise ValueError("Non-grace note without duration")
                    duration = Fraction(0) if grace else Fraction(el.findtext("duration", "0")) / divisions
                    if duration < 0:
                        raise ValueError("Negative note duration")
                    onset = previous_onset if is_chord else cursor
                    if onset is None:
                        raise ValueError("Chord member without preceding note")
                    if not is_chord:
                        group = eid
                    pitch = el.find("pitch")
                    spelling = None if pitch is None else {
                        "step": pitch.findtext("step"), "alter": pitch.findtext("alter", "0"),
                        "octave": int(pitch.findtext("octave"))}
                    staff, voice = el.findtext("staff", "1"), el.findtext("voice", "1")
                    sounding = None
                    sounding_class = None
                    if spelling:
                        midi = (12 * (spelling["octave"] + 1) +
                                dict(C=0, D=2, E=4, F=5, G=7, A=9, B=11)[spelling["step"]] +
                                Fraction(spelling["alter"]) + transpositions.get(staff, transpositions.get("*", 0)))
                        sounding = {"midi": rational(midi), "status": "derived_from_written_transpose"}
                        chromatic = pitch_class_transpositions.get(staff, pitch_class_transpositions.get("*", 0))
                        if chromatic is not None:
                            pc = (dict(C=0, D=2, E=4, F=5, G=7, A=9, B=11)[spelling["step"]] +
                                  Fraction(spelling["alter"]) + chromatic) % 12
                            if pc.denominator == 1:
                                sounding_class = {"value": rational(pc), "status": "derived_from_written_transpose"}
                    ties = sorted({t.get("type") for t in el.findall("tie") + el.findall("notations/tied")})
                    events.append({"id": eid, "kind": "pitched" if pitch is not None else
                                   ("rest" if el.find("rest") is not None else "unpitched"),
                        "part_id": pid, "staff": staff, "voice": voice, "measure_id": mid,
                        "measure_onset": rational(onset), "duration": rational(duration),
                        "grace": grace, "chord_group": group, "written_pitch": spelling,
                        "sounding_pitch": sounding, "sounding_pitch_class": sounding_class, "ties": ties, "tie_previous": None,
                        "tie_next": None, "xml": {"part": pi, "measure": mi, "note": ni,
                                                    "id": el.get("id")}})
                    ni += 1
                    previous_onset = onset
                    extent = max(extent, onset + duration)
                    if not is_chord:
                        cursor += duration
            m["actual_duration"] = rational(extent)
            if not extent:
                issues.append({"code": "empty_measure_duration_unknown", "measure_id": mid})
    # Source measures align by ordinal across parts, not by printed number.
    lengths = {}
    for m in measures:
        lengths[m["order"]] = max(lengths.get(m["order"], Fraction(0)), Fraction(m["actual_duration"]))
    starts, position = {}, Fraction(0)
    for order in sorted(lengths):
        starts[order] = position
        position = position + lengths[order] if position is not None and lengths[order] else None
    lookup = {m["id"]: m for m in measures}
    for m in measures:
        m["score_onset"] = rational(starts[m["order"]]) if starts[m["order"]] is not None else None
        m["aligned_duration"] = rational(lengths[m["order"]])
    for item in events + [mark["location"] for mark in markings]:
        start = lookup[item["measure_id"]]["score_onset"]
        item["score_onset"] = rational(Fraction(start) + Fraction(item["measure_onset"])) if start is not None else None
    # Tie links require one unambiguous, contiguous member in the same part/staff/voice.
    pending = {}
    for event in events:
        if event["score_onset"] is None:
            continue
        key = (event["part_id"], event["staff"], event["voice"], str(event["written_pitch"]))
        if "stop" in event["ties"]:
            end_key = (key, Fraction(event["score_onset"]))
            candidates = pending.get(end_key, [])
            if len(candidates) == 1:
                prev = candidates[0]
                event["tie_previous"], prev["tie_next"] = prev["id"], event["id"]
                del pending[end_key]
            else:
                issues.append({"code": "unresolved_tie", "event_id": event["id"]})
        if "start" in event["ties"]:
            end_key = (key, Fraction(event["score_onset"]) + Fraction(event["duration"]))
            pending.setdefault(end_key, []).append(event)
    for candidates in pending.values():
        issues.extend({"code": "unresolved_tie", "event_id": e["id"]} for e in candidates)
    # Shared written markings are one finding with all source locations retained.
    shared = {}
    for mark in markings:
        key = (mark["kind"], str(mark["value"]), mark["location"]["score_onset"], mark["staff"])
        if key not in shared:
            shared[key] = {"id": f"mark{len(shared)}", "kind": mark["kind"],
                           "value": mark["value"], "sources": []}
        shared[key]["sources"].append({"location": mark["location"], "staff": mark["staff"], "xml": mark["xml"]})
    # OSMD has no dependable public XML note-id field in 1.9.0. Join by source
    # ordinal and musical coordinates; ambiguous unisons must never select arbitrarily.
    joins = {}
    for e in events:
        key = (e["part_id"], e["measure_id"], e["staff"], e["voice"],
               e["measure_onset"], e["duration"], e["kind"], str(e["written_pitch"]))
        joins.setdefault(key, []).append(e)
    for candidates in joins.values():
        for e in candidates:
            e["osmd_join"] = {"status": "candidate" if len(candidates) == 1 and
                e["kind"] != "unpitched" and not e["grace"] and e["voice"].isdigit()
                else "ambiguous_or_unsupported", "model_version": "1.9.0"}
    if any(i["code"] in ("double_transposition_unsupported", "octave_shift_sounding_unsupported") for i in issues):
        for e in events:
            if e["written_pitch"]:
                e["sounding_pitch"] = {"status": "unsupported", "midi": None}
    # Exact-pitch safeguards above remain unchanged. Only independently known
    # pitch classes survive ordinary octave shifts; unknown shift sizes and
    # doubling transposition must not inherit that exception.
    if any(i["code"] == "double_transposition_unsupported" or
           (i["code"] == "octave_shift_sounding_unsupported" and not i["pitch_class_invariant"])
           for i in issues):
        for e in events:
            e["sounding_pitch_class"] = None
    unavailable = navigation or bool(issues) or any(e["kind"] == "unpitched" or e["grace"] for e in events)
    playback = {"status": "unavailable" if unavailable else "linear_written_order",
                "navigation": "unsupported_repeats_endings_jumps" if navigation else "none",
                "seconds": "unavailable", "midi_alignment": "unverified", "occurrences": []}
    if not unavailable:
        by_id = {e["id"]: e for e in events}
        for e in events:
            if e["kind"] != "pitched" or e["tie_previous"]:
                continue
            chain, end = [e["id"]], e
            while end["tie_next"]:
                end = by_id[end["tie_next"]]
                chain.append(end["id"])
            playback["occurrences"].append({"id": f"occ:{e['id']}:0", "event_ids": chain,
                "onset": e["score_onset"], "duration": rational(
                    Fraction(end["score_onset"]) + Fraction(end["duration"]) - Fraction(e["score_onset"])),
                "sounding_pitch": e["sounding_pitch"]})
    return dict(base, status="available" if events else "absent", complete=True,
                parts=parts, measures=measures, events=events, markings=list(shared.values()),
                playback=playback, issues=issues)
