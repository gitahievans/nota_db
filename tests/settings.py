"""Standalone settings: no .env, production database, broker, or cloud storage."""
import atexit
from pathlib import Path
import tempfile

_workspace = tempfile.TemporaryDirectory(prefix="nota-verification-")
atexit.register(_workspace.cleanup)
BASE_DIR = Path(_workspace.name)
TEMP_STORAGE_DIR = BASE_DIR / "sessions"
TEMP_STORAGE_DIR.mkdir()
MEDIA_ROOT = BASE_DIR / "media"
SECRET_KEY = "local-verification-only"
DEBUG = False
ALLOWED_HOSTS = ["testserver", "localhost"]
INSTALLED_APPS = ["django.contrib.auth", "django.contrib.contenttypes", "files", "rest_framework"]
DATABASES = {"default": {"ENGINE": "django.db.backends.sqlite3", "NAME": ":memory:"}}
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
ROOT_URLCONF = "tests.urls"
MIDDLEWARE = []
USE_TZ = True
STORAGES = {"default": {"BACKEND": "django.core.files.storage.FileSystemStorage"}}
CACHES = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}}
CELERY_BROKER_URL = "memory://"
CELERY_RESULT_BACKEND = "cache+memory://"
CELERY_TASK_ALWAYS_EAGER = False
CLEANUP_DELAY_SECONDS = 3600
REST_FRAMEWORK = {"DEFAULT_AUTHENTICATION_CLASSES": [], "UNAUTHENTICATED_USER": None}
