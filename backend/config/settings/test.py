"""Test settings. pytest connects as the owner role (it creates the test database);
tests then switch to the runtime role with SET LOCAL ROLE so RLS is exercised."""

from .base import *  # noqa: F403

DEBUG = False
ALLOWED_HOSTS = ["testserver", "localhost"]
PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]
CACHES = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}}
MAILERS = {"default": {"BACKEND": "django.core.mail.backends.locmem.EmailBackend"}}
JWT_TEST_KEY = "test-signing-key-at-least-32-bytes-long!!"
SIMPLE_JWT = {**SIMPLE_JWT, "SIGNING_KEY": JWT_TEST_KEY}  # noqa: F405
CELERY_TASK_ALWAYS_EAGER = True
CELERY_TASK_EAGER_PROPAGATES = True
REFRESH_COOKIE_SECURE = False
CSRF_COOKIE_SECURE = False
STORAGES["staticfiles"] = {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"}  # noqa: F405
REST_FRAMEWORK["DEFAULT_THROTTLE_RATES"] = {  # noqa: F405
    **REST_FRAMEWORK["DEFAULT_THROTTLE_RATES"],  # noqa: F405
    "user": "10000/min",
}
LOGGING["root"]["level"] = "WARNING"  # noqa: F405
MIDDLEWARE = [m for m in MIDDLEWARE if "whitenoise" not in m]  # noqa: F405
