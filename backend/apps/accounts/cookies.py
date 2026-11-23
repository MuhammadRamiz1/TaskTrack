from django.conf import settings
from django.middleware.csrf import get_token
from rest_framework.authentication import CSRFCheck
from rest_framework.exceptions import PermissionDenied

from .tokens import refresh_lifetime

SESSION_HINT_COOKIE = "tt_session"


def set_refresh_cookie(response, request, raw_refresh: str) -> None:
    response.set_cookie(
        settings.REFRESH_COOKIE_NAME,
        raw_refresh,
        max_age=int(refresh_lifetime().total_seconds()),
        path=settings.REFRESH_COOKIE_PATH,
        secure=settings.REFRESH_COOKIE_SECURE,
        httponly=True,
        samesite="Strict",
    )
    # Non-secret hint for the web app's proxy (redirect to /login when absent). It grants
    # nothing; every API call is still authenticated with the access token.
    response.set_cookie(
        SESSION_HINT_COOKIE,
        "1",
        max_age=int(refresh_lifetime().total_seconds()),
        path="/",
        secure=settings.REFRESH_COOKIE_SECURE,
        httponly=False,
        samesite="Lax",
    )
    get_token(request)  # ensures the csrftoken cookie is (re)issued for the SPA


def clear_refresh_cookie(response) -> None:
    response.delete_cookie(settings.REFRESH_COOKIE_NAME, path=settings.REFRESH_COOKIE_PATH, samesite="Strict")
    response.delete_cookie(SESSION_HINT_COOKIE, path="/", samesite="Lax")


def read_refresh_cookie(request) -> str | None:
    return request.COOKIES.get(settings.REFRESH_COOKIE_NAME)


def enforce_csrf(request) -> None:
    """Double-submit check for cookie-authenticated endpoints (refresh, logout)."""

    def dummy_get_response(_request):
        return None

    check = CSRFCheck(dummy_get_response)
    check.process_request(request)
    reason = check.process_view(request, None, (), {})
    if reason:
        raise PermissionDenied(f"CSRF failed: {reason}", code="csrf_failed")
