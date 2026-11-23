import re
from datetime import timedelta

import pytest
from django.utils import timezone
from freezegun import freeze_time

from apps.accounts.models import InviteToken, PasswordResetToken, User
from apps.audit.models import AuditLog
from apps.common.security import sha256_hex
from tests import factories as f

NEW_PASSWORD = "Fresh-Secure-Pass9!"


def link_token(message, kind):
    return re.search(rf"/{kind}/([A-Za-z0-9_\-]+)", message.body).group(1)


@pytest.fixture
def hr(company_a):
    return f.make_user(company_a, "HR", email="hr@acme.test")


@pytest.fixture
def invited(hr, mailbox):
    with mailbox():
        response = f.client_for(hr).post(
            "/api/v1/hr/employees/",
            {"email": "new.hire@acme.test", "first_name": "New", "last_name": "Hire"},
            format="json",
        )
    assert response.status_code == 201, response.content
    user = User.objects.get(email="new.hire@acme.test")
    return user, link_token(mailbox.outbox[-1], "accept-invite")


class TestInvites:
    def test_invite_email_sent_and_only_hash_stored(self, invited, mailbox):
        user, raw = invited
        assert user.status == User.Status.INVITED and not user.has_usable_password()
        invite = InviteToken.objects.get(user=user)
        assert len(raw) >= 43  # 32 random bytes, base64url
        assert invite.token_hash == sha256_hex(raw) and raw not in invite.token_hash
        assert mailbox.outbox[-1].to == ["new.hire@acme.test"]
        assert not AuditLog.objects.filter(new_value__icontains=raw).exists()

    def test_describe_link(self, anon, invited):
        _, raw = invited
        body = anon.get(f"/api/v1/auth/invites/{raw}/").json()
        assert body["email"] == "new.hire@acme.test" and body["company_name"] == "Acme"

    def test_accept_activates_and_logs_in(self, anon, invited):
        user, raw = invited
        response = anon.post("/api/v1/auth/invites/accept/", {"token": raw, "password": NEW_PASSWORD}, format="json")
        assert response.status_code == 201
        assert response.json()["access"] and response.cookies["tt_refresh"].value
        user.refresh_from_db()
        assert user.status == User.Status.ACTIVE and user.check_password(NEW_PASSWORD)
        anon.credentials(HTTP_AUTHORIZATION=f"Bearer {response.json()['access']}")
        assert anon.get("/api/v1/auth/me/").status_code == 200

    def test_link_is_single_use(self, anon, invited):
        _, raw = invited
        anon.post("/api/v1/auth/invites/accept/", {"token": raw, "password": NEW_PASSWORD}, format="json")
        again = anon.post("/api/v1/auth/invites/accept/", {"token": raw, "password": NEW_PASSWORD}, format="json")
        assert again.status_code == 410 and again.json()["error"]["code"] == "link_used"
        assert "Ask HR for a new link" in again.json()["error"]["message"]

    def test_link_expires(self, anon, invited, company_a):
        _, raw = invited
        with freeze_time(timezone.now() + timedelta(hours=company_a.invite_expiry_hours, minutes=1)):
            response = anon.post(
                "/api/v1/auth/invites/accept/", {"token": raw, "password": NEW_PASSWORD}, format="json"
            )
            assert anon.get(f"/api/v1/auth/invites/{raw}/").status_code == 410
        assert response.status_code == 410 and response.json()["error"]["code"] == "link_expired"

    def test_revoked_link(self, anon, invited, hr):
        user, raw = invited
        assert f.client_for(hr).delete(f"/api/v1/hr/employees/{user.pk}/invite/").status_code == 204
        response = anon.post("/api/v1/auth/invites/accept/", {"token": raw, "password": NEW_PASSWORD}, format="json")
        assert response.status_code == 410 and response.json()["error"]["code"] == "link_revoked"

    def test_resend_invalidates_previous_link(self, anon, invited, hr, mailbox):
        user, old_raw = invited
        with mailbox():
            response = f.client_for(hr).post(f"/api/v1/hr/employees/{user.pk}/invite/")
        assert response.status_code == 201 and response.json()["send_count"] == 2
        new_raw = link_token(mailbox.outbox[-1], "accept-invite")
        assert anon.get(f"/api/v1/auth/invites/{old_raw}/").json()["error"]["code"] == "link_revoked"
        ok = anon.post("/api/v1/auth/invites/accept/", {"token": new_raw, "password": NEW_PASSWORD}, format="json")
        assert ok.status_code == 201

    def test_invite_status_for_hr(self, invited, hr):
        user, _ = invited
        body = f.client_for(hr).get(f"/api/v1/hr/employees/{user.pk}/invite/").json()
        assert body["state"] == "pending" and body["send_count"] == 1

    def test_unknown_token(self, anon):
        response = anon.get("/api/v1/auth/invites/not-a-real-token/")
        assert response.status_code == 410 and response.json()["error"]["code"] == "link_invalid"

    def test_weak_password_rejected_and_link_still_valid(self, anon, invited):
        _, raw = invited
        weak = anon.post("/api/v1/auth/invites/accept/", {"token": raw, "password": "password"}, format="json")
        assert weak.status_code == 400 and "password" in weak.json()["error"]["details"]
        assert anon.get(f"/api/v1/auth/invites/{raw}/").status_code == 200

    def test_cannot_invite_active_user(self, hr, company_a):
        active = f.make_user(company_a)
        response = f.client_for(hr).post(f"/api/v1/hr/employees/{active.pk}/invite/")
        assert response.status_code == 409


class TestSelfServiceReset:
    def test_forgot_password_is_not_enumerable(self, anon, company_a, mailbox):
        user = f.make_user(company_a)
        with mailbox():
            known = anon.post("/api/v1/auth/password/forgot/", {"email": user.email}, format="json")
            unknown = anon.post("/api/v1/auth/password/forgot/", {"email": "ghost@acme.test"}, format="json")
        assert known.status_code == unknown.status_code == 202
        assert known.json() == unknown.json()
        assert len(mailbox.outbox) == 1 and mailbox.outbox[0].to == [user.email]

    def test_reset_flow(self, anon, company_a, mailbox):
        user = f.make_user(company_a)
        other_device = f.client_for(user)
        with mailbox():
            anon.post("/api/v1/auth/password/forgot/", {"email": user.email}, format="json")
        raw = link_token(mailbox.outbox[-1], "reset-password")
        assert PasswordResetToken.objects.get(user=user).token_hash == sha256_hex(raw)
        assert anon.get(f"/api/v1/auth/password/reset/{raw}/").status_code == 200
        response = anon.post(
            "/api/v1/auth/password/reset/", {"token": raw, "new_password": NEW_PASSWORD}, format="json"
        )
        assert response.status_code == 200
        user.refresh_from_db()
        assert user.check_password(NEW_PASSWORD)
        assert other_device.get("/api/v1/auth/me/").status_code == 401  # all sessions ended
        again = anon.post("/api/v1/auth/password/reset/", {"token": raw, "new_password": NEW_PASSWORD}, format="json")
        assert again.status_code == 410 and again.json()["error"]["code"] == "link_used"

    def test_reset_link_expires(self, anon, company_a, mailbox):
        user = f.make_user(company_a)
        with mailbox():
            anon.post("/api/v1/auth/password/forgot/", {"email": user.email}, format="json")
        raw = link_token(mailbox.outbox[-1], "reset-password")
        with freeze_time(timezone.now() + timedelta(minutes=61)):
            response = anon.post(
                "/api/v1/auth/password/reset/", {"token": raw, "new_password": NEW_PASSWORD}, format="json"
            )
        assert response.status_code == 410 and response.json()["error"]["code"] == "link_expired"


class TestHRPasswordActions:
    def test_hr_sends_reset_link(self, hr, company_a, mailbox):
        member = f.make_user(company_a)
        member_client = f.client_for(member)
        with mailbox():
            response = f.client_for(hr).post(f"/api/v1/hr/employees/{member.pk}/password-reset-link/")
        assert response.status_code == 202
        assert member_client.get("/api/v1/auth/me/").status_code == 401
        assert "HR started a password reset" in mailbox.outbox[-1].body
        assert AuditLog.objects.filter(
            action="password.hr_reset_link_sent", entity_id=str(member.pk), actor_id=hr.pk
        ).exists()

    def test_hr_sets_temporary_password(self, hr, company_a, anon, mailbox):
        member = f.make_user(company_a)
        with mailbox():
            response = f.client_for(hr).post(
                f"/api/v1/hr/employees/{member.pk}/temporary-password/",
                {"password": "Temp-Passw0rd-2026!"},
                format="json",
            )
        assert response.status_code == 200
        member.refresh_from_db()
        assert member.must_change_password and member.check_password("Temp-Passw0rd-2026!")
        assert "Temp-Passw0rd-2026!" not in mailbox.outbox[-1].body
        entry = AuditLog.objects.get(action="password.hr_temporary_set")
        assert "Temp-Passw0rd" not in str(entry.new_value)
        body = anon.post(
            "/api/v1/auth/login/", {"email": member.email, "password": "Temp-Passw0rd-2026!"}, format="json"
        ).json()
        assert body["user"]["must_change_password"] is True

    @pytest.mark.parametrize(
        ("actor_role", "target_role", "allowed"),
        [
            ("HR", "TEAM_MEMBER", True),
            ("HR", "MANAGER", True),
            ("HR", "TEAM_LEAD", True),
            ("HR", "HR", False),
            ("HR", "COMPANY_ADMIN", False),
            ("COMPANY_ADMIN", "HR", True),
            ("COMPANY_ADMIN", "COMPANY_ADMIN", False),
            ("MANAGER", "TEAM_MEMBER", False),
            ("TEAM_MEMBER", "TEAM_MEMBER", False),
        ],
    )
    def test_reset_restrictions_by_rank(self, company_a, actor_role, target_role, allowed):
        actor = f.make_user(company_a, actor_role)
        target = f.make_user(company_a, target_role)
        client = f.client_for(actor)
        for url, data in (
            (f"/api/v1/hr/employees/{target.pk}/password-reset-link/", None),
            (f"/api/v1/hr/employees/{target.pk}/temporary-password/", {"password": "Temp-Passw0rd-26!"}),
        ):
            response = client.post(url, data, format="json")
            if allowed:
                assert response.status_code in (200, 202), response.content
            else:
                assert response.status_code in (403, 404, 422), response.content
                target.refresh_from_db()
                assert not target.must_change_password

    def test_hr_cannot_reset_own_password_via_hr_endpoint(self, hr):
        response = f.client_for(hr).post(f"/api/v1/hr/employees/{hr.pk}/password-reset-link/")
        assert response.status_code in (409, 422)

    def test_hr_cannot_reset_super_admin(self, hr, super_admin):
        response = f.client_for(hr).post(f"/api/v1/hr/employees/{super_admin.pk}/password-reset-link/")
        assert response.status_code == 404
