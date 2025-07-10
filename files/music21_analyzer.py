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
)
import logging
import json
from typing import Dict, List, Any, Optional, Tuple
from collections import defaultdict, Counter
from django.conf import settings

logger = logging.getLogger(__name__)


class MusicAnalysisOptimizer:
    """Optimized music analysis with caching and efficient traversal"""

    def __init__(self, score_stream):
        self.score_stream = score_stream
        self.parts = list(score_stream.parts) if score_stream.parts else []
        self.analysis_cache = {}
        self._elements_cache = None
        self._notes_cache = None

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

    def analyze_key(self) -> str:
        """Optimized key analysis"""
        cache_key = "key_analysis"
        if cache_key not in self.analysis_cache:
            try:
                key_result = self.score_stream.analyze("key")
                self.analysis_cache[cache_key] = str(key_result)
                logger.info(f"Detected key: {self.analysis_cache[cache_key]}")
            except Exception as e:
                logger.warning(f"Key analysis failed: {str(e)}")
                self.analysis_cache[cache_key] = f"Error: {str(e)}"
        return self.analysis_cache[cache_key]

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

    def analyze_chords(self, max_chords=10) -> List[Dict[str, Any]]:
        """Optimized chord analysis with limit"""
        cache_key = f"chords_analysis_{max_chords}"
        if cache_key not in self.analysis_cache:
            try:
                chords = []
                for part in self.parts:
                    if len(chords) >= max_chords:
                        break

                    try:
                        chordified = part.chordify()
                        part_chords = chordified.recurse().getElementsByClass(
                            chord.Chord
                        )

                        for c in part_chords:
                            if len(chords) >= max_chords:
                                break
                            chord_name = c.pitchedCommonName if c.isChord else "N/A"
                            chords.append(
                                {"pitch": chord_name, "offset": float(c.offset)}
                            )
                    except Exception as part_error:
                        logger.warning(
                            f"Chord analysis failed for part {part.id}: {part_error}"
                        )
                        continue

                self.analysis_cache[cache_key] = chords
                logger.info(f"Detected {len(chords)} chords")
            except Exception as e:
                logger.error(f"Chord analysis failed: {str(e)}")
                self.analysis_cache[cache_key] = [f"Error: {str(e)}"]
        return self.analysis_cache[cache_key]

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
        """Optimized notable elements analysis with single traversal"""
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

                # Single traversal for all elements
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

                    # Articulations analysis
                    for art in element.articulations:
                        if isinstance(art, articulations.Staccato):
                            notable_elements["articulations"]["staccato"]["count"] += 1
                            notable_elements["articulations"]["staccato"][
                                "has_staccato"
                            ] = True
                        elif isinstance(art, articulations.Accent):
                            notable_elements["articulations"]["accent"]["count"] += 1
                            notable_elements["articulations"]["accent"][
                                "has_accent"
                            ] = True
                        elif isinstance(art, articulations.Tenuto):
                            notable_elements["articulations"]["tenuto"]["count"] += 1
                            notable_elements["articulations"]["tenuto"][
                                "has_tenuto"
                            ] = True

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
                logger.info(f"Detected notable elements in single traversal")
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

    def analyze_meter_changes(self) -> Dict[str, Any]:
        """Analyze meter/time signature changes throughout the score"""
        cache_key = "meter_changes_analysis"
        if cache_key not in self.analysis_cache:
            try:
                meter_data = {
                    "time_signatures": [],
                    "changes": [],
                    "total_changes": 0,
                    "has_meter_changes": False,
                }

                # Get all time signatures from the score
                time_signatures = self.score_stream.recurse().getElementsByClass(
                    meter.TimeSignature
                )

                current_ts = None
                for ts in time_signatures:
                    ts_string = str(ts.ratioString)
                    offset = float(ts.offset) if hasattr(ts, "offset") else 0.0

                    # Track unique time signatures
                    if ts_string not in [
                        t["signature"] for t in meter_data["time_signatures"]
                    ]:
                        meter_data["time_signatures"].append(
                            {
                                "signature": ts_string,
                                "numerator": ts.numerator,
                                "denominator": ts.denominator,
                                "first_occurrence": offset,
                            }
                        )

                    # Track changes
                    if current_ts is not None and current_ts != ts_string:
                        meter_data["changes"].append(
                            {
                                "from_signature": current_ts,
                                "to_signature": ts_string,
                                "offset": offset,
                                "measure": self._offset_to_measure(offset),
                            }
                        )
                        meter_data["total_changes"] += 1
                        meter_data["has_meter_changes"] = True

                    current_ts = ts_string

                # If no time signatures found, set default
                if not meter_data["time_signatures"]:
                    meter_data["time_signatures"].append(
                        {
                            "signature": "4/4",
                            "numerator": 4,
                            "denominator": 4,
                            "first_occurrence": 0.0,
                        }
                    )

                self.analysis_cache[cache_key] = meter_data
                logger.info(
                    f"Detected {len(meter_data['time_signatures'])} time signatures with {meter_data['total_changes']} changes"
                )
            except Exception as e:
                logger.error(f"Meter changes analysis failed: {str(e)}")
                self.analysis_cache[cache_key] = {"error": f"Error: {str(e)}"}
        return self.analysis_cache[cache_key]

    def analyze_tempo(self) -> Dict[str, Any]:
        """Analyze tempo markings and BPM throughout the score"""
        cache_key = "tempo_analysis"
        if cache_key not in self.analysis_cache:
            try:
                tempo_data = {
                    "tempo_markings": [],
                    "bpm_changes": [],
                    "initial_bpm": None,
                    "average_bpm": None,
                    "has_tempo_changes": False,
                }

                # Get all tempo indications
                tempo_indications = self.score_stream.recurse().getElementsByClass(
                    tempo.TempoIndication
                )
                metronome_marks = self.score_stream.recurse().getElementsByClass(
                    tempo.MetronomeMark
                )

                all_tempos = []

                # Process tempo indications (like "Allegro", "Andante", etc.)
                for ti in tempo_indications:
                    tempo_info = {
                        "type": "indication",
                        "text": str(ti.text) if hasattr(ti, "text") else str(ti),
                        "offset": float(ti.offset) if hasattr(ti, "offset") else 0.0,
                        "bpm": None,
                    }

                    # Try to get BPM from tempo indication
                    if hasattr(ti, "getSoundingQuarterBPM"):
                        try:
                            tempo_info["bpm"] = ti.getSoundingQuarterBPM()
                        except:
                            pass

                    tempo_data["tempo_markings"].append(tempo_info)
                    if tempo_info["bpm"]:
                        all_tempos.append(tempo_info["bpm"])

                # Process metronome marks (explicit BPM markings)
                for mm in metronome_marks:
                    tempo_info = {
                        "type": "metronome",
                        "text": str(mm),
                        "offset": float(mm.offset) if hasattr(mm, "offset") else 0.0,
                        "bpm": None,
                    }

                    # Get BPM from metronome mark
                    if hasattr(mm, "number"):
                        tempo_info["bpm"] = mm.number
                    elif hasattr(mm, "getQuarterBPM"):
                        try:
                            tempo_info["bpm"] = mm.getQuarterBPM()
                        except:
                            pass

                    tempo_data["tempo_markings"].append(tempo_info)
                    if tempo_info["bpm"]:
                        all_tempos.append(tempo_info["bpm"])

                # Analyze tempo changes
                previous_bpm = None
                for marking in sorted(
                    tempo_data["tempo_markings"], key=lambda x: x["offset"]
                ):
                    if marking["bpm"]:
                        if previous_bpm is not None and previous_bpm != marking["bpm"]:
                            tempo_data["bpm_changes"].append(
                                {
                                    "from_bpm": previous_bpm,
                                    "to_bpm": marking["bpm"],
                                    "offset": marking["offset"],
                                    "measure": self._offset_to_measure(
                                        marking["offset"]
                                    ),
                                }
                            )
                            tempo_data["has_tempo_changes"] = True

                        if tempo_data["initial_bpm"] is None:
                            tempo_data["initial_bpm"] = marking["bpm"]

                        previous_bpm = marking["bpm"]

                # Calculate average BPM
                if all_tempos:
                    tempo_data["average_bpm"] = sum(all_tempos) / len(all_tempos)

                # If no tempo found, try to estimate from the score
                if not tempo_data["tempo_markings"]:
                    try:
                        # music21 can sometimes infer tempo
                        estimated_tempo = self.score_stream.metronomeMarkBoundaries()
                        if estimated_tempo:
                            tempo_data["tempo_markings"].append(
                                {
                                    "type": "estimated",
                                    "text": "Estimated",
                                    "offset": 0.0,
                                    "bpm": (
                                        estimated_tempo[0][2].number
                                        if hasattr(estimated_tempo[0][2], "number")
                                        else None
                                    ),
                                }
                            )
                    except:
                        pass

                self.analysis_cache[cache_key] = tempo_data
                logger.info(
                    f"Detected {len(tempo_data['tempo_markings'])} tempo markings"
                )
            except Exception as e:
                logger.error(f"Tempo analysis failed: {str(e)}")
                self.analysis_cache[cache_key] = {"error": f"Error: {str(e)}"}
        return self.analysis_cache[cache_key]

    def _offset_to_measure(self, offset: float) -> int:
        """Convert offset to approximate measure number"""
        try:
            # This is a simplified conversion - in practice, you'd need to account for time signatures
            # Assuming 4/4 time for now
            return int(offset / 4.0) + 1
        except:
            return 1

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
                    score_structure["parts"] = ["Soprano", "Alto", "Tenor", "Bass"]
                    return "SATB"
            except Exception as e:
                logger.warning(f"Pitch range analysis failed: {e}")

        return "Custom Ensemble"


def analyze_with_music21(mxl_path: str, score) -> Dict[str, Any]:
    """
    Optimized Music21 analysis with improved performance and resource management
    """
    try:
        # Parse the MusicXML file
        logger.info(f"Parsing MusicXML file: {mxl_path}")
        score_stream = converter.parse(mxl_path)

        # Initialize optimizer
        optimizer = MusicAnalysisOptimizer(score_stream)

        # Initialize analysis structure
        analysis = {
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
            score_stream.write("midi", fp=midi_file)
            score.midi_url = f"/api/serve-midi/{score.id}/"
            logger.info(f"Generated MIDI file for score {score.id}")
        except Exception as e:
            logger.error(f"MIDI generation failed: {str(e)}")
            score.midi_url = f"Error: {str(e)}"

        # Perform optimized analysis
        logger.info("Starting optimized musical analysis")

        # Core analysis using optimizer
        analysis["key"] = optimizer.analyze_key()
        analysis["parts"] = optimizer.analyze_parts()
        analysis["chords"] = optimizer.analyze_chords(max_chords=10)
        analysis["time_signature"] = optimizer.analyze_time_signature()
        analysis["notable_elements"] = optimizer.analyze_notable_elements()
        analysis["score_structure"] = optimizer.analyze_score_structure()
        analysis["measures"] = optimizer.analyze_measures()
        analysis["instrumentation"] = optimizer.analyze_instrumentation()
        analysis["meter_changes"] = optimizer.analyze_meter_changes()
        analysis["tempo"] = optimizer.analyze_tempo()

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
                analysis["text_content"] = {
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
            f"  - Tempo markings: {len(analysis['tempo'].get('tempo_markings', []))}"
        )
        logger.info(
            f"  - Meter changes: {len(analysis['meter_changes'].get('changes', []))}"
        )

        return analysis

    except Exception as e:
        logger.error(f"Music21 analysis failed: {str(e)}")
        return {
            "error": f"Analysis failed: {str(e)}",
            "key": "Error",
            "parts": ["Error"],
            "chords": [],
            "time_signature": "Error",
            "notable_elements": {"error": str(e)},
            "score_structure": {"error": str(e)},
            "text_content": {"error": str(e)},
            "tempo": {"error": str(e)},
            "meter_changes": {"error": str(e)},
            "measures": {"error": str(e)},
            "instrumentation": {"error": str(e)},
        }
