"""Analysis retention. All writers and deletion share OS locks on the artifact volume.

Locks are striped: the fixed infrastructure files contain no session identifiers or
content. They must never be unlinked while services are running (inode races).
"""
from contextlib import contextmanager, ExitStack
from contextvars import ContextVar
from datetime import timedelta
from functools import wraps
from pathlib import Path
import logging
import os
import shutil

from django.conf import settings
from django.http import JsonResponse
from django.http import Http404
from django.utils import timezone

from .models import PDFFile

logger = logging.getLogger(__name__)
_operations = ContextVar("analysis_operations", default=None)


class SessionBusy(Exception):
    pass


def storage_root():
    root = Path(settings.TEMP_STORAGE_DIR).resolve()
    repo = Path(__file__).resolve().parent.parent
    # Never permit a cleanup configuration to reach repository inputs/catalog.
    for protected in (repo / "tests", repo / "output", repo / "files"):
        if root == protected or root in protected.parents or protected in root.parents:
            raise ValueError("Unsafe analysis storage root")
    return root


@contextmanager
def session_lock(score_id, blocking=False):
    lock_root = storage_root() / ".locks"
    lock_root.mkdir(parents=True, exist_ok=True)
    path = lock_root / str(int(score_id) % 256)
    with path.open("a+b") as handle:
        if os.name == "nt":
            import msvcrt
            if path.stat().st_size == 0:
                handle.write(b"0")
                handle.flush()
            handle.seek(0)
            # LK_LOCK has a finite wait; workers use Celery retry on contention.
            mode = msvcrt.LK_LOCK if blocking else msvcrt.LK_NBLCK
            try:
                msvcrt.locking(handle.fileno(), mode, 1)
            except OSError as exc:
                raise SessionBusy() from exc
        else:
            import fcntl
            try:
                fcntl.flock(handle, fcntl.LOCK_EX | (0 if blocking else fcntl.LOCK_NB))
            except BlockingIOError as exc:
                raise SessionBusy() from exc
        try:
            yield
        finally:
            if os.name == "nt":
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(handle, fcntl.LOCK_UN)


def operation_scope(method):
    """Hold an upload's lock from creation through dispatch, including OCR."""
    @wraps(method)
    def wrapped(*args, **kwargs):
        with ExitStack() as stack:
            token = _operations.set(stack)
            try:
                return method(*args, **kwargs)
            finally:
                _operations.reset(token)
    return wrapped


def hold_upload(score):
    _operations.get().enter_context(session_lock(score.pk, blocking=True))


def expired(score, now=None):
    return score.retention_kind == "analysis" and (
        score.deletion_pending or (score.expires_at is not None and score.expires_at <= (now or timezone.now())))


def terminal_fields(score, now=None):
    if score.retention_kind == "analysis" and score.terminal_at is None:
        score.terminal_at = now or timezone.now()
        score.expires_at = score.terminal_at + timedelta(seconds=settings.CLEANUP_DELAY_SECONDS)
    return {"terminal_at": score.terminal_at, "expires_at": score.expires_at}


def lifetime(score):
    if score.retention_kind != "analysis":
        return {"schema_version": 1, "policy": score.retention_kind, "expires_at": None}
    return {"schema_version": 1, "policy": "temporary_analysis", "retention_seconds": settings.CLEANUP_DELAY_SECONDS,
            "terminal_at": score.terminal_at.isoformat() if score.terminal_at else None,
            "expires_at": score.expires_at.isoformat() if score.expires_at else None,
            "state": "expired" if expired(score) else "available" if score.terminal_at else "processing",
            "message": "Temporary results are available for one hour after processing finishes, then deleted."}


def unavailable():
    # No tombstone: absence is not evidence that an ID previously existed.
    response = JsonResponse({"code": "analysis_unavailable_or_expired",
                             "error": "This score is unavailable or its temporary analysis has expired."}, status=404)
    response["Cache-Control"] = "no-store"
    return response


def visible_score(score_id):
    score = PDFFile.objects.filter(pk=score_id).first()
    return score if score and not expired(score) else None


def session_view(mutating=False):
    """Gate every ID route; mutation lock spans provider work and final write."""
    def decorate(method):
        @wraps(method)
        def wrapped(self, request, *args, **kwargs):
            score_id = kwargs.get("score_id", kwargs.get("pk"))
            if score_id is None:
                score_id = request.data.get("score_id")
            if score_id is None:
                return method(self, request, *args, **kwargs)
            try:
                score = visible_score(score_id)
            except (ValueError, TypeError):
                return unavailable()
            if score is None:
                return unavailable()
            if not mutating:
                try:
                    response = method(self, request, *args, **kwargs)
                except (Http404, PDFFile.DoesNotExist, FileNotFoundError):
                    return unavailable()
                if not visible_score(score_id):
                    response.close()
                    return unavailable()
                if score.retention_kind == "analysis":
                    response["Cache-Control"] = "no-store"
                return response
            try:
                with session_lock(score_id):
                    if not visible_score(score_id):
                        return unavailable()
                    response = method(self, request, *args, **kwargs)
                    if score.retention_kind == "analysis":
                        response["Cache-Control"] = "no-store"
                    return response
            except SessionBusy:
                return JsonResponse({"code": "analysis_busy", "error": "Processing is active; retry later."}, status=409)
        return wrapped
    return decorate


def worker_session(method):
    @wraps(method)
    def wrapped(task, score_id, *args, **kwargs):
        try:
            with session_lock(score_id):
                score = visible_score(score_id)
                if score is None or score.retention_kind == "catalog":
                    return {"stage": "UNAVAILABLE", "message": "Analysis is unavailable."}
                return method(task, score_id, *args, **kwargs)
        except SessionBusy:
            raise task.retry(countdown=10, max_retries=360)
    return wrapped


def cleanup_session(score_id, expected_task_id=None):
    try:
        with session_lock(score_id):
            score = PDFFile.objects.filter(pk=score_id, retention_kind="analysis").first()
            if not score:
                return "excluded_or_missing"
            if expected_task_id and score.analysis_task_id != expected_task_id:
                return "superseded"
            if score.job_state not in {"SUCCESS", "FAILURE"} and not score.deletion_pending:
                return "not_due"
            if not expired(score):
                return "not_due"
            # Persist intent before filesystem mutation. Row retained on failure for retry.
            PDFFile.objects.filter(pk=score.pk).update(deletion_pending=True)
            root = storage_root()
            directory = root / str(int(score_id))
            if directory.is_symlink() or directory.resolve().parent != root:
                raise ValueError("Unsafe analysis directory")
            # New sessions never own catalog storage. Unexpected FileField needs review.
            if score.file:
                raise ValueError("Analysis has an unexpected catalog storage reference")
            if directory.exists():
                shutil.rmtree(directory)
            if score.analysis_task_id:
                try:
                    from celery.result import AsyncResult
                    AsyncResult(score.analysis_task_id).forget()
                except Exception:
                    # Backend TTL independently bounds result metadata during outages.
                    logger.exception("Task metadata forget failed for %s; backend TTL applies", score_id)
            # Relations cascade only through the M2M join; Category rows survive.
            score.delete()
            return "deleted"
    except SessionBusy:
        return "busy"


def recover_sessions():
    """Broker-independent, bounded-memory sweep. Only explicitly owned sessions."""
    from .jobs import fail_job
    counts = {}
    for score_id in PDFFile.objects.filter(retention_kind="analysis").values_list("pk", flat=True).iterator(chunk_size=200):
        try:
            with session_lock(score_id):
                score = PDFFile.objects.filter(pk=score_id, retention_kind="analysis").first()
                if not score:
                    continue
                if score.terminal_at is None:
                    if score.job_state in {"SUCCESS", "FAILURE"}:
                        fields = terminal_fields(score)
                        PDFFile.objects.filter(pk=score_id).update(**fields)
                    else:
                        last_progress = score.job_updated_at or score.uploaded_at
                        if (timezone.now() - last_progress).total_seconds() >= getattr(settings, "ANALYSIS_JOB_STALE_SECONDS", 3600):
                            fail_job(score, score.job_stage or "QUEUED", "job_progress_timeout")
            result = cleanup_session(score_id)
        except SessionBusy:
            result = "busy"
        except Exception:
            logger.exception("Analysis cleanup failed for %s; retained for retry", score_id)
            result = "retry"
        counts[result] = counts.get(result, 0) + 1
    return counts
