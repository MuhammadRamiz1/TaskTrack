from .base import *  # noqa: F403
from .base import env

DEBUG = True
ALLOWED_HOSTS = ["*"]
REFRESH_COOKIE_SECURE = env.bool("REFRESH_COOKIE_SECURE", False)
CSRF_COOKIE_SECURE = REFRESH_COOKIE_SECURE
