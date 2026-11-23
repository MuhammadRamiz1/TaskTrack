"""Structural rules that keep security properties from eroding as the code grows."""

import pytest
from django.urls import get_resolver

from apps.common.schema import TenantSafeSchemaGenerator as SchemaGenerator
from apps.common.views import BASE_VIEW_CLASSES

METHODS = ("get", "post", "put", "patch", "delete")


def _api_views():
    views = []

    def walk(patterns, prefix=""):
        for p in patterns:
            if hasattr(p, "url_patterns"):
                walk(p.url_patterns, prefix + str(p.pattern))
            elif (prefix + str(p.pattern)).startswith("api/v1/") and hasattr(p.callback, "view_class"):
                views.append((p.name, p.callback.view_class))

    walk(get_resolver().url_patterns)
    return views


SCHEMA_VIEWS = {"schema", "docs", "redoc"}


@pytest.mark.parametrize(
    ("name", "view"),
    [v for v in _api_views() if v[0] not in SCHEMA_VIEWS],
    ids=[v[0] for v in _api_views() if v[0] not in SCHEMA_VIEWS],
)
def test_views_use_base_classes_and_declare_permissions(name, view):
    assert issubclass(view, BASE_VIEW_CLASSES), f"{name} must inherit a common.views base class"
    if getattr(view, "enforce_policy", False):
        for method in METHODS:
            if hasattr(view, method):
                assert method.upper() in view.permission_map, f"{name}: no permission for {method.upper()}"


def test_openapi_schema_generates_without_errors():
    schema = SchemaGenerator().get_schema(request=None, public=True)
    paths = schema["paths"]
    assert "/api/v1/auth/login/" in paths and "/api/v1/hr/employees/{user_id}/" in paths
    assert schema["components"]["securitySchemes"]["jwtAuth"]["scheme"] == "bearer"


def test_schema_endpoint(anon):
    response = anon.get("/api/v1/schema/")
    assert response.status_code == 200


def test_health_live(anon):
    assert anon.get("/health/live").json() == {"status": "ok"}


def test_error_envelope_shape(anon):
    body = anon.get("/api/v1/auth/me/").json()
    assert set(body["error"]) == {"code", "message", "details", "request_id"}
    assert body["error"]["request_id"]
