from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from rest_framework import serializers

from .models import Company, Plan


def _validate_tz(value):
    try:
        ZoneInfo(value)
    except (ZoneInfoNotFoundError, ValueError, KeyError) as exc:
        raise serializers.ValidationError("Not a valid IANA time zone.") from exc
    return value


def _validate_working_days(value):
    if not isinstance(value, list) or not value or any(not isinstance(d, int) or d < 0 or d > 6 for d in value):
        raise serializers.ValidationError("Use a non-empty list of weekday numbers 0 (Monday) to 6 (Sunday).")
    return sorted(set(value))


class PlanSerializer(serializers.ModelSerializer):
    class Meta:
        model = Plan
        fields = ["id", "code", "name", "max_users", "max_storage_mb", "features", "is_active", "created_at"]
        read_only_fields = ["id", "created_at"]


class CompanySettingsSerializer(serializers.ModelSerializer):
    """Fields a company admin may edit."""

    timezone = serializers.CharField(max_length=64, validators=[_validate_tz], required=False)
    working_days = serializers.JSONField(validators=[_validate_working_days], required=False)

    class Meta:
        model = Company
        fields = [
            "id",
            "name",
            "slug",
            "status",
            "timezone",
            "week_start",
            "working_days",
            "daily_working_minutes",
            "invite_expiry_hours",
            "enforce_2fa",
            "require_assignment_ack",
            "timer_start_moves_to_in_progress",
            "enforce_dependencies",
            "allow_self_review",
            "max_timer_hours",
        ]
        read_only_fields = ["id", "slug", "status"]


class CompanyOutput(serializers.ModelSerializer):
    plan = PlanSerializer()
    max_users = serializers.IntegerField(read_only=True)
    max_storage_mb = serializers.IntegerField(read_only=True)
    user_count = serializers.IntegerField(read_only=True, required=False)

    class Meta:
        model = Company
        fields = [
            "id",
            "name",
            "slug",
            "status",
            "plan",
            "max_users_override",
            "max_storage_mb_override",
            "max_users",
            "max_storage_mb",
            "storage_used_bytes",
            "timezone",
            "week_start",
            "working_days",
            "daily_working_minutes",
            "invite_expiry_hours",
            "enforce_2fa",
            "require_assignment_ack",
            "timer_start_moves_to_in_progress",
            "enforce_dependencies",
            "allow_self_review",
            "max_timer_hours",
            "suspended_at",
            "suspended_reason",
            "deleted_at",
            "created_at",
            "user_count",
        ]


class CompanyWriteInput(serializers.ModelSerializer):
    plan = serializers.PrimaryKeyRelatedField(queryset=Plan.objects.filter(is_active=True))
    slug = serializers.SlugField(max_length=80, required=False)
    timezone = serializers.CharField(max_length=64, validators=[_validate_tz], required=False)
    working_days = serializers.JSONField(validators=[_validate_working_days], required=False)

    class Meta:
        model = Company
        fields = [
            "name",
            "slug",
            "plan",
            "max_users_override",
            "max_storage_mb_override",
            "timezone",
            "week_start",
            "working_days",
            "daily_working_minutes",
            "invite_expiry_hours",
            "enforce_2fa",
            "require_assignment_ack",
            "timer_start_moves_to_in_progress",
            "enforce_dependencies",
            "allow_self_review",
            "max_timer_hours",
        ]
        extra_kwargs = {"name": {"validators": []}, "slug": {"validators": []}}


class SuspendInput(serializers.Serializer):
    reason = serializers.CharField(min_length=3, max_length=500)


class UsageOutput(serializers.Serializer):
    users = serializers.DictField(child=serializers.IntegerField())
    max_users = serializers.IntegerField()
    storage_used_bytes = serializers.IntegerField()
    max_storage_mb = serializers.IntegerField()
