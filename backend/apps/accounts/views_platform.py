from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.response import Response

from apps.common.views import PlatformAPIView

from . import serializers as s
from .models import ImpersonationSession
from .services import platform


class ImpersonationStartView(PlatformAPIView):
    queryset = ImpersonationSession._base_manager.none()  # schema hint only
    permission_map = {"POST": "platform.impersonate"}

    @extend_schema(
        request=s.ImpersonationInput,
        responses={201: s.ImpersonationOutput},
        tags=["platform"],
        summary="Start a read-only, 30-minute impersonation session (audited)",
    )
    def post(self, request):
        data = s.ImpersonationInput(data=request.data)
        data.is_valid(raise_exception=True)
        session, access = platform.start_impersonation(
            actor=request.user, target_user_id=data.validated_data["user_id"], reason=data.validated_data["reason"]
        )
        body = {
            "id": session.pk,
            "access": access,
            "expires_at": session.expires_at,
            "target_user": s.UserBrief(session.target_user).data,
            "company_id": session.company_id,
        }
        return Response(body, status=status.HTTP_201_CREATED)


class ImpersonationEndView(PlatformAPIView):
    queryset = ImpersonationSession._base_manager.none()  # schema hint only
    permission_map = {"POST": "platform.impersonate"}

    @extend_schema(request=None, responses={204: None}, tags=["platform"], summary="End an impersonation session")
    def post(self, request, session_id):
        platform.end_impersonation(actor=request.user, session_id=session_id)
        return Response(status=status.HTTP_204_NO_CONTENT)
