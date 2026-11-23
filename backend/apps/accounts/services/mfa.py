"""TOTP two-factor authentication with single-use recovery codes."""

import secrets

import pyotp
from django.utils import timezone

from apps.audit.services import record
from apps.common.exceptions import Conflict, Forbidden, InvalidInput
from apps.common.security import decrypt, encrypt, sha256_hex

from ..models import RecoveryCode, User

ISSUER = "TaskTrack"
RECOVERY_CODE_COUNT = 10


def _totp(user: User) -> pyotp.TOTP | None:
    if not user.totp_secret_enc:
        return None
    return pyotp.TOTP(decrypt(user.totp_secret_enc))


def _normalise(code: str) -> str:
    return (code or "").replace(" ", "").replace("-", "").strip().lower()


def verify_totp(user: User, code: str) -> bool:
    totp = _totp(user)
    code = _normalise(code)
    return bool(totp and code.isdigit() and len(code) == 6 and totp.verify(code, valid_window=1))


def verify_code_or_recovery(user: User, code: str) -> bool:
    if verify_totp(user, code):
        return True
    normalised = _normalise(code)
    if not normalised:
        return False
    match = RecoveryCode.objects.filter(user=user, code_hash=sha256_hex(normalised), used_at__isnull=True).first()
    if match is None:
        return False
    RecoveryCode.objects.filter(pk=match.pk).update(used_at=timezone.now())
    record(actor=user, action="auth.recovery_code_used", entity=user)
    return True


def begin_setup(user: User) -> dict:
    if user.totp_enabled:
        raise Conflict("Two-factor authentication is already enabled.", code="mfa_already_enabled")
    secret = pyotp.random_base32()
    user.totp_secret_enc = encrypt(secret)
    user.save(update_fields=["totp_secret_enc"])
    record(actor=user, action="auth.mfa_setup_started", entity=user)
    return {
        "secret": secret,
        "otpauth_uri": pyotp.TOTP(secret).provisioning_uri(name=user.email, issuer_name=ISSUER),
    }


def _new_recovery_codes(user: User) -> list[str]:
    RecoveryCode.objects.filter(user=user).delete()
    codes = [f"{secrets.token_hex(3)}-{secrets.token_hex(3)}" for _ in range(RECOVERY_CODE_COUNT)]
    RecoveryCode.objects.bulk_create(
        RecoveryCode(company_id=user.company_id, user=user, code_hash=sha256_hex(_normalise(c))) for c in codes
    )
    return codes


def confirm_setup(user: User, code: str) -> list[str]:
    if user.totp_enabled:
        raise Conflict("Two-factor authentication is already enabled.", code="mfa_already_enabled")
    if not verify_totp(user, code):
        raise InvalidInput(details={"code": ["The code is not valid. Check your authenticator app's clock."]})
    user.totp_enabled = True
    user.save(update_fields=["totp_enabled"])
    codes = _new_recovery_codes(user)
    record(actor=user, action="auth.mfa_enabled", entity=user)
    return codes


def disable(user: User, password: str, code: str) -> None:
    if not user.totp_enabled:
        raise Conflict("Two-factor authentication is not enabled.", code="mfa_not_enabled")
    if user.company_id and user.company.enforce_2fa:
        raise Forbidden("Your company requires two-factor authentication.", code="mfa_required_by_company")
    if not user.check_password(password) or not verify_code_or_recovery(user, code):
        raise InvalidInput(details={"code": ["Password or code is incorrect."]})
    user.totp_enabled = False
    user.totp_secret_enc = None
    user.save(update_fields=["totp_enabled", "totp_secret_enc"])
    RecoveryCode.objects.filter(user=user).delete()
    record(actor=user, action="auth.mfa_disabled", entity=user)


def regenerate_recovery_codes(user: User, code: str) -> list[str]:
    if not user.totp_enabled:
        raise Conflict("Two-factor authentication is not enabled.", code="mfa_not_enabled")
    if not verify_totp(user, code):
        raise InvalidInput(details={"code": ["The code is not valid."]})
    codes = _new_recovery_codes(user)
    record(actor=user, action="auth.mfa_recovery_codes_regenerated", entity=user)
    return codes
