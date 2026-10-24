"""Persisted job association and polling recovery with P6 terminal deadlines."""
from django.conf import settings
from django.utils import timezone
from .outcomes import finalize, outcome, read_results, RECOGNITION_FAILURE_MESSAGE
from .lifecycle import terminal_fields, session_lock, SessionBusy


def fail_job(score, stage, code):
    previous_state, previous_update = score.job_state, score.job_updated_at
    results = read_results(score.results)
    results.setdefault("processing", {}).setdefault("components", {})["job"] = outcome(
        "failed", stage, code, "The job stopped before recording a complete outcome; available outputs are retained.")
    score.results = finalize(score, results)
    score.job_state = "SUCCESS" if score.processed else "FAILURE"
    score.job_stage = "PARTIAL" if score.processed else "FAILED"
    score.job_updated_at = timezone.now()
    terminal_fields(score)
    fields = ("results", "processed", "job_state", "job_stage", "job_updated_at", "terminal_at", "expires_at")
    PDFFile = type(score)
    updated = PDFFile.objects.filter(pk=score.id, analysis_task_id=score.analysis_task_id, deletion_pending=False,
                                    job_state=previous_state, job_updated_at=previous_update).update(
        **{field: getattr(score, field) for field in fields})
    if not updated:
        score.refresh_from_db()


def task_status(score, backend):
    if not score.job_state:
        results = read_results(score.results)
        if not results and not score.processed:
            return None
        return {"state": "SUCCESS" if score.processed else "FAILURE",
                "info": {"stage": "COMPLETED" if score.processed else "FAILED", "message": "Legacy status; component outcomes are unavailable."}}
    if score.job_state not in {"SUCCESS", "FAILURE"}:
        try:
            state = backend(score.analysis_task_id).state if score.analysis_task_id else "PENDING"
        except Exception:
            state = "UNAVAILABLE"
        elapsed = (timezone.now() - score.job_updated_at).total_seconds() if score.job_updated_at else float("inf")
        code = ("job_outcome_missing" if state in {"FAILURE", "REVOKED", "SUCCESS"}
                else "job_progress_timeout" if elapsed > getattr(settings, "ANALYSIS_JOB_STALE_SECONDS", 3600) else None)
        if code:
            if score.retention_kind == "analysis":
                try:
                    with session_lock(score.id):
                        fail_job(score, score.job_stage, code)
                except SessionBusy:
                    pass  # A writer is still alive; do not terminalize active processing.
            else:
                fail_job(score, score.job_stage, code)
    message = ("Processing failed; consult component outcomes for the failing stage." if score.job_state == "FAILURE"
               else "Usable outputs are available with limitations." if score.job_stage == "PARTIAL"
               else "Analysis completed." if score.job_state == "SUCCESS"
               else "Processing is pending or active.")
    failure = None
    if score.job_state == "FAILURE":
        components = read_results(score.results).get("processing", {}).get("components", {})
        # Prefer the cause over downstream missing-artifact consequences.
        for name in ("job", "recognition", "pipeline"):
            candidate = components.get(name)
            if isinstance(candidate, dict) and candidate.get("status") == "failed":
                failure = candidate
                message = candidate.get("message") or message
                if name == "recognition" and score.source_type in {"pdf", "image"}:
                    message = RECOGNITION_FAILURE_MESSAGE
                break
    return {"state": score.job_state if score.job_state in {"SUCCESS", "FAILURE"} else score.job_stage or "PENDING",
            "info": {"stage": score.job_stage, "message": message,
                     "failure_stage": failure.get("stage") if failure else None,
                     "code": failure.get("code") if failure else None,
                     "status": read_results(score.results).get("processing", {}).get("status"),
                     "progress_percent": 100 if score.job_state in {"SUCCESS", "FAILURE"} else None}}
