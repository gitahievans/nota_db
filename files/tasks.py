import json
from celery import shared_task
import boto3
import os
import subprocess
from music21 import converter, stream, chord, tempo, meter
from django.conf import settings
from .models import PDFFile
import logging

logger = logging.getLogger(__name__)


@shared_task
def process_score(score_id):
    try:
        # Fetch the PDF file record
        score = PDFFile.objects.get(id=score_id)
        logger.info(f"Processing score ID: {score_id}")

        # Download PDF from Cloudflare R2
        s3_client = boto3.client(
            "s3",
            endpoint_url=settings.AWS_S3_ENDPOINT_URL,
            aws_access_key_id=settings.AWS_ACCESS_KEY_ID,
            aws_secret_access_key=settings.AWS_SECRET_ACCESS_KEY,
        )
        file_key = f"nota-pdfs/{os.path.basename(score.pdf_file.name)}"
        pdf_path = f"/processing/input/{os.path.basename(score.pdf_file.name)}"
        os.makedirs(os.path.dirname(pdf_path), exist_ok=True)
        logger.info(
            f"Downloading file from bucket {settings.AWS_STORAGE_BUCKET_NAME} with key {file_key}"
        )
        s3_client.download_file(settings.AWS_STORAGE_BUCKET_NAME, file_key, pdf_path)
        logger.info(f"Downloaded PDF to {pdf_path}")

        # Verify working directory
        audiveris_dir = "/app/audiveris"
        if not os.path.exists(audiveris_dir):
            logger.error(f"Audiveris directory {audiveris_dir} does not exist")
            raise FileNotFoundError(
                f"Audiveris directory {audiveris_dir} does not exist"
            )
        logger.info(f"Audiveris directory contents: {os.listdir(audiveris_dir)}")

        # Run Audiveris to convert PDF to MusicXML
        mxl_path = f"/processing/output/{score.id}"
        audiveris_cmd = [
            "/opt/gradle-8.7/bin/gradle",
            "run",
            "-PjvmLineArgs=-Xmx3g",
            f"-PcmdLineArgs=-batch,-export,-output,{mxl_path},--,{pdf_path}",
        ]
        logger.info(f"Running Audiveris command: {' '.join(audiveris_cmd)}")
        try:
            result = subprocess.run(
                audiveris_cmd,
                check=True,
                capture_output=True,
                text=True,
                cwd=audiveris_dir,
            )
            logger.info(f"Audiveris output: {result.stdout}")
            logger.info(f"Converted PDF to MusicXML at {mxl_path}")
        except subprocess.CalledProcessError as e:
            logger.error(f"Audiveris failed: {e.stderr}")
            raise

        # Find the generated MusicXML file
        mxl_files = [f for f in os.listdir(mxl_path) if f.endswith(".mxl")]
        if not mxl_files:
            raise Exception("No MusicXML files generated")
        mxl_file = os.path.join(mxl_path, mxl_files[0])
        logger.info(f"Found MusicXML file: {mxl_file}")

        # Analyze MusicXML with music21
        score_stream = converter.parse(mxl_file)
        analysis = {
            "key": None,
            "parts": [],
            "chords": [],
            "tempo": None,
            "time_signature": None,
        }

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
                chordified = part.chordify()  # Combine notes into chords
                for c in chordified.recurse().getElementsByClass(chord.Chord):
                    chord_name = c.pitchedCommonName if c.isChord else "N/A"
                    chords.append({"pitch": chord_name, "offset": float(c.offset)})
            analysis["chords"] = chords[:10]  # Limit to first 10 for brevity
            logger.info(f"Detected chords: {analysis['chords']}")
        except Exception as e:
            logger.error(f"Chord analysis failed: {str(e)}")
            analysis["chords"] = [f"Error: {str(e)}"]

        # Extract tempo
        try:
            metronome = (
                score_stream.recurse().getElementsByClass(tempo.MetronomeMark).first()
            )
            if metronome:
                analysis["tempo"] = {
                    "text": metronome.text,
                    "bpm": (
                        float(metronome.getQuarterBPM())
                        if metronome.getQuarterBPM()
                        else None
                    ),
                }
            else:
                analysis["tempo"] = "No tempo marking found"
            logger.info(f"Detected tempo: {analysis['tempo']}")
        except Exception as e:
            logger.error(f"Tempo analysis failed: {str(e)}")
            analysis["tempo"] = f"Error: {str(e)}"

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

        # Log MusicXML structure for debugging
        logger.info(f"Number of parts in MusicXML: {len(score_stream.parts)}")
        for i, part in enumerate(score_stream.parts):
            logger.info(
                f"Part {i+1} ID: {part.id}, PartName: {getattr(part, 'partName', 'None')}"
            )

        # Save results to database as valid JSON
        score.results = json.dumps(analysis)  # Serialize to JSON string
        score.processed = bool(
            analysis["key"]
            and analysis["parts"]
            and analysis["chords"]
            and analysis["tempo"]
            and analysis["time_signature"]
            and "Error" not in str(analysis)
        )
        score.save()
        logger.info(f"Saved analysis for score ID: {score_id}")

    except Exception as e:
        logger.error(f"Error processing score ID {score_id}: {str(e)}")
        score.processed = False
        score.results = json.dumps({"error": str(e)})  # Save error as valid JSON
        score.save()
        raise
