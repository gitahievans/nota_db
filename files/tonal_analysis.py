"""P4 interpretation of revision-scoped written facts; no notation mutation."""
from collections import Counter, defaultdict
from fractions import Fraction
from xml.etree import ElementTree as ET
from music21 import chord, pitch, tempo


def envelope(identity):
    return {"schema_version": 1, "artifact_revision": identity.get("artifact_revision")}


def key_analysis(score, identity, audio=False):
    result = dict(envelope(identity), signatures=[], estimate={"status": "absent", "code": "no_pitched_events",
                      "message": "No pitched content is available for key estimation."},
                  signature_origin="inferred_audio_draft" if audio else "canonical_notation",
                  limitation="A signature does not determine major/minor or establish a modulation.")
    for marking in identity.get("markings", []):
        if marking["kind"] == "key":
            value = marking["value"]
            result["signatures"].append({"marking_id": marking["id"], "written": value,
                "status": "observed" if "fifths" in value else "unsupported_nontraditional_signature",
                "sources": marking["sources"]})
    changes, by_scope = [], defaultdict(list)
    result["signature_conflicts"] = []
    for signature in result["signatures"]:
        for source in signature["sources"]:
            pid = source["location"]["part_id"]
            staves = ([source["staff"]] if source.get("staff") else
                      sorted({e["staff"] for e in identity.get("events", []) if e["part_id"] == pid}) or ["1"])
            for staff in staves:
                by_scope[(pid, staff)].append((source, signature))
    for scope, entries in by_scope.items():
        entries.sort(key=lambda item: (item[0]["location"]["score_onset"] is None,
                                      Fraction(item[0]["location"]["score_onset"] or 0)))
        previous = None
        positions = defaultdict(list)
        for source, signature in entries:
            positions[source["location"]["score_onset"]].append((source, signature))
        for position, group in positions.items():
            source, signature = group[0]
            if position is None or len({str(sig["written"]) for _, sig in group}) > 1:
                result["signature_conflicts"].append({"part_id": scope[0], "staff": scope[1],
                    "score_onset": position, "marking_ids": [sig["marking_id"] for _, sig in group],
                    "code": "unknown_location" if position is None else "conflicting_signatures"})
                previous = None
                continue
            if previous is not None and previous["written"] != signature["written"]:
                changes.append({"from_marking_id": previous["marking_id"],
                    "to_marking_id": signature["marking_id"], "location": source["location"],
                    "staff": scope[1], "interpretation": "written_signature_change_only"})
            previous = signature
    result["changes"] = changes
    result["unspecified_part_ids"] = [p["id"] for p in identity.get("parts", [])
        if not any(scope[0] == p["id"] and any(source["location"]["score_onset"] == "0" for source, _ in entries)
                   for scope, entries in by_scope.items())]
    result["signature_status"] = "present" if result["signatures"] else "unspecified"
    pitched = [e for e in identity.get("events", []) if e["kind"] == "pitched"]
    if pitched:
        unknown_octaves = any(not e["sounding_pitch"] or e["sounding_pitch"].get("midi") is None for e in pitched)
        verified_classes = octave_shift_key_content(identity, pitched) if unknown_octaves else None
        if unknown_octaves and verified_classes is None:
            reasons = sorted({issue["code"] for issue in identity.get("issues", [])
                if issue["code"] in ("octave_shift_sounding_unsupported", "double_transposition_unsupported")})
            result["estimate"] = {"status": "unsupported", "code": "unknown_sounding_pitch",
                "source_codes": reasons,
                "message": "Some sounding pitches cannot be resolved safely; no whole-score key estimate was produced."}
        else:
            try:
                # Preserve the ordinary estimator, import semantics and duration
                # weighting. The octave-only exception additionally reconciles
                # every imported pitch/duration with independently indexed content.
                concert = score.toSoundingPitch(inPlace=False)
                if verified_classes is not None and imported_key_content(concert) != verified_classes:
                    result["estimate"] = {"status": "unsupported", "code": "unverified_pitch_class_content",
                        "source_codes": ["octave_shift_sounding_unsupported"],
                        "message": "The complete pitch-class and duration content could not be verified; no whole-score key estimate was produced."}
                else:
                    estimate = concert.analyze("KrumhanslSchmuckler")
                    result["estimate"] = {"status": "estimated", "label": str(estimate),
                        "method": "music21 KrumhanslSchmuckler", "pitch_space": "sounding",
                        "correlation": estimate.correlationCoefficient,
                        "event_ids": [e["id"] for e in pitched],
                        "limitation": "Whole-score pitch-profile correlation; not a probability or local key/modulation finding."}
                    if verified_classes is not None:
                        result["estimate"].update(
                            pitch_basis="verified_sounding_pitch_classes",
                            exact_octaves="unresolved",
                            source_codes=["octave_shift_sounding_unsupported"],
                            limitation=result["estimate"]["limitation"] +
                                " All pitched events and duration weights were verified by pitch class; exact octave-shift interpretation, playback and dependent analyses remain unresolved.")
            except Exception:
                result["estimate"] = {"status": "failed", "code": "key_estimation_failed",
                    "message": "Key estimation could not be completed."}
    if not identity.get("complete"):
        result.update(signature_status="unavailable", estimate={"status": "unsupported", "code": "identity_unavailable",
            "message": "The notation index is incomplete or unavailable; no whole-score key estimate was produced."})
    return result


def octave_shift_key_content(identity, pitched):
    """Narrow exception for verified classes, never inferred exact octaves.

    Reject missing/older class metadata, any other unsupported identity issue,
    nonintegral pitch classes, and incomplete indexes. No subset is acceptable.
    """
    issues = identity.get("issues", [])
    if (not identity.get("complete") or not issues or
            any(i["code"] != "octave_shift_sounding_unsupported" or
                i.get("pitch_class_invariant") is not True for i in issues)):
        return None
    content = Counter()
    for event in pitched:
        pc = event.get("sounding_pitch_class")
        if not event.get("written_pitch") or not pc or pc.get("status") != "derived_from_written_transpose":
            return None
        try:
            value, duration = Fraction(pc["value"]), Fraction(event["duration"])
        except (KeyError, ValueError, TypeError, ZeroDivisionError):
            return None
        if value.denominator != 1 or not 0 <= value < 12 or duration < 0:
            return None
        content[(int(value), duration)] += 1
    return content


def imported_key_content(concert):
    """Mirror music21's per-chord-member weighting, retaining zero durations.

    A multiset (rather than just a summed histogram) detects missing, duplicated
    or reweighted members before permitting the whole-score exception.
    """
    content = Counter()
    for n in concert.flatten().notes:
        for p in n.pitches:
            if not float(p.ps).is_integer():
                return None
            content[(p.pitchClass, Fraction(n.quarterLength))] += 1
    return content


BEATS = {"whole": 4, "half": 2, "quarter": 1, "eighth": Fraction(1, 2),
         "16th": Fraction(1, 4), "32nd": Fraction(1, 8), "64th": Fraction(1, 16)}


def tempo_analysis(identity):
    result = dict(envelope(identity), status="absent", tempo_markings=[], bpm_changes=[],
                  initial_bpm=None, average_bpm=None, has_tempo_changes=False,
                  average_definition="Not computed: written-order markings are not elapsed-time weights.",
                  playback_default={"quarter_bpm": 120, "origin": "music21_export_default", "observed": False})
    if not identity.get("complete", True):
        return dict(result, status="unsupported", code="identity_unavailable")
    records = []
    for m in identity.get("markings", []):
        kind = m["kind"]
        if kind not in ("metronome", "sound_tempo", "words"):
            continue
        r = {"marking_id": m["id"], "sources": m["sources"], "type": kind,
             "bpm": None, "printed": None, "text": None, "origin": "explicit_numeric"}
        try:
            if kind == "sound_tempo":
                r["bpm"] = float(Fraction(m["value"]))
            else:
                el = ET.fromstring(m["value"])
                if kind == "words":
                    r.update(text="".join(el.itertext()), origin="text_unquantified")
                else:
                    unit, number = el.findtext("beat-unit"), el.findtext("per-minute")
                    dots = len(el.findall("beat-unit-dot"))
                    r["printed"] = {"beat_unit": unit, "dots": dots, "per_minute": number}
                    if unit in BEATS and number and len(el.findall("beat-unit")) == 1:
                        r["bpm"] = float(Fraction(number) * BEATS[unit] *
                                         sum((Fraction(1, 2**i) for i in range(dots + 1)), Fraction(0)))
                    else:
                        r["origin"] = "unsupported_metronome"
            if r["bpm"] is not None and r["bpm"] <= 0:
                r.update(bpm=None, origin="invalid_numeric")
        except (ValueError, ZeroDivisionError):
            r.update(bpm=None, origin="unsupported_numeric")
        records.append(r)
    # One map entry per written position and speed, retaining every source marking.
    grouped = {}
    for r in records:
        for source in r["sources"]:
            loc = source["location"]
            key = (loc["score_onset"], r["bpm"], r["text"],
                   r["origin"] if r["bpm"] is None else "numeric")
            # Unknown timelines cannot reconcile unrelated locations.
            if loc["score_onset"] is None:
                key += (loc["measure_id"], loc["measure_onset"])
            if key not in grouped:
                grouped[key] = {"offset": float(Fraction(loc["score_onset"])) if loc["score_onset"] is not None else None,
                    "bpm": r["bpm"], "origin": r["origin"], "text": r["text"],
                    "locations": [], "marking_ids": [], "printed": []}
            entry = grouped[key]
            if loc not in entry["locations"]:
                entry["locations"].append(loc)
            if r["marking_id"] not in entry["marking_ids"]:
                entry["marking_ids"].append(r["marking_id"])
            if r["printed"] and r["printed"] not in entry["printed"]:
                entry["printed"].append(r["printed"])
    entries = sorted(grouped.values(), key=lambda e: (e["offset"] is None, e["offset"] or 0))
    for entry in entries:
        entry["interpreted_quarter_bpm"] = None
        if entry["text"]:
            interpreted = tempo.TempoText(entry["text"]).getMetronomeMark()
            entry["interpreted_quarter_bpm"] = interpreted.getQuarterBPM()
    result["text_interpretation_limit"] = "Lexical music21 suggestion only; exporter may use its default instead. Not an observed or guaranteed playback speed."
    result["tempo_markings"] = entries
    result["status"] = "present" if entries else "absent"
    numeric = defaultdict(list)
    for e in entries:
        if e["bpm"] is not None and e["offset"] is not None:
            numeric[e["offset"]].append(e)
    result["conflicting_positions"] = [p for p, es in numeric.items() if len({e["bpm"] for e in es}) > 1]
    previous = None
    for pos, es in sorted(numeric.items()):
        if pos in result["conflicting_positions"]:
            previous = None
            continue
        e = es[0]
        if pos == 0:
            result["initial_bpm"] = e["bpm"]
        if previous is not None and previous != e["bpm"]:
            result["bpm_changes"].append({"from_bpm": previous, "to_bpm": e["bpm"],
                "offset": pos, "locations": e["locations"], "marking_ids": e["marking_ids"]})
        previous = e["bpm"]
    if result["conflicting_positions"]:
        result["status"] = "conflicting"
    elif any(e["offset"] is None for e in entries):
        result["status"] = "unsupported_timeline"
    result["playback_default"]["applies_at_start"] = (None if
        0 in result["conflicting_positions"] or any(e["text"] and e["offset"] in (None, 0) for e in entries)
        else result["initial_bpm"] is None)
    result["has_tempo_changes"] = bool(result["bpm_changes"])
    return result


def describe_sonority(midis, spellings):
    """Only familiar, complete triads/sevenths receive a tentative label."""
    c = chord.Chord([pitch.Pitch(midi=n) for n in sorted(set(midis))])
    bass = min(midis)
    suggestion = None
    if all(float(n).is_integer() for n in midis) and (c.isMajorTriad() or c.isMinorTriad() or
            c.isDiminishedTriad() or c.isAugmentedTriad() or c.isDominantSeventh() or c.isDiminishedSeventh()):
        # Preserve spelling for nontransposing collections, rather than MIDI respelling.
        if spellings:
            spelled = chord.Chord(spellings)
            if {p.pitchClass for p in spelled.pitches} == {p.pitchClass for p in c.pitches}:
                c = spelled
        suggestion = {"label": c.pitchedCommonName, "root": c.root().name,
                      "bass": c.bass().nameWithOctave, "inversion": c.inversion(),
                      "status": "suggested", "method": "complete_triad_or_seventh_pitch_collection",
                      "limitation": "Sonority label, not underlying harmony or harmonic function."}
    return bass, suggestion


def harmony_analysis(identity):
    base = dict(envelope(identity), status="complete", complete=True, sonorities=[],
                interpretation="simultaneous_sonorities_in_written_order",
                segmentation="Every pitched onset/end; ties join acoustically but retain written member boundaries; no merging.",
                limits=dict(identity.get("limits") or {}, harmony_memberships=MAX_HARMONY_MEMBERS))
    if not identity.get("complete"):
        return dict(base, status="unsupported", complete=False, code="identity_unavailable")
    events = [e for e in identity["events"] if e["kind"] == "pitched" and Fraction(e["duration"]) > 0]
    if any(e["score_onset"] is None or not e["sounding_pitch"] or e["sounding_pitch"].get("midi") is None for e in events):
        return dict(base, status="unsupported", complete=False, code="unknown_timeline_or_sounding_pitch")
    boundaries = defaultdict(lambda: {"start": [], "end": []})
    for e in events:
        start = Fraction(e["score_onset"])
        boundaries[start]["start"].append(e)
        boundaries[start + Fraction(e["duration"])]["end"].append(e)
    active = {}
    positions = sorted(boundaries)
    # Bound output membership, which can be quadratic for pathological overlaps.
    members = 0
    for i, start in enumerate(positions[:-1]):
        for e in boundaries[start]["end"]:
            active.pop(e["id"], None)
        for e in boundaries[start]["start"]:
            active[e["id"]] = e
        if not active:
            continue
        members += len(active)
        if members > MAX_HARMONY_MEMBERS:
            return dict(base, status="unsupported", complete=False, code="harmony_membership_limit", sonorities=[])
        es = sorted(active.values(), key=lambda e: e["id"])
        midis = [float(Fraction(e["sounding_pitch"]["midi"])) for e in es]
        names = []
        for e in es:
            w = e["written_pitch"]
            try:
                p = pitch.Pitch(step=w["step"], octave=w["octave"], accidental=float(Fraction(w["alter"])))
            except pitch.AccidentalException:
                continue
            if p.ps == float(Fraction(e["sounding_pitch"]["midi"])):
                names.append(p.nameWithOctave)
        bass, suggestion = describe_sonority(midis, names if len(names) == len(es) else [])
        base["sonorities"].append({"id": f"sonority{len(base['sonorities'])}",
            "start": str(start), "end": str(positions[i+1]), "duration": str(positions[i+1]-start),
            "event_ids": [e["id"] for e in es], "measure_ids": sorted({e["measure_id"] for e in es}),
            "part_ids": sorted({e["part_id"] for e in es}),
            "members": [{k: e[k] for k in ("id", "part_id", "staff", "voice", "measure_id", "written_pitch", "sounding_pitch", "chord_group", "ties")} for e in es],
            "sounding_midis": sorted(set(midis)), "bass_midi": bass, "suggestion": suggestion})
    if not events:
        base["status"] = "absent"
    return base


MAX_HARMONY_MEMBERS = 200000


def accidental_observations(path):
    root = ET.parse(path).getroot()
    for el in root.iter():
        el.tag = el.tag.rsplit("}", 1)[-1]
    observations = []
    for pi, part in enumerate(root.findall("part")):
        for mi, measure in enumerate(part.findall("measure")):
            for ni, n in enumerate(measure.findall("note")):
                p, accidental = n.find("pitch"), n.find("accidental")
                if p is not None:
                    observations.append({"event_id": f"p{pi}:m{mi}:n{ni}",
                        "pitch_alter": p.findtext("alter", "0"),
                        "accidental": accidental.text if accidental is not None else None,
                        "attributes": dict(accidental.attrib) if accidental is not None else {}})
    return observations
