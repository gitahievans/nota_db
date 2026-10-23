import logging
import os
import shutil
from pathlib import Path

from celery import shared_task
from django.conf import settings
from music21 import converter, stream

from .audio_processor import transcribe_audio_to_musicxml
from .audiveris_processor import process_with_audiveris
from .models import PDFFile
from .music21_analyzer import analyze_with_music21
from .score_cleanup import normalize_score_stream

logger = logging.getLogger(__name__)


@shared_task(bind=True)
def process_score(self, score_id, file_ext, source_type=None):
    score = None
    current_stage = "VALIDATING"

    def update_stage(stage, message, progress_percent=None):
        meta = {"stage": stage, "message": message}
        if progress_percent is not None:
            meta["progress_percent"] = progress_percent
        self.update_state(state=stage, meta=meta)

    try:
        score = PDFFile.objects.get(id=score_id)
        resolved_source_type = source_type or score.source_type or PDFFile.SOURCE_TYPE_PDF
        logger.info(
            "Processing score ID %s with extension %s and source type %s",
            score_id,
            file_ext,
            resolved_source_type,
        )

        update_stage("VALIDATING", "Validating uploaded file", 10)
        input_path = settings.TEMP_STORAGE_DIR / f"{score.id}/input.{file_ext}"
        if not input_path.exists():
            raise FileNotFoundError(f"File not found at {input_path}")

        file_size = os.path.getsize(input_path)
        logger.info("File size: %s bytes", file_size)

        audio_metadata = None
        omr_metadata = None
        if resolved_source_type == PDFFile.SOURCE_TYPE_AUDIO:
            current_stage = "TRANSCRIBING_AUDIO"
            output_score_path, audio_metadata = transcribe_audio_to_musicxml(
                score_id=score_id,
                input_path=input_path,
                progress_callback=update_stage,
            )
        else:
            current_stage = "GENERATING_MUSICXML"
            update_stage(
                "GENERATING_MUSICXML",
                "Generating MusicXML from uploaded score",
                40,
            )
            output_score_path, _ = process_with_audiveris(score_id, file_ext, input_path)
            current_stage = "CLEANING_TRANSCRIPTION"
            update_stage(
                "CLEANING_TRANSCRIPTION",
                "Cleaning recognized score notation",
                65,
            )
            omr_stream = converter.parse(output_score_path)
            if isinstance(omr_stream, stream.Opus):
                omr_stream = omr_stream.toScore()
            cleaned_score, omr_metadata = normalize_score_stream(
                omr_stream,
                resolved_source_type,
            )
            cleaned_xml_path = Path(settings.TEMP_STORAGE_DIR) / str(score_id) / "output.xml"
            cleaned_score.write("musicxml", fp=cleaned_xml_path)
            output_score_path = str(cleaned_xml_path)

        current_stage = "ANALYZING_SCORE"
        update_stage("ANALYZING_SCORE", "Running score analysis with Music21", 85)
        analysis = analyze_with_music21(output_score_path, score)
        if audio_metadata:
            analysis["audio_transcription"] = audio_metadata
        elif resolved_source_type != PDFFile.SOURCE_TYPE_AUDIO:
            analysis["score_cleanup"] = omr_metadata

        score.results = analysis
        core_valid = (
            analysis.get("key")
            and "Error" not in str(analysis["key"])
            and analysis.get("parts")
            and "Error" not in str(analysis["parts"])
            and analysis.get("chords") is not None
            and analysis.get("time_signature")
            and "Error" not in str(analysis["time_signature"])
            and score.musicxml_url
            and "Error" not in score.musicxml_url
        )
        midi_valid = score.midi_url and "Error" not in score.midi_url
        additional_valid = (
            analysis.get("notable_elements") is not None
            and analysis.get("score_structure") is not None
        )
        score.processed = bool(core_valid and additional_valid)

        if not score.processed or not midi_valid:
            logger.warning("Processed status for score ID %s has issues", score_id)

        score.save()
        update_stage("COMPLETED", "Analysis completed", 100)
        logger.info("Saved analysis for score ID %s, processed=%s", score_id, score.processed)
        return {
            "stage": "COMPLETED",
            "message": "Analysis completed",
            "progress_percent": 100,
        }

    except Exception as exc:
        logger.error("Error processing score ID %s: %s", score_id, str(exc))
        error_payload = {
            "error": str(exc),
            "stage": current_stage,
            "message": str(exc),
            "error_type": current_stage.lower(),
        }
        if score is not None:
            score.processed = False
            score.results = error_payload
            score.save()
        self.update_state(state="FAILED", meta=error_payload)
        raise
    finally:
        cleanup_temp_files.apply_async(
            (score_id,), countdown=settings.CLEANUP_DELAY_SECONDS
        )
        logger.info(
            "Scheduled cleanup for score %s in %s seconds",
            score_id,
            settings.CLEANUP_DELAY_SECONDS,
        )


@shared_task
def cleanup_temp_files(score_id):
    try:
        temp_dir = settings.TEMP_STORAGE_DIR / str(score_id)
        if temp_dir.exists():
            shutil.rmtree(temp_dir)
            logger.info(
                "Cleaned up temporary files for score ID %s at %s",
                score_id,
                temp_dir,
            )
        else:
            logger.warning("Temporary directory does not exist: %s", temp_dir)
    except Exception as exc:
        logger.error("Error cleaning up temporary files for score ID %s: %s", score_id, str(exc))
        raise
