from django.conf import settings
from django.db import models

from apps.common.models import TenantManager, TenantModel


class Status(models.TextChoices):
    BACKLOG = "BACKLOG", "Backlog"
    ASSIGNED = "ASSIGNED", "Assigned"
    IN_PROGRESS = "IN_PROGRESS", "In progress"
    IN_REVIEW = "IN_REVIEW", "In review"
    ON_HOLD = "ON_HOLD", "On hold"
    BLOCKED = "BLOCKED", "Blocked"
    REOPENED = "REOPENED", "Reopened"
    COMPLETED = "COMPLETED", "Completed"
    CANCELLED = "CANCELLED", "Cancelled"


READ_ONLY_STATUSES = frozenset({Status.COMPLETED, Status.CANCELLED})
OPEN_STATUSES = frozenset(set(Status) - READ_ONLY_STATUSES)


class Priority(models.TextChoices):
    LOW = "LOW", "Low"
    MEDIUM = "MEDIUM", "Medium"
    HIGH = "HIGH", "High"
    URGENT = "URGENT", "Urgent"


class Trigger(models.TextChoices):
    MANUAL = "MANUAL", "Manual"
    ASSIGN = "ASSIGN", "Assignment"
    TIMER = "TIMER", "Timer start"
    SUBMIT = "SUBMIT", "Submit for review"
    APPROVE = "APPROVE", "Review approved"
    REQUEST_CHANGES = "REQUEST_CHANGES", "Changes requested"
    SYSTEM = "SYSTEM", "System"


class LiveTaskManager(TenantManager):
    """Default manager: hides soft-deleted tasks."""

    def get_queryset(self):
        return super().get_queryset().filter(deleted_at__isnull=True)


class Task(TenantModel):
    project = models.ForeignKey("org.Project", on_delete=models.PROTECT, related_name="tasks")
    parent = models.ForeignKey("self", null=True, blank=True, on_delete=models.PROTECT, related_name="subtasks")
    number = models.PositiveIntegerField()
    title = models.CharField(max_length=300)
    description = models.TextField(blank=True)
    instructions = models.TextField(blank=True)
    acceptance_criteria = models.TextField(blank=True)
    priority = models.CharField(max_length=6, choices=Priority.choices, default=Priority.MEDIUM)
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.BACKLOG)
    start_date = models.DateField(null=True, blank=True)
    due_date = models.DateField(null=True, blank=True)
    estimated_minutes = models.PositiveIntegerField(null=True, blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="created_tasks")
    reviewer = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="review_tasks"
    )
    blocked_reason = models.TextField(blank=True)
    review_round = models.PositiveIntegerField(default=0)
    needs_reassignment = models.BooleanField(default=False)
    completed_at = models.DateTimeField(null=True, blank=True)
    locked_at = models.DateTimeField(null=True, blank=True)
    version = models.PositiveIntegerField(default=1)
    deleted_at = models.DateTimeField(null=True, blank=True)

    objects = LiveTaskManager()
    with_deleted = TenantManager()

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(fields=["project", "number"], name="tasks_task_number_per_project"),
            models.CheckConstraint(
                condition=models.Q(due_date__isnull=True)
                | models.Q(start_date__isnull=True)
                | models.Q(due_date__gte=models.F("start_date")),
                name="tasks_task_due_after_start",
            ),
            models.CheckConstraint(condition=models.Q(status__in=Status.values), name="tasks_task_status_valid"),
        ]
        indexes = [
            models.Index(
                fields=["company", "status"], name="tasks_company_status", condition=models.Q(deleted_at__isnull=True)
            ),
            models.Index(
                fields=["company", "due_date"], name="tasks_company_due", condition=models.Q(deleted_at__isnull=True)
            ),
            models.Index(fields=["project", "status"], name="tasks_project_status"),
            models.Index(fields=["parent"], name="tasks_parent"),
        ]

    def __str__(self):
        return f"{self.key} {self.title}"

    @property
    def key(self) -> str:
        return f"{self.project.key}-{self.number}"

    @property
    def is_read_only(self) -> bool:
        return self.status in READ_ONLY_STATUSES or self.locked_at is not None

    @property
    def effective_reviewer_id(self):
        return self.reviewer_id or self.created_by_id

    #: Status as loaded from the database; the workflow guard compares against it.
    _loaded_status = Status.BACKLOG

    @classmethod
    def from_db(cls, db, field_names, values):
        instance = super().from_db(db, field_names, values)
        instance._loaded_status = instance.__dict__.get("status")
        return instance

    def refresh_from_db(self, *args, **kwargs):
        super().refresh_from_db(*args, **kwargs)
        self._loaded_status = self.status

    def save(self, *args, **kwargs):
        from .workflow import guard_status_write

        update_fields = kwargs.get("update_fields")
        if update_fields is None or "status" in update_fields:
            guard_status_write(self)
        super().save(*args, **kwargs)
        if update_fields is None or "status" in update_fields:
            self._loaded_status = self.status


class TaskAssignee(TenantModel):
    task = models.ForeignKey(Task, on_delete=models.CASCADE, related_name="assignees")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="task_assignments")
    task_status = models.CharField(max_length=12, choices=Status.choices)  # denormalised for "my tasks"
    assigned_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    acknowledged_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["task", "user"], name="tasks_assignee_unique")]
        indexes = [models.Index(fields=["user", "task_status"], name="tasks_assignee_user_status")]


class TaskChecklist(TenantModel):
    task = models.ForeignKey(Task, on_delete=models.CASCADE, related_name="checklists")
    title = models.CharField(max_length=200)
    position = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["position", "created_at"]


class ChecklistItem(TenantModel):
    checklist = models.ForeignKey(TaskChecklist, on_delete=models.CASCADE, related_name="items")
    text = models.CharField(max_length=500)
    is_required = models.BooleanField(default=False)
    is_done = models.BooleanField(default=False)
    done_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    done_at = models.DateTimeField(null=True, blank=True)
    position = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["position", "created_at"]


class TaskDependency(TenantModel):
    """``task`` cannot start until ``blocked_by`` is completed or cancelled."""

    task = models.ForeignKey(Task, on_delete=models.CASCADE, related_name="dependencies")
    blocked_by = models.ForeignKey(Task, on_delete=models.CASCADE, related_name="dependents")
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["task", "blocked_by"], name="tasks_dependency_unique"),
            models.CheckConstraint(condition=~models.Q(task=models.F("blocked_by")), name="tasks_dependency_not_self"),
        ]


class TaskComment(TenantModel):
    class Kind(models.TextChoices):
        COMMENT = "COMMENT", "Comment"
        REVIEW = "REVIEW", "Review"
        SYSTEM = "SYSTEM", "System"

    task = models.ForeignKey(Task, on_delete=models.CASCADE, related_name="comments")
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    body = models.TextField()
    kind = models.CharField(max_length=8, choices=Kind.choices, default=Kind.COMMENT)
    edited_at = models.DateTimeField(null=True, blank=True)
    deleted_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["created_at"]


class CommentMention(TenantModel):
    comment = models.ForeignKey(TaskComment, on_delete=models.CASCADE, related_name="mentions")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="+")

    class Meta:
        constraints = [models.UniqueConstraint(fields=["comment", "user"], name="tasks_mention_unique")]


class TaskAttachment(TenantModel):
    class State(models.TextChoices):
        ACTIVE = "ACTIVE", "Active"
        DELETED = "DELETED", "Deleted"

    task = models.ForeignKey(Task, on_delete=models.CASCADE, related_name="attachments")
    comment = models.ForeignKey(
        TaskComment, null=True, blank=True, on_delete=models.SET_NULL, related_name="attachments"
    )
    storage_key = models.CharField(max_length=500)
    filename = models.CharField(max_length=255)
    content_type = models.CharField(max_length=120)
    size_bytes = models.BigIntegerField()
    sha256 = models.CharField(max_length=64)
    status = models.CharField(max_length=8, choices=State.choices, default=State.ACTIVE)
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )

    class Meta:
        ordering = ["-created_at"]


class TaskActivity(TenantModel):
    """User-facing history of a task. Append-only; kept even when the task is deleted."""

    task = models.ForeignKey(Task, on_delete=models.CASCADE, related_name="activity")
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    verb = models.CharField(max_length=40)
    data = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["task", "-created_at"], name="tasks_activity_task_time")]


class StatusTransitionRule(TenantModel):
    from_status = models.CharField(max_length=12, choices=Status.choices)
    to_status = models.CharField(max_length=12, choices=Status.choices)
    trigger = models.CharField(max_length=16, choices=Trigger.choices, default=Trigger.MANUAL)
    allowed_roles = models.JSONField(default=list, blank=True)
    requires_comment = models.BooleanField(default=False)
    requires_reviewer = models.BooleanField(default=False)
    is_locked = models.BooleanField(default=False, help_text="Core rule: cannot be disabled or deleted.")
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["from_status", "to_status"]
        constraints = [
            models.UniqueConstraint(
                fields=["company", "from_status", "to_status", "trigger"], name="tasks_rule_unique"
            ),
        ]
