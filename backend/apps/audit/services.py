"""Helpers for writing audit entries from views, services and signals."""

from django.contrib.contenttypes.models import ContentType
from django.db.models.fields.related import ForeignKey

from .models import AuditLog


def diff_instances(old, new, fields=None):
    """Return {field: {"old": x, "new": y}} for fields that differ between two model instances."""
    model = new._meta.model
    names = fields or [f.name for f in model._meta.concrete_fields if f.name not in {"updated_at"}]
    changes = {}
    for name in names:
        field = model._meta.get_field(name)
        attr = field.attname if isinstance(field, ForeignKey) else name
        before, after = getattr(old, attr, None), getattr(new, attr, None)
        if before != after:
            changes[name] = {"old": _jsonable(before), "new": _jsonable(after)}
    return changes


def _jsonable(value):
    if value is None or isinstance(value, (bool, int, float, str, list, dict)):
        return value
    return str(value)


def get_client_ip(request):
    if request is None:
        return None
    forwarded = request.META.get("HTTP_X_FORWARDED_FOR")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR")


def log_action(actor, action, obj=None, changes=None, request=None, object_repr=""):
    """Create an AuditLog entry. `actor` may be None for system actions."""
    content_type = None
    object_id = ""
    if obj is not None:
        content_type = ContentType.objects.get_for_model(obj, for_concrete_model=False)
        object_id = str(obj.pk) if obj.pk is not None else ""
        object_repr = object_repr or str(obj)[:255]
    return AuditLog.objects.create(
        actor=actor if getattr(actor, "pk", None) else None,
        actor_email=getattr(actor, "email", "") or "",
        action=action,
        content_type=content_type,
        object_id=object_id,
        object_repr=object_repr[:255],
        changes=changes or {},
        ip_address=get_client_ip(request),
    )
