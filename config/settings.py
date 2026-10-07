"""Setari Django pentru Pontaj Bucatarie.

Valorile sensibile vin din variabile de mediu; in dezvoltare exista valori implicite.
"""

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

DEBUG = os.environ.get('DJANGO_DEBUG', '1') == '1'
SECRET_KEY = os.environ.get('DJANGO_SECRET_KEY', 'dev-only-not-secret')
if not DEBUG and SECRET_KEY == 'dev-only-not-secret':
    raise RuntimeError('Seteaza DJANGO_SECRET_KEY in productie.')

ALLOWED_HOSTS = [h for h in os.environ.get('DJANGO_ALLOWED_HOSTS', 'localhost,127.0.0.1').split(',') if h]
CSRF_TRUSTED_ORIGINS = [o for o in os.environ.get('DJANGO_CSRF_ORIGINS', '').split(',') if o]
if render_host := os.environ.get('RENDER_EXTERNAL_HOSTNAME'):  # setat automat de Render
    ALLOWED_HOSTS.append(render_host)
    CSRF_TRUSTED_ORIGINS.append(f'https://{render_host}')

# Toate datele stau in Firebase Realtime Database (vezi pontaj/firebase.py).
FIREBASE_DB_URL = os.environ.get(
    'FIREBASE_DB_URL', 'https://pontajunda-default-rtdb.europe-west1.firebasedatabase.app')

INSTALLED_APPS = [
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'pontaj',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'pontaj.auth.AuthMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'config.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.request',
                'django.contrib.messages.context_processors.messages',
                'pontaj.context_processors.roles',
            ],
        },
    },
]

WSGI_APPLICATION = 'config.wsgi.application'

DATABASES = {}  # fara baza SQL: sesiunile sunt cookie-uri semnate, datele in Firebase
SESSION_ENGINE = 'django.contrib.sessions.backends.signed_cookies'
MESSAGE_STORAGE = 'django.contrib.messages.storage.cookie.CookieStorage'

# Primul hasher e cel folosit pentru parole noi; LegacySHA256 accepta parolele
# importate din Firebase si le re-hash-uieste automat la primul login.
PASSWORD_HASHERS = [
    'django.contrib.auth.hashers.PBKDF2PasswordHasher',
    'pontaj.hashers.LegacySHA256PasswordHasher',
]

LOGIN_URL = '/login/'
SESSION_COOKIE_AGE = 60 * 60 * 24 * 30  # 30 de zile, ca pe telefon sa nu tot ceara parola

LANGUAGE_CODE = 'ro'
TIME_ZONE = 'Europe/Bucharest'
USE_I18N = True
USE_TZ = True

STATIC_URL = 'static/'
STATIC_ROOT = BASE_DIR / 'staticfiles'
STORAGES = {
    'default': {'BACKEND': 'django.core.files.storage.FileSystemStorage'},
    'staticfiles': {
        'BACKEND': 'whitenoise.storage.CompressedManifestStaticFilesStorage' if not DEBUG
        else 'django.contrib.staticfiles.storage.StaticFilesStorage',
    },
}

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

if not DEBUG:
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
