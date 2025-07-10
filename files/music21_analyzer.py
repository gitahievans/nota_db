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
from django.conf import settings

logger = logging.getLogger(__name__)


def analyze_with_music21(mxl_path, score):
    score_stream = converter.parse(mxl_path)
    analysis = {
        "key": None,
        "parts": [],
        "chords": [],
        "time_signature": None,
    }

    # Set URLs
    try:
        score.musicxml_url = f"/api/serve-musicxml/{score.id}/"
        logger.info(f"Set MusicXML URL for score {score.id}: {score.musicxml_url}")
    except Exception as e:
        logger.error(f"Failed to set MusicXML URL: {str(e)}")
        score.musicxml_url = f"Error: {str(e)}"

    try:
        midi_file = settings.TEMP_STORAGE_DIR / f"{score.id}/{score.id}.mid"
        score_stream.write("midi", fp=midi_file)
        score.midi_url = f"/api/serve-midi/{score.id}/"
        logger.info(f"Set MIDI URL for score {score.id}: {score.midi_url}")
    except Exception as e:
        logger.error(f"MIDI generation failed: {str(e)}")
        score.midi_url = f"Error: {str(e)}"

    # Extract key
    try:
        analysis["key"] = str(score_stream.analyze("key"))
        logger.info(f"Detected key: {analysis['key']}")
    except Exception as e:
        logger.warning(f"Key analysis failed: {str(e)}")
        analysis["key"] = f"Error: {str(e)}"

    # Extract part names
    try:
        if not score_stream.parts:
            analysis["parts"] = ["No parts detected"]
            logger.warning("No parts found in MusicXML")
        else:
            for part in score_stream.parts:
                part_name = getattr(part, "partName", None)
                analysis["parts"].append(part_name if part_name else "Unnamed Part")
                logger.info(
                    f"Part ID: {part.id}, PartName: {getattr(part, 'partName', 'None')}"
                )
            logger.info(f"Detected parts: {analysis['parts']}")
    except Exception as e:
        logger.error(f"Part analysis failed: {str(e)}")
        analysis["parts"] = [f"Error: {str(e)}"]

    # Extract chords
    try:
        chords = []
        for part in score_stream.parts:
            chordified = part.chordify()
            for c in chordified.recurse().getElementsByClass(chord.Chord):
                chord_name = c.pitchedCommonName if c.isChord else "N/A"
                chords.append({"pitch": chord_name, "offset": float(c.offset)})
        analysis["chords"] = chords[:10]
        logger.info(f"Detected chords: {analysis['chords']}")
    except Exception as e:
        logger.error(f"Chord analysis failed: {str(e)}")
        analysis["chords"] = [f"Error: {str(e)}"]

    # Extract time signature
    try:
        time_sig = (
            score_stream.recurse().getElementsByClass(meter.TimeSignature).first()
        )
        analysis["time_signature"] = (
            str(time_sig.ratioString) if time_sig else "No time signature found"
        )
        logger.info(f"Detected time signature: {analysis['time_signature']}")
    except Exception as e:
        logger.error(f"Time signature analysis failed: {str(e)}")
        analysis["time_signature"] = f"Error: {str(e)}"

    # Notable elements analysis
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
            "visualizations": {
                "notable_elements_chart": {
                    "type": "bar",
                    "data": {
                        "labels": [],
                        "datasets": [
                            {
                                "label": "Count of Notable Elements",
                                "data": [],
                                "backgroundColor": [],
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
            },
        }

        for element in score_stream.recurse():
            if isinstance(element, note.Note):
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

                for art in element.articulations:
                    if isinstance(art, articulations.Staccato):
                        notable_elements["articulations"]["staccato"]["count"] += 1
                        notable_elements["articulations"]["staccato"][
                            "has_staccato"
                        ] = True
                    elif isinstance(art, articulations.Accent):
                        notable_elements["articulations"]["accent"]["count"] += 1
                        notable_elements["articulations"]["accent"]["has_accent"] = True
                    elif isinstance(art, articulations.Tenuto):
                        notable_elements["articulations"]["tenuto"]["count"] += 1
                        notable_elements["articulations"]["tenuto"]["has_tenuto"] = True

            if isinstance(element, dynamics.Dynamic):
                dyn_value = element.value
                if dyn_value not in notable_elements["dynamics"]["values"]:
                    notable_elements["dynamics"]["values"].append(dyn_value)
                    notable_elements["dynamics"]["has_dynamics"] = True

        notable_elements["dynamics"]["values"].sort()
        chart = notable_elements["visualizations"]["notable_elements_chart"]["data"]
        chart["labels"] = [
            "Sharps",
            "Flats",
            "Naturals",
            "Other Accidentals",
            "Staccato",
            "Accent",
            "Tenuto",
            *notable_elements["dynamics"]["values"],
        ]
        chart["datasets"][0]["data"] = [
            notable_elements["accidentals"]["sharps"],
            notable_elements["accidentals"]["flats"],
            notable_elements["accidentals"]["naturals"],
            notable_elements["accidentals"]["others"],
            notable_elements["articulations"]["staccato"]["count"],
            notable_elements["articulations"]["accent"]["count"],
            notable_elements["articulations"]["tenuto"]["count"],
            *([1] * len(notable_elements["dynamics"]["values"])),
        ]
        chart["datasets"][0]["backgroundColor"] = [
            "#FF6384",
            "#FF6384",
            "#FF6384",
            "#FF6384",
            "#36A2EB",
            "#36A2EB",
            "#36A2EB",
            *(["#FFCE56"] * len(notable_elements["dynamics"]["values"])),
        ]
        analysis["notable_elements"] = notable_elements
        logger.info(f"Detected notable elements: {notable_elements}")
    except Exception as e:
        logger.error(f"Notable elements analysis failed: {str(e)}")
        analysis["notable_elements"] = {"error": f"Error: {str(e)}"}

    # Score structure analysis
    try:
        score_structure = {
            "score_type": "unknown",
            "ensemble_type": "unknown",
            "music_type": "unknown",
            "parts": [],
        }
        parts = score_stream.getElementsByClass(stream.Part)
        score_structure["parts"] = [
            getattr(part, "partName", part.id if part.id else f"Part {i+1}")
            for i, part in enumerate(parts)
        ]
        logger.info(f"Detected parts: {score_structure['parts']}")

        staff_groups = score_stream.getElementsByClass(layout.StaffGroup)
        staves = score_stream.recurse().getElementsByClass(layout.Staff)
        num_staves = len(staves)
        num_parts = len(parts)
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

        lyrics_found = False
        for part in parts:
            for n in part.recurse().getElementsByClass(note.Note):
                if n.lyrics:
                    lyrics_found = True
                    break
            if lyrics_found:
                break

        instruments = []
        for part in parts:
            instr = part.getElementsByClass(instrument.Instrument).first()
            if instr and instr.instrumentName:
                instruments.append(instr.instrumentName)
            else:
                instruments.append(score_structure["parts"][parts.index(part)])
        score_structure["instruments"] = instruments

        if lyrics_found:
            score_structure["music_type"] = (
                "vocal"
                if all(
                    "voice" in instr.lower()
                    or part_name.lower() in ["soprano", "alto", "tenor", "bass"]
                    for instr, part_name in zip(instruments, score_structure["parts"])
                )
                else "mixed"
            )
        else:
            score_structure["music_type"] = "instrumental"
        logger.info(f"Music type: {score_structure['music_type']}")

        part_names_lower = [name.lower() for name in score_structure["parts"]]
        if len(parts) == 4 and all(
            any(role in name for role in ["soprano", "alto", "tenor", "bass"])
            for name in part_names_lower
        ):
            score_structure["ensemble_type"] = "SATB"
        else:
            pitch_ranges = []
            for part in parts:
                midi_pitches = [
                    n.pitch.midi
                    for n in part.recurse().getElementsByClass(note.Note)
                    if n.pitch
                ]
                if midi_pitches:
                    pitch_ranges.append(
                        {
                            "part": part.partName or part.id,
                            "min_midi": min(midi_pitches),
                            "max_midi": max(midi_pitches),
                        }
                    )
                else:
                    pitch_ranges.append(
                        {
                            "part": part.partName or part.id,
                            "min_midi": None,
                            "max_midi": None,
                        }
                    )
            satb_roles = ["Soprano", "Alto", "Tenor", "Bass"]
            satb_ranges = [(60, 84), (53, 72), (48, 67), (36, 60)]
            is_satb = len(pitch_ranges) == 4 and all(
                pr["min_midi"] is not None
                and pr["max_midi"] is not None
                and (pr["min_midi"] >= low - 5 and pr["max_midi"] <= high + 5)
                for pr, (low, high) in zip(pitch_ranges, satb_ranges)
            )
            if is_satb:
                score_structure["ensemble_type"] = "SATB"
                score_structure["parts"] = satb_roles
            else:
                if (
                    any("violin" in instr.lower() for instr in instruments)
                    and len(parts) == 4
                ):
                    score_structure["ensemble_type"] = "String Quartet"
                elif (
                    any("piano" in instr.lower() for instr in instruments)
                    and num_staves <= 2
                ):
                    score_structure["ensemble_type"] = "Piano Solo"
                else:
                    score_structure["ensemble_type"] = "Custom Ensemble"
            logger.info(f"Pitch ranges: {pitch_ranges}")
        logger.info(f"Ensemble type: {score_structure['ensemble_type']}")
        analysis["score_structure"] = score_structure
        logger.info(f"Detected score structure: {score_structure}")
    except Exception as e:
        logger.error(f"Score structure analysis failed: {str(e)}")
        analysis["score_structure"] = {"error": f"Error: {str(e)}"}

    # Load text extraction results
    try:
        text_results_path = settings.TEMP_STORAGE_DIR / f"{score.id}/text_results.json"
        if text_results_path.exists():
            with open(text_results_path, "r", encoding="utf-8") as f:
                text_results = json.load(f)
            analysis["text_content"] = text_results
            logger.info(f"Added text extraction results: {text_results}")
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

    logger.info(f"Number of parts in MusicXML: {len(score_stream.parts)}")
    for i, part in enumerate(score_stream.parts):
        logger.info(
            f"Part {i+1} ID: {part.id}, PartName: {getattr(part, 'partName', 'None')}"
        )

    return analysis
