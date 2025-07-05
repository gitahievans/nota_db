from celery import shared_task
import boto3
import os
import subprocess
from music21 import (
    converter,
    chord,
    tempo,
    meter,
    note,
    articulations,
    dynamics,
    instrument,
    layout,
    stream,
    harmony,
    roman,
    key,
    note,
)
import json
from django.conf import settings
from .models import PDFFile
import logging
import shutil
import zipfile
import traceback

logger = logging.getLogger(__name__)

R2_PUBLIC_BASE_URL = "https://pub-346d1123eac74c91ab270858cf24924e.r2.dev"
AUDIVERIS_HOME = "/app/audiveris"


@shared_task
def process_score(score_id, file_ext):
    try:
        # Fetch the file record
        score = PDFFile.objects.get(id=score_id)
        logger.info(f"Processing score ID: {score_id} with file extension: {file_ext}")

        # Get file locally
        input_path = settings.TEMP_STORAGE_DIR / f"{score.id}/input.{file_ext}"
        if not input_path.exists():
            logger.error(f"File not found at {input_path}")
            raise FileNotFoundError(f"File not found at {input_path}")
        logger.info(f"File found at {input_path}")

        # Log file size for debugging
        file_size = os.path.getsize(input_path)
        logger.info(f"File size: {file_size} bytes")

        # Verify working directory
        audiveris_dir = "/app/audiveris"
        if not os.path.exists(audiveris_dir):
            logger.error(f"Audiveris directory {audiveris_dir} does not exist")
            raise FileNotFoundError(
                f"Audiveris directory {audiveris_dir} does not exist"
            )
        logger.info(f"Audiveris directory contents: {os.listdir(audiveris_dir)}")

        # Run Audiveris to convert file to MusicXML
        mxl_path = settings.TEMP_STORAGE_DIR / f"{score_id}"
        logger.info(f"Starting Audiveris processing for score {score_id}")

        # Build the command line arguments string for Audiveris
        cmd_args = f"-batch,-export,-output,{mxl_path}"

        # Add image-specific parameters for better recognition
        if file_ext.lower() in ["jpg", "jpeg", "png", "tiff", "tif"]:
            # Image-specific Audiveris parameters
            image_options = [
                "-option,org.audiveris.omr.sheet.Scale.targetInterline=20",
                "-option,org.audiveris.omr.sheet.Scale.minInterline=12",
                "-option,org.audiveris.omr.image.ImageFormatException.maxImageWidth=8192",
                "-option,org.audiveris.omr.image.ImageFormatException.maxImageHeight=8192",
                "-option,org.audiveris.omr.sheet.Sheet.maxSheetWidth=8192",
                "-option,org.audiveris.omr.sheet.Sheet.maxSheetHeight=8192",
                "-option,org.audiveris.omr.text.tesseract.TesseractOCR.useOCR=true",
                "-option,org.audiveris.omr.classifier.SampleRepository.useRepository=true",
            ]

            # Add image options to command args
            cmd_args += "," + ",".join(image_options)

        # Add the input file path to command args
        cmd_args += f",{input_path}"

        # Build final Audiveris command
        audiveris_cmd = [
            "/opt/gradle-8.7/bin/gradle",
            "run",
            "-PjvmLineArgs=-Xmx3g",  # Increased memory for image processing
            f"-PcmdLineArgs={cmd_args}",
        ]

        try:
            logger.info(f"Running Audiveris command: {' '.join(audiveris_cmd)}")
            result = subprocess.run(
                audiveris_cmd,
                check=True,
                capture_output=True,
                text=True,
                cwd=audiveris_dir,
                timeout=300,  # 5 minute timeout
            )
            logger.info(f"Audiveris stdout: {result.stdout}")
            if result.stderr:
                logger.warning(f"Audiveris stderr: {result.stderr}")
            logger.info(f"Converted file to MusicXML at {mxl_path}")

        except subprocess.TimeoutExpired:
            logger.error(f"Audiveris processing timed out for score {score_id}")
            raise Exception(
                "Audiveris processing timed out - file may be too complex or large"
            )

        except subprocess.CalledProcessError as e:
            logger.error(f"Audiveris failed with return code {e.returncode}")
            logger.error(f"Audiveris stderr: {e.stderr}")
            logger.error(f"Audiveris stdout: {e.stdout}")

            # Check for specific error patterns and provide helpful messages
            if "too low interline value" in e.stderr:
                raise Exception(
                    "Image resolution too low for music recognition. "
                    "Please upload a higher resolution image (recommended: 300 DPI or higher)"
                )
            elif (
                "Could not export since transcription did not complete successfully"
                in e.stderr
            ):
                raise Exception(
                    "Music recognition failed. Please ensure the image contains clear, "
                    "well-lit sheet music with good contrast"
                )
            elif "OutOfMemoryError" in e.stderr:
                raise Exception(
                    "Image too large to process. Please reduce image size or complexity"
                )
            else:
                raise Exception(f"Audiveris processing failed: {e.stderr}")

        # Find the generated MusicXML file
        try:
            mxl_files = [f for f in os.listdir(mxl_path) if f.endswith(".mxl")]
            if not mxl_files:
                # List all files in the output directory for debugging
                all_files = os.listdir(mxl_path) if os.path.exists(mxl_path) else []
                logger.error(
                    f"No MusicXML files generated. Files in output directory: {all_files}"
                )

                # Check for common Audiveris output files that might indicate what went wrong
                omr_files = [f for f in all_files if f.endswith(".omr")]
                if omr_files:
                    logger.info(
                        f"Found OMR files: {omr_files} - this suggests partial processing"
                    )

                raise Exception(
                    "No MusicXML files generated. This usually means the image quality "
                    "is insufficient for music recognition or the image doesn't contain "
                    "recognizable sheet music."
                )

            mxl_file = os.path.join(mxl_path, mxl_files[0])
            logger.info(f"Found MusicXML file: {mxl_file}")

            # Verify the MXL file is valid by checking its size and structure
            mxl_size = os.path.getsize(mxl_file)
            logger.info(f"MusicXML file size: {mxl_size} bytes")

            if mxl_size < 100:  # Very small files are likely empty or corrupt
                logger.error(f"Generated MusicXML file is too small ({mxl_size} bytes)")
                raise Exception(
                    "Generated MusicXML file appears to be empty or corrupt"
                )

        except Exception as e:
            logger.error(f"Error finding/validating MusicXML file: {str(e)}")
            raise

        # Rename to standard output name
        output_mxl_path = os.path.join(mxl_path, "output.mxl")
        try:
            os.rename(mxl_file, output_mxl_path)
            logger.info(f"Renamed MusicXML file to: {output_mxl_path}")
            if not os.path.exists(output_mxl_path):
                logger.error(
                    f"Renamed file {output_mxl_path} does not exist after rename"
                )
                raise Exception("Renamed MusicXML file does not exist")
        except Exception as e:
            logger.error(f"Failed to rename MusicXML file: {str(e)}")
            raise

        # Create XML version for serving via API
        xml_output_path = None
        try:
            # Create XML file for serving
            xml_output_path = os.path.join(mxl_path, "output.xml")

            # Extract XML from MXL file
            with zipfile.ZipFile(output_mxl_path, "r") as mxl_zip:
                file_list = mxl_zip.namelist()
                logger.info(f"Files in MXL for XML extraction: {file_list}")

                # Find the main XML file
                xml_files = [
                    f for f in file_list if f.endswith(".xml") and "/" not in f
                ]
                if not xml_files:
                    xml_files = [f for f in file_list if f.endswith(".xml")]

                if not xml_files:
                    raise Exception("No XML file found in MXL archive for serving")

                xml_filename = xml_files[0]
                logger.info(f"Extracting XML for serving: {xml_filename}")

                # Extract and save the XML content
                with mxl_zip.open(xml_filename) as xml_file:
                    xml_content = xml_file.read()
                    with open(xml_output_path, "wb") as output_file:
                        output_file.write(xml_content)

            logger.info(f"Created XML file for serving at: {xml_output_path}")

        except Exception as e:
            logger.error(f"Failed to create XML file for serving: {str(e)}")
            xml_output_path = None

        # Copy the MusicXML file to the output directory (mounted to host)
        try:
            # Create output directory if it doesn't exist
            output_dir = os.path.join(settings.BASE_DIR, "output")
            os.makedirs(output_dir, exist_ok=True)

            destination_path = os.path.join(output_dir, f"output_{score_id}.xml")

            logger.info(f"About to extract and copy MusicXML file:")
            logger.info(f"  Source MXL: {output_mxl_path}")
            logger.info(f"  Source exists: {os.path.exists(output_mxl_path)}")
            logger.info(f"  Output directory: {output_dir}")
            logger.info(f"  Output directory exists: {os.path.exists(output_dir)}")
            logger.info(
                f"  Output directory writable: {os.access(output_dir, os.W_OK)}"
            )
            logger.info(f"  Destination XML: {destination_path}")

            # Extract XML from MXL (which is a ZIP file)
            with zipfile.ZipFile(output_mxl_path, "r") as mxl_zip:
                # List all files in the MXL
                file_list = mxl_zip.namelist()
                logger.info(f"Files in MXL: {file_list}")

                # Find the main XML file
                xml_files = [
                    f for f in file_list if f.endswith(".xml") and "/" not in f
                ]
                if not xml_files:
                    xml_files = [f for f in file_list if f.endswith(".xml")]

                if not xml_files:
                    raise Exception("No XML file found in MXL archive")

                xml_filename = xml_files[0]
                logger.info(f"Extracting XML file: {xml_filename}")

                # Extract and save the XML content
                with mxl_zip.open(xml_filename) as xml_file:
                    xml_content = xml_file.read()
                    with open(destination_path, "wb") as output_file:
                        output_file.write(xml_content)

            logger.info(
                f"Successfully extracted and saved XML file to: {destination_path}"
            )

            # Verify the file was actually created
            if os.path.exists(destination_path):
                file_size = os.path.getsize(destination_path)
                logger.info(f"XML file created successfully. Size: {file_size} bytes")
            else:
                logger.error("XML file was not created despite successful extraction")

        except Exception as e:
            logger.error(
                f"Failed to extract and copy XML file to output directory: {str(e)}"
            )
            logger.error(f"Exception type: {type(e).__name__}")
            logger.error(f"Traceback: {traceback.format_exc()}")

        # Continue with music21 analysis...
        logger.info(
            f"Successfully processed {file_ext.upper()} file with score ID: {score_id}"
        )

        # Analyze MusicXML with music21
        score_stream = converter.parse(output_mxl_path)
        analysis = {
            "key": None,
            "parts": [],
            "chords": [],
            "time_signature": None,
        }

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

        # Extract part names safely
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
            analysis["chords"] = chords[:10]  # Limit to first 10 for brevity
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

        # Add notable elements analysis
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

            # Single pass through score for efficiency
            for element in score_stream.recurse():
                if isinstance(element, note.Note):
                    # Accidentals
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

                    # Articulations
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

                # Dynamics
                if isinstance(element, dynamics.Dynamic):
                    dyn_value = element.value
                    if dyn_value not in notable_elements["dynamics"]["values"]:
                        notable_elements["dynamics"]["values"].append(dyn_value)
                        notable_elements["dynamics"]["has_dynamics"] = True

            # Sort dynamics for consistency
            notable_elements["dynamics"]["values"].sort()

            # Prepare visualization data
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
                *(
                    [1] * len(notable_elements["dynamics"]["values"])
                ),  # Count 1 per unique dynamic
            ]
            chart["datasets"][0]["backgroundColor"] = [
                "#FF6384",
                "#FF6384",
                "#FF6384",
                "#FF6384",  # Accidentals (red)
                "#36A2EB",
                "#36A2EB",
                "#36A2EB",  # Articulations (blue)
                *(
                    ["#FFCE56"] * len(notable_elements["dynamics"]["values"])
                ),  # Dynamics (yellow)
            ]

            # Add to analysis dict
            analysis["notable_elements"] = notable_elements
            logger.info(f"Detected notable elements: {notable_elements}")
        except Exception as e:
            logger.error(f"Notable elements analysis failed: {str(e)}")
            analysis["notable_elements"] = {"error": f"Error: {str(e)}"}

        # SCORE STRUCTURE ANALYSIS

        # Add score structure analysis
        try:
            score_structure = {
                "score_type": "unknown",
                "ensemble_type": "unknown",
                "music_type": "unknown",
                "parts": [],
            }

            # Extract parts
            parts = score_stream.getElementsByClass(stream.Part)
            score_structure["parts"] = [
                getattr(part, "partName", part.id if part.id else f"Part {i+1}")
                for i, part in enumerate(parts)
            ]
            logger.info(f"Detected parts: {score_structure['parts']}")

            # Open vs. Closed Score
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

            # Check for lyrics to determine vocal/instrumental
            lyrics_found = False
            for part in parts:
                for n in part.recurse().getElementsByClass(note.Note):
                    if n.lyrics:
                        lyrics_found = True
                        break
                if lyrics_found:
                    break

            # Instrument detection
            instruments = []
            for part in parts:
                instr = part.getElementsByClass(instrument.Instrument).first()
                if instr and instr.instrumentName:
                    instruments.append(instr.instrumentName)
                else:
                    instruments.append(score_structure["parts"][parts.index(part)])
            score_structure["instruments"] = instruments

            # Vocal/Instrumental classification
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
            logger.info(f"Music type: {score_structure['music_type']}")

            # SATB or other ensemble detection
            part_names_lower = [name.lower() for name in score_structure["parts"]]
            if len(parts) == 4 and all(
                any(role in name for role in ["soprano", "alto", "tenor", "bass"])
                for name in part_names_lower
            ):
                score_structure["ensemble_type"] = "SATB"
            else:
                # Pitch range analysis for ambiguous cases
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

                # Check if ranges match typical SATB
                satb_roles = ["Soprano", "Alto", "Tenor", "Bass"]
                satb_ranges = [(60, 84), (53, 72), (48, 67), (36, 60)]  # MIDI ranges
                is_satb = len(pitch_ranges) == 4 and all(
                    pr["min_midi"] is not None
                    and pr["max_midi"] is not None
                    and (
                        pr["min_midi"] >= low - 5 and pr["max_midi"] <= high + 5
                    )  # Allow some flexibility
                    for pr, (low, high) in zip(pitch_ranges, satb_ranges)
                )
                if is_satb:
                    score_structure["ensemble_type"] = "SATB"
                    score_structure["parts"] = (
                        satb_roles  # Override with standard names
                    )
                else:
                    # Infer other ensemble types based on instruments
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

            # Add to analysis dict
            analysis["score_structure"] = score_structure
            logger.info(f"Detected score structure: {score_structure}")
        except Exception as e:
            logger.error(f"Score structure analysis failed: {str(e)}")
            analysis["score_structure"] = {"error": f"Error: {str(e)}"}

        # END OF SCORE STRUCTURE ANALYSIS

        # CHORD PROGRESSIONS ANALYSIS

        # END OF CHORD PROGRESSIONS ANALYSIS

        # Log MusicXML structure for debugging
        logger.info(f"Number of parts in MusicXML: {len(score_stream.parts)}")
        for i, part in enumerate(score_stream.parts):
            logger.info(
                f"Part {i+1} ID: {part.id}, PartName: {getattr(part, 'partName', 'None')}"
            )

        # Save results to database
        try:
            score.results = json.dumps(analysis)
            # Check if core analysis components are valid
            core_valid = (
                analysis.get("key")
                and "Error" not in str(analysis["key"])
                and analysis.get("parts")
                and "Error" not in str(analysis["parts"])
                and analysis.get("chords") is not None  # Allow empty chord list
                and analysis.get("time_signature")
                and "Error" not in str(analysis["time_signature"])
                and score.musicxml_url
                and "Error" not in score.musicxml_url
            )
            # MIDI is optional: log error but don't fail processed
            midi_valid = score.midi_url and "Error" not in score.midi_url
            # Check if additional analyses are present (allow errors in nested fields)
            additional_valid = (
                analysis.get("notable_elements") is not None
                and analysis.get("score_structure") is not None
            )
            # Set processed to True if core analyses are valid, regardless of MIDI
            score.processed = core_valid and additional_valid
            if not score.processed or not midi_valid:
                logger.warning(
                    f"Processed status for score ID: {score_id}. Reasons for issues:"
                )
                if not analysis.get("key") or "Error" in str(analysis["key"]):
                    logger.warning(" - Key analysis failed or empty")
                if not analysis.get("parts") or "Error" in str(analysis["parts"]):
                    logger.warning(" - Parts analysis failed or empty")
                if analysis.get("chords") is None:
                    logger.warning(" - Chords analysis failed")
                if not analysis.get("time_signature") or "Error" in str(
                    analysis["time_signature"]
                ):
                    logger.warning(" - Time signature analysis failed or empty")
                if not score.musicxml_url or "Error" in score.musicxml_url:
                    logger.warning(" - MusicXML URL invalid")
                if not midi_valid:
                    logger.warning(f" - MIDI generation failed: {score.midi_url}")
                if analysis.get("notable_elements") is None:
                    logger.warning(" - Notable elements analysis missing")
                if analysis.get("score_structure") is None:
                    logger.warning(" - Score structure analysis missing")
            score.save()
            logger.info(
                f"Saved analysis for score ID: {score_id}, processed: {score.processed}, results: {score.results}"
            )
        except Exception as e:
            logger.error(f"Error saving analysis for score ID: {score_id}: {str(e)}")
            score.processed = False
            score.results = f"Error: {str(e)}"
            score.save()
            logger.info(
                f"Saved analysis for score ID: {score_id}, processed: {score.processed}, results: {score.results}"
            )
        except Exception as e:
            logger.error(f"Error saving analysis for score ID: {score_id}: {str(e)}")
            score.processed = False
            score.results = f"Error: {str(e)}"
            score.save()

        logger.info(
            f"Saved analysis for score ID: {score_id}, processed: {score.processed}, results: {score.results}"
        )

        cleanup_temp_files.apply_async(
            (score_id,), countdown=settings.CLEANUP_DELAY_SECONDS
        )
        logger.info(
            f"Scheduled cleanup for score {score_id} in {settings.CLEANUP_DELAY_SECONDS} seconds"
        )

    except Exception as e:
        logger.error(f"Error processing score ID {score_id}: {str(e)}")
        score.processed = False
        score.results = f"Error: {str(e)}"
        score.save()
        raise


@shared_task
def cleanup_temp_files(score_id):
    try:
        temp_dir = settings.TEMP_STORAGE_DIR / str(score_id)
        if temp_dir.exists():
            shutil.rmtree(temp_dir)
            logger.info(
                f"Cleaned up temporary files for score ID: {score_id} at {temp_dir}"
            )
        else:
            logger.warning(f"Temporary directory does not exist: {temp_dir}")
    except Exception as e:
        logger.error(
            f"Error cleaning up temporary files for score ID {score_id}: {str(e)}"
        )
        raise
