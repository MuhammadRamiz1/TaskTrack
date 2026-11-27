from django.urls import path

from . import views_auth as v

urlpatterns = [
    path("login/", v.LoginView.as_view(), name="auth-login"),
    path("2fa/verify/", v.MfaVerifyView.as_view(), name="auth-2fa-verify"),
    path("refresh/", v.RefreshView.as_view(), name="auth-refresh"),
    path("logout/", v.LogoutView.as_view(), name="auth-logout"),
    path("logout-all/", v.LogoutAllView.as_view(), name="auth-logout-all"),
    path("me/", v.MeView.as_view(), name="auth-me"),
    path("invites/accept/", v.InviteAcceptView.as_view(), name="auth-invite-accept"),
    path("invites/<str:token>/", v.InviteDetailView.as_view(), name="auth-invite-detail"),
    path("password/forgot/", v.ForgotPasswordView.as_view(), name="auth-password-forgot"),
    path("password/reset/", v.ResetPasswordView.as_view(), name="auth-password-reset"),
    path("password/reset/<str:token>/", v.ResetPasswordDetailView.as_view(), name="auth-password-reset-detail"),
    path("password/change/", v.ChangePasswordView.as_view(), name="auth-password-change"),
    path("sessions/", v.SessionListView.as_view(), name="auth-sessions"),
    path("sessions/<uuid:session_id>/", v.SessionDetailView.as_view(), name="auth-session-detail"),
    path("2fa/setup/", v.MfaSetupView.as_view(), name="auth-2fa-setup"),
    path("2fa/confirm/", v.MfaConfirmView.as_view(), name="auth-2fa-confirm"),
    path("2fa/disable/", v.MfaDisableView.as_view(), name="auth-2fa-disable"),
    path("2fa/recovery-codes/", v.MfaRecoveryCodesView.as_view(), name="auth-2fa-recovery-codes"),
]
