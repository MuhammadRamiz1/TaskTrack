# config/settings/test.py
from .base import *  # noqa
PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]  # faster tests
