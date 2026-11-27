from rest_framework.throttling import SimpleRateThrottle

from apps.common.security import sha256_hex


class _IPThrottle(SimpleRateThrottle):
    def get_cache_key(self, request, view):
        return self.cache_format % {"scope": self.scope, "ident": self.get_ident(request)}


class _EmailThrottle(SimpleRateThrottle):
    def get_cache_key(self, request, view):
        email = str(request.data.get("email", "")).strip().lower() if hasattr(request, "data") else ""
        if not email:
            return None
        return self.cache_format % {"scope": self.scope, "ident": sha256_hex(email)}


class LoginIPThrottle(_IPThrottle):
    scope = "login"


class LoginEmailThrottle(SimpleRateThrottle):
    scope = "login_email"

    def get_cache_key(self, request, view):
        email = str(request.data.get("email", "")).strip().lower()
        if not email:
            return None
        return self.cache_format % {"scope": self.scope, "ident": sha256_hex(f"{email}|{self.get_ident(request)}")}


class MfaThrottle(_IPThrottle):
    scope = "mfa"


class PasswordResetThrottle(_EmailThrottle):
    scope = "password_reset"


class InviteAcceptThrottle(_IPThrottle):
    scope = "invite_accept"
