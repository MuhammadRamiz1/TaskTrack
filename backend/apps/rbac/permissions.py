from rest_framework.permissions import BasePermission

from . import policy


class PolicyPermission(BasePermission):
    """View-level check: the user must hold the permission mapped to the HTTP method.

    Views declare ``permission_map = {"GET": "employee.view_private", "POST": ...}``.
    A method with no entry is denied (fail closed). Object-level checks happen in
    services via ``policy.require``.
    """

    message = "You do not have permission to perform this action."

    def has_permission(self, request, view):
        if request.method == "OPTIONS":
            return True
        code = getattr(view, "permission_map", {}).get(request.method)
        if code is None:
            return False
        return policy.has_perm(request.user, code)
