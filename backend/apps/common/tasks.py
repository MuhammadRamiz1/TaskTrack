"""Celery base task and the templated email task."""

import structlog
from celery import Task, shared_task
from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.template import TemplateDoesNotExist
from django.template.loader import render_to_string

from . import tenancy

logger = structlog.get_logger(__name__)


class TenantTask(Task):
    """Runs the task body inside the tenant (or platform) context named by the
    ``company_id`` keyword argument. ``company_id=None`` means platform context."""

    abstract = True
    autoretry_for = (ConnectionError, TimeoutError)
    retry_backoff = True
    retry_kwargs = {"max_retries": 5}

    def __call__(self, *args, **kwargs):
        company_id = kwargs.get("company_id")
        with tenancy.context_for_company(company_id):
            return super().__call__(*args, **kwargs)


@shared_task(name="common.send_templated_email", bind=True, autoretry_for=(OSError,), retry_backoff=True, max_retries=5)
def send_templated_email(self, *, template: str, to: str, context: dict) -> None:
    """Render ``templates/email/<template>.txt`` (+ optional ``.html``) and send it."""
    context = {"product_name": "TaskTrack", "web_origin": settings.WEB_ORIGIN, **context}
    subject = render_to_string(f"email/{template}.subject.txt", context).strip()
    text = render_to_string(f"email/{template}.txt", context)
    message = EmailMultiAlternatives(subject=subject, body=text, to=[to])
    try:
        message.attach_alternative(render_to_string(f"email/{template}.html", context), "text/html")
    except TemplateDoesNotExist:
        logger.debug("email.no_html_part", template=template)  # plain-text only template
    message.send()
    logger.info("email.sent", template=template)


#: (model label, child field, parent path) pairs whose company must match.
INTEGRITY_CHECKS = [
    ("tasks.Task", "project__company_id"),
    ("tasks.TaskAssignee", "task__company_id"),
    ("tasks.TaskAssignee", "user__company_id"),
    ("tasks.TaskDependency", "blocked_by__company_id"),
    ("tasks.TaskComment", "task__company_id"),
    ("tasks.TaskAttachment", "task__company_id"),
    ("org.Project", "team__company_id"),
    ("org.TeamMember", "user__company_id"),
    ("org.ProjectMember", "user__company_id"),
    ("rbac.UserRole", "user__company_id"),
    ("rbac.UserRole", "role__company_id"),
    ("timetracking.TimeEntry", "task__company_id"),
    ("timetracking.TimeEntry", "user__company_id"),
    ("reviews.TaskReview", "task__company_id"),
]


@shared_task(name="common.verify_tenant_integrity")
def verify_tenant_integrity() -> dict:
    """Nightly: find rows whose related rows belong to a different company. Services make
    this impossible; the job proves it and alerts (error log -> Sentry) if not."""
    from django.apps import apps
    from django.db.models import F

    from . import tenancy

    problems = {}
    with tenancy.platform_context():
        for label, path in INTEGRITY_CHECKS:
            model = apps.get_model(label)
            count = model._base_manager.exclude(**{path: F("company_id")}).count()
            if count:
                problems[f"{label}.{path}"] = count
    if problems:
        logger.error("tenant_integrity.violations", problems=problems)
    return problems
