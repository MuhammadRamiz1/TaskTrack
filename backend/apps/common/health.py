import tempfile

from django.conf import settings
from django.core.cache import cache
from django.db import connection
from django.http import JsonResponse
from django.views.decorators.http import require_GET


@require_GET
def live(_request):
    return JsonResponse({"status": "ok"})


def _check_db():
    with connection.cursor() as cursor:
        cursor.execute("SELECT 1")


def _check_cache():
    cache.set("health:ping", "1", 5)
    if cache.get("health:ping") != "1":
        raise RuntimeError("cache read-back failed")


def _check_storage():
    if settings.USE_S3:
        from django.core.files.storage import default_storage

        default_storage.connection.meta.client.head_bucket(Bucket=settings.S3_BUCKET)
    else:
        settings.MEDIA_ROOT.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=settings.MEDIA_ROOT):
            pass


@require_GET
def ready(_request):
    checks = {}
    for name, check in (("database", _check_db), ("cache", _check_cache), ("storage", _check_storage)):
        try:
            check()
            checks[name] = "ok"
        except Exception:  # noqa: BLE001 - report, never leak internals
            checks[name] = "error"
    healthy = all(v == "ok" for v in checks.values())
    return JsonResponse({"status": "ok" if healthy else "degraded", "checks": checks}, status=200 if healthy else 503)
