from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from apps.accounts.models import User
from apps.accounts.serializers import TeamRef, UserBrief

from .models import Holiday, LeaveDay, Project, Team


class TeamOutput(serializers.ModelSerializer):
    lead = UserBrief(allow_null=True)
    member_count = serializers.IntegerField(read_only=True, required=False)
    project_count = serializers.IntegerField(read_only=True, required=False)

    class Meta:
        model = Team
        fields = ["id", "name", "description", "lead", "is_archived", "member_count", "project_count", "created_at"]


class TeamInput(serializers.Serializer):
    name = serializers.CharField(max_length=150)
    description = serializers.CharField(required=False, allow_blank=True, default="")


class TeamUpdateInput(serializers.Serializer):
    name = serializers.CharField(max_length=150, required=False)
    description = serializers.CharField(required=False, allow_blank=True)


class UserIdsInput(serializers.Serializer):
    user_ids = serializers.ListField(child=serializers.UUIDField(), min_length=1, max_length=200)


class UserIdInput(serializers.Serializer):
    user_id = serializers.UUIDField()


class MemberOutput(serializers.Serializer):
    user = UserBrief(source="*")
    job_title = serializers.CharField()
    status = serializers.CharField()


class ProjectOutput(serializers.ModelSerializer):
    team = serializers.SerializerMethodField()
    owner = UserBrief(allow_null=True)
    member_count = serializers.IntegerField(read_only=True, required=False)
    open_task_count = serializers.IntegerField(read_only=True, required=False)

    class Meta:
        model = Project
        fields = [
            "id",
            "key",
            "name",
            "description",
            "status",
            "team",
            "owner",
            "start_date",
            "end_date",
            "member_count",
            "open_task_count",
            "created_at",
        ]

    @extend_schema_field(TeamRef)
    def get_team(self, obj) -> dict:
        return {"id": str(obj.team_id), "name": obj.team.name}


class ProjectInput(serializers.Serializer):
    team_id = serializers.UUIDField()
    key = serializers.RegexField(r"^[A-Za-z][A-Za-z0-9]{1,9}$", help_text="2-10 letters/digits, e.g. WEB")
    name = serializers.CharField(max_length=200)
    description = serializers.CharField(required=False, allow_blank=True, default="")
    owner_id = serializers.UUIDField(required=False, allow_null=True)
    start_date = serializers.DateField(required=False, allow_null=True)
    end_date = serializers.DateField(required=False, allow_null=True)


class ProjectUpdateInput(serializers.Serializer):
    name = serializers.CharField(max_length=200, required=False)
    description = serializers.CharField(required=False, allow_blank=True)
    status = serializers.ChoiceField(choices=Project.Status.choices, required=False)
    owner_id = serializers.UUIDField(required=False, allow_null=True)
    start_date = serializers.DateField(required=False, allow_null=True)
    end_date = serializers.DateField(required=False, allow_null=True)


class DirectoryOutput(serializers.ModelSerializer):
    full_name = serializers.CharField(read_only=True)

    class Meta:
        model = User
        fields = ["id", "email", "first_name", "last_name", "full_name", "job_title", "status"]


class HolidaySerializer(serializers.ModelSerializer):
    class Meta:
        model = Holiday
        fields = ["id", "date", "name"]
        read_only_fields = ["id"]


class LeaveOutput(serializers.ModelSerializer):
    user = UserBrief()

    class Meta:
        model = LeaveDay
        fields = ["id", "user", "date", "kind", "half_day", "note", "created_at"]


class LeaveInput(serializers.Serializer):
    user_id = serializers.UUIDField()
    date = serializers.DateField()
    kind = serializers.ChoiceField(choices=LeaveDay.Kind.choices, default=LeaveDay.Kind.ANNUAL)
    half_day = serializers.BooleanField(default=False)
    note = serializers.CharField(max_length=200, required=False, allow_blank=True, default="")
