"""Production overrides, selected only by the production Compose project."""
from .settings import *  # noqa: F403

if DEBUG:
    raise ImproperlyConfigured("Production settings require DJANGO_DEBUG=False.")

CSRF_TRUSTED_ORIGINS = [
    value.strip()
    for value in os.environ.get("CSRF_TRUSTED_ORIGINS", "").split(",")
    if value.strip()
]
SESSION_COOKIE_SECURE = os.environ.get("HTTPS_ENABLED", "False") == "True"
CSRF_COOKIE_SECURE = SESSION_COOKIE_SECURE
SECURE_SSL_REDIRECT = SESSION_COOKIE_SECURE
# Enable only behind a proxy that overwrites X-Forwarded-Proto.
if os.environ.get("TRUST_PROXY_HEADERS", "False") == "True":
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

EMAIL_BACKEND = "django.core.mail.backends.smtp.EmailBackend"
EMAIL_HOST = os.environ.get("EMAIL_HOST", "in-v3.mailjet.com")
EMAIL_PORT = int(os.environ.get("EMAIL_PORT", "587"))
EMAIL_HOST_USER = os.environ.get("EMAIL_HOST_USER") or MAILJET_API_KEY
EMAIL_HOST_PASSWORD = os.environ.get("EMAIL_HOST_PASSWORD") or MAILJET_API_SECRET
EMAIL_USE_TLS = True
EMAIL_TIMEOUT = 15
DEFAULT_FROM_EMAIL = MAIL_FROM_EMAIL

if STORAGE_TYPE != "r2":
    raise ImproperlyConfigured("Production requires STORAGE_TYPE=r2; local media is not served.")
for name in ("R2_BUCKET_NAME", "R2_ACCOUNT_ID", "R2_ACCESS_KEY_ID", "R2_SECRET_ACCESS_KEY"):
    if not globals().get(name):
        raise ImproperlyConfigured(f"{name} is required in production.")
