from pathlib import Path
from datetime import timedelta
import os
import sys
from urllib.parse import urlsplit
from corsheaders.defaults import default_headers as default_cors_headers
from django.core.exceptions import ImproperlyConfigured

try:
    from dotenv import load_dotenv
except ModuleNotFoundError:
    def load_dotenv(*args, **kwargs):
        return False

load_dotenv()

# Build paths inside the project like this: BASE_DIR / 'subdir'.
BASE_DIR = Path(__file__).resolve().parent.parent


# Quick-start development settings - unsuitable for production
# See https://docs.djangoproject.com/en/4.2/howto/deployment/checklist/

# SECURITY WARNING: keep the secret key used in production secret!
DEFAULT_SECRET_KEY = 'django-insecure-()x#erm&sib*1ms&tj4zn85&uz-vp0&%bz!7xl!^!b-s*(2zvy'

DEBUG = os.environ.get("DJANGO_DEBUG", "False") == "True"

# A development key is allowed only when debug is explicitly enabled.
SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", "")
if DEBUG and not SECRET_KEY.strip():
    SECRET_KEY = DEFAULT_SECRET_KEY

if not DEBUG and (
    not SECRET_KEY.strip()
    or SECRET_KEY == DEFAULT_SECRET_KEY
    or SECRET_KEY.startswith("django-insecure-")
    or len(SECRET_KEY) < 50
    or len(set(SECRET_KEY)) < 5
):
    raise ImproperlyConfigured(
        "DJANGO_SECRET_KEY must be a non-development secret with at least "
        "50 characters and 5 distinct characters when DJANGO_DEBUG is False."
    )

ALLOWED_HOSTS = os.environ.get(
    "DJANGO_ALLOWED_HOSTS",
    "localhost,127.0.0.1",
).split(",")

AUTH_USER_MODEL = "users.User"

# Application definition

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    "corsheaders",
    "django_extensions",

    "rest_framework",
    "drf_spectacular",
    "rest_framework_simplejwt",
    "rest_framework_simplejwt.token_blacklist",
    "mptt",

    # ClassPing
    "apps.users",
    "apps.locations",
    "apps.schools",
    "apps.staffs",
    "apps.academic_years",
    "apps.classes",
    "apps.students",
    "apps.guardians",
    "apps.fee_types",
    "apps.student_invoices",
    "apps.payments",
    "apps.payment_gateway.apps.PaymentGatewayConfig",
    "apps.wallets.apps.WalletsConfig",
    "apps.report_layouts",
    "apps.report_sections",
    "apps.score_settings",
    "apps.indicators",
    "apps.activities",
    "apps.assessments",
    "apps.parent_portal",
    "apps.uploads.apps.UploadsConfig",

    "apps.core.apps.CoreConfig",

    # Admin web application
    "apps.admin_web",
]

MIDDLEWARE = [
    # First, so the reported server time covers every other middleware too.
    "apps.core.middleware.ServerTimingMiddleware",
    'django.middleware.security.SecurityMiddleware',
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "corsheaders.middleware.CorsMiddleware",
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'apps.admin_web.middleware.AdminWebRoleMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'config.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        "DIRS": [BASE_DIR / "templates"],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

WSGI_APPLICATION = 'config.wsgi.application'


# Database
# https://docs.djangoproject.com/en/4.2/ref/settings/#databases

import dj_database_url

DATABASES = {
    "default": dj_database_url.config(
        default=os.environ.get("DATABASE_URL")
    )
}


# Password validation
# https://docs.djangoproject.com/en/4.2/ref/settings/#auth-password-validators

AUTH_PASSWORD_VALIDATORS = [
    {
        'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator',
    },
]


# Internationalization
# https://docs.djangoproject.com/en/4.2/topics/i18n/

LANGUAGE_CODE = 'en-us'

TIME_ZONE = os.environ.get("DJANGO_TIME_ZONE", "Asia/Jakarta")

USE_I18N = True

USE_TZ = True

# Local frontend development runs on ports 3000/3001 while the API runs on 8000.
CORS_ALLOWED_ORIGINS = [
    origin.strip()
    for origin in os.environ.get(
        "CORS_ALLOWED_ORIGINS",
        "http://localhost:3000,http://localhost:3001,http://127.0.0.1:3000,http://127.0.0.1:3001",
    ).split(",")
    if origin.strip()
]
# Browsers must be allowed to send Idempotency-Key (gateway checkout).
CORS_ALLOW_HEADERS = (*default_cors_headers, "idempotency-key")

# Let browser clients read the Server-Timing header on cross-origin calls.
CORS_EXPOSE_HEADERS = ["Server-Timing"]

# Server-Timing header on /api/ responses (server time and DB query usage).
SERVER_TIMING_ENABLED = os.environ.get("SERVER_TIMING_ENABLED", "True") == "True"
SERVER_TIMING_PATH_PREFIX = "/api/"

# Static files (CSS, JavaScript, Images)
# https://docs.djangoproject.com/en/4.2/howto/static-files/

STATIC_URL = "/static/"

STATICFILES_DIRS = [
    BASE_DIR / "static",
]
STATIC_ROOT = BASE_DIR / "staticfiles"

# Default primary key field type
# https://docs.djangoproject.com/en/4.2/ref/settings/#default-auto-field

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

REST_FRAMEWORK = {
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
    "DEFAULT_AUTHENTICATION_CLASSES": (
        "apps.users.authentication.CustomJWTAuthentication",
    ),
    "DEFAULT_PERMISSION_CLASSES": (
        "apps.users.permissions.RoleBasedAccessPermission",
    ),
    "DEFAULT_PAGINATION_CLASS": "apps.core.pagination.StandardResultsSetPagination",
    "PAGE_SIZE": 20,
    "DEFAULT_FILTER_BACKENDS": (
        "apps.core.pagination.SafeOrderingFilter",
    ),
    # Applied per view by apps.users.throttling; see ACCOUNT_ROLE_POLICY.md.
    "DEFAULT_THROTTLE_RATES": {
        "login_ip": "20/min",
        "login_email": "5/min",
        "token_refresh": "30/min",
        "password_forgot_ip": "10/hour",
        "password_forgot_email": "3/hour",
        "password_reset": "20/hour",
        "password_change": "5/min",
        "gateway_checkout": "10/min",
        "withdrawal_otp": "5/min",
    },
    # Ignore X-Forwarded-For unless production trusts its proxy.
    "NUM_PROXIES": 0,
}

# Log to stdout so container platforms can collect application logs.
LOG_LEVEL = os.environ.get("DJANGO_LOG_LEVEL", "INFO").upper()

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "standard": {
            "format": "%(asctime)s %(levelname)s %(name)s: %(message)s",
        },
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "standard",
        },
    },
    "root": {
        "handlers": ["console"],
        "level": LOG_LEVEL,
    },
    "loggers": {
        "django": {
            "handlers": ["console"],
            "level": LOG_LEVEL,
            "propagate": False,
        },
        "django.request": {
            "handlers": ["console"],
            "level": "WARNING",
            "propagate": False,
        },
        "apps": {
            "handlers": ["console"],
            "level": LOG_LEVEL,
            "propagate": False,
        },
        # Provider responses are logged at INFO for payment troubleshooting,
        # even when the deployment's general DJANGO_LOG_LEVEL is WARNING.
        "payment_aggregator.providers.rintisan.client": {
            "handlers": ["console"],
            "level": "INFO",
            "propagate": False,
        },
    },
}

# Password changes invalidate access and refresh tokens from every login.
SIMPLE_JWT = {
    "ACCESS_TOKEN_LIFETIME": timedelta(minutes=10),
    "CHECK_REVOKE_TOKEN": True,
    "TOKEN_REFRESH_SERIALIZER": "apps.users.serializers.PasswordAwareTokenRefreshSerializer",
}

EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"
DEFAULT_FROM_EMAIL = "noreply@classping.com"
PASSWORD_RESET_URL = os.environ.get(
    "PASSWORD_RESET_URL",
    "http://localhost:3000/reset-password/",
)
SCHOOL_PASSWORD_RESET_URL = os.environ.get(
    "SCHOOL_PASSWORD_RESET_URL",
    PASSWORD_RESET_URL,
)

# Swagger/ReDoc/schema are exposed only in debug unless explicitly enabled.
API_DOCS_ENABLED = os.environ.get(
    "API_DOCS_ENABLED",
    "True" if DEBUG else "False",
) == "True"

SPECTACULAR_SETTINGS = {
    "TITLE": "ClassPing API",
    "DESCRIPTION": "ClassPing Backend API",
    "VERSION": "1.0.0",

    # Group APIs by the first path after /api/
    "SCHEMA_PATH_PREFIX": r"/api/",

    # JWT authentication
    "APPEND_COMPONENTS": {
        "securitySchemes": {
            "BearerAuth": {
                "type": "http",
                "scheme": "bearer",
                "bearerFormat": "JWT",
            }
        }
    },

    # Apply Bearer authentication to endpoints
    "SECURITY": [
        {
            "BearerAuth": [],
        }
    ],
}

# Media Files Configuration
MEDIA_URL = "/media/"
MEDIA_ROOT = BASE_DIR / "media"

# Storage Configuration
# Set to 'r2' for Cloudflare R2, or 'local' for local filesystem
STORAGE_TYPE = os.environ.get("STORAGE_TYPE", "local")

# Cloudflare R2 Configuration
R2_BUCKET_NAME = os.environ.get("R2_BUCKET_NAME", "classping-media")
R2_ACCOUNT_ID = os.environ.get("R2_ACCOUNT_ID", "")
R2_ACCESS_KEY_ID = os.environ.get("R2_ACCESS_KEY_ID", "")
R2_SECRET_ACCESS_KEY = os.environ.get("R2_SECRET_ACCESS_KEY", "")
R2_REGION = os.environ.get("R2_REGION", "auto")

# Site URL for generating full URLs
SITE_URL = os.environ.get("SITE_URL", "http://localhost:8000")

# Upload metadata cache. Redis is used when configured; local development can
# fall back to the in-process cache in MediaService.
REDIS_URL = os.environ.get("REDIS_URL", "")
UPLOAD_METADATA_TTL = int(os.environ.get("UPLOAD_METADATA_TTL", "3600"))
# Uploads above this size are rejected when they are attached to a record.
MAX_UPLOAD_BYTES = int(os.environ.get("MAX_UPLOAD_BYTES", str(10 * 1024 * 1024)))
# Storage capacity for branches without their own storage_capacity_bytes.
DEFAULT_BRANCH_STORAGE_BYTES = int(os.environ.get("DEFAULT_BRANCH_STORAGE_BYTES", str(5 * 1024 ** 3)))

RUNNING_TESTS = len(sys.argv) > 1 and sys.argv[1] == "test"

# Rate-limit counters must be shared by every worker, so use Redis when set.
# Tests get a no-op cache; throttling tests opt into a local cache.
if RUNNING_TESTS:
    CACHES = {"default": {"BACKEND": "django.core.cache.backends.dummy.DummyCache"}}
elif REDIS_URL:
    CACHES = {"default": {"BACKEND": "django.core.cache.backends.redis.RedisCache", "LOCATION": REDIS_URL}}

# Celery (config/celery.py). The broker is the same Redis as REDIS_URL but
# database /1, so queues never mix with the Django cache in /0. Empty when
# REDIS_URL is not set (then tasks are not queued; see payment_gateway).
CELERY_BROKER_URL = urlsplit(REDIS_URL)._replace(path="/1").geturl() if REDIS_URL else ""
CELERY_TIMEZONE = TIME_ZONE
CELERY_TASK_SERIALIZER = "json"
CELERY_ACCEPT_CONTENT = ["json"]
# A task is acknowledged only after it finished, so a worker restart puts
# in-flight and delayed (eta) tasks back on the queue instead of losing them.
CELERY_TASK_ACKS_LATE = True
CELERY_WORKER_PREFETCH_MULTIPLIER = 1
CELERY_WORKER_HIJACK_ROOT_LOGGER = False
CELERY_BROKER_CONNECTION_RETRY_ON_STARTUP = True
CELERY_BROKER_CONNECTION_TIMEOUT = 3
CELERY_BROKER_TRANSPORT_OPTIONS = {
    # Must exceed the longest eta delay (payment expiry is ~62 minutes),
    # otherwise Redis redelivers the delayed task and it runs twice.
    "visibility_timeout": 2 * 60 * 60,
    "socket_connect_timeout": 3,
    "socket_timeout": 5,
}
# Publishing from a web request must fail fast instead of blocking it.
CELERY_TASK_PUBLISH_RETRY_POLICY = {
    "max_retries": 2,
    "interval_start": 0,
    "interval_step": 0.5,
    "interval_max": 1,
}
# Tests run tasks inline and need no broker or worker.
CELERY_TASK_ALWAYS_EAGER = RUNNING_TESTS
CELERY_TASK_EAGER_PROPAGATES = RUNNING_TESTS

# Mailjet Configuration
MAILJET_API_KEY = os.environ.get("MAILJET_API_KEY")
MAILJET_API_SECRET = os.environ.get("MAILJET_API_SECRET")
MAIL_FROM_EMAIL = os.environ.get("MAIL_FROM_EMAIL", "the.class.ping@gmail.com")
MAIL_FROM_NAME = os.environ.get("MAIL_FROM_NAME", "ClassPing")
MAILJET_TEMPLATES = {
    "invoice_reminder": 8345505,
    "payment_submitted": 8345507,
    "payment_completed": 8345508,
    "payment_rejected": 8345509,
    "welcome_email": 8388105,
    # Withdrawals (branch email). Without withdrawal_otp no withdrawal can be
    # made (OTP_NOT_SENT); without withdrawal_status the email is skipped.
    "withdrawal_otp": 8507159,
    "withdrawal_status": 8507188,
    # Nightly branch balance mismatch alert to OPS_ALERT_EMAIL.
    "balance_alert": 8507233,
}
