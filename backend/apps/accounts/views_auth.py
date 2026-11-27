"""/api/v1/auth/ endpoints."""

from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import status
from rest_framework.response import Response

from apps.audit.services import record
from apps.common import tenancy
from apps.common.exceptions import NotFound, error_response
from apps.common.views import AuthenticatedAPIView, PublicAPIView

from . import serializers as s
from .cookies import clear_refresh_cookie, enforce_csrf, read_refresh_cookie, set_refresh_cookie
from .models import UserSession
from .services import auth, invites, mfa, passwords
from .services import sessions as session_service
from .throttles import (
    InviteAcceptThrottle,
    LoginEmailThrottle,
    LoginIPThrottle,
    MfaThrottle,
    PasswordResetThrottle,
)

ERRORS = {401: OpenApiResponse(description="Error envelope"), 400: OpenApiResponse(description="Error envelope")}


def _invalid_credentials() -> Response:
    return error_response(auth.AuthFailed.code, auth.AuthFailed.message, status.HTTP_401_UNAUTHORIZED)


def _session_response(request, outcome_user, issued, status_code=status.HTTP_200_OK, extra=None) -> Response:
    # The user has just proven their identity; continue the request in their context.
    tenancy.activate(tenancy.state_for_company(outcome_user.company_id))
    body = {"access": issued.access, "user": s.MeOutput(outcome_user).data, **(extra or {})}
    response = Response(body, status=status_code)
    set_refresh_cookie(response, request, issued.refresh)
    return response


class LoginView(PublicAPIView):
    throttle_classes = (LoginIPThrottle, LoginEmailThrottle)

    @extend_schema(
        request=s.LoginInput,
        responses={200: s.LoginOutput, **ERRORS},
        tags=["auth"],
        summary="Sign in with email and password",
    )
    def post(self, request):
        data = s.LoginInput(data=request.data)
        data.is_valid(raise_exception=True)
        outcome = auth.login(data.validated_data["email"], data.validated_data["password"])
        if not outcome.ok:
            return _invalid_credentials()
        if outcome.mfa_required:
            return Response({"mfa_required": True, "mfa_token": outcome.mfa_token})
        return _session_response(request, outcome.user, outcome.tokens, extra={"mfa_required": False})


class MfaVerifyView(PublicAPIView):
    throttle_classes = (MfaThrottle,)

    @extend_schema(
        request=s.MfaVerifyInput,
        responses={200: s.AccessOutput, **ERRORS},
        tags=["auth"],
        summary="Complete sign-in with a TOTP or recovery code",
    )
    def post(self, request):
        data = s.MfaVerifyInput(data=request.data)
        data.is_valid(raise_exception=True)
        outcome = auth.verify_mfa_login(data.validated_data["mfa_token"], data.validated_data["code"])
        if not outcome.ok:
            return _invalid_credentials()
        return _session_response(request, outcome.user, outcome.tokens)


class RefreshView(PublicAPIView):
    @extend_schema(
        request=None,
        responses={200: s.AccessOutput, **ERRORS},
        tags=["auth"],
        summary="Exchange the refresh cookie for a new access token (rotates the cookie)",
    )
    def post(self, request):
        enforce_csrf(request)
        outcome = auth.refresh(read_refresh_cookie(request))
        if not outcome.ok:
            response = error_response(
                "session_revoked", auth.SessionInvalid.message, status.HTTP_401_UNAUTHORIZED, {"reason": outcome.reason}
            )
            clear_refresh_cookie(response)
            return response
        return _session_response(request, outcome.user, outcome.tokens)


class LogoutView(PublicAPIView):
    @extend_schema(request=None, responses={204: None}, tags=["auth"], summary="Sign out of this device")
    def post(self, request):
        enforce_csrf(request)
        auth.logout(read_refresh_cookie(request))
        response = Response(status=status.HTTP_204_NO_CONTENT)
        clear_refresh_cookie(response)
        return response


class LogoutAllView(AuthenticatedAPIView):
    allow_password_change_required = True
    allow_mfa_enrolment = True

    @extend_schema(
        request=None, responses={200: s.DeactivationOutput}, tags=["auth"], summary="Sign out of every device"
    )
    def post(self, request):
        count = auth.logout_everywhere(request.user)
        response = Response({"sessions_revoked": count})
        clear_refresh_cookie(response)
        return response


class MeView(AuthenticatedAPIView):
    allow_password_change_required = True
    allow_mfa_enrolment = True

    def _out(self, request):
        return s.MeOutput(request.user, context={"impersonation": getattr(request, "impersonation", None)}).data

    @extend_schema(responses=s.MeOutput, tags=["auth"], summary="Current user, roles and permissions")
    def get(self, request):
        return Response(self._out(request))

    @extend_schema(request=s.ProfileUpdateInput, responses=s.MeOutput, tags=["auth"], summary="Edit own profile")
    def patch(self, request):
        data = s.ProfileUpdateInput(data=request.data, partial=True)
        data.is_valid(raise_exception=True)
        user = request.user
        old = {k: getattr(user, k) for k in data.validated_data}
        for key, value in data.validated_data.items():
            setattr(user, key, value)
        user.save()
        if data.validated_data:
            record(actor=user, action="profile.updated", entity=user, old_value=old, new_value=data.validated_data)
        return Response(self._out(request))


class InviteDetailView(PublicAPIView):
    throttle_classes = (InviteAcceptThrottle,)

    @extend_schema(
        responses={200: s.InviteInfoOutput, 410: OpenApiResponse(description="Link expired, used or revoked")},
        tags=["auth"],
        summary="Check an invite link",
    )
    def get(self, request, token):
        return Response(s.InviteInfoOutput(invites.describe(token)).data)


class InviteAcceptView(PublicAPIView):
    throttle_classes = (InviteAcceptThrottle,)

    @extend_schema(
        request=s.InviteAcceptInput,
        responses={201: s.AccessOutput, 410: OpenApiResponse()},
        tags=["auth"],
        summary="Set a password from an invite link and sign in",
    )
    def post(self, request):
        data = s.InviteAcceptInput(data=request.data)
        data.is_valid(raise_exception=True)
        user, issued = invites.accept(data.validated_data["token"], data.validated_data["password"])
        return _session_response(request, user, issued, status.HTTP_201_CREATED)


class ForgotPasswordView(PublicAPIView):
    throttle_classes = (PasswordResetThrottle,)

    @extend_schema(
        request=s.ForgotPasswordInput,
        responses={202: s.DetailOutput},
        tags=["auth"],
        summary="Email a password reset link (always 202)",
    )
    def post(self, request):
        data = s.ForgotPasswordInput(data=request.data)
        data.is_valid(raise_exception=True)
        passwords.request_reset(data.validated_data["email"])
        return Response(
            {"detail": "If an account exists for this email, a reset link has been sent."},
            status=status.HTTP_202_ACCEPTED,
        )


class ResetPasswordDetailView(PublicAPIView):
    throttle_classes = (InviteAcceptThrottle,)

    @extend_schema(
        responses={200: s.ResetInfoOutput, 410: OpenApiResponse()}, tags=["auth"], summary="Check a password reset link"
    )
    def get(self, request, token):
        return Response(s.ResetInfoOutput(passwords.describe_reset(token)).data)


class ResetPasswordView(PublicAPIView):
    throttle_classes = (InviteAcceptThrottle,)

    @extend_schema(
        request=s.ResetPasswordInput,
        responses={200: s.DetailOutput, 410: OpenApiResponse()},
        tags=["auth"],
        summary="Set a new password from a reset link",
    )
    def post(self, request):
        data = s.ResetPasswordInput(data=request.data)
        data.is_valid(raise_exception=True)
        passwords.reset(data.validated_data["token"], data.validated_data["new_password"])
        return Response({"detail": "Your password has been reset. Sign in with your new password."})


class ChangePasswordView(AuthenticatedAPIView):
    allow_password_change_required = True

    @extend_schema(
        request=s.ChangePasswordInput,
        responses={200: s.AccessOutput},
        tags=["auth"],
        summary="Change own password (signs out other devices)",
    )
    def post(self, request):
        data = s.ChangePasswordInput(data=request.data)
        data.is_valid(raise_exception=True)
        access = passwords.change(
            request.user,
            data.validated_data["current_password"],
            data.validated_data["new_password"],
            getattr(request, "session_id", None),
        )
        return Response({"access": access, "user": s.MeOutput(request.user).data})


class SessionListView(AuthenticatedAPIView):
    allow_password_change_required = True

    @extend_schema(responses=s.SessionOutput(many=True), tags=["auth"], summary="Own active sessions")
    def get(self, request):
        sessions = UserSession.objects.filter(user=request.user, revoked_at__isnull=True).order_by("-last_used_at")
        sessions = [x for x in sessions if x.is_active]
        return Response(
            s.SessionOutput(
                sessions, many=True, context={"current_session_id": getattr(request, "session_id", None)}
            ).data
        )


class SessionDetailView(AuthenticatedAPIView):
    allow_password_change_required = True

    @extend_schema(responses={204: None}, tags=["auth"], summary="Revoke one own session")
    def delete(self, request, session_id):
        session = UserSession.objects.filter(pk=session_id, user=request.user, revoked_at__isnull=True).first()
        if session is None:
            raise NotFound()
        session_service.revoke(session, "revoked_by_user")
        record(actor=request.user, action="auth.session_revoked", entity=session)
        return Response(status=status.HTTP_204_NO_CONTENT)


class MfaSetupView(AuthenticatedAPIView):
    allow_mfa_enrolment = True

    @extend_schema(request=None, responses=s.MfaSetupOutput, tags=["auth"], summary="Start TOTP enrolment")
    def post(self, request):
        return Response(mfa.begin_setup(request.user))


class MfaConfirmView(AuthenticatedAPIView):
    allow_mfa_enrolment = True

    @extend_schema(
        request=s.MfaCodeInput,
        responses=s.RecoveryCodesOutput,
        tags=["auth"],
        summary="Confirm TOTP enrolment; returns recovery codes once",
    )
    def post(self, request):
        data = s.MfaCodeInput(data=request.data)
        data.is_valid(raise_exception=True)
        return Response({"recovery_codes": mfa.confirm_setup(request.user, data.validated_data["code"])})


class MfaDisableView(AuthenticatedAPIView):
    @extend_schema(request=s.MfaDisableInput, responses={204: None}, tags=["auth"], summary="Disable TOTP")
    def post(self, request):
        data = s.MfaDisableInput(data=request.data)
        data.is_valid(raise_exception=True)
        mfa.disable(request.user, data.validated_data["password"], data.validated_data["code"])
        return Response(status=status.HTTP_204_NO_CONTENT)


class MfaRecoveryCodesView(AuthenticatedAPIView):
    @extend_schema(
        request=s.MfaCodeInput, responses=s.RecoveryCodesOutput, tags=["auth"], summary="Regenerate recovery codes"
    )
    def post(self, request):
        data = s.MfaCodeInput(data=request.data)
        data.is_valid(raise_exception=True)
        return Response({"recovery_codes": mfa.regenerate_recovery_codes(request.user, data.validated_data["code"])})
