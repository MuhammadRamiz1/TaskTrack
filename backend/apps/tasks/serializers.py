from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from apps.accounts.serializers import UserBrief

from .models import (
    ChecklistItem,
    Priority,
    Status,
    StatusTransitionRule,
    Task,
    TaskActivity,
    TaskAttachment,
    TaskChecklist,
    TaskComment,
    TaskDependency,
)


class ProjectBrief(serializers.Serializer):
    id = serializers.UUIDField()
    key = serializers.CharField()
    name = serializers.CharField()


class AssigneeOutput(serializers.Serializer):
    user = UserBrief()
    acknowledged_at = serializers.DateTimeField(allow_null=True)
    assigned_at = serializers.DateTimeField(source="created_at")


class TaskSummary(serializers.ModelSerializer):
    key = serializers.CharField(read_only=True)
    project = ProjectBrief()
    assignees = AssigneeOutput(many=True)
    reviewer = UserBrief(allow_null=True)
    parent_id = serializers.UUIDField(allow_null=True)
    is_read_only = serializers.BooleanField(read_only=True)
    is_overdue = serializers.SerializerMethodField()

    class Meta:
        model = Task
        fields = [
            "id",
            "key",
            "number",
            "title",
            "status",
            "priority",
            "project",
            "parent_id",
            "start_date",
            "due_date",
            "estimated_minutes",
            "assignees",
            "reviewer",
            "needs_reassignment",
            "is_read_only",
            "is_overdue",
            "version",
            "created_at",
            "updated_at",
        ]

    def get_is_overdue(self, task) -> bool:
        from datetime import date

        return bool(task.due_date and task.due_date < date.today() and not task.is_read_only)


class ChecklistItemOutput(serializers.ModelSerializer):
    done_by = UserBrief(allow_null=True)

    class Meta:
        model = ChecklistItem
        fields = ["id", "text", "is_required", "is_done", "done_by", "done_at", "position"]


class ChecklistOutput(serializers.ModelSerializer):
    items = ChecklistItemOutput(many=True)

    class Meta:
        model = TaskChecklist
        fields = ["id", "title", "position", "items"]


class AllowedTransitionOutput(serializers.Serializer):
    to_status = serializers.ChoiceField(choices=Status.choices)
    requires_comment = serializers.BooleanField()


class TaskRefOutput(serializers.Serializer):
    id = serializers.UUIDField()
    key = serializers.CharField()
    title = serializers.CharField()
    status = serializers.ChoiceField(choices=Status.choices)


class DependencyOutput(serializers.ModelSerializer):
    blocked_by = serializers.SerializerMethodField()

    class Meta:
        model = TaskDependency
        fields = ["id", "blocked_by", "created_at"]

    @extend_schema_field(TaskRefOutput)
    def get_blocked_by(self, dep) -> dict:
        t = dep.blocked_by
        return {"id": str(t.pk), "key": t.key, "title": t.title, "status": t.status}


class TaskDetail(TaskSummary):
    created_by = UserBrief()
    checklists = ChecklistOutput(many=True)
    dependencies = DependencyOutput(many=True)
    dependents = serializers.SerializerMethodField()
    subtasks = serializers.SerializerMethodField()
    allowed_transitions = serializers.SerializerMethodField()

    class Meta(TaskSummary.Meta):
        fields = [
            *TaskSummary.Meta.fields,
            "description",
            "instructions",
            "acceptance_criteria",
            "created_by",
            "blocked_reason",
            "review_round",
            "completed_at",
            "locked_at",
            "checklists",
            "dependencies",
            "dependents",
            "subtasks",
            "allowed_transitions",
        ]

    @extend_schema_field(TaskRefOutput(many=True))
    def get_dependents(self, task) -> list[dict]:
        return [
            {"id": str(d.task_id), "key": d.task.key, "title": d.task.title, "status": d.task.status}
            for d in task.dependents.select_related("task__project")
            if d.task.deleted_at is None
        ]

    @extend_schema_field(TaskRefOutput(many=True))
    def get_subtasks(self, task) -> list[dict]:
        return [
            {"id": str(t.pk), "key": t.key, "title": t.title, "status": t.status}
            for t in Task.objects.filter(parent=task).select_related("project").order_by("number")
        ]

    @extend_schema_field(AllowedTransitionOutput(many=True))
    def get_allowed_transitions(self, task) -> list[dict]:
        from .workflow import allowed_targets

        request = self.context.get("request")
        return allowed_targets(request.user, task) if request else []


class TaskCreateInput(serializers.Serializer):
    project_id = serializers.UUIDField()
    parent_id = serializers.UUIDField(required=False, allow_null=True)
    title = serializers.CharField(max_length=300)
    description = serializers.CharField(required=False, allow_blank=True, default="")
    instructions = serializers.CharField(required=False, allow_blank=True, default="")
    acceptance_criteria = serializers.CharField(required=False, allow_blank=True, default="")
    priority = serializers.ChoiceField(choices=Priority.choices, default=Priority.MEDIUM)
    start_date = serializers.DateField(required=False, allow_null=True)
    due_date = serializers.DateField(required=False, allow_null=True)
    estimated_minutes = serializers.IntegerField(required=False, allow_null=True, min_value=0, max_value=100000)
    reviewer_id = serializers.UUIDField(required=False, allow_null=True)
    assignee_ids = serializers.ListField(child=serializers.UUIDField(), required=False, max_length=50)


class TaskUpdateInput(serializers.Serializer):
    version = serializers.IntegerField(min_value=1, help_text="The version you last read (optimistic locking).")
    title = serializers.CharField(max_length=300, required=False)
    description = serializers.CharField(required=False, allow_blank=True)
    instructions = serializers.CharField(required=False, allow_blank=True)
    acceptance_criteria = serializers.CharField(required=False, allow_blank=True)
    priority = serializers.ChoiceField(choices=Priority.choices, required=False)
    start_date = serializers.DateField(required=False, allow_null=True)
    due_date = serializers.DateField(required=False, allow_null=True)
    estimated_minutes = serializers.IntegerField(required=False, allow_null=True, min_value=0, max_value=100000)
    reviewer_id = serializers.UUIDField(required=False, allow_null=True)


class TransitionInput(serializers.Serializer):
    to_status = serializers.ChoiceField(choices=Status.choices)
    comment = serializers.CharField(required=False, allow_blank=True, default="", max_length=5000)
    version = serializers.IntegerField(required=False, min_value=1)


class CommentInput(serializers.Serializer):
    comment = serializers.CharField(max_length=5000)


class NoteInput(serializers.Serializer):
    note = serializers.CharField(required=False, allow_blank=True, default="", max_length=2000)


class AssignInput(serializers.Serializer):
    user_ids = serializers.ListField(child=serializers.UUIDField(), min_length=1, max_length=50)


class ReassignInput(serializers.Serializer):
    from_user_id = serializers.UUIDField()
    to_user_id = serializers.UUIDField()


class BulkAssignInput(serializers.Serializer):
    task_ids = serializers.ListField(child=serializers.UUIDField(), min_length=1, max_length=200)
    user_ids = serializers.ListField(child=serializers.UUIDField(), min_length=1, max_length=50)
    mode = serializers.ChoiceField(choices=["add", "replace"], default="add")


class CountOutput(serializers.Serializer):
    count = serializers.IntegerField()


class ChecklistInput(serializers.Serializer):
    title = serializers.CharField(max_length=200)
    position = serializers.IntegerField(required=False, min_value=0)


class ChecklistUpdateInput(serializers.Serializer):
    title = serializers.CharField(max_length=200, required=False)
    position = serializers.IntegerField(required=False, min_value=0)


class ChecklistItemInput(serializers.Serializer):
    text = serializers.CharField(max_length=500)
    is_required = serializers.BooleanField(default=False)


class ChecklistItemUpdateInput(serializers.Serializer):
    text = serializers.CharField(max_length=500, required=False)
    is_required = serializers.BooleanField(required=False)
    is_done = serializers.BooleanField(required=False)
    position = serializers.IntegerField(required=False, min_value=0)


class DependencyInput(serializers.Serializer):
    blocked_by_id = serializers.UUIDField()


class CommentOutput(serializers.ModelSerializer):
    author = UserBrief(allow_null=True)
    mentions = serializers.SerializerMethodField()
    body = serializers.SerializerMethodField()
    is_deleted = serializers.SerializerMethodField()

    class Meta:
        model = TaskComment
        fields = ["id", "author", "body", "kind", "mentions", "edited_at", "is_deleted", "created_at"]

    def get_mentions(self, comment) -> list[str]:
        return [str(m.user_id) for m in comment.mentions.all()]

    def get_body(self, comment) -> str:
        return "" if comment.deleted_at else comment.body

    def get_is_deleted(self, comment) -> bool:
        return comment.deleted_at is not None


class CommentBodyInput(serializers.Serializer):
    body = serializers.CharField(max_length=10000, help_text="Markdown. Mention with @[Name](user:<uuid>).")


class AttachmentOutput(serializers.ModelSerializer):
    uploaded_by = UserBrief(allow_null=True)

    class Meta:
        model = TaskAttachment
        fields = ["id", "filename", "content_type", "size_bytes", "sha256", "uploaded_by", "created_at"]


class AttachmentInput(serializers.Serializer):
    file = serializers.FileField()


class ActivityOutput(serializers.ModelSerializer):
    actor = UserBrief(allow_null=True)

    class Meta:
        model = TaskActivity
        fields = ["id", "verb", "actor", "data", "created_at"]


class RuleOutput(serializers.ModelSerializer):
    class Meta:
        model = StatusTransitionRule
        fields = [
            "id",
            "from_status",
            "to_status",
            "trigger",
            "allowed_roles",
            "requires_comment",
            "requires_reviewer",
            "is_locked",
            "is_active",
        ]


class RuleUpdateInput(serializers.Serializer):
    allowed_roles = serializers.ListField(child=serializers.CharField(max_length=40), required=False)
    requires_comment = serializers.BooleanField(required=False)
    is_active = serializers.BooleanField(required=False)


class WorkloadOutput(serializers.Serializer):
    user = UserBrief()
    open_tasks = serializers.IntegerField()
    estimated_minutes = serializers.IntegerField()
    due_in_period = serializers.IntegerField()
    overdue = serializers.IntegerField()
    capacity_minutes = serializers.IntegerField()
    leave_days = serializers.FloatField()
    load_percent = serializers.IntegerField(allow_null=True)


class AllowedMove(serializers.Serializer):
    to_status = serializers.ChoiceField(choices=Status.choices)
    action = serializers.ChoiceField(choices=["transition", "assign", "submit", "approve", "request_changes"])
    requires_comment = serializers.BooleanField()


class BoardCard(TaskSummary):
    allowed_moves = serializers.SerializerMethodField()
    # Annotated by TaskBoardView.
    checklist_total = serializers.IntegerField(read_only=True)
    checklist_done = serializers.IntegerField(read_only=True)
    comment_count = serializers.IntegerField(read_only=True)
    attachment_count = serializers.IntegerField(read_only=True)

    class Meta(TaskSummary.Meta):
        fields = [
            *TaskSummary.Meta.fields,
            "allowed_moves",
            "checklist_total",
            "checklist_done",
            "comment_count",
            "attachment_count",
        ]

    @extend_schema_field(AllowedMove(many=True))
    def get_allowed_moves(self, task) -> list[dict]:
        from .board import allowed_moves

        return allowed_moves(self.context["request"].user, task, rules=self.context["rules"])


class BoardColumnOutput(serializers.Serializer):
    status = serializers.ChoiceField(choices=Status.choices)
    tasks = BoardCard(many=True)


class BoardOutput(serializers.Serializer):
    project = ProjectBrief()
    columns = BoardColumnOutput(many=True)
