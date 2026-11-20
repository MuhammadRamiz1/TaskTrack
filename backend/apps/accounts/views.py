from django.contrib.auth.models import update_last_login
from drf_spectacular.utils import extend_schema, inline_serializer
from rest_framework import serializers, status
from rest_framework.authtoken.models import Token
from rest_framework.decorators import api_view, permission_classes,authentication_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

from .serializers import LoginSerializer, UserSerializer


@api_view(["POST"])
@permission_classes([AllowAny])
@authentication_classes([])
def login(request):
    serializer = LoginSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)

    user = serializer.validated_data["user"]

    token, _ = Token.objects.get_or_create(user=user)
    update_last_login(None, user)

    return Response(
        {
            "token": token.key,
            "user": UserSerializer(user).data,
        },
        status=status.HTTP_200_OK,
    )


@api_view(["GET"])
@permission_classes([AllowAny])
def demo_detail(request, pk):
    """GET /api/accounts/demo/<pk>/ - demo single user."""
    return Response({"id": pk, "name": f"User {pk}", "email": f"user{pk}@example.com"})


@api_view(["POST"])
@permission_classes([AllowAny])
def demo_create(request):
    """POST /api/accounts/demo/create/ - echoes back the data you send."""
    name = request.data.get("name")
    if not name:
        return Response({"error": "name is required"}, status=status.HTTP_400_BAD_REQUEST)
    return Response({"message": "Created (demo, not saved)", "data": request.data},
                    status=status.HTTP_201_CREATED)
