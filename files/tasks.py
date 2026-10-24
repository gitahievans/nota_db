import logging
import os
from pathlib import Path

from celery import shared_task
from django.conf import settings
from django.utils import timezone
from .outcomes import finalize, outcome, read_results, available

from .audio_processor import transcribe_audio_to_musicxml
from .audiveris_processor import process_with_audiveris, RecognitionError
from .models import PDFFile
from .music21_analyzer import analyze_with_music21
from .artifacts import canonicalize_notation, artifact_metadata
from .lifecycle import worker_session, terminal_fields, cleanup_session

logger = logging.getLogger(__name__)


class JobNoLongerActive(Exception):
    pass


@shared_task(bind=True, soft_time_limit=3540, time_limit=3600)
@worker_session
def process_score(self, score_id, file_ext, source_type=None):
    score = None
    current_stage = "VALIDATING"
    analysis = {}
    recognition = None
    superseded = False
    terminal_payload = None

    def update_stage(stage, message, progress_percent=None):
        nonlocal current_stage
        current_stage = stage
        if score is not None:
            score.job_state = "RUNNING"
            score.job_stage = stage
            score.job_updated_at = timezone.now()
            updated = PDFFile.objects.filter(pk=score.id, analysis_task_id=score.analysis_task_id, deletion_pending=False, job_state__in=["", "QUEUED", "RUNNING"]).update(
                job_state=score.job_state, job_stage=stage, job_updated_at=score.job_updated_at)
            if not updated:
                raise JobNoLongerActive()
        meta = {"stage": stage, "message": message}
        if progress_percent is not None:
            meta["progress_percent"] = progress_percent
        try:
            self.update_state(state=stage, meta=meta)
        except Exception:
            logger.exception("Progress backend unavailable for score %s", score_id)

    def save_terminal():
        nonlocal superseded
        # A delayed worker must not replace a terminal timeout/revocation outcome.
        terminal_fields(score)
        fields = ("results", "processed", "musicxml_url", "midi_url", "job_state", "job_stage", "job_updated_at", "terminal_at", "expires_at")
        updated = PDFFile.objects.filter(pk=score.id, analysis_task_id=score.analysis_task_id, deletion_pending=False, job_state__in=["", "QUEUED", "RUNNING"]).update(
            **{field: getattr(score, field) for field in fields})
        if not updated:
            superseded = True
            score.refresh_from_db()

    try:
        score = PDFFile.objects.get(id=score_id)
        request_id = self.request.id
        if score.analysis_task_id and request_id and score.analysis_task_id != request_id:
            superseded = True
            return {"stage": "SUPERSEDED", "message": "A newer job owns this score."}
        if request_id and score.job_state in {"SUCCESS", "FAILURE"}:
            superseded = True
            return {"stage": score.job_stage, "status": read_results(score.results).get("processing", {}).get("status")}
        if request_id:
            score.analysis_task_id = request_id
            score.save(update_fields=["analysis_task_id"])
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
            update_stage("TRANSCRIBING_AUDIO", "Preparing audio transcription", 20)
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
            omr_metadata = {
                "applied": False,
                "source": "omr",
                "notation": "preserved_recognition",
                "recognition_quality": "unverified",
            }

        recognition = outcome("success", current_stage, "recognition_available",
                              "Approximate transcription is available." if resolved_source_type == "audio" else "Recognized notation is available; fidelity is unverified.", ["notation"])
        current_stage = "GENERATING_MUSICXML"
        output_score_path = canonicalize_notation(output_score_path, score_id)

        score.musicxml_url = f"/api/serve-musicxml/{score.id}/"
        score.midi_url = None
        text_content = read_results(score.results).get("text_content")
        score.results = {"text_content": text_content, "schema_version": 2, "processing": {"schema_version": 1, "status": "running", "terminal": False,
                         "components": {"recognition": recognition}}}
        updated = PDFFile.objects.filter(pk=score.id, analysis_task_id=score.analysis_task_id, deletion_pending=False, job_state__in=["", "QUEUED", "RUNNING"]).update(
            musicxml_url=score.musicxml_url, midi_url=None, results=score.results)
        if not updated:
            raise JobNoLongerActive()
        current_stage = "ANALYZING_SCORE"
        update_stage("ANALYZING_SCORE", "Running score analysis with Music21", 85)
        analysis = analyze_with_music21(output_score_path, score)
        if audio_metadata:
            analysis["audio_transcription"] = audio_metadata
        elif resolved_source_type != PDFFile.SOURCE_TYPE_AUDIO:
            analysis["score_cleanup"] = omr_metadata

        if not available(score, "midi"):
            score.midi_url = None
        analysis["artifacts"] = artifact_metadata(score, file_ext, resolved_source_type)
        score.results = analysis
        score.results = finalize(score, analysis, recognition)
        partial = score.results["processing"]["status"] != "success"
        score.job_state = "SUCCESS" if score.processed else "FAILURE"
        score.job_stage = "PARTIAL" if partial and score.processed else "COMPLETED" if score.processed else "FAILED"
        score.job_updated_at = timezone.now()
        save_terminal()
        terminal_payload = {"stage": score.job_stage, "message": "Usable outputs are available with limitations." if partial else "Analysis completed",
                "progress_percent": 100, "status": score.results["processing"]["status"]}
        return terminal_payload

    except JobNoLongerActive:
        superseded = True
        score.refresh_from_db()
        return {"stage": score.job_stage, "status": read_results(score.results).get("processing", {}).get("status")}
    except Exception as exc:
        logger.error("Error processing score ID %s: %s", score_id, str(exc))
        error_payload = {"error": "Processing could not be completed.", "stage": current_stage,
                         "message": "Processing could not be completed.", "error_type": current_stage.lower()}
        if score is not None:
            analysis.update(error_payload)
            recognition = recognition or outcome("failed", current_stage,
                exc.code if isinstance(exc, RecognitionError) else "recognition_failed",
                exc.public_message if isinstance(exc, RecognitionError) else "Input could not be converted to notation.")
            score.results = finalize(score, analysis, recognition, failure_stage=current_stage)
            score.job_state = "SUCCESS" if score.processed else "FAILURE"
            score.job_stage = "PARTIAL" if score.processed else "FAILED"
            score.job_updated_at = timezone.now()
            save_terminal()
            if score.processed:
                return {"stage": "PARTIAL", "message": "Notation remains available; processing was limited.", "status": "partial", "progress_percent": 100}
        raise
    finally:
        # Scheduling failure must never replace the processing outcome/exception.
        try:
            if not superseded:
                if score is not None and score.retention_kind == "analysis" and score.analysis_task_id:
                    cleanup_temp_files.apply_async((score_id,), kwargs={"expected_task_id": score.analysis_task_id}, countdown=settings.CLEANUP_DELAY_SECONDS)
                else:
                    cleanup_temp_files.apply_async((score_id,), countdown=settings.CLEANUP_DELAY_SECONDS)
        except Exception:
            logger.exception("Cleanup scheduling failed for score %s", score_id)
            try:
                if score is not None and score.job_state in {"SUCCESS", "FAILURE"}:
                    results = read_results(score.results)
                    results.setdefault("processing", {}).setdefault("components", {})["cleanup_scheduling"] = outcome(
                        "failed", "SCHEDULING_CLEANUP", "cleanup_schedule_failed", "Cleanup could not be scheduled.")
                    score.results = finalize(score, results)
                    if score.processed:
                        score.job_stage = "PARTIAL"
                    PDFFile.objects.filter(pk=score.pk, analysis_task_id=score.analysis_task_id, deletion_pending=False).update(
                        results=score.results, job_stage=score.job_stage)
                    if terminal_payload is not None:
                        terminal_payload.update(stage=score.job_stage, status=score.results["processing"]["status"],
                                                message="Processing finished with limitations.")
            except Exception:
                logger.exception("Could not persist cleanup scheduling failure for score %s", score_id)


@shared_task(autoretry_for=(OSError,), retry_backoff=True, retry_kwargs={"max_retries": 8})
def cleanup_temp_files(score_id, expected_task_id=None):
    return cleanup_session(score_id, expected_task_id)
