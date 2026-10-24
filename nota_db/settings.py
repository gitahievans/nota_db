from pathlib import Path
import os
from dotenv import load_dotenv
import dj_database_url

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent.parent

SECRET_KEY = os.environ.get("SECRET_KEY", "django-insecure-key-for-dev")

DEBUG = os.environ.get("DEBUG", "False").lower() in ("true", "1", "yes")


def env_list(name, default=()):
    value = os.environ.get(name, "")
    return [item.strip() for item in value.split(",") if item.strip()] or list(default)

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

# Enhanced ALLOWED_HOSTS configuration
if DEBUG:
    ALLOWED_HOSTS = [
        "127.0.0.1",
        "localhost",
        "api.notadb.xyz",
    ]
else:
    base_hosts = [
        "api.scorelearn.site",
        "web",
    ]
    ALLOWED_HOSTS = list(set(base_hosts + env_list("ALLOWED_HOSTS")))

# Add this for better security with reverse proxy
USE_X_FORWARDED_HOST = True
USE_X_FORWARDED_PORT = True
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")


TEMP_STORAGE_DIR = Path("/tmp/nota")
TEMP_STORAGE_DIR.mkdir(parents=True, exist_ok=True)

CLEANUP_DELAY_SECONDS = 60 * 60  # 1 hour
ANALYSIS_JOB_STALE_SECONDS = 3600
# P5 polling recovery: maximum interval without a recorded stage update, not retention.
ANALYSIS_JOB_STALE_SECONDS = 60 * 60

OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")


INSTALLED_APPS = [
    "django.contrib.auth",  # Required for Permission model
    "django.contrib.admin",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "nota_db",
    "files",
    "corsheaders",
    "rest_framework",
    "django_ai_assistant",
]


MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "corsheaders.middleware.CorsMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "nota_db.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "nota_db.wsgi.application"


# Database configuration
if DEBUG:
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.postgresql",
            "NAME": os.environ.get("DB_NAME", "nota_db"),
            "USER": os.environ.get("DB_USER", "postgres"),
            "PASSWORD": os.environ.get("DB_PASSWORD", "password"),
            "HOST": os.environ.get("DB_HOST", "db"),
            "PORT": os.environ.get("DB_PORT", "5432"),
        }
    }
else:
    database_url = os.environ.get("DATABASE_URL")
    if database_url:
        DATABASES = {
            "default": dj_database_url.parse(
                database_url, conn_max_age=600, ssl_require=False
            )
        }
    else:
        # Fallback to individual credentials if DATABASE_URL is missing
        DATABASES = {
            "default": {
                "ENGINE": "django.db.backends.postgresql",
                "NAME": os.environ.get("DB_NAME", "nota_db"),
                "USER": os.environ.get("DB_USER", "postgres"),
                "PASSWORD": os.environ.get("DB_PASSWORD", "password"),
                "HOST": os.environ.get("DB_HOST", "db"),
                "PORT": os.environ.get("DB_PORT", "5432"),
            }
        }


CORS_ALLOWED_ORIGINS = [
    "http://localhost:9002",
    "http://127.0.0.1:9002",
    "https://scorelearn.site",
]
if not DEBUG:
    production_url = os.environ.get("PRODUCTION_URL", "")
    if production_url and production_url.startswith(("http://", "https://")):
        CORS_ALLOWED_ORIGINS.append(production_url)

CORS_ALLOW_ALL_ORIGINS = False
CORS_ALLOW_METHODS = [
    "DELETE",
    "GET",
    "OPTIONS",
    "PATCH",
    "POST",
    "PUT",
]


CSRF_TRUSTED_ORIGINS = env_list(
    "CSRF_TRUSTED_ORIGINS",
    ["https://api.scorelearn.site", "https://scorelearn.site"],
)


# Security settings
SECURE_SSL_REDIRECT = not DEBUG
SESSION_COOKIE_SECURE = not DEBUG
CSRF_COOKIE_SECURE = not DEBUG
SESSION_COOKIE_SAMESITE = "Lax"
SECURE_BROWSER_XSS_FILTER = True
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_HSTS_SECONDS = 31536000 if not DEBUG else 0
SECURE_HSTS_INCLUDE_SUBDOMAINS = False
SECURE_HSTS_PRELOAD = False
X_FRAME_OPTIONS = "DENY"


AUTH_PASSWORD_VALIDATORS = [
    {
        "NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.CommonPasswordValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.NumericPasswordValidator",
    },
]


LANGUAGE_CODE = "en-us"

TIME_ZONE = "UTC"

USE_I18N = True

USE_TZ = True


# Static files configuration
STATIC_URL = "/static/"
STATIC_ROOT = "/app/staticfiles"
STATICFILES_STORAGE = "whitenoise.storage.CompressedManifestStaticFilesStorage"


DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

AWS_ACCESS_KEY_ID = os.environ.get("AWS_ACCESS_KEY_ID")
AWS_SECRET_ACCESS_KEY = os.environ.get("AWS_SECRET_ACCESS_KEY")
AWS_STORAGE_BUCKET_NAME = os.environ.get("AWS_STORAGE_BUCKET_NAME", "nota-pdfs")
AWS_S3_SIGNATURE_VERSION = "s3v4"
AWS_S3_REGION_NAME = "auto"
AWS_S3_FILE_OVERWRITE = False
AWS_DEFAULT_ACL = None
AWS_S3_ENDPOINT_URL = (
    "https://80b4ea6aaa8ed2b91c16beb44843b4ed.r2.cloudflarestorage.com"
)

# Use the custom storage class
DEFAULT_FILE_STORAGE = "files.storage.PDFFileStorage"

# Media files configuration
MEDIA_URL = (
    f"https://{AWS_STORAGE_BUCKET_NAME}.r2.cloudflarestorage.com/"
)
MEDIA_ROOT = BASE_DIR / "media" if DEBUG else None

# Celery configuration
CELERY_BROKER_URL = "redis://redis:6379/0"
CELERY_RESULT_BACKEND = "redis://redis:6379/0"
CELERY_RESULT_EXPIRES = 3600  # Task metadata is temporary too; cleanup also forgets it.
CELERY_REDIS_SOCKET_CONNECT_TIMEOUT = 2
CELERY_REDIS_SOCKET_TIMEOUT = 2
CELERY_ACCEPT_CONTENT = ["json"]
CELERY_TASK_SERIALIZER = "json"
CELERY_RESULT_SERIALIZER = "json"
CELERY_TIMEZONE = "Africa/Nairobi"
CELERY_BROKER_CONNECTION_RETRY_ON_STARTUP = True

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
        },
    },
    "loggers": {
        "": {
            "handlers": ["console"],
            "level": "INFO",
        },
    },
}
