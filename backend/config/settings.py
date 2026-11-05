"""Django settings for the Betewubet ERP.

Configuration comes from environment variables (see ../.env.example).
Without DATABASE_URL the project falls back to SQLite for quick local work;
production and docker-compose use PostgreSQL.
"""
from pathlib import Path

import environ

BASE_DIR = Path(__file__).resolve().parent.parent

env = environ.Env(
    DEBUG=(bool, False),
    ALLOWED_HOSTS=(list, ["localhost", "127.0.0.1"]),
    CSRF_TRUSTED_ORIGINS=(list, ["http://localhost:5173", "http://127.0.0.1:5173"]),
)
environ.Env.read_env(BASE_DIR.parent / ".env")
# On cPanel the settings sit in site.env (a visible file is easier to edit in File Manager).
environ.Env.read_env(BASE_DIR.parent / "site.env")

SECRET_KEY = env("SECRET_KEY", default="dev-only-insecure-key-change-me")

# Where the app lives on the web server: "" at the domain root, or e.g. "/Betewubet" for
# https://www.eruditeafrica.net/Betewubet/. Must match VITE_APP_ROOT used to build the web app.
URL_PREFIX = env("URL_PREFIX", default="").rstrip("/")
FORCE_SCRIPT_NAME = URL_PREFIX or None
SESSION_COOKIE_PATH = CSRF_COOKIE_PATH = f"{URL_PREFIX}/"
DEBUG = env("DEBUG")
ALLOWED_HOSTS = env("ALLOWED_HOSTS")
# The web app's address (the Vite dev server in development).
CSRF_TRUSTED_ORIGINS = env("CSRF_TRUSTED_ORIGINS")

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "rest_framework",
    "apps.core",
    "apps.catalog",
    "apps.inventory",
    "apps.sales",
    "apps.production",
    "apps.purchasing",
    "apps.maintenance",
    "apps.dispatch",
    "apps.finance",
    "apps.quality",
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

DATABASES = {
    "default": env.db("DATABASE_URL", default=f"sqlite:///{BASE_DIR / 'db.sqlite3'}"),
}
if DATABASES["default"]["ENGINE"] == "django.db.backends.mysql":
    # cPanel hosting usually offers MySQL/MariaDB. PyMySQL is pure Python, so it installs
    # without a compiler, unlike mysqlclient.
    import pymysql

    pymysql.install_as_MySQLdb()
    DATABASES["default"].setdefault("OPTIONS", {}).update(
        {"charset": "utf8mb4", "init_command": "SET sql_mode='STRICT_TRANS_TABLES'"})

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "en"
LANGUAGES = [("en", "English"), ("am", "Amharic")]
TIME_ZONE = "Africa/Addis_Ababa"
USE_I18N = True
USE_TZ = True

STATIC_URL = f"{URL_PREFIX}/static/"
STATIC_ROOT = env.str("STATIC_ROOT", default=str(BASE_DIR / "staticfiles"))
# The built web app (frontend/dist) is served as static files under static/app/.
FRONTEND_DIST = env.str("FRONTEND_DIST", default=str(BASE_DIR.parent / "frontend" / "dist"))
STATICFILES_DIRS = [("app", FRONTEND_DIST)] if Path(FRONTEND_DIST).is_dir() else []
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedStaticFilesStorage"},
}

# Behind HTTPS (cPanel AutoSSL or any proxy): secure cookies and trust the proxy's scheme header.
HTTPS = env.bool("HTTPS", default=not DEBUG)
if HTTPS:
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    SESSION_COOKIE_SECURE = CSRF_COOKIE_SECURE = True

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

REST_FRAMEWORK = {
    "DEFAULT_PERMISSION_CLASSES": ["rest_framework.permissions.IsAuthenticated"],
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "rest_framework.authentication.SessionAuthentication",
        "rest_framework.authentication.BasicAuthentication",
    ],
    "DEFAULT_PAGINATION_CLASS": "apps.core.api.Pagination",
    "PAGE_SIZE": 50,
    "COERCE_DECIMAL_TO_STRING": True,
    "EXCEPTION_HANDLER": "apps.core.api.exception_handler",
}

# Business defaults (Ethiopia). Rates live in the database where users edit them;
# these are only fallbacks used when nothing is configured.
ERP = {
    "BASE_CURRENCY": "ETB",
    "VAT_RATE": "0.15",
    "DEFAULT_NESTING_YIELD": "0.85",
    "MIN_OFFCUT_MM": 300,
}
