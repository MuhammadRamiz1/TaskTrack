from datetime import timedelta

import pyotp
import pytest
from django.conf import settings
from django.utils import timezone
from freezegun import freeze_time

from apps.accounts.models import User, UserSession
from apps.audit.models import AuditLog
from apps.common.security import decrypt
from tests import factories as f

LOGIN = "/api/v1/auth/login/"
ME = "/api/v1/auth/me/"
REFRESH = "/api/v1/auth/refresh/"


def login(client, email, password=f.PASSWORD):
    return client.post(LOGIN, {"email": email, "password": password}, format="json")


def csrf(client):
    """Fetch-style double submit: copy the csrftoken cookie into the header."""
    token = client.cookies.get("csrftoken")
    return {"HTTP_X_CSRFTOKEN": token.value if token else ""}


@pytest.fixture
def member(company_a):
    return f.make_user(company_a, "TEAM_MEMBER", email="member@acme.test")


class TestLogin:
    def test_success_returns_access_and_httponly_refresh_cookie(self, anon, member):
        response = login(anon, member.email)
        assert response.status_code == 200
        body = response.json()
        assert body["access"] and body["mfa_required"] is False
        assert body["user"]["email"] == member.email
        cookie = response.cookies[settings.REFRESH_COOKIE_NAME]
        assert cookie["httponly"] and cookie["samesite"] == "Strict" and cookie["path"] == "/api/v1/auth/"
        assert "refresh" not in body
        assert AuditLog.objects.filter(action="auth.login", entity_id=str(member.pk)).exists()

    def test_email_is_case_insensitive(self, anon, member):
        assert login(anon, member.email.upper()).status_code == 200

    def test_wrong_password_and_unknown_email_look_identical(self, anon, member):
        wrong = login(anon, member.email, "Wrong-password-123!")
        unknown = login(anon, "nobody@acme.test", "Wrong-password-123!")
        assert wrong.status_code == unknown.status_code == 401
        assert wrong.json()["error"]["code"] == unknown.json()["error"]["code"] == "invalid_credentials"
        assert wrong.json()["error"]["message"] == unknown.json()["error"]["message"]

    def test_lockout_after_repeated_failures(self, anon, member):
        for _ in range(settings.LOGIN_MAX_FAILURES):
            login(anon, member.email, "Wrong-password-123!")
            from django.core.cache import cache

            cache.clear()  # isolate lockout from throttling
        member.refresh_from_db()
        assert member.is_locked()
        assert login(anon, member.email).status_code == 401  # correct password, still locked
        assert AuditLog.objects.filter(action="auth.account_locked", entity_id=str(member.pk)).exists()
        with freeze_time(timezone.now() + timedelta(minutes=16)):
            assert login(anon, member.email).status_code == 200

    def test_failed_attempt_counter_is_committed(self, anon, member):
        login(anon, member.email, "Wrong-password-123!")
        member.refresh_from_db()
        assert member.failed_login_count == 1

    def test_throttled_per_email(self, anon, member):
        codes = [login(anon, member.email, "Wrong-password-123!").status_code for _ in range(6)]
        assert codes[-1] == 429

    @pytest.mark.parametrize("status", [User.Status.INVITED, User.Status.DEACTIVATED])
    def test_inactive_accounts_cannot_log_in(self, anon, company_a, status):
        user = f.make_user(company_a, status=status)
        user.set_password(f.PASSWORD)
        user.save()
        assert login(anon, user.email).status_code == 401

    def test_suspended_company_cannot_log_in(self, anon, member, company_a):
        company_a.status = "SUSPENDED"
        company_a.save()
        assert login(anon, member.email).status_code == 401

    def test_super_admin_logs_in_without_company(self, anon, super_admin):
        response = login(anon, super_admin.email)
        assert response.status_code == 200
        assert response.json()["user"]["is_platform_admin"] is True
        assert "platform.company.manage" in response.json()["user"]["permissions"]


class TestTokens:
    def test_me_requires_authentication(self, anon):
        response = anon.get(ME)
        assert response.status_code == 401
        assert response.json()["error"]["code"] == "not_authenticated"

    def test_garbage_token_rejected(self, anon):
        anon.credentials(HTTP_AUTHORIZATION="Bearer not-a-jwt")
        assert anon.get(ME).json()["error"]["code"] == "token_invalid"

    def test_expired_access_token_rejected(self, member):
        client = f.client_for(member)
        with freeze_time(timezone.now() + timedelta(minutes=11)):
            response = client.get(ME)
        assert response.status_code == 401 and response.json()["error"]["code"] == "token_expired"

    def test_me_returns_roles_and_permissions(self, member):
        body = f.client_for(member).get(ME).json()
        assert [r["key"] for r in body["roles"]] == ["TEAM_MEMBER"]
        assert body["permissions"]["task.view"] == ["OWN"]
        assert "employee.create" not in body["permissions"]
        assert body["company"]["slug"] == "acme"

    def test_update_own_profile(self, member):
        client = f.client_for(member)
        response = client.patch(ME, {"first_name": "Renamed", "timezone": "Asia/Karachi"}, format="json")
        assert response.status_code == 200 and response.json()["first_name"] == "Renamed"
        assert client.patch(ME, {"timezone": "Mars/Base"}, format="json").status_code == 400


class TestRefreshAndSessions:
    def _login(self, anon, user):
        response = login(anon, user.email)
        anon.credentials(HTTP_AUTHORIZATION=f"Bearer {response.json()['access']}")
        return response

    def test_refresh_requires_csrf(self, anon, member):
        self._login(anon, member)
        anon.handler.enforce_csrf_checks = True
        assert anon.post(REFRESH).status_code == 403
        response = anon.post(REFRESH, **csrf(anon))
        assert response.status_code == 200 and response.json()["access"]

    def test_refresh_rotates_and_detects_reuse(self, anon, member):
        first = self._login(anon, member).cookies[settings.REFRESH_COOKIE_NAME].value
        rotated = anon.post(REFRESH)
        assert rotated.status_code == 200
        second = rotated.cookies[settings.REFRESH_COOKIE_NAME].value
        assert second != first
        anon.cookies[settings.REFRESH_COOKIE_NAME] = first  # replay the old token
        replay = anon.post(REFRESH)
        assert replay.status_code == 401 and replay.json()["error"]["details"]["reason"] == "reuse_detected"
        anon.cookies[settings.REFRESH_COOKIE_NAME] = second  # the whole session is now dead
        assert anon.post(REFRESH).status_code == 401
        assert AuditLog.objects.filter(action="auth.refresh_reuse_detected").exists()

    def test_logout_revokes_session_and_access(self, anon, member):
        self._login(anon, member)
        assert anon.post("/api/v1/auth/logout/").status_code == 204
        assert anon.get(ME).json()["error"]["code"] == "session_revoked"
        assert anon.post(REFRESH).status_code == 401

    def test_logout_everywhere(self, member):
        phone, laptop = f.client_for(member), f.client_for(member)
        response = laptop.post("/api/v1/auth/logout-all/")
        assert response.status_code == 200 and response.json()["sessions_revoked"] == 2
        assert phone.get(ME).status_code == 401
        assert laptop.get(ME).status_code == 401

    def test_list_and_revoke_own_sessions(self, member, company_a):
        phone, laptop = f.client_for(member), f.client_for(member)
        sessions = laptop.get("/api/v1/auth/sessions/").json()
        assert len(sessions) == 2 and sum(s["current"] for s in sessions) == 1
        response = laptop.delete(f"/api/v1/auth/sessions/{phone.session_obj.pk}/")
        assert response.status_code == 204
        assert phone.get(ME).status_code == 401 and laptop.get(ME).status_code == 200
        other = f.make_user(company_a)
        other_client = f.client_for(other)
        assert laptop.delete(f"/api/v1/auth/sessions/{other_client.session_obj.pk}/").status_code == 404

    def test_deactivated_user_tokens_stop_working(self, member):
        client = f.client_for(member)
        User.objects.filter(pk=member.pk).update(status=User.Status.DEACTIVATED)
        assert client.get(ME).status_code == 401


class TestChangePassword:
    URL = "/api/v1/auth/password/change/"

    def test_change_password_revokes_other_sessions(self, member, mailbox):
        other, current = f.client_for(member), f.client_for(member)
        with mailbox():
            response = current.post(
                self.URL, {"current_password": f.PASSWORD, "new_password": "N3w-Secure-Passw0rd!"}, format="json"
            )
        assert response.status_code == 200
        current.credentials(HTTP_AUTHORIZATION=f"Bearer {response.json()['access']}")
        assert current.get(ME).status_code == 200
        assert other.get(ME).status_code == 401
        assert mailbox.outbox[-1].subject == "Your TaskTrack password was changed"

    def test_wrong_current_password(self, member):
        response = f.client_for(member).post(
            self.URL, {"current_password": "nope-nope-nope", "new_password": "N3w-Secure-Passw0rd!"}, format="json"
        )
        assert response.status_code == 400 and "current_password" in response.json()["error"]["details"]

    @pytest.mark.parametrize("weak", ["short1!", "alllowercaseletters", "123456789012", "password1234"])
    def test_weak_passwords_rejected(self, member, weak):
        response = f.client_for(member).post(
            self.URL, {"current_password": f.PASSWORD, "new_password": weak}, format="json"
        )
        assert response.status_code == 400 and "new_password" in response.json()["error"]["details"]

    def test_must_change_password_blocks_other_endpoints(self, company_a):
        user = f.make_user(company_a, "HR", must_change_password=True)
        client = f.client_for(user)
        blocked = client.get("/api/v1/hr/employees/")
        assert blocked.status_code == 403 and blocked.json()["error"]["code"] == "password_change_required"
        assert client.get(ME).status_code == 200
        response = client.post(
            self.URL, {"current_password": f.PASSWORD, "new_password": "N3w-Secure-Passw0rd!"}, format="json"
        )
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {response.json()['access']}")
        assert client.get("/api/v1/hr/employees/").status_code == 200


class TestTwoFactor:
    def _enable(self, user):
        client = f.client_for(user)
        setup = client.post("/api/v1/auth/2fa/setup/").json()
        code = pyotp.TOTP(setup["secret"]).now()
        codes = client.post("/api/v1/auth/2fa/confirm/", {"code": code}, format="json").json()["recovery_codes"]
        return setup["secret"], codes

    def test_enrol_and_login_with_totp(self, anon, member):
        secret, codes = self._enable(member)
        member.refresh_from_db()
        assert member.totp_enabled and decrypt(member.totp_secret_enc) == secret
        assert len(codes) == 10
        first = login(anon, member.email).json()
        assert first["mfa_required"] is True and "access" not in first
        bad = anon.post("/api/v1/auth/2fa/verify/", {"mfa_token": first["mfa_token"], "code": "000000"}, format="json")
        assert bad.status_code == 401
        ok = anon.post(
            "/api/v1/auth/2fa/verify/",
            {"mfa_token": first["mfa_token"], "code": pyotp.TOTP(secret).now()},
            format="json",
        )
        assert ok.status_code == 200 and ok.json()["access"]

    def test_recovery_code_is_single_use(self, anon, member):
        _, codes = self._enable(member)
        token = login(anon, member.email).json()["mfa_token"]
        verify = {"mfa_token": token, "code": codes[0]}
        assert anon.post("/api/v1/auth/2fa/verify/", verify, format="json").status_code == 200
        token = login(anon, member.email).json()["mfa_token"]
        assert anon.post("/api/v1/auth/2fa/verify/", {**verify, "mfa_token": token}, format="json").status_code == 401

    def test_disable_and_regenerate(self, member):
        secret, _ = self._enable(member)
        client = f.client_for(member)
        regen = client.post("/api/v1/auth/2fa/recovery-codes/", {"code": pyotp.TOTP(secret).now()}, format="json")
        assert regen.status_code == 200 and len(regen.json()["recovery_codes"]) == 10
        response = client.post(
            "/api/v1/auth/2fa/disable/", {"password": f.PASSWORD, "code": pyotp.TOTP(secret).now()}, format="json"
        )
        assert response.status_code == 204
        member.refresh_from_db()
        assert not member.totp_enabled

    def test_company_enforcement_limits_token_to_enrolment(self, anon, member, company_a):
        company_a.enforce_2fa = True
        company_a.save()
        body = login(anon, member.email).json()
        assert body["user"]["mfa_enrolment_required"] is True
        anon.credentials(HTTP_AUTHORIZATION=f"Bearer {body['access']}")
        blocked = anon.get("/api/v1/company/settings/")
        assert blocked.status_code == 403 and blocked.json()["error"]["code"] == "mfa_enrolment_required"
        assert anon.post("/api/v1/auth/2fa/setup/").status_code == 200

    def test_cannot_disable_when_company_enforces(self, member, company_a):
        secret, _ = self._enable(member)
        company_a.enforce_2fa = True
        company_a.save()
        response = f.client_for(member).post(
            "/api/v1/auth/2fa/disable/", {"password": f.PASSWORD, "code": pyotp.TOTP(secret).now()}, format="json"
        )
        assert response.status_code == 403


def test_session_rows_store_no_raw_tokens(member):
    client = f.client_for(member)
    session = UserSession.objects.get(pk=client.session_obj.pk)
    assert client.refresh_token not in {session.refresh_jti, session.user_agent}
