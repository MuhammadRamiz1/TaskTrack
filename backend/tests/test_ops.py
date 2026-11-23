"""Operational pieces: scheduled cleanup, health checks, log redaction, celery wiring."""

from datetime import timedelta

from django.utils import timezone

from apps.accounts.models import InviteToken, UserSession
from apps.accounts.tasks import purge_expired_tokens
from apps.common.logging import REDACTED, redact, sentry_before_send
from tests import factories as f


def test_purge_expired_tokens_keeps_recent_rows(company_a):
    user = f.make_user(company_a, status="INVITED")
    old = timezone.now() - timedelta(days=40)
    InviteToken.objects.create(company=company_a, user=user, token_hash="a" * 64, expires_at=old, revoked_at=old)
    InviteToken.objects.create(
        company=company_a, user=user, token_hash="b" * 64, expires_at=timezone.now() + timedelta(hours=1)
    )
    active = f.make_user(company_a)
    f.client_for(active)
    UserSession.objects.create(company=company_a, user=active, refresh_jti="x", expires_at=old)

    counts = purge_expired_tokens()

    assert counts["invites"] == 1 and counts["sessions"] == 1
    assert InviteToken.objects.filter(user=user).count() == 1
    assert UserSession.objects.filter(user=active).count() == 1


def test_health_ready_reports_each_dependency(anon, settings, tmp_path):
    settings.MEDIA_ROOT = tmp_path
    response = anon.get("/health/ready")
    body = response.json()
    assert response.status_code == 200 and body["status"] == "ok"
    assert body["checks"] == {"database": "ok", "cache": "ok", "storage": "ok"}


def test_health_ready_degrades_without_leaking_details(anon, settings, tmp_path):
    blocker = tmp_path / "file"
    blocker.write_text("not a directory")
    settings.MEDIA_ROOT = blocker
    response = anon.get("/health/ready")
    assert response.status_code == 503
    assert response.json()["checks"]["storage"] == "error"


def test_log_redaction():
    event = redact(
        None, None, {"event": "x", "password": "p", "email": "a@b.c", "Authorization": "Bearer t", "user_id": "123"}
    )
    assert event["password"] == event["email"] == event["Authorization"] == REDACTED
    assert event["user_id"] == "123"


def test_sentry_scrubs_request_bodies_and_headers():
    event = {
        "request": {
            "data": {"password": "p"},
            "cookies": {"tt_refresh": "r"},
            "headers": {"Authorization": "Bearer t", "Accept": "json"},
        },
        "user": {"email": "a@b.c"},
    }
    scrubbed = sentry_before_send(event, None)
    assert "data" not in scrubbed["request"] and "cookies" not in scrubbed["request"]
    assert scrubbed["request"]["headers"]["Authorization"] == REDACTED
    assert scrubbed["request"]["headers"]["Accept"] == "json" and "user" not in scrubbed


def test_celery_app_registers_tasks():
    from config.celery import app

    app.loader.import_default_modules()
    assert {"accounts.purge_expired_tokens", "common.send_templated_email"} <= set(app.tasks)
    assert "purge-expired-auth-tokens" in app.conf.beat_schedule
