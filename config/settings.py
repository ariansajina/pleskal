from pathlib import Path

import environ

BASE_DIR = Path(__file__).resolve().parent.parent

env = environ.Env(DEBUG=(bool, False))
environ.Env.read_env(BASE_DIR / ".env", overwrite=False)

SECRET_KEY = env("SECRET_KEY", default="django-insecure-dev-key-change-in-production")
DEBUG = env("DEBUG")
ALLOWED_HOSTS = env.list("ALLOWED_HOSTS", default=[])

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
    "axes",
    "markdownx",
    "allauth",
    "allauth.account",
    # Local
    "accounts",
    "events",
]

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
    "django.contrib.auth.backends.ModelBackend",
    "allauth.account.auth_backends.AuthenticationBackend",
]

LOGIN_URL = "/accounts/login/"
LOGIN_REDIRECT_URL = "/"
LOGOUT_REDIRECT_URL = "/"

# django.contrib.sites (required by allauth)
SITE_ID = 1

PASSWORD_PEPPER = env("PASSWORD_PEPPER", default="")

PASSWORD_HASHERS = [
    # Primary: PBKDF2-SHA256 with an HMAC-SHA256 server-side pepper.
    # Existing plain PBKDF2 hashes are verified via the fallback below and
    # automatically re-hashed with this hasher on next successful login.
    "accounts.hashers.HmacPepperedPasswordHasher",
    "django.contrib.auth.hashers.PBKDF2PasswordHasher",
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

# Cloudflare R2 storage (production)
if env("AWS_STORAGE_BUCKET_NAME", default=None):
    STORAGES["default"] = {
        "BACKEND": "storages.backends.s3boto3.S3Boto3Storage",
    }
    AWS_ACCESS_KEY_ID = env("AWS_ACCESS_KEY_ID")
    AWS_SECRET_ACCESS_KEY = env("AWS_SECRET_ACCESS_KEY")
    AWS_STORAGE_BUCKET_NAME = env("AWS_STORAGE_BUCKET_NAME")
    AWS_S3_ENDPOINT_URL = env("AWS_S3_ENDPOINT_URL")
    AWS_S3_CUSTOM_DOMAIN = env("AWS_S3_CUSTOM_DOMAIN", default=None)
    AWS_DEFAULT_ACL = "public-read"
    AWS_QUERYSTRING_AUTH = False
    AWS_S3_FILE_OVERWRITE = False
    AWS_S3_OBJECT_PARAMETERS = {"CacheControl": "max-age=86400"}

# Email

DEFAULT_FROM_EMAIL = env("DEFAULT_FROM_EMAIL", default="Pleskal <noreply@pleskal.dk>")
SERVER_EMAIL = env("SERVER_EMAIL", default="Pleskal <noreply@pleskal.dk>")

# ADMINS receives server error emails and new-user signup notifications.
# Format: comma-separated email addresses, e.g.:
#   ADMINS=admin1@example.com,admin2@example.com
_admins_raw = env("ADMINS", default="")
ADMINS = [addr.strip() for addr in _admins_raw.split(",") if addr.strip()]

if DEBUG:
    # Emails print to the terminal — no external service needed.
    EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"
else:
    # Production: use django-anymail.
    # Once a provider is chosen, swap in the provider-specific extra, e.g.:
    #   pip install django-anymail[mailgun]   → ANYMAIL_EMAIL_BACKEND = "anymail.backends.mailgun.EmailBackend"
    #   pip install django-anymail[resend]    → ANYMAIL_EMAIL_BACKEND = "anymail.backends.resend.EmailBackend"
    EMAIL_BACKEND = env(
        "ANYMAIL_EMAIL_BACKEND",
        default="anymail.backends.mailgun.EmailBackend",
    )
    ANYMAIL = {
        # Set the provider API key via environment variable; never hard-code it.
        # e.g. for Mailgun:  ANYMAIL_MAILGUN_API_KEY=<your-key>
        #      for Resend:   ANYMAIL_RESEND_API_KEY=<your-key>
        # django-anymail reads ANYMAIL_<PROVIDER>_API_KEY automatically;
        # additional per-provider settings can be added here as needed.
    }

# django-allauth — email confirmation & signup
# Future: enable passwordless / OTP login with allauth's "headless" or
# allauth.mfa once the provider email integration is confirmed working.
ACCOUNT_LOGIN_METHODS = {"email"}  # log in with email, not username
ACCOUNT_SIGNUP_FIELDS = ["email*", "username*", "password1*", "password2*"]
ACCOUNT_EMAIL_VERIFICATION = "mandatory"
ACCOUNT_UNIQUE_EMAIL = True
ACCOUNT_LOGIN_ON_EMAIL_CONFIRMATION = True

# django-axes (brute-force protection)

AXES_FAILURE_LIMIT = 5
AXES_COOLOFF_TIME = 0.5  # 30 minutes in hours
AXES_LOCK_OUT_BY = ["ip_address"]
AXES_RESET_ON_SUCCESS = True

# Sentry

SENTRY_DSN = env("SENTRY_DSN", default="")
if SENTRY_DSN:
    import sentry_sdk

    sentry_sdk.init(dsn=SENTRY_DSN, traces_sample_rate=0.1)

# Security (production only)

if not DEBUG:
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

# django-markdownx

MARKDOWNX_MARKDOWN_EXTENSIONS = ["fenced_code"]
# Restrict image uploads via markdownx preview endpoint (not used for event images)
MARKDOWNX_UPLOAD_MAX_SIZE = 4 * 1024 * 1024  # 4 MB
MARKDOWNX_UPLOAD_CONTENT_TYPES = ["image/jpeg", "image/png", "image/webp"]
