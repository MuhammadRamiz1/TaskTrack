from rest_framework.decorators import api_view
from rest_framework.response import Response
from rest_framework import status


@api_view(["GET"])
def demo_list(request):
    """GET /api/accounts/demo/ - demo list of users."""
    data = [
        {"id": 1, "name": "Ali", "email": "ali@example.com"},
        {"id": 2, "name": "Sara", "email": "sara@example.com"},
    ]
    return Response({"message": "Accounts demo API is working", "results": data})


@api_view(["GET"])
def demo_detail(request, pk):
    """GET /api/accounts/demo/<pk>/ - demo single user."""
    return Response({"id": pk, "name": f"User {pk}", "email": f"user{pk}@example.com"})


@api_view(["POST"])
def demo_create(request):
    """POST /api/accounts/demo/create/ - echoes back the data you send."""
    name = request.data.get("name")
    if not name:
        return Response({"error": "name is required"}, status=status.HTTP_400_BAD_REQUEST)
    return Response({"message": "Created (demo, not saved)", "data": request.data},
                    status=status.HTTP_201_CREATED)
