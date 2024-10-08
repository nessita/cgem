"""
Django settings for gem project.

Generated by 'django-admin startproject' using Django 1.10.4.

For more information on this file, see
https://docs.djangoproject.com/en/1.10/topics/settings/

For the full list of settings and their values, see
https://docs.djangoproject.com/en/1.10/ref/settings/
"""

import os

import dj_database_url
from django.contrib.messages import constants as message_constants

# Build paths inside the project like this: os.path.join(BASE_DIR, ...)
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


# Quick-start development settings - unsuitable for production
# See https://docs.djangoproject.com/en/1.10/howto/deployment/checklist/

# SECURITY WARNING: keep the secret key used in production secret!
SECRET_KEY = os.environ.get("SECRET_KEY")

DEBUG = False

ALLOWED_HOSTS = os.environ.get("ALLOWED_HOSTS", "*").split(",")

DEFAULT_AUTO_FIELD = "django.db.models.AutoField"

# Application definition

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.messages",
    "django.contrib.postgres",
    "django.contrib.sessions",
    "django.contrib.sites",
    "django.contrib.staticfiles",
    "django_countries",
    "django_htmx",
    "gemcore",
    "health_check",                             # required
    "health_check.db",                          # stock Django health checkers
    "health_check.cache",
    "health_check.storage",
    "health_check.contrib.migrations",
    "rest_framework",
    "rest_framework.authtoken",
    "qurl_templatetag",
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
    "django_htmx.middleware.HtmxMiddleware",
]

ROOT_URLCONF = "gem.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.template.context_processors.i18n",
                "django.template.context_processors.media",
                "django.template.context_processors.static",
                "django.template.context_processors.tz",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "gem.wsgi.application"


# Database
# https://docs.djangoproject.com/en/1.10/ref/settings/#databases


DATABASES = {
    # Parse database configuration from $DATABASE_URL
    'default': dj_database_url.config(),
}


# Password validation
# https://docs.djangoproject.com/en/1.10/ref/settings/#auth-password-validators
_VALIDATORS = (
    "UserAttributeSimilarityValidator", "MinimumLengthValidator",
    "CommonPasswordValidator", "NumericPasswordValidator")
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.%s" % i}
    for i in _VALIDATORS
]


# Internationalization
# https://docs.djangoproject.com/en/1.10/topics/i18n/

LANGUAGE_CODE = "en-us"

TIME_ZONE = "America/Buenos_Aires"

USE_I18N = False

USE_L10N = False

USE_TZ = True


# Static files (CSS, JavaScript, Images)
# https://docs.djangoproject.com/en/1.10/howto/static-files/

STATIC_ROOT = os.path.join(BASE_DIR, "staticfiles")
STATIC_URL = "/static/"
STORAGES = {
    "staticfiles": {
        "BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage",
    },
}

# Honor the "X-Forwarded-Proto" header for request.is_secure()
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

ADMINS = [("Admin", os.environ.get("ADMINS"))]
DATE_FORMAT = "Y-m-d"
LOGIN_URL = "login"
LOGIN_REDIRECT_URL = "/"
MESSAGE_TAGS = {message_constants.ERROR: "danger"}
PYFLAKES_IGNORE_FILE = os.path.join(
    BASE_DIR, "gemcore", "tests", "pyflakes-ignore.txt")

CSRF_COOKIE_SECURE = True
SECURE_SSL_REDIRECT = True
SESSION_COOKIE_AGE = 43200  # 12 hours
SESSION_COOKIE_SECURE = True

SITE_ID = 1

ASSET_CATEGORIES = [
    ("cash", "Cash"),
    ("commodities", "Commodities"),
    ("fixed-income", "Fixed Income"),
    ("funds", "Funds"),
    ("real-state", "Real State"),
    ("stocks", "Stocks"),
    ("vehicle", "Vehicle"),
]
ENTRY_TAGS = [
    ("CL", "Clothing"),
    ("FD", "Food"),
    ("HE", "Healthcare"),
    ("HS", "Housing"),
    ("IM", "Imported"),
    ("TR", "Transportation"),
    ("UT", "Utilities"),
]
ENTRY_DEFAULT_TAG = "IM"

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "verbose": {
            "format": ("%(asctime)s [%(process)d] [%(levelname)s] " +
                       "pathname=%(pathname)s lineno=%(lineno)s " +
                       "funcname=%(funcName)s %(message)s"),
            "datefmt": "%Y-%m-%d %H:%M:%S"
        },
        "simple": {
            "format": "%(levelname)s %(message)s"
        }
    },
    "handlers": {
        "null": {
            "level": "DEBUG",
            "class": "logging.NullHandler",
        },
        "console": {
            "level": "DEBUG",
            "class": "logging.StreamHandler",
            "formatter": "verbose"
        }
    },
    "loggers": {
        "testlogger": {
            "handlers": ["console"],
            "level": "INFO",
        }
    }
}

try:
    from gem.local_settings import *  # noqa
except ImportError:
    pass
