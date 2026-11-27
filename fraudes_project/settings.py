import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

SECRET_KEY = 'django-insecure-test-key-for-cu-01'
DEBUG = True
ALLOWED_HOSTS = [
    '127.0.0.1',
    'localhost',
    '0.0.0.0',
    '172.31.7.29',
    '172.31.15.255',
]

# Permite túneles HTTPS efímeros solo cuando se inicia expresamente la demo.
# cloudflared termina TLS en trycloudflare.com y envía la petición a Django por localhost.
if os.environ.get('ENABLE_TEMPORARY_DEMO_TUNNEL') == '1':
    ALLOWED_HOSTS += ['.trycloudflare.com']
    CSRF_TRUSTED_ORIGINS = ['https://*.trycloudflare.com']
    SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'llamadas',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'fraudes_project.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / 'templates'],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

WSGI_APPLICATION = 'fraudes_project.wsgi.application'
ASGI_APPLICATION = 'fraudes_project.asgi.application'

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': BASE_DIR / 'db.sqlite3',
    }
}

AUTH_PASSWORD_VALIDATORS = []

LANGUAGE_CODE = 'es-es'
TIME_ZONE = 'America/Mexico_City'
USE_I18N = True
USE_TZ = True

STATIC_URL = 'static/'
STATICFILES_DIRS = [BASE_DIR / 'static']
MEDIA_URL = '/media/'
MEDIA_ROOT = BASE_DIR / 'media'
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'
LOGIN_URL = 'login'
LOGIN_REDIRECT_URL = 'inicio_roles'
NOTIFICACIONES_EMAIL_ACTIVAS = os.environ.get('NOTIFICACIONES_EMAIL_ACTIVAS', '').lower() in {'1', 'true', 'yes'}

# Configuración para Render
if os.environ.get("RENDER"):
    SECRET_KEY = os.environ["SECRET_KEY"]
    DEBUG = False

    RENDER_HOST = os.environ.get("RENDER_EXTERNAL_HOSTNAME")

    if RENDER_HOST:
        ALLOWED_HOSTS = [RENDER_HOST]
        CSRF_TRUSTED_ORIGINS = [
            f"https://{RENDER_HOST}"
        ]

    SECURE_PROXY_SSL_HEADER = (
        "HTTP_X_FORWARDED_PROTO", "https"
    )

    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True

    MIDDLEWARE.insert(
        1,
        "whitenoise.middleware.WhiteNoiseMiddleware"
    )

    STATIC_ROOT = BASE_DIR / "staticfiles"

    STATICFILES_DIRS = [
        BASE_DIR / "static"
    ] if (BASE_DIR / "static").exists() else []
