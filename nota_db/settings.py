from pathlib import Path
import os
from dotenv import load_dotenv
import dj_database_url

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent.parent

SECRET_KEY = os.environ.get("SECRET_KEY")

DEBUG = os.environ.get("DEBUG", "False").lower() == "true"

#ALLOWED_HOSTS = os.environ.get("ALLOWED_HOSTS", "127.0.0.1,localhost").split(",")




# Enhanced ALLOWED_HOSTS configuration
if DEBUG:
    ALLOWED_HOSTS = ['127.0.0.1', 'localhost', 'api.notadb.xyz',]
else:
    # Production hosts
    allowed_hosts_env = os.environ.get("ALLOWED_HOSTS", "")
    base_hosts = [
        'api.notadb.xyz',
	'api.notadb.xyz:8443'
        'notadb.xyz',
        '5.189.190.253',  # Your VPS IP
        'nota_web',  # Container name
        'nota-caddy',  # Caddy container name
    ]
    
    if allowed_hosts_env:
        env_hosts = [host.strip() for host in allowed_hosts_env.split(",")]
        ALLOWED_HOSTS = list(set(base_hosts + env_hosts))
    else:
        ALLOWED_HOSTS = base_hosts

# Add this for better security with reverse proxy
USE_X_FORWARDED_HOST = True
USE_X_FORWARDED_PORT = True
SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')


TEMP_STORAGE_DIR = Path("/tmp/nota")
TEMP_STORAGE_DIR.mkdir(parents=True, exist_ok=True)

CLEANUP_DELAY_SECONDS = 60 * 60  # 1 hour

OPENAI_API_KEY = os.environ.get(
    "OPENAI_API_KEY",
    "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",
)


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
            "NAME": os.environ.get("DB_NAME"),
            "USER": os.environ.get("DB_USER"),
            "PASSWORD": os.environ.get("DB_PASSWORD"),
            "HOST": os.environ.get("DB_HOST"),
            "PORT": os.environ.get("DB_PORT", "5432"),
        }
    }
else:
    database_url = os.environ.get("DATABASE_URL")
    DATABASES = {
        "default": dj_database_url.parse(
            database_url, conn_max_age=600, ssl_require=False
        )
    }


CORS_ALLOWED_ORIGINS = [
    "https://nota-db-git-main-gitahievans-projects.vercel.app",
    "http://localhost:9002",
    "http://127.0.0.1:8000",
    "https://api.notadb.xyz",
    "https://api.notadb.xyz:8443", 
    "https://notadb.xyz",
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


# If using custom ports, also add:
if not DEBUG:
    CORS_ALLOWED_ORIGINS.extend([
        "https://api.notadb.xyz:8443",
        "http://api.notadb.xyz:8080",
    ])


# Security settings
SECURE_SSL_REDIRECT = (
    False  # Disable in development, will be handled by Caddy in production
)
SESSION_COOKIE_SECURE = False  # Disable in development, will be handled in production
CSRF_COOKIE_SECURE = False  # Disable in development, will be handled in production
SESSION_COOKIE_SAMESITE = "Lax"
SECURE_BROWSER_XSS_FILTER = True
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_HSTS_SECONDS = 0  # Disable HSTS in development
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
AWS_STORAGE_BUCKET_NAME = "nota-pdfs"
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
    f"https://{os.environ.get('AWS_STORAGE_BUCKET_NAME')}.r2.cloudflarestorage.com/"
)
MEDIA_ROOT = BASE_DIR / "media" if DEBUG else None

# Celery configuration
CELERY_BROKER_URL = "redis://redis:6379/0"
CELERY_RESULT_BACKEND = "redis://redis:6379/0"
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
