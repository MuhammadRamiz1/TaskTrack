from django.conf import settings
from django.db import models

from apps.common.models import TenantModel


class TaskReview(TenantModel):
    """One review round of a task. Decided rows are never modified (history)."""

    class Decision(models.TextChoices):
        PENDING = "PENDING", "Pending"
        APPROVED = "APPROVED", "Approved"
        CHANGES_REQUESTED = "CHANGES_REQUESTED", "Changes requested"

    task = models.ForeignKey("tasks.Task", on_delete=models.CASCADE, related_name="reviews")
    round = models.PositiveIntegerField()
    submitted_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    submitted_at = models.DateTimeField(auto_now_add=True)
    submission_note = models.TextField(blank=True)
    reviewer = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="assigned_reviews")
    decision = models.CharField(max_length=18, choices=Decision.choices, default=Decision.PENDING)
    decided_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    comment = models.TextField(blank=True)
    decided_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["round"]
        constraints = [
            models.UniqueConstraint(fields=["task", "round"], name="reviews_round_unique"),
            models.UniqueConstraint(
                fields=["task"], condition=models.Q(decision="PENDING"), name="reviews_one_pending_per_task"
            ),
        ]
        indexes = [models.Index(fields=["reviewer", "decision"], name="reviews_reviewer_decision")]
