from celery import shared_task
import os
import logging
from django.conf import settings
from .models import PDFFile
from .audiveris_processor import process_with_audiveris
from .music21_analyzer import analyze_with_music21
import json
import shutil

logger = logging.getLogger(__name__)


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

        # Process with Audiveris
        output_mxl_path, xml_output_path = process_with_audiveris(
            score_id, file_ext, input_path
        )

        # Analyze with music21
        analysis = analyze_with_music21(output_mxl_path, score)

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
