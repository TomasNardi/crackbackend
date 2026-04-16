"""
CrackBackend - Django Settings
================================
Configuración unificada para desarrollo y producción.
Las variables sensibles se cargan desde .env (ver .env.example).
"""

from pathlib import Path
from datetime import timedelta
import os
import dj_database_url
from dotenv import load_dotenv

load_dotenv()

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
BASE_DIR = Path(__file__).resolve().parent.parent

# ---------------------------------------------------------------------------
# Security
# ---------------------------------------------------------------------------
SECRET_KEY = os.environ.get("SECRET_KEY", "PapaPuebloTango")

DEBUG = os.environ.get("DEBUG", "True").lower() == "true"

ALLOWED_HOSTS = ["localhost", "127.0.0.1", "testserver"]

RENDER_EXTERNAL_HOSTNAME = os.environ.get("RENDER_EXTERNAL_HOSTNAME")
if RENDER_EXTERNAL_HOSTNAME:
    ALLOWED_HOSTS.append(RENDER_EXTERNAL_HOSTNAME)

# ---------------------------------------------------------------------------
# Application definition
# ---------------------------------------------------------------------------
DJANGO_APPS = [
    "unfold",
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
]

THIRD_PARTY_APPS = [
    "rest_framework",
    "rest_framework_simplejwt",
    "rest_framework_simplejwt.token_blacklist",
    "corsheaders",
    "whitenoise.runserver_nostatic",
    "django_filters",
    "django_ratelimit",
    "django_q",
    "ckeditor",
]

LOCAL_APPS = [
    "apps.core",
    "apps.products",
    "apps.orders",
    "apps.users",
]

INSTALLED_APPS = DJANGO_APPS + THIRD_PARTY_APPS + LOCAL_APPS

# ---------------------------------------------------------------------------
# Middleware
# ---------------------------------------------------------------------------
MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",       # Debe ir justo después de SecurityMiddleware
    "django.contrib.sessions.middleware.SessionMiddleware",
    "corsheaders.middleware.CorsMiddleware",            # Antes de CommonMiddleware
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "crackbackend.urls"

WSGI_APPLICATION = "crackbackend.wsgi.application"

# ---------------------------------------------------------------------------
# Templates
# ---------------------------------------------------------------------------
TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

# ---------------------------------------------------------------------------
# Database
# ---------------------------------------------------------------------------
# Desarrollo: SQLite (simple, sin setup)
# Producción: PostgreSQL via DATABASE_URL en .env
#
# Para activar Postgres en Render, setear en las env vars:
#   DATABASE_URL=postgresql://user:pass@host:5432/dbname
#
DATABASE_URL = os.environ.get("DATABASE_URL")

if DATABASE_URL:
    DATABASES = {
        "default": dj_database_url.config(
            default=DATABASE_URL,
            conn_max_age=600,
            conn_health_checks=True,
        )
    }
else:
    # Desarrollo local con SQLite
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": BASE_DIR / "db.sqlite3",
        }
    }

# ---------------------------------------------------------------------------
# Auth & JWT
# ---------------------------------------------------------------------------
AUTH_USER_MODEL = "users.User"

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

# ---------------------------------------------------------------------------
# Django REST Framework
# ---------------------------------------------------------------------------
REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": (
        "rest_framework_simplejwt.authentication.JWTAuthentication",
    ),
    "DEFAULT_PERMISSION_CLASSES": (
        "rest_framework.permissions.IsAuthenticatedOrReadOnly",
    ),
    "DEFAULT_FILTER_BACKENDS": (
        "django_filters.rest_framework.DjangoFilterBackend",
        "rest_framework.filters.SearchFilter",
        "rest_framework.filters.OrderingFilter",
    ),
    "DEFAULT_PAGINATION_CLASS": "rest_framework.pagination.PageNumberPagination",
    "PAGE_SIZE": 12,
    "DEFAULT_RENDERER_CLASSES": (
        "rest_framework.renderers.JSONRenderer",
    ),
}

# ---------------------------------------------------------------------------
# Simple JWT
# ---------------------------------------------------------------------------
SIMPLE_JWT = {
    "ACCESS_TOKEN_LIFETIME": timedelta(minutes=30),
    "REFRESH_TOKEN_LIFETIME": timedelta(days=7),
    "ROTATE_REFRESH_TOKENS": True,
    "BLACKLIST_AFTER_ROTATION": True,
    "AUTH_HEADER_TYPES": ("Bearer",),
}

# ---------------------------------------------------------------------------
# CORS
# ---------------------------------------------------------------------------
CORS_ALLOWED_ORIGINS = [
    "http://localhost:3000",
    "http://localhost:5173",
    "http://127.0.0.1:3000",
    "https://0v0rzg6p-3000.brs.devtunnels.ms",
]

# Agregar el dominio del frontend en producción via env var
FRONTEND_URL = os.environ.get("FRONTEND_URL")
if FRONTEND_URL and FRONTEND_URL.startswith("http"):
    CORS_ALLOWED_ORIGINS.append(FRONTEND_URL)

# Dominio fijo de Vercel
CORS_ALLOWED_ORIGINS.append("https://crackfrontend-eyci.vercel.app")

# Dominio productivo
CORS_ALLOWED_ORIGINS.append("https://www.cracktcg.com")
CORS_ALLOWED_ORIGINS.append("https://cracktcg.com")

# Permite subdominios de Vercel automáticamente
CORS_ALLOWED_ORIGIN_REGEXES = [
    r"^https://[\w-]+\.vercel\.app$",
    r"^https://[\w-]+-3000\.brs\.devtunnels\.ms$",
]

CORS_ALLOW_CREDENTIALS = True

# ---------------------------------------------------------------------------
# Static files (WhiteNoise)
# ---------------------------------------------------------------------------
STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_DIRS = [BASE_DIR / "static"]
STATICFILES_STORAGE = "whitenoise.storage.CompressedManifestStaticFilesStorage"

# ---------------------------------------------------------------------------
# Cache & Rate limiting
# ---------------------------------------------------------------------------
# Producción: Upstash Redis (setear USE_UPSTASH=true + credenciales en .env)
# Desarrollo: LocMemCache (sin setup)
USE_UPSTASH = os.environ.get("USE_UPSTASH", "false").lower() == "true"

if USE_UPSTASH:
    UPSTASH_REDIS_REST_URL = os.environ.get("UPSTASH_REDIS_REST_URL", "")
    UPSTASH_REDIS_REST_TOKEN = os.environ.get("UPSTASH_REDIS_REST_TOKEN", "")

    if not UPSTASH_REDIS_REST_URL or not UPSTASH_REDIS_REST_TOKEN:
        raise ValueError("Faltan UPSTASH_REDIS_REST_URL o UPSTASH_REDIS_REST_TOKEN en .env")

    _redis_url = (
        f"rediss://default:{UPSTASH_REDIS_REST_TOKEN}"
        f"@{UPSTASH_REDIS_REST_URL.replace('https://', '')}"
    )
    _redis_options = {
        "CLIENT_CLASS": "django_redis.client.DefaultClient",
        "SSL": True,
        "SOCKET_CONNECT_TIMEOUT": 10,
        "SOCKET_TIMEOUT": 10,
        "CONNECTION_POOL_KWARGS": {"ssl_cert_reqs": None},
    }
    CACHES = {
        "default": {
            "BACKEND": "django_redis.cache.RedisCache",
            "LOCATION": _redis_url,
            "OPTIONS": _redis_options,
        },
        "ratelimit": {
            "BACKEND": "django_redis.cache.RedisCache",
            "LOCATION": _redis_url,
            "OPTIONS": _redis_options,
        },
    }
else:
    CACHES = {
        "default": {
            "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
        },
        "ratelimit": {
            "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
            "LOCATION": "ratelimit",
        },
    }
    # Silenciar errores de ratelimit en desarrollo (no hay Redis local)
    SILENCED_SYSTEM_CHECKS = ["django_ratelimit.E003"]

RATELIMIT_USE_CACHE = "ratelimit"

# ---------------------------------------------------------------------------
# Email (Resend)
# ---------------------------------------------------------------------------
RESEND_API_KEY = os.environ.get("RESEND_API_KEY", "re_7nKA3kPy_2qFTu2Kwa3iyMVXrWgXbctNd")

# Email de desarrollo: cracktcg@gmail.com
# En producción, cambia a un dominio verificado en Resend (ej: noreply@cracktcg.com)
RESEND_FROM_EMAIL = os.environ.get("RESEND_FROM_EMAIL", "cracktcg@gmail.com")

# ---------------------------------------------------------------------------
# MercadoPago
# ---------------------------------------------------------------------------
# Variables recomendadas en .env:
# MP_PUBLIC_KEY=...
# MP_ACCESS_TOKEN=...
# BACKEND_PUBLIC_URL=https://tu-api.com
# FRONTEND_URL=https://tu-frontend.com
MERCADOPAGO_PUBLIC_KEY = os.environ.get(
    "MP_PUBLIC_KEY",
    "APP_USR-f93fc978-d364-447f-af2f-0f55d494005c",
)
MERCADOPAGO_ACCESS_TOKEN = os.environ.get(
    "MP_ACCESS_TOKEN",
    "APP_USR-126784700889279-041314-5d53c1bfe2976f356c1f3a226d077c18-2149863724",
)
MERCADOPAGO_WEBHOOK_SECRET = os.environ.get("MP_WEBHOOK_SECRET", "")
# Opcional: forzar URL pública de retorno para Checkout Pro en desarrollo local.
# Se puede sobreescribir con MP_FRONTEND_RETURN_URL en entorno.
MERCADOPAGO_FRONTEND_RETURN_URL = os.environ.get(
    "MP_FRONTEND_RETURN_URL",
    "https://0v0rzg6p-3000.brs.devtunnels.ms",
)

BACKEND_PUBLIC_URL = os.environ.get("BACKEND_PUBLIC_URL", "http://localhost:8000")

# ---------------------------------------------------------------------------
# Paq.ar (Correo Argentino) — Integración de envíos
# ---------------------------------------------------------------------------
# Obtener agreement y API-Key del área Comercial de Correo Argentino.
# Completar en .env:
#   PAQAR_API_KEY=tu_api_key
#   PAQAR_AGREEMENT=tu_numero_acuerdo   (ej: 18017)
#   PAQAR_SERVICE_TYPE=CP               (2 letras — definido en tu contrato)
#   PAQAR_SANDBOX=True                  (False en producción)
#   PAQAR_SENDER_NAME=Crack
#   PAQAR_SENDER_STREET=Tu Calle
#   PAQAR_SENDER_STREET_NUMBER=123
#   PAQAR_SENDER_CITY=Buenos Aires
#   PAQAR_SENDER_STATE=C                (código de provincia — C = CABA)
#   PAQAR_SENDER_ZIP=1000
#   PAQAR_SENDER_EMAIL=tu@email.com
#   PAQAR_SENDER_PHONE=1112345678
#   PAQAR_DEFAULT_WEIGHT_GRAMS=500      (peso default por paquete)
#   PAQAR_SHIPPING_COST=2500            (costo de envío configurado en tu acuerdo)

PAQAR_API_KEY = os.environ.get("PAQAR_API_KEY", "")
PAQAR_AGREEMENT = os.environ.get("PAQAR_AGREEMENT", "")
PAQAR_SANDBOX = os.environ.get("PAQAR_SANDBOX", "True").lower() == "true"
PAQAR_BASE_URL = (
    "https://apitest.correoargentino.com.ar/paqar/v1"
    if os.environ.get("PAQAR_SANDBOX", "True").lower() == "true"
    else "https://api.correoargentino.com.ar/paqar/v1"
)
PAQAR_SERVICE_TYPE = os.environ.get("PAQAR_SERVICE_TYPE", "CP")
PAQAR_SENDER_NAME = os.environ.get("PAQAR_SENDER_NAME", "Crack")
PAQAR_SENDER_STREET = os.environ.get("PAQAR_SENDER_STREET", "")
PAQAR_SENDER_STREET_NUMBER = os.environ.get("PAQAR_SENDER_STREET_NUMBER", "")
PAQAR_SENDER_CITY = os.environ.get("PAQAR_SENDER_CITY", "")
PAQAR_SENDER_STATE = os.environ.get("PAQAR_SENDER_STATE", "C")
PAQAR_SENDER_ZIP = os.environ.get("PAQAR_SENDER_ZIP", "")
PAQAR_SENDER_EMAIL = os.environ.get("PAQAR_SENDER_EMAIL", "")
PAQAR_SENDER_PHONE = os.environ.get("PAQAR_SENDER_PHONE", "")
PAQAR_DEFAULT_WEIGHT_GRAMS = int(os.environ.get("PAQAR_DEFAULT_WEIGHT_GRAMS", "500"))

# ---------------------------------------------------------------------------
# Internationalization
# ---------------------------------------------------------------------------
LANGUAGE_CODE = "es-ar"
TIME_ZONE = "America/Argentina/Buenos_Aires"
USE_I18N = True
USE_TZ = True

# ---------------------------------------------------------------------------
# Django Q — Task queue (async emails, background jobs)
# Usa la misma DB (ORM backend), sin Redis extra.
# El worker se levanta con: python manage.py qcluster
# ---------------------------------------------------------------------------
Q_CLUSTER = {
    "name": "CrackBackend",
    "workers": 1,
    "timeout": 900,       # 15 min — 500 mails × 0.5s = ~250s, margen amplio
    "retry": 1200,        # reintentar tareas fallidas después de 20 min
    "queue_limit": 500,
    "bulk": 5,
    "orm": "default",     # usa la misma PostgreSQL
    "catch_up": False,    # no acumular tareas perdidas al reiniciar
}

# ---------------------------------------------------------------------------
# CKEditor
# ---------------------------------------------------------------------------
CKEDITOR_CONFIGS = {
    "default": {
        "toolbar": "Custom",
        "toolbar_Custom": [
            ["Bold", "Italic", "Underline", "Strike"],
            ["NumberedList", "BulletedList", "-", "Outdent", "Indent"],
            ["Link", "Unlink"],
            ["RemoveFormat", "Source"],
        ],
        "height": 300,
        "width": "100%",
        "removePlugins": "elementspath",
        "extraPlugins": ",".join(["list"]),
    },
}

# ---------------------------------------------------------------------------
# Unfold Admin — Theme
# ---------------------------------------------------------------------------
def admin_has_perm(perm):
    return lambda request: request.user.has_perm(perm)


UNFOLD = {
    "SITE_TITLE": "CRACK TCG — Admin",
    "SITE_HEADER": "CRACK TCG",
    "SITE_SUBHEADER": "Panel de administración",
    "SITE_URL": os.environ.get("SITE_URL", "https://crack-front-rho.vercel.app/"),
    "SITE_SYMBOL": "style",  # Material Symbols icon
    "SHOW_HISTORY": True,
    "SHOW_VIEW_ON_SITE": False,
    "THEME": "light",
    "STYLES": [
        lambda request: "admin/css/crack_admin.css",
    ],
    "COLORS": {
        "font": {
            "subtle-light": "107 101 96",        # #6B6560
            "subtle-dark": "163 163 163",
            "default-light": "26 26 26",          # #1A1A1A
            "default-dark": "212 207 198",        # #D4CFC6
            "important-light": "26 26 26",        # #1A1A1A
            "important-dark": "250 250 247",      # #FAFAF7
        },
        "primary": {
            "50": "254 249 238",
            "100": "252 239 207",
            "200": "250 222 158",
            "300": "246 200 100",
            "400": "240 175 55",
            "500": "200 151 46",                  # #C8972E
            "600": "184 133 31",                  # #B8851F
            "700": "153 105 22",
            "800": "126 84 22",
            "900": "104 69 22",
            "950": "60 37 7",
        },
    },
    "SIDEBAR": {
        "show_search": True,
        "show_all_applications": False,
        "navigation": [
            {
                "title": "Tienda",
                "separator": True,
                "collapsible": False,
                "items": [
                    {
                        "title": "Productos",
                        "icon": "inventory_2",
                        "link": "/admin/products/product/",
                        "permission": admin_has_perm("products.view_product"),
                    },
                    {
                        "title": "TCGs",
                        "icon": "playing_cards",
                        "link": "/admin/products/tcg/",
                        "permission": admin_has_perm("products.view_tcg"),
                    },
                    {
                        "title": "Categorías",
                        "icon": "category",
                        "link": "/admin/products/productcategory/",
                        "permission": admin_has_perm("products.view_productcategory"),
                    },
                    {
                        "title": "Condiciones",
                        "icon": "grade",
                        "link": "/admin/products/cardcondition/",
                        "permission": admin_has_perm("products.view_cardcondition"),
                    },
                    {
                        "title": "Certificadoras",
                        "icon": "verified",
                        "link": "/admin/products/certificationentity/",
                        "permission": admin_has_perm("products.view_certificationentity"),
                    },
                    {
                        "title": "Notas de certificación",
                        "icon": "scoreboard",
                        "link": "/admin/products/certificationgrade/",
                        "permission": admin_has_perm("products.view_certificationgrade"),
                    },
                ],
            },
            {
                "title": "Ventas",
                "separator": True,
                "collapsible": False,
                "items": [
                    {
                        "title": "Órdenes",
                        "icon": "receipt_long",
                        "link": "/admin/orders/order/",
                        "permission": admin_has_perm("orders.view_order"),
                    },
                    {
                        "title": "Pagos MercadoPago",
                        "icon": "payments",
                        "link": "/admin/orders/mercadopagopayment/",
                        "permission": admin_has_perm("orders.view_mercadopagopayment"),
                    },
                    {
                        "title": "Códigos de descuento",
                        "icon": "sell",
                        "link": "/admin/orders/discountcode/",
                        "permission": admin_has_perm("orders.view_discountcode"),
                    },
                    {
                        "title": "Productos sugeridos",
                        "icon": "view_carousel",
                        "link": "/admin/orders/suggestedproductscarousel/",
                        "permission": admin_has_perm("orders.view_suggestedproductscarousel"),
                    },
                ],
            },
            {
                "title": "Configuración",
                "separator": True,
                "collapsible": False,
                "items": [
                    {
                        "title": "Estado del sitio",
                        "icon": "settings",
                        "link": "/admin/core/siteconfig/",
                        "permission": admin_has_perm("core.view_siteconfig"),
                    },
                    {
                        "title": "Pago en efectivo",
                        "icon": "point_of_sale",
                        "link": "/admin/core/paymentsettings/",
                        "permission": admin_has_perm("core.view_paymentsettings"),
                    },
                    {
                        "title": "Tipo de cambio",
                        "icon": "currency_exchange",
                        "link": "/admin/core/exchangerate/",
                        "permission": admin_has_perm("core.view_exchangerate"),
                    },
                    {
                        "title": "Suscripciones",
                        "icon": "mail",
                        "link": "/admin/core/emailsubscription/",
                        "permission": admin_has_perm("core.view_emailsubscription"),
                    },
                    {
                        "title": "Campañas de email",
                        "icon": "campaign",
                        "link": "/admin/core/emailcampaign/",
                        "permission": admin_has_perm("core.view_emailcampaign"),
                    },
                    {
                        "title": "Mensajes de contacto",
                        "icon": "forum",
                        "link": "/admin/core/contactmessage/",
                        "permission": admin_has_perm("core.view_contactmessage"),
                    },
                ],
            },
            {
                "title": "Usuarios",
                "separator": True,
                "collapsible": False,
                "items": [
                    {
                        "title": "Usuarios",
                        "icon": "people",
                        "link": "/admin/users/user/",
                        "permission": admin_has_perm("users.view_user"),
                    },
                    {
                        "title": "Grupos",
                        "icon": "group",
                        "link": "/admin/auth/group/",
                        "permission": admin_has_perm("auth.view_group"),
                    },
                ],
            },
        ],
    },
}

# ---------------------------------------------------------------------------
# Misc
# ---------------------------------------------------------------------------
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# URL base del sitio (usada para links en emails, SEO, admin, etc.)
SITE_URL = os.environ.get("SITE_URL", "https://crack-front-rho.vercel.app/")

# ---------------------------------------------------------------------------
# Logging — visible en Render logs
# ---------------------------------------------------------------------------
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "render": {
            "format": "[{asctime}] [{levelname}] {name}: {message}",
            "style": "{",
            "datefmt": "%Y-%m-%d %H:%M:%S",
        },
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "render",
        },
    },
    "root": {
        "handlers": ["console"],
        "level": "INFO",
    },
    "loggers": {
        "django": {
            "handlers": ["console"],
            "level": "WARNING",   # Solo warnings/errors de Django core
            "propagate": False,
        },
        "django_q": {
            "handlers": ["console"],
            "level": "INFO",      # Logs del cluster y tareas
            "propagate": False,
        },
        "apps.core.tasks": {
            "handlers": ["console"],
            "level": "INFO",      # Logs del envío de campañas
            "propagate": False,
        },
        "apps.orders": {
            "handlers": ["console"],
            "level": "INFO",
            "propagate": False,
        },
    },
}
