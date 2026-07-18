"""
Django settings for TLoretail (TimorMart).

Production-sensitive values (SECRET_KEY, DEBUG, ALLOWED_HOSTS) are read from
environment variables so the same code can run in development and production.

https://docs.djangoproject.com/en/5.2/howto/deployment/checklist/
"""

import os
from pathlib import Path

import dj_database_url
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent

# Loads variables from a local .env file (git-ignored — see .gitignore) into
# the process environment. Harmless if the file doesn't exist (e.g. in
# production, where real env vars are set directly by the host) — existing
# environment variables always take precedence over .env, so this never
# overrides real deployment config.
load_dotenv(BASE_DIR / ".env")

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

# Cloudinary media storage (product images, delivery proofs) — only enabled
# when CLOUDINARY_URL is set (e.g. in production). Locally, uploads just go
# to the filesystem as before. cloudinary_storage must precede staticfiles;
# cloudinary itself just needs to be present somewhere in the list.
USE_CLOUDINARY = bool(os.environ.get("CLOUDINARY_URL"))
if USE_CLOUDINARY:
    INSTALLED_APPS.insert(INSTALLED_APPS.index("django.contrib.staticfiles"), "cloudinary_storage")
    INSTALLED_APPS.append("cloudinary")

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
                "olretail.context_processors.notifications",
                "olretail.context_processors.cart_count",
                "olretail.context_processors.wishlist_count",
            ],
        },
    },
]

WSGI_APPLICATION = "TLoretail.wsgi.application"

# Database — Postgres in production via DATABASE_URL (set automatically by
# most hosts, including Render, when a database is attached); falls back to
# the local sqlite3 file when it's unset, so local dev is unchanged.
DATABASES = {
    "default": dj_database_url.config(
        default=f"sqlite:///{BASE_DIR / 'db.sqlite3'}",
        conn_max_age=600,
    )
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
    ("pt-pt", "Português"),
    ("id", "Bahasa Indonesia"),
]
MODELTRANSLATION_DEFAULT_LANGUAGE = "en"
MODELTRANSLATION_LANGUAGES = ("en", "tet", "pt-pt", "id")

# Register custom language codes not built into Django's language database.
# "tet" (Tetum, ISO 639-3) and "pt-pt" (Portugal Portuguese, a regional
# variant Django doesn't ship metadata for — only generic "pt"/"pt-br") both
# need this patch so django-modeltranslation can find language metadata.
# "id" (Indonesian) is already built into Django, no patch needed.
from django.conf.locale import LANG_INFO  # noqa: E402

if 'tet' not in LANG_INFO:
    LANG_INFO['tet'] = {
        'bidi': False,
        'code': 'tet',
        'name': 'Tetum',
        'name_local': 'Tetun',
    }
if 'pt-pt' not in LANG_INFO:
    LANG_INFO['pt-pt'] = {
        'bidi': False,
        'code': 'pt-pt',
        'name': 'Portuguese',
        'name_local': 'Português',
    }

# Static files (served by WhiteNoise) and user-uploaded media

STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_DIRS = [STATIC_DIR]

STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedStaticFilesStorage"},
}
if USE_CLOUDINARY:
    STORAGES["default"] = {"BACKEND": "cloudinary_storage.storage.MediaCloudinaryStorage"}
    # django-cloudinary-storage's own `collectstatic` override (which takes
    # over from Django's built-in command once `cloudinary_storage` is in
    # INSTALLED_APPS) reads the legacy STATICFILES_STORAGE setting directly
    # rather than the modern STORAGES dict this project otherwise uses —
    # without this, collectstatic crashes with AttributeError since that
    # setting is never defined. Static files still go through WhiteNoise,
    # not Cloudinary — this only exists so that equality check doesn't blow
    # up; it deliberately does NOT match StaticCloudinaryStorage.
    STATICFILES_STORAGE = STORAGES["staticfiles"]["BACKEND"]
WHITENOISE_USE_FINDERS = True  # serve from static/ even before collectstatic

MEDIA_URL = "/media/"
MEDIA_ROOT = BASE_DIR / "media"

# Backstop behind the per-form 5MB image-size validators (olretail/validators.py)
# — rejects oversized uploads before they're even fully read into memory.
DATA_UPLOAD_MAX_MEMORY_SIZE = 10 * 1024 * 1024  # 10MB
FILE_UPLOAD_MAX_MEMORY_SIZE = 10 * 1024 * 1024  # 10MB

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

# Flat courier/delivery fee, charged once per seller in the cart (one
# courier pickup = one delivery), regardless of product category.
DELIVERY_FEE = float(os.environ.get("DELIVERY_FEE", "1.00"))

# ──────────────────────────────────────────────────────────────────
# SIMULATED BANK GATEWAY (dev/test automated bank transfer — see
# olretail/payment_gateways.py). Same commission rate as Stripe
# (COMMISSION_RATE above), but its own processing-fee schedule since a real
# bank transfer typically costs less than a card network.
# ──────────────────────────────────────────────────────────────────
SIMULATED_BANK_FEE_PERCENT = float(os.environ.get("SIMULATED_BANK_FEE_PERCENT", "0.015"))
SIMULATED_BANK_FEE_FIXED = float(os.environ.get("SIMULATED_BANK_FEE_FIXED", "0.10"))
# How long a simulated transaction stays "pending" before auto-settling.
SIMULATED_BANK_SETTLE_DELAY_SECONDS = int(os.environ.get("SIMULATED_BANK_SETTLE_DELAY_SECONDS", "8"))
# A transaction with no scheduled settlement (the "always timeout" test
# account) is flagged TIMEOUT once it's sat PENDING longer than this.
SIMULATED_BANK_TIMEOUT_SECONDS = int(os.environ.get("SIMULATED_BANK_TIMEOUT_SECONDS", "120"))
SIMULATED_BANK_WEBHOOK_SECRET = os.environ.get("SIMULATED_BANK_WEBHOOK_SECRET", "whsec_sim_test_demo")
# Static API key for the developer REST API (olretail/banking_api.py) — this
# app has no per-seller/buyer API-key infra and is single-merchant, so one
# shared key (like STRIPE_SECRET_KEY) is proportionate.
BANK_SIMULATOR_API_KEY = os.environ.get("BANK_SIMULATOR_API_KEY", "sk_sim_test_demo")
# Gates the "here are some test account numbers" hint box on checkout.
BANK_SIMULATOR_SHOW_TEST_ACCOUNTS = DEBUG

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
