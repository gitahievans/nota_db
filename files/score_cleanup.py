import logging
import statistics
from collections import defaultdict

from music21 import chord, clef, duration, instrument, meter, note, stream, tempo

logger = logging.getLogger(__name__)

BASE_ALLOWED_DURATIONS = [0.25, 1 / 3, 0.5, 2 / 3, 0.75, 1.0, 1.5, 2.0, 3.0, 4.0]


def _nearest_multiple(value: float, base: float) -> float:
    return round(value / base) * base


def _quantize_offset(value: float, aggressive: bool) -> float:
    quarter = _nearest_multiple(value, 0.25)
    if not aggressive:
        return max(0.0, quarter)
    triplet = _nearest_multiple(value, 1 / 3)
    return max(0.0, quarter if abs(quarter - value) <= abs(triplet - value) else triplet)


def _quantize_duration(value: float, aggressive: bool) -> float:
    min_duration = 0.125 if aggressive else 0.25
    allowed_durations = BASE_ALLOWED_DURATIONS if aggressive else [0.25, 0.5, 1.0, 2.0, 4.0]
    value = max(value, min_duration)
    return min(allowed_durations, key=lambda allowed: abs(allowed - value))


def _detect_time_signature(score_stream: stream.Stream) -> meter.TimeSignature:
    time_signatures = score_stream.recurse().getElementsByClass(meter.TimeSignature)
    if time_signatures:
        return meter.TimeSignature(str(time_signatures.first().ratioString))
    return meter.TimeSignature("4/4")


def _detect_tempo(score_stream: stream.Stream) -> tempo.MetronomeMark:
    tempo_marks = list(score_stream.recurse().getElementsByClass(tempo.MetronomeMark))
    for mark in tempo_marks:
        if mark.number:
            return tempo.MetronomeMark(number=mark.number)
    return tempo.MetronomeMark(number=120)


def _extract_note_events(score_stream: stream.Stream, aggressive: bool) -> list[dict]:
    events = []
    for element in score_stream.flatten().notes:
        if isinstance(element, note.Note):
            pitches = [int(element.pitch.midi)]
            velocity = getattr(element.volume, "velocity", None) or 64
        elif isinstance(element, chord.Chord):
            pitches = [int(p.midi) for p in element.pitches]
            velocity = getattr(element.volume, "velocity", None) or 64
        else:
            continue

        raw_duration = float(element.quarterLength or 0)
        if raw_duration < (0.08 if aggressive else 0.15):
            continue

        quantized_offset = _quantize_offset(float(element.offset or 0), aggressive)
        quantized_duration = _quantize_duration(raw_duration, aggressive)
        for pitch_value in pitches:
            events.append(
                {
                    "offset": quantized_offset,
                    "duration": quantized_duration,
                    "pitch": pitch_value,
                    "velocity": velocity,
                }
            )
    return events


def _dedupe_and_prune_events(events: list[dict], aggressive: bool) -> list[dict]:
    grouped = defaultdict(dict)
    for event in events:
        current = grouped[event["offset"]].get(event["pitch"])
        if current is None or event["duration"] > current["duration"]:
            grouped[event["offset"]][event["pitch"]] = event

    cleaned = []
    previous_end_by_pitch: dict[int, float] = {}
    onset_limit = 6 if aggressive else 8
    overlap_tolerance = 0.05 if aggressive else 0.01
    for offset in sorted(grouped.keys()):
        onset_events = sorted(
            grouped[offset].values(),
            key=lambda item: (item["duration"], item["velocity"]),
            reverse=True,
        )[:onset_limit]
        for event in sorted(onset_events, key=lambda item: item["pitch"]):
            previous_end = previous_end_by_pitch.get(event["pitch"], -1)
            if event["offset"] < previous_end - overlap_tolerance:
                continue
            previous_end_by_pitch[event["pitch"]] = event["offset"] + event["duration"]
            cleaned.append(event)
    return cleaned


def _looks_like_piano(events: list[dict]) -> bool:
    if len(events) < 12:
        return False
    pitches = [event["pitch"] for event in events]
    return max(pitches) - min(pitches) >= 18


def _group_events_by_offset(events: list[dict]) -> dict[float, list[dict]]:
    grouped = defaultdict(list)
    for event in events:
        grouped[event["offset"]].append(event)
    return dict(sorted(grouped.items()))


def _create_music21_element(events: list[dict]):
    pitches = [event["pitch"] for event in events]
    max_duration = max(event["duration"] for event in events)
    note_duration = duration.Duration(max_duration)
    if len(pitches) == 1:
        element = note.Note()
        element.pitch.midi = pitches[0]
    else:
        element = chord.Chord(pitches)
    element.duration = note_duration
    return element


def _assign_piano_hands(events: list[dict]) -> tuple[list[dict], list[dict], int]:
    pitches = [event["pitch"] for event in events]
    threshold = max(57, min(64, round(statistics.median(pitches))))
    right_hand = []
    left_hand = []
    for onset_events in _group_events_by_offset(events).values():
        rh_group = []
        lh_group = []
        for event in sorted(onset_events, key=lambda item: item["pitch"]):
            if event["pitch"] >= threshold + 2:
                rh_group.append(event)
            elif event["pitch"] <= threshold - 2:
                lh_group.append(event)
            elif event["pitch"] >= threshold:
                rh_group.append(event)
            else:
                lh_group.append(event)
        right_hand.extend(rh_group)
        left_hand.extend(lh_group)
    return right_hand, left_hand, threshold


def _build_single_part(events: list[dict], part_clef, part_name: str, time_signature) -> stream.Part:
    part = stream.Part()
    part.insert(0, instrument.Piano())
    part.insert(0, part_clef)
    part.insert(0, meter.TimeSignature(time_signature.ratioString))
    part.partName = part_name
    for offset, onset_events in _group_events_by_offset(events).items():
        part.insert(offset, _create_music21_element(onset_events))
    part.makeMeasures(inPlace=True)
    part.makeNotation(inPlace=True)
    return part


def normalize_score_stream(
    raw_stream: stream.Stream,
    source_type: str,
) -> tuple[stream.Score, dict]:
    if source_type != "audio":
        raise ValueError("Event reconstruction is only supported for approximate audio drafts")
    aggressive = True
    raw_note_events = _extract_note_events(raw_stream, aggressive)
    cleaned_events = _dedupe_and_prune_events(raw_note_events, aggressive)

    cleaned_score = stream.Score()
    time_signature = _detect_time_signature(raw_stream)
    tempo_mark = _detect_tempo(raw_stream)
    piano_split_used = _looks_like_piano(cleaned_events)

    cleaned_score.insert(0, tempo_mark)
    metadata = {
        "applied": True,
        "source": "audio" if aggressive else "omr",
        "transcription_quality": "draft" if aggressive else "repaired",
        "approximate": True,
        "inferred_choices": {"instrument": "piano_synthesis_default", "staves": "pitch_range_heuristic",
                             "meter": time_signature.ratioString, "tempo_bpm": tempo_mark.number,
                             "context": "MIDI context or fallback, not written recording facts"},
        "used_piano_split": piano_split_used,
        "cleanup_summary": {
            "raw_note_events": len(raw_note_events),
            "cleaned_note_events": len(cleaned_events),
        },
    }

    if piano_split_used:
        right_hand_events, left_hand_events, threshold = _assign_piano_hands(cleaned_events)
        right_part = _build_single_part(
            right_hand_events,
            clef.TrebleClef(),
            "Inferred Upper Staff",
            time_signature,
        )
        left_part = _build_single_part(
            left_hand_events,
            clef.BassClef(),
            "Inferred Lower Staff",
            time_signature,
        )
        cleaned_score.insert(0, right_part)
        cleaned_score.insert(0, left_part)
        metadata["cleanup_summary"]["piano_split_threshold"] = threshold
    else:
        average_pitch = statistics.mean(event["pitch"] for event in cleaned_events) if cleaned_events else 60
        part_clef = clef.TrebleClef() if average_pitch >= 60 else clef.BassClef()
        single_part = _build_single_part(
            cleaned_events,
            part_clef,
            "Audio Draft",
            time_signature,
        )
        cleaned_score.insert(0, single_part)

    cleaned_score.makeNotation(inPlace=True)
    return cleaned_score, metadata
