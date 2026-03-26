from pathlib import Path

import environ

BASE_DIR = Path(__file__).resolve().parent.parent

env = environ.Env(DEBUG=(bool, False))
environ.Env.read_env(BASE_DIR / ".env", overwrite=False)

SECRET_KEY = env("SECRET_KEY", default="django-insecure-dev-key-change-in-production")
DEBUG = env("DEBUG")
ALLOWED_HOSTS = env.list("ALLOWED_HOSTS", default=[])

# Railway: automatically trust the Railway-assigned public domain and internal healthcheck host
_railway_domain = env("RAILWAY_PUBLIC_DOMAIN", default=None)
if _railway_domain and _railway_domain not in ALLOWED_HOSTS:
    ALLOWED_HOSTS.append(_railway_domain)
if "healthcheck.railway.app" not in ALLOWED_HOSTS:
    ALLOWED_HOSTS.append("healthcheck.railway.app")

CSRF_TRUSTED_ORIGINS = env.list("CSRF_TRUSTED_ORIGINS", default=[])
if _railway_domain:
    _railway_origin = f"https://{_railway_domain}"
    if _railway_origin not in CSRF_TRUSTED_ORIGINS:
        CSRF_TRUSTED_ORIGINS.append(_railway_origin)

# Application definition

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.sites",
    # Third-party
    "anymail",
    "axes",
    "markdownx",
    "allauth",
    "allauth.account",
    # Local
    "accounts",
    "events",
]

SITE_ID = 1
SITE_DOMAIN = env("SITE_DOMAIN", default="pleskal.dk")
SITE_NAME = env("SITE_NAME", default="pleskal")

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "axes.middleware.AxesMiddleware",
    "allauth.account.middleware.AccountMiddleware",
    "config.middleware.ContentSecurityPolicyMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"

# Database

DATABASES = {"default": env.db(default="sqlite:///db.sqlite3")}

# Auth

AUTH_USER_MODEL = "accounts.User"

AUTHENTICATION_BACKENDS = [
    "axes.backends.AxesStandaloneBackend",
    "allauth.account.auth_backends.AuthenticationBackend",
]

LOGIN_URL = "/accounts/login/"
LOGIN_REDIRECT_URL = "/"
LOGOUT_REDIRECT_URL = "/"

PASSWORD_PEPPER = env("PASSWORD_PEPPER", default="")

PASSWORD_HASHERS = [
    "accounts.hashers.HmacPepperedArgon2PasswordHasher",
]

AUTH_PASSWORD_VALIDATORS = [
    {
        "NAME": "django.contrib.auth.password_validation."
        "UserAttributeSimilarityValidator",
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
    {
        "NAME": "accounts.validators.ZxcvbnPasswordValidator",
        "OPTIONS": {"min_score": 2},
    },
]

# Internationalization

LANGUAGE_CODE = "en-us"
TIME_ZONE = "Europe/Copenhagen"
USE_I18N = True
USE_TZ = True

# Static files

STATIC_URL = "static/"
STATICFILES_DIRS = [BASE_DIR / "static"]
STATIC_ROOT = BASE_DIR / "staticfiles"
if DEBUG:
    STORAGES = {
        "default": {
            "BACKEND": "django.core.files.storage.FileSystemStorage",
        },
        "staticfiles": {
            "BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage",
        },
    }
else:
    STORAGES = {
        "default": {
            "BACKEND": "django.core.files.storage.FileSystemStorage",
        },
        "staticfiles": {
            "BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage",
        },
    }

# Media files

MEDIA_URL = "/media/"
MEDIA_ROOT = BASE_DIR / "media"

# Image processing settings

MAX_IMAGE_SIZE_BYTES = 10 * 1024 * 1024  # 10 MB
MAX_IMAGE_DIMENSION = 1200  # px, applied to both axes
IMAGE_WEBP_QUALITY = 70

# Event settings

SCRAPED_EVENT_DISCLAIMER = (
    "> This event was scraped and may be partly inaccurate. "
    "Follow the more info link to read the source page when "
    "planning your visit/participation."
)

# Cloudflare R2 storage (production)
if env("R2_BUCKET_NAME", default=None):
    STORAGES["default"] = {
        "BACKEND": "storages.backends.s3boto3.S3Boto3Storage",
    }
    AWS_ACCESS_KEY_ID = env("R2_ACCESS_KEY")
    AWS_SECRET_ACCESS_KEY = env("R2_SECRET_KEY")
    AWS_STORAGE_BUCKET_NAME = env("R2_BUCKET_NAME")
    AWS_S3_ENDPOINT_URL = env("R2_ENDPOINT_URL")
    AWS_S3_CUSTOM_DOMAIN = env("CDN_DOMAIN", default=None)
    AWS_DEFAULT_ACL = None
    AWS_QUERYSTRING_AUTH = False
    AWS_S3_FILE_OVERWRITE = False
    AWS_S3_OBJECT_PARAMETERS = {"CacheControl": "max-age=31536000"}

# Email

DEFAULT_FROM_EMAIL = env(
    "DEFAULT_FROM_EMAIL", default="pleskal <noreply@contact.pleskal.dk>"
)
SERVER_EMAIL = env("SERVER_EMAIL", default="pleskal <noreply@contact.pleskal.dk>")

# ADMINS receives server error emails and new-user signup notifications.
# Format: comma-separated email addresses, e.g.:
#   ADMINS=admin1@example.com,admin2@example.com
_admins_raw = env("ADMINS", default="")
ADMINS = [addr.strip() for addr in _admins_raw.split(",") if addr.strip()]

_resend_api_key = env("RESEND_API_KEY", default=None)
RESEND_API_KEY = _resend_api_key
RESEND_SEGMENT_ID = env("RESEND_SEGMENT_ID", default=None)
if _resend_api_key:
    # Use Resend via django-anymail whenever an API key is present (dev or prod).
    EMAIL_BACKEND = "anymail.backends.resend.EmailBackend"
    ANYMAIL = {"RESEND_API_KEY": _resend_api_key}
elif DEBUG:
    # Emails print to the terminal — no external service needed.
    EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"
else:
    # Production fallback: use console backend if RESEND_API_KEY not set
    # (e.g. during collectstatic in CI). Actual email sending requires the key.
    EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"

# django-allauth

ACCOUNT_LOGIN_METHODS = {"email"}
ACCOUNT_SIGNUP_FIELDS = ["email*", "password1*", "password2*"]
ACCOUNT_USER_MODEL_USERNAME_FIELD = None
ACCOUNT_EMAIL_VERIFICATION = "mandatory"
ACCOUNT_UNIQUE_EMAIL = True
ACCOUNT_PREVENT_ENUMERATION = True
# Disable allauth's own signup — registration is handled by the claim-code flow.
ACCOUNT_ALLOW_REGISTRATION = False

# django-axes (brute-force protection)

AXES_FAILURE_LIMIT = 5
AXES_COOLOFF_TIME = 0.5  # 30 minutes in hours
AXES_LOCK_OUT_BY = ["ip_address"]
AXES_RESET_ON_SUCCESS = True

# Sentry

SENTRY_DSN = env("SENTRY_DSN", default="")
if SENTRY_DSN:
    import sentry_sdk
    from sentry_sdk.integrations.django import DjangoIntegration

    sentry_sdk.init(
        dsn=SENTRY_DSN,
        integrations=[DjangoIntegration(middleware_spans=True)],
        traces_sample_rate=0.2,
        send_default_pii=False,
    )

# Security (production only)

if not DEBUG:
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    SECURE_SSL_REDIRECT = True
    SECURE_HSTS_SECONDS = 31_536_000
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    SESSION_COOKIE_SECURE = True
    SESSION_COOKIE_HTTPONLY = True
    CSRF_COOKIE_SECURE = True

# Debug toolbar (development only)

if DEBUG:
    try:
        import debug_toolbar  # noqa: F401

        INSTALLED_APPS.append("debug_toolbar")
        MIDDLEWARE.insert(0, "debug_toolbar.middleware.DebugToolbarMiddleware")
        INTERNAL_IPS = ["127.0.0.1"]
    except ImportError:
        pass

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# Logging

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
        },
    },
    "root": {
        "handlers": ["console"],
        "level": "WARNING",
    },
    "loggers": {
        "django": {
            "handlers": ["console"],
            "level": "WARNING",
            "propagate": False,
        },
        "django.request": {
            "handlers": ["console"],
            "level": "ERROR",
            "propagate": False,
        },
    },
}

# django-markdownx

MARKDOWNX_MARKDOWN_EXTENSIONS = ["fenced_code"]
# Restrict image uploads via markdownx preview endpoint (not used for event images)
MARKDOWNX_UPLOAD_MAX_SIZE = 4 * 1024 * 1024  # 4 MB
MARKDOWNX_UPLOAD_CONTENT_TYPES = ["image/jpeg", "image/png", "image/webp"]
