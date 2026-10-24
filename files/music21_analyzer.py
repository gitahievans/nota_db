import copy
from fractions import Fraction
from music21 import (
    converter,
    chord,
    meter,
    note,
    articulations,
    dynamics,
    stream,
    instrument,
    layout,
    tempo,
)
import logging
import json
from typing import Dict, List, Any, Optional, Tuple
from collections import defaultdict, Counter
from django.conf import settings

logger = logging.getLogger(__name__)


class MusicAnalysisOptimizer:
    """Optimized music analysis with caching and efficient traversal"""

    def __init__(self, score_stream, source_identity=None):
        self.score_stream = score_stream
        self.parts = list(score_stream.parts) if score_stream.parts else []
        self.analysis_cache = {}
        self._elements_cache = None
        self._notes_cache = None
        self.identity_state = source_identity
        self.source_identity = source_identity if source_identity and source_identity.get("complete") else None

    def _part_reference(self, part):
        if self.source_identity is None:
            return f"p{self.parts.index(part)}", None
        source_ids = {i.partId for i in part.getInstruments() if i.partId}
        matches = [p for p in self.source_identity["parts"] if p["xml_id"] in source_ids]
        if len(matches) != 1:
            return None, None
        staff = str(part.id).rsplit("-Staff", 1)[-1] if isinstance(part, stream.PartStaff) else None
        return matches[0]["id"], staff

    def _chord_span(self, c, chordified, part):
        pid, staff = self._part_reference(part)
        start = c.getOffsetInHierarchy(chordified)
        if self.source_identity:
            measure = c.getContextByClass(stream.Measure)
            ms = list(chordified.getElementsByClass(stream.Measure))
            mi = ms.index(measure) if measure in ms else None
            match = next((m for m in self.source_identity["measures"]
                          if m["part_id"] == pid and m["order"] == mi), None)
            if match and match["score_onset"] is not None:
                start = Fraction(match["score_onset"]) + Fraction(c.getOffsetInHierarchy(measure))
            else:
                return {"status": "unavailable", "part_id": None}
        return {"part_id": pid, "staff": staff, "start": str(start),
                "duration": str(c.duration.quarterLength)}

    def get_all_elements(self, force_refresh=False):
        """Cache all elements for efficient repeated access"""
        if self._elements_cache is None or force_refresh:
            logger.info("Caching all musical elements for analysis")
            self._elements_cache = list(self.score_stream.recurse())
            logger.info(f"Cached {len(self._elements_cache)} elements")
        return self._elements_cache

    def get_all_notes(self, force_refresh=False):
        """Cache all notes for efficient repeated access"""
        if self._notes_cache is None or force_refresh:
            elements = self.get_all_elements(force_refresh)
            self._notes_cache = [el for el in elements if isinstance(el, note.Note)]
            logger.info(f"Cached {len(self._notes_cache)} notes")
        return self._notes_cache

    def _iter_articulations(self):
        """Yield markings once per note/chord event, including distinct member marks.

        Parsed MusicXML normally promotes member articulations to the chord;
        constructed streams can retain them on members. Identity deduplication
        within each event handles aliases without merging distinct markings.
        """
        elements = self.get_all_elements()
        member_ids = {id(n) for el in elements if isinstance(el, chord.Chord)
                      for n in el.notes}
        seen_events = set()
        for element in elements:
            if isinstance(element, chord.Chord):
                owners = (element, *element.notes)
            elif isinstance(element, note.Note) and id(element) not in member_ids:
                owners = (element,)
            else:
                continue
            if id(element) in seen_events:
                continue
            seen_events.add(id(element))
            seen_markings = set()
            for owner in owners:
                for marking in owner.articulations:
                    if id(marking) not in seen_markings:
                        seen_markings.add(id(marking))
                        yield marking

    def analyze_key(self) -> str:
        """Legacy labelled estimate; written signatures live in key_analysis."""
        try:
            if not self.score_stream.recurse().notes:
                return "Not specified"
            estimate = self.score_stream.toSoundingPitch(inPlace=False).analyze("KrumhanslSchmuckler")
            return f"Estimated tonal key: {estimate}"
        except Exception:
            return "Not specified"

    def analyze_parts(self) -> List[str]:
        """Optimized part analysis"""
        cache_key = "parts_analysis"
        if cache_key not in self.analysis_cache:
            try:
                if not self.parts:
                    self.analysis_cache[cache_key] = ["No parts detected"]
                    logger.warning("No parts found in MusicXML")
                else:
                    part_names = []
                    for part in self.parts:
                        part_name = getattr(part, "partName", None)
                        part_names.append(part_name if part_name else "Unnamed Part")
                        logger.info(f"Part ID: {part.id}, PartName: {part_name}")
                    self.analysis_cache[cache_key] = part_names
                    logger.info(f"Detected parts: {part_names}")
            except Exception as e:
                logger.error(f"Part analysis failed: {str(e)}")
                self.analysis_cache[cache_key] = [f"Error: {str(e)}"]
        return self.analysis_cache[cache_key]

    def analyze_chords(self, max_chords=None) -> List[Dict[str, Any]]:
        """Complete simultaneous sonorities; max_chords is retained but never truncates."""
        if self.identity_state is not None and not self.identity_state.get("complete"):
            return []
        if self.source_identity:
            from .tonal_analysis import harmony_analysis
            if "harmony" not in self.analysis_cache:
                self.analysis_cache["harmony"] = harmony_analysis(self.source_identity)
            return [{"pitch": s["suggestion"]["label"] if s["suggestion"] else "Unlabelled sonority",
                     "offset": float(Fraction(s["start"])), "sonority_id": s["id"],
                     "span": {"part_id": None, "start": s["start"], "duration": s["duration"]},
                     "event_ids": s["event_ids"]}
                    for s in self.analysis_cache["harmony"]["sonorities"]]
        # Internal stream-only callers have no served-artifact revision to reference.
        from .tonal_analysis import describe_sonority
        combined = self.score_stream.toSoundingPitch(inPlace=False).chordify()
        result = []
        for c in combined.recurse().getElementsByClass(chord.Chord):
            _, suggestion = describe_sonority([p.ps for p in c.pitches], [p.nameWithOctave for p in c.pitches])
            start = c.getOffsetInHierarchy(combined)
            result.append({"pitch": suggestion["label"] if suggestion else "Unlabelled sonority",
                           "offset": float(start), "span": {"part_id": None,
                           "start": str(start), "duration": str(c.duration.quarterLength)}})
        return result

    def analyze_time_signature(self) -> str:
        """Optimized time signature analysis"""
        cache_key = "time_signature_analysis"
        if cache_key not in self.analysis_cache:
            try:
                time_sigs = self.score_stream.recurse().getElementsByClass(
                    meter.TimeSignature
                )
                time_sig = time_sigs.first() if time_sigs else None
                result = (
                    str(time_sig.ratioString) if time_sig else "No time signature found"
                )
                self.analysis_cache[cache_key] = result
                logger.info(f"Detected time signature: {result}")
            except Exception as e:
                logger.error(f"Time signature analysis failed: {str(e)}")
                self.analysis_cache[cache_key] = f"Error: {str(e)}"
        return self.analysis_cache[cache_key]

    def analyze_notable_elements(self) -> Dict[str, Any]:
        """Analyze markings using cached elements and legacy accidental scope."""
        cache_key = "notable_elements_analysis"
        if cache_key not in self.analysis_cache:
            try:
                notable_elements = {
                    "accidentals": {
                        "sharps": 0,
                        "flats": 0,
                        "naturals": 0,
                        "others": 0,
                        "has_accidentals": False,
                    },
                    "articulations": {
                        "staccato": {"count": 0, "has_staccato": False},
                        "accent": {"count": 0, "has_accent": False},
                        "tenuto": {"count": 0, "has_tenuto": False},
                    },
                    "dynamics": {"values": [], "has_dynamics": False},
                }

                # Preserve legacy pitch-alteration counts on standalone notes.
                notes = self.get_all_notes()
                dynamics_set = set()

                # Process notes efficiently
                for element in notes:
                    # Accidentals analysis
                    if element.pitch.accidental is not None:
                        notable_elements["accidentals"]["has_accidentals"] = True
                        acc_name = element.pitch.accidental.name
                        if acc_name == "sharp":
                            notable_elements["accidentals"]["sharps"] += 1
                        elif acc_name == "flat":
                            notable_elements["accidentals"]["flats"] += 1
                        elif acc_name == "natural":
                            notable_elements["accidentals"]["naturals"] += 1
                        else:
                            notable_elements["accidentals"]["others"] += 1

                # Count notation markings, not the number of affected pitches.
                for art in self._iter_articulations():
                    if isinstance(art, articulations.Staccato):
                        notable_elements["articulations"]["staccato"]["count"] += 1
                    elif isinstance(art, articulations.Accent):
                        notable_elements["articulations"]["accent"]["count"] += 1
                    elif isinstance(art, articulations.Tenuto):
                        notable_elements["articulations"]["tenuto"]["count"] += 1
                for name, values in notable_elements["articulations"].items():
                    values[f"has_{name}"] = values["count"] > 0

                # Process dynamics separately (less common)
                for element in self.get_all_elements():
                    if isinstance(element, dynamics.Dynamic):
                        dynamics_set.add(element.value)
                        notable_elements["dynamics"]["has_dynamics"] = True

                notable_elements["dynamics"]["values"] = sorted(list(dynamics_set))

                # Generate visualization data
                notable_elements["visualizations"] = self._create_visualization_data(
                    notable_elements
                )

                self.analysis_cache[cache_key] = notable_elements
                logger.info("Detected notable elements from cached score elements")
            except Exception as e:
                logger.error(f"Notable elements analysis failed: {str(e)}")
                self.analysis_cache[cache_key] = {"error": f"Error: {str(e)}"}
        return self.analysis_cache[cache_key]

    def _create_visualization_data(self, notable_elements: Dict) -> Dict:
        """Create visualization data efficiently"""
        chart_data = {
            "notable_elements_chart": {
                "type": "bar",
                "data": {
                    "labels": [
                        "Sharps",
                        "Flats",
                        "Naturals",
                        "Other Accidentals",
                        "Staccato",
                        "Accent",
                        "Tenuto",
                    ],
                    "datasets": [
                        {
                            "label": "Count of Notable Elements",
                            "data": [
                                notable_elements["accidentals"]["sharps"],
                                notable_elements["accidentals"]["flats"],
                                notable_elements["accidentals"]["naturals"],
                                notable_elements["accidentals"]["others"],
                                notable_elements["articulations"]["staccato"]["count"],
                                notable_elements["articulations"]["accent"]["count"],
                                notable_elements["articulations"]["tenuto"]["count"],
                            ],
                            "backgroundColor": [
                                "#FF6384",
                                "#FF6384",
                                "#FF6384",
                                "#FF6384",
                                "#36A2EB",
                                "#36A2EB",
                                "#36A2EB",
                            ],
                        }
                    ],
                },
                "options": {
                    "scales": {
                        "y": {
                            "beginAtZero": True,
                            "title": {"display": True, "text": "Count"},
                        },
                        "x": {"title": {"display": True, "text": "Element"}},
                    },
                    "plugins": {
                        "title": {
                            "display": True,
                            "text": "Notable Musical Elements",
                        }
                    },
                },
            }
        }

        # Add dynamics to chart if present
        if notable_elements["dynamics"]["values"]:
            chart_data["notable_elements_chart"]["data"]["labels"].extend(
                notable_elements["dynamics"]["values"]
            )
            chart_data["notable_elements_chart"]["data"]["datasets"][0]["data"].extend(
                [1] * len(notable_elements["dynamics"]["values"])
            )
            chart_data["notable_elements_chart"]["data"]["datasets"][0][
                "backgroundColor"
            ].extend(["#FFCE56"] * len(notable_elements["dynamics"]["values"]))

        return chart_data

    def analyze_score_structure(self) -> Dict[str, Any]:
        """Optimized score structure analysis"""
        cache_key = "score_structure_analysis"
        if cache_key not in self.analysis_cache:
            try:
                score_structure = {
                    "score_type": "unknown",
                    "ensemble_type": "unknown",
                    "music_type": "unknown",
                    "parts": [],
                    "instruments": [],
                }

                # Basic part information
                score_structure["parts"] = [
                    getattr(part, "partName", part.id if part.id else f"Part {i+1}")
                    for i, part in enumerate(self.parts)
                ]

                # Determine score type
                staff_groups = self.score_stream.getElementsByClass(layout.StaffGroup)
                staves = self.score_stream.recurse().getElementsByClass(layout.Staff)
                num_staves = len(staves)
                num_parts = len(self.parts)

                if num_parts == 0:
                    score_structure["score_type"] = "empty"
                elif num_staves >= num_parts and not any(
                    sg.systemDecoration == "brace" for sg in staff_groups
                ):
                    score_structure["score_type"] = "open"
                else:
                    score_structure["score_type"] = "closed"

                logger.info(
                    f"Score type: {score_structure['score_type']} (staves: {num_staves}, parts: {num_parts})"
                )

                # Analyze instruments and detect lyrics efficiently
                lyrics_found = False
                instruments = []

                for part in self.parts:
                    # Get instrument
                    instr = part.getElementsByClass(instrument.Instrument).first()
                    if instr and instr.instrumentName:
                        instruments.append(instr.instrumentName)
                    else:
                        instruments.append(
                            score_structure["parts"][self.parts.index(part)]
                        )

                    # Check for lyrics (stop at first occurrence)
                    if not lyrics_found:
                        for n in part.recurse().getElementsByClass(note.Note):
                            if n.lyrics:
                                lyrics_found = True
                                break

                score_structure["instruments"] = instruments

                # Determine music type
                if lyrics_found:
                    score_structure["music_type"] = (
                        "vocal"
                        if all(
                            "voice" in instr.lower()
                            or part_name.lower() in ["soprano", "alto", "tenor", "bass"]
                            for instr, part_name in zip(
                                instruments, score_structure["parts"]
                            )
                        )
                        else "mixed"
                    )
                else:
                    score_structure["music_type"] = "instrumental"

                # Efficient ensemble type detection
                score_structure["ensemble_type"] = self._detect_ensemble_type(
                    score_structure, instruments
                )

                self.analysis_cache[cache_key] = score_structure
                logger.info(f"Detected score structure: {score_structure}")
            except Exception as e:
                logger.error(f"Score structure analysis failed: {str(e)}")
                self.analysis_cache[cache_key] = {"error": f"Error: {str(e)}"}
        return self.analysis_cache[cache_key]

    def analyze_measures(self) -> Dict[str, Any]:
        """Analyze number of measures/bars in the score"""
        cache_key = "measures_analysis"
        if cache_key not in self.analysis_cache:
            try:
                measures_data = {
                    "total_measures": 0,
                    "measures_per_part": [],
                    "has_pickup": False,
                    "incomplete_measures": 0,
                }

                if not self.parts:
                    # Try to get measures from the main score stream
                    measures = self.score_stream.getElementsByClass(stream.Measure)
                    measures_data["total_measures"] = len(measures)
                    logger.info(f"Found {len(measures)} measures in score stream")
                else:
                    # Analyze each part
                    for i, part in enumerate(self.parts):
                        part_measures = part.getElementsByClass(stream.Measure)
                        part_name = getattr(part, "partName", f"Part {i+1}")
                        measures_count = len(part_measures)

                        measures_data["measures_per_part"].append(
                            {"part_name": part_name, "measure_count": measures_count}
                        )

                        # Check for pickup measure (incomplete first measure)
                        if part_measures and hasattr(part_measures[0], "barDuration"):
                            expected_duration = part_measures[
                                0
                            ].barDuration.quarterLength
                            actual_duration = part_measures[0].duration.quarterLength
                            if actual_duration < expected_duration:
                                measures_data["has_pickup"] = True

                        # Count incomplete measures
                        for measure in part_measures:
                            if hasattr(measure, "barDuration") and hasattr(
                                measure, "duration"
                            ):
                                if (
                                    measure.duration.quarterLength
                                    < measure.barDuration.quarterLength
                                ):
                                    measures_data["incomplete_measures"] += 1

                    # Set total measures as the maximum from all parts
                    if measures_data["measures_per_part"]:
                        measures_data["total_measures"] = max(
                            part["measure_count"]
                            for part in measures_data["measures_per_part"]
                        )

                self.analysis_cache[cache_key] = measures_data
                logger.info(f"Detected {measures_data['total_measures']} measures")
            except Exception as e:
                logger.error(f"Measures analysis failed: {str(e)}")
                self.analysis_cache[cache_key] = {"error": f"Error: {str(e)}"}
        return self.analysis_cache[cache_key]

    def analyze_instrumentation(self) -> Dict[str, Any]:
        """Analyze instrumentation and instruments used"""
        cache_key = "instrumentation_analysis"
        if cache_key not in self.analysis_cache:
            try:
                instrumentation_data = {
                    "instruments": [],
                    "instrument_families": {},
                    "total_parts": len(self.parts),
                    "unique_instruments": set(),
                }

                family_mapping = {
                    "piano": "keyboard",
                    "violin": "strings",
                    "viola": "strings",
                    "cello": "strings",
                    "bass": "strings",
                    "guitar": "strings",
                    "flute": "woodwinds",
                    "clarinet": "woodwinds",
                    "oboe": "woodwinds",
                    "bassoon": "woodwinds",
                    "saxophone": "woodwinds",
                    "trumpet": "brass",
                    "horn": "brass",
                    "trombone": "brass",
                    "tuba": "brass",
                    "drums": "percussion",
                    "timpani": "percussion",
                    "voice": "vocal",
                    "soprano": "vocal",
                    "alto": "vocal",
                    "tenor": "vocal",
                    "bass": "vocal",
                }

                for i, part in enumerate(self.parts):
                    # Get instrument information
                    instr = part.getElementsByClass(instrument.Instrument).first()
                    part_name = getattr(part, "partName", f"Part {i+1}")

                    instrument_info = {
                        "part_name": part_name,
                        "instrument_name": None,
                        "instrument_family": "unknown",
                        "midi_program": None,
                    }

                    if instr:
                        instrument_info["instrument_name"] = instr.instrumentName
                        instrument_info["midi_program"] = getattr(
                            instr, "midiProgram", None
                        )

                        # Determine instrument family
                        instr_name_lower = (
                            instr.instrumentName.lower() if instr.instrumentName else ""
                        )
                        for keyword, family in family_mapping.items():
                            if keyword in instr_name_lower:
                                instrument_info["instrument_family"] = family
                                break
                    else:
                        # Try to infer from part name
                        part_name_lower = part_name.lower()
                        for keyword, family in family_mapping.items():
                            if keyword in part_name_lower:
                                instrument_info["instrument_family"] = family
                                instrument_info["instrument_name"] = part_name
                                break

                    instrumentation_data["instruments"].append(instrument_info)

                    # Track unique instruments and families
                    if instrument_info["instrument_name"]:
                        instrumentation_data["unique_instruments"].add(
                            instrument_info["instrument_name"]
                        )

                    family = instrument_info["instrument_family"]
                    if family not in instrumentation_data["instrument_families"]:
                        instrumentation_data["instrument_families"][family] = 0
                    instrumentation_data["instrument_families"][family] += 1

                # Convert set to list for JSON serialization
                instrumentation_data["unique_instruments"] = list(
                    instrumentation_data["unique_instruments"]
                )

                self.analysis_cache[cache_key] = instrumentation_data
                logger.info(
                    f"Detected {len(instrumentation_data['instruments'])} instruments"
                )
            except Exception as e:
                logger.error(f"Instrumentation analysis failed: {str(e)}")
                self.analysis_cache[cache_key] = {"error": f"Error: {str(e)}"}
        return self.analysis_cache[cache_key]

    def _location(self, element):
        measure = element.getContextByClass(stream.Measure)
        part = element.getContextByClass(stream.Part)
        pid, staff = self._part_reference(part) if part in self.parts else (None, None)
        ms = list(part.getElementsByClass(stream.Measure)) if part is not None else []
        mi = ms.index(measure) if measure in ms else None
        local = element.getOffsetInHierarchy(measure) if measure is not None else None
        onset = element.getOffsetInHierarchy(self.score_stream)
        if self.source_identity:
            match = next((m for m in self.source_identity["measures"]
                          if m["part_id"] == pid and m["order"] == mi), None)
            onset = Fraction(match["score_onset"]) + Fraction(local) if match and match["score_onset"] is not None and local is not None else None
        return {"score_onset": str(onset) if onset is not None else None,
                "measure_onset": str(local) if local is not None else None,
                "part_id": pid, "staff": staff,
                "measure_id": f"{pid}:m{mi}" if mi is not None and pid else None}

    def analyze_meter_changes(self) -> Dict[str, Any]:
        """Compare chronological markings within each part, then reconcile copies."""
        signatures, changes = {}, {}
        for pi, part in enumerate(self.parts):
            previous = None
            markings = sorted(part.recurse().getElementsByClass(meter.TimeSignature),
                              key=lambda t: t.getOffsetInHierarchy(self.score_stream))
            for ts in markings:
                loc = self._location(ts)
                if loc["score_onset"] is None:
                    continue
                offset = float(Fraction(loc["score_onset"]))
                signature = ts.ratioString
                existing = signatures.get(signature)
                if existing is None or offset < existing["first_occurrence"]:
                    signatures[signature] = {"signature": signature, "numerator": ts.numerator,
                        "denominator": ts.denominator, "first_occurrence": offset}
                if previous is not None and previous != signature:
                    key = (offset, previous, signature)
                    if key not in changes:
                        m = ts.getContextByClass(stream.Measure)
                        changes[key] = {"from_signature": previous, "to_signature": signature,
                            "offset": offset, "measure": m.number if m is not None else None,
                            "locations": []}
                    changes[key]["locations"].append(loc)
                previous = signature
        result = sorted(changes.values(), key=lambda c: c["offset"])
        return {"time_signatures": sorted(signatures.values(), key=lambda t: t["first_occurrence"]),
                "changes": result, "total_changes": len(result), "has_meter_changes": bool(result)}

    def analyze_tempo(self) -> Dict[str, Any]:
        """Structured map; the HTTP legacy projection is a separate display string."""
        from .tonal_analysis import tempo_analysis
        if self.identity_state is not None:
            return tempo_analysis(self.identity_state)
        # Stream-only analysis must distinguish text-derived speed from explicit numbers.
        markings = []
        for el in self.score_stream.recurse().getElementsByClass(tempo.MetronomeMark):
            loc = self._location(el)
            if el.number is not None and not el.numberImplicit:
                value = str(el.getQuarterBPM())
                kind = "sound_tempo"
            else:
                from xml.sax.saxutils import escape
                value = "<words>" + escape(el.text or "Tempo text") + "</words>"
                kind = "words"
            markings.append({"id": f"stream-tempo{len(markings)}", "kind": kind,
                             "value": value, "sources": [{"location": loc}]})
        return tempo_analysis({"markings": markings})

    def _offset_to_measure(self, offset):
        """Legacy numeric label; absent when no real containing measure exists."""
        if not self.parts:
            return None
        measures = list(self.parts[0].getElementsByClass(stream.Measure))
        for m in reversed(measures):
            start = float(m.getOffsetInHierarchy(self.score_stream))
            if start <= offset < start + float(m.duration.quarterLength):
                return m.number
        return None

    def _detect_ensemble_type(
        self, score_structure: Dict, instruments: List[str]
    ) -> str:
        """Efficiently detect ensemble type"""
        part_names_lower = [name.lower() for name in score_structure["parts"]]

        # Quick SATB detection by name
        if len(self.parts) == 4 and all(
            any(role in name for role in ["soprano", "alto", "tenor", "bass"])
            for name in part_names_lower
        ):
            return "SATB"

        # Common ensemble patterns
        if any("piano" in instr.lower() for instr in instruments):
            if len(self.parts) <= 2:
                return "Piano Solo"

        if (
            any("violin" in instr.lower() for instr in instruments)
            and len(self.parts) == 4
        ):
            return "String Quartet"

        # SATB detection by pitch range (more expensive, done last)
        if len(self.parts) == 4:
            try:
                pitch_ranges = []
                for part in self.parts:
                    midi_pitches = [
                        n.pitch.midi
                        for n in part.recurse().getElementsByClass(note.Note)
                        if n.pitch
                    ]
                    if midi_pitches:
                        pitch_ranges.append(
                            {
                                "min_midi": min(midi_pitches),
                                "max_midi": max(midi_pitches),
                            }
                        )
                    else:
                        pitch_ranges.append({"min_midi": None, "max_midi": None})

                # Check if ranges match SATB pattern
                satb_ranges = [(60, 84), (53, 72), (48, 67), (36, 60)]
                is_satb = all(
                    pr["min_midi"] is not None
                    and pr["max_midi"] is not None
                    and (pr["min_midi"] >= low - 5 and pr["max_midi"] <= high + 5)
                    for pr, (low, high) in zip(pitch_ranges, satb_ranges)
                )

                if is_satb:
                    score_structure["inferred_part_roles"] = ["Soprano", "Alto", "Tenor", "Bass"]
                    score_structure["inference_method"] = "pitch_range_heuristic"
                    return "Custom Ensemble"
            except Exception as e:
                logger.warning(f"Pitch range analysis failed: {e}")

        return "Custom Ensemble"


def analyze_with_music21(mxl_path: str, score) -> Dict[str, Any]:
    """
    Optimized Music21 analysis with improved performance and resource management
    """
    analysis = {}
    def attempt(callback):
        try:
            return callback()
        except Exception:
            logger.exception("Analysis component failed")
            return {"error": "Component could not be completed."}

    def legacy_attempt(name, callback, fallback):
        from .outcomes import has_error, outcome
        value = attempt(callback)
        if has_error(value):
            analysis.setdefault("analysis_errors", {})[name] = outcome(
                "failed", "ANALYZING_SCORE", name + "_failed", name.replace("_", " ") + " could not be completed.")
            return fallback
        return value

    try:
        # Parse the MusicXML file
        logger.info(f"Parsing MusicXML file: {mxl_path}")
        score_stream = converter.parse(mxl_path, forceSource=True)

        # Additive source index; failures never discard P2 notation/playback artifacts.
        from .musical_identity import build_identity
        try:
            identity = build_identity(mxl_path)
        except Exception:
            identity = {"schema_version": 1, "status": "failed", "complete": False,
                        "code": "invalid_source_index"}

        # Initialize optimizer
        optimizer = MusicAnalysisOptimizer(score_stream, source_identity=identity)

        # Initialize analysis structure
        analysis = {
            "musical_identity": identity,
            "key": None,
            "measures": {},
            "instrumentation": {},
            "tempo": {},
            "meter_changes": {},
            "parts": [],
            "chords": [],
            "time_signature": None,
        }

        # Set URLs (non-blocking operations)
        try:
            score.musicxml_url = f"/api/serve-musicxml/{score.id}/"
            logger.info(f"Set MusicXML URL for score {score.id}")
        except Exception as e:
            logger.error(f"Failed to set MusicXML URL: {str(e)}")
            score.musicxml_url = f"Error: {str(e)}"

        # Generate MIDI (potentially expensive operation)
        try:
            midi_file = settings.TEMP_STORAGE_DIR / f"{score.id}/{score.id}.mid"
            midi_file.unlink(missing_ok=True)
            copy.deepcopy(score_stream).write("midi", fp=midi_file)
            analysis["playback"] = {"status": "available", "derived_from": "canonical_displayed_xml", "synchronization": "not_guaranteed"}
            score.midi_url = f"/api/serve-midi/{score.id}/"
            logger.info(f"Generated MIDI file for score {score.id}")
        except Exception as e:
            logger.error(f"MIDI generation failed: {str(e)}")
            midi_file.unlink(missing_ok=True)
            score.midi_url = None
            analysis["playback"] = {"status": "failed", "derived_from": "canonical_displayed_xml", "error": str(e)}

        # Persist export availability before independently fallible analyses.
        type(score).objects.filter(pk=score.id, job_state="RUNNING").update(midi_url=score.midi_url)

        # Perform optimized analysis
        logger.info("Starting optimized musical analysis")

        # Core analysis using optimizer
        analysis["parts"] = legacy_attempt("parts", lambda: optimizer.analyze_parts(), [])
        analysis["chords"] = legacy_attempt("chords", lambda: optimizer.analyze_chords(), [])
        analysis["time_signature"] = legacy_attempt("time_signature", lambda: optimizer.analyze_time_signature(), "Not specified")
        analysis["notable_elements"] = attempt(lambda: optimizer.analyze_notable_elements())
        analysis["score_structure"] = attempt(lambda: optimizer.analyze_score_structure())
        analysis["measures"] = attempt(lambda: optimizer.analyze_measures())
        analysis["instrumentation"] = attempt(lambda: optimizer.analyze_instrumentation())
        analysis["meter_changes"] = attempt(lambda: optimizer.analyze_meter_changes())
        analysis["tempo_analysis"] = attempt(lambda: optimizer.analyze_tempo())
        initial = analysis["tempo_analysis"].get("initial_bpm")
        analysis["tempo"] = f"{initial:g} quarter notes/min" if initial is not None else "Not specified"
        from .tonal_analysis import key_analysis, harmony_analysis, accidental_observations
        audio = getattr(score, "source_type", None) == "audio"
        analysis["key_analysis"] = attempt(lambda: key_analysis(score_stream, identity, audio=audio))
        estimate = analysis["key_analysis"].get("estimate", {})
        analysis["key"] = ("Estimated tonal key: " + estimate["label"]
                           if estimate.get("status") == "estimated" else "Not specified")
        analysis["harmony"] = attempt(lambda: harmony_analysis(identity))
        analysis["accidental_observations"] = attempt(lambda: dict(
            schema_version=1, artifact_revision=identity.get("artifact_revision"),
            status="complete" if identity.get("complete") else "unsupported",
            observations=accidental_observations(mxl_path) if identity.get("complete") else [],
            legacy_counts="Pitch alterations on standalone notes; not printed accidental counts."))
        if audio:
            analysis["tempo_analysis"]["notation_origin"] = "inferred_audio_draft"
        else:
            analysis["tempo_analysis"]["notation_origin"] = "canonical_notation"

        if identity.get("complete"):
            from .musical_identity import anchor_analysis
            analysis["analysis_references"] = attempt(lambda: anchor_analysis(analysis, identity))

        # Load text extraction results (I/O operation)
        try:
            text_results_path = (
                settings.TEMP_STORAGE_DIR / f"{score.id}/text_results.json"
            )
            if text_results_path.exists():
                with open(text_results_path, "r", encoding="utf-8") as f:
                    text_results = json.load(f)
                analysis["text_content"] = text_results
                logger.info("Added text extraction results")
            else:
                logger.warning("No text extraction results found")
                from .outcomes import read_results
                analysis["text_content"] = read_results(score.results).get("text_content") or {
                    "message": "No text extraction results available"
                }
        except Exception as e:
            logger.error(f"Failed to load text extraction results: {str(e)}")
            analysis["text_content"] = {
                "error": f"Failed to load text extraction results: {str(e)}"
            }

        # Log summary
        logger.info(f"Analysis completed successfully:")
        logger.info(f"  - Number of parts: {len(optimizer.parts)}")
        logger.info(f"  - Key: {analysis['key']}")
        logger.info(f"  - Time signature: {analysis['time_signature']}")
        logger.info(
            f"  - Ensemble type: {analysis['score_structure'].get('ensemble_type', 'unknown')}"
        )
        logger.info(
            f"  - Total measures: {analysis['measures'].get('total_measures', 0)}"
        )
        logger.info(
            f" - Instrumentation: {analysis['instrumentation'].get('instruments', [])}"
        )
        logger.info(
            f"  - Tempo markings: {len(analysis['tempo_analysis'].get('tempo_markings', []))}"
        )
        logger.info(
            f"  - Meter changes: {len(analysis['meter_changes'].get('changes', []))}"
        )

        return analysis

    except Exception as e:
        logger.error(f"Music21 analysis failed: {str(e)}")
        analysis["failure_stage"] = "ANALYZING_SCORE" if analysis else "PARSING_MUSICXML"
        analysis["error"] = "Analysis could not be completed."
        analysis.setdefault("key", "Error")
        analysis.setdefault("tempo", {"error": "Tempo unavailable."})
        return analysis
