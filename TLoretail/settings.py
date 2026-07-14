"""
Django settings for TLoretail (TimorMart).

Production-sensitive values (SECRET_KEY, DEBUG, ALLOWED_HOSTS) are read from
environment variables so the same code can run in development and production.

https://docs.djangoproject.com/en/5.2/howto/deployment/checklist/
"""

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

TEMPLATE_DIR = BASE_DIR / "templates"
STATIC_DIR = BASE_DIR / "static"

# SECURITY: never ship the fallback key to production — set DJANGO_SECRET_KEY.
SECRET_KEY = os.environ.get(
    "DJANGO_SECRET_KEY",
    "django-insecure-dev-only-x+_$tgpn^-m^8_mhrk5lmiu)==ej@%*ke_r#c&1dza",
)

DEBUG = os.environ.get("DJANGO_DEBUG", "").lower() in ("1", "true", "yes")

ALLOWED_HOSTS = [
    h.strip()
    for h in os.environ.get(
        "DJANGO_ALLOWED_HOSTS",
        "onlineretails2021.herokuapp.com,localhost,127.0.0.1",
    ).split(",")
    if h.strip()
]

CSRF_TRUSTED_ORIGINS = [
    o.strip()
    for o in os.environ.get(
        "DJANGO_CSRF_TRUSTED_ORIGINS", "https://onlineretails2021.herokuapp.com"
    ).split(",")
    if o.strip()
]

# Application definition

INSTALLED_APPS = [
    "modeltranslation",  # must precede django.contrib.admin
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.humanize",
    "olretail",
    "accounts",
    "dashboard",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.locale.LocaleMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "TLoretail.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [TEMPLATE_DIR],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "olretail.context_processors.categories",
                "olretail.context_processors.roles",
            ],
        },
    },
]

WSGI_APPLICATION = "TLoretail.wsgi.application"

# Database

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": BASE_DIR / "db.sqlite3",
    }
}

# Keep legacy AutoField primary keys (project predates BigAutoField default).
DEFAULT_AUTO_FIELD = "django.db.models.AutoField"

# Password validation

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

# Internationalization
# NOTE: the original project used "tt" for Tetum, but "tt" is Tatar in Django,
# which made Django's bundled Tatar (Cyrillic) translations leak into the UI.
# "tet" is the correct ISO 639 code for Tetum and has no bundled translations.

LANGUAGE_CODE = "en"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

LOCALE_PATHS = [BASE_DIR / "locale"]
LANGUAGES = [
    ("en", "English"),
    ("tet", "Tetum"),
]
MODELTRANSLATION_DEFAULT_LANGUAGE = "en"
MODELTRANSLATION_LANGUAGES = ("en", "tet")

# Register custom language code "tet" (Tetum) in Django's language database.
# "tet" is the correct ISO 639-3 code but isn't built into Django,
# so django-modeltranslation can't find language metadata without this patch.
from django.conf.locale import LANG_INFO  # noqa: E402

if 'tet' not in LANG_INFO:
    LANG_INFO['tet'] = {
        'bidi': False,
        'code': 'tet',
        'name': 'Tetum',
        'name_local': 'Tetun',
    }

# Static files (served by WhiteNoise) and user-uploaded media

STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_DIRS = [STATIC_DIR]

STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedStaticFilesStorage"},
}
WHITENOISE_USE_FINDERS = True  # serve from static/ even before collectstatic

MEDIA_URL = "/media/"
MEDIA_ROOT = BASE_DIR / "media"

# Authentication flow

LOGIN_URL = "/accounts/login/"
LOGIN_REDIRECT_URL = "/seller/"
LOGOUT_REDIRECT_URL = "/"

# Messages -> Bootstrap alert classes
from django.contrib.messages import constants as message_constants  # noqa: E402

MESSAGE_TAGS = {message_constants.ERROR: "danger"}

# Email: console backend unless SMTP is configured via env.
if os.environ.get("EMAIL_HOST"):
    EMAIL_BACKEND = "django.core.mail.backends.smtp.EmailBackend"
    EMAIL_HOST = os.environ["EMAIL_HOST"]
    EMAIL_PORT = int(os.environ.get("EMAIL_PORT", "587"))
    EMAIL_HOST_USER = os.environ.get("EMAIL_HOST_USER", "")
    EMAIL_HOST_PASSWORD = os.environ.get("EMAIL_HOST_PASSWORD", "")
    EMAIL_USE_TLS = os.environ.get("EMAIL_USE_TLS", "true").lower() == "true"
else:
    EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"
DEFAULT_FROM_EMAIL = os.environ.get("DEFAULT_FROM_EMAIL", "noreply@localhost")

# Production security hardening (skipped while DEBUG for local development).
if not DEBUG:
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    SECURE_SSL_REDIRECT = os.environ.get("DJANGO_SSL_REDIRECT", "").lower() in (
        "1",
        "true",
        "yes",
    )
    SESSION_COOKIE_SECURE = SECURE_SSL_REDIRECT
    CSRF_COOKIE_SECURE = SECURE_SSL_REDIRECT
    if SECURE_SSL_REDIRECT:
        SECURE_HSTS_SECONDS = 60 * 60 * 24 * 30  # 30 days; raise once verified
        SECURE_HSTS_INCLUDE_SUBDOMAINS = True

SESSION_COOKIE_HTTPONLY = True
CSRF_COOKIE_HTTPONLY = True
SECURE_REFERRER_POLICY = "same-origin"
X_FRAME_OPTIONS = "DENY"

# ──────────────────────────────────────────────────────────────────
# PAYMENT CONFIGURATION (Stripe)
# ──────────────────────────────────────────────────────────────────

# os.environ.get(NAME, default): the first argument is the VARIABLE NAME, the
# second the fallback. Test-mode keys are acceptable as dev fallbacks; set the
# environment variables (and rotate keys) before any production deployment.
STRIPE_PUBLIC_KEY = os.environ.get("STRIPE_PUBLIC_KEY", "pk_test_demo")
STRIPE_SECRET_KEY = os.environ.get("STRIPE_SECRET_KEY", "sk_test_demo")
STRIPE_WEBHOOK_SECRET = os.environ.get("STRIPE_WEBHOOK_SECRET", "whsec_test_demo")

# Payment settings
STRIPE_CURRENCY = os.environ.get("STRIPE_CURRENCY", "USD")
COMMISSION_RATE = 0.15  # 15% platform commission
STRIPE_FEE_PERCENT = 0.029  # 2.9% Stripe processing fee
STRIPE_FEE_FIXED = 0.30  # $0.30 fixed fee per transaction

MIN_PAYOUT_AMOUNT = 50000  # $500 minimum payout (in cents)
PAYOUT_SCHEDULE = "monthly"  # 'daily', 'weekly', 'monthly'

# Where sellers send platform subscription payments (monthly/yearly listing
# plans) — no automated billing, an admin confirms receipt manually.
PLATFORM_PAYMENT_INSTRUCTIONS = os.environ.get(
    "PLATFORM_PAYMENT_INSTRUCTIONS",
    "BNCTL Timor-Leste — Account name: TimorMart, Account #: 000-000-0000. "
    "Or mobile money to +670 7000-0000. Include your username as the reference.",
)

# Logging: concise console logging suitable for Heroku / systemd capture.
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "simple": {"format": "{levelname} {asctime} {name} {message}", "style": "{"},
    },
    "handlers": {
        "console": {"class": "logging.StreamHandler", "formatter": "simple"},
    },
    "root": {"handlers": ["console"], "level": "INFO"},
    "loggers": {
        "django.request": {"level": "WARNING"},
    },
}
