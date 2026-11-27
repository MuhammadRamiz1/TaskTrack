"""Task attachments.

Files are stored through Django's default storage under a tenant-prefixed key
(``companies/<company>/tasks/<task>/<attachment>/<name>``): the local media volume when
USE_S3=false, a private S3 bucket when USE_S3=true. Files are never served by a URL
route; the download endpoint streams them after a permission check.

Validation: size limit, company storage quota, an allow-list by extension, and a
content sniff of the first bytes that must match the extension (so a renamed HTML or
executable file is rejected). SVG and HTML are never accepted.
"""

import hashlib
import os
import uuid

from django.conf import settings
from django.core.files.storage import default_storage
from django.db import transaction
from django.db.models import F
from django.utils.text import get_valid_filename

from apps.audit.services import record
from apps.common.exceptions import DomainError, Forbidden, InvalidInput, NotFound
from apps.companies.models import Company
from apps.rbac import policy

from ..models import TaskAttachment
from . import activity
from .tasks import ensure_editable, get_task

ZIP_MAGIC = b"PK\x03\x04"
# extension -> (content type, sniff kind)
ALLOWED = {
    ".png": ("image/png", "png"),
    ".jpg": ("image/jpeg", "jpeg"),
    ".jpeg": ("image/jpeg", "jpeg"),
    ".gif": ("image/gif", "gif"),
    ".webp": ("image/webp", "webp"),
    ".pdf": ("application/pdf", "pdf"),
    ".txt": ("text/plain", "text"),
    ".log": ("text/plain", "text"),
    ".csv": ("text/csv", "text"),
    ".md": ("text/markdown", "text"),
    ".json": ("application/json", "text"),
    ".docx": ("application/vnd.openxmlformats-officedocument.wordprocessingml.document", "zip"),
    ".xlsx": ("application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", "zip"),
    ".pptx": ("application/vnd.openxmlformats-officedocument.presentationml.presentation", "zip"),
    ".zip": ("application/zip", "zip"),
}


class FileTooLarge(DomainError):
    status_code = 413
    code = "file_too_large"


def sniff(head: bytes) -> str:
    if head.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if head.startswith(b"\xff\xd8\xff"):
        return "jpeg"
    if head[:6] in (b"GIF87a", b"GIF89a"):
        return "gif"
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return "webp"
    if head.startswith(b"%PDF-"):
        return "pdf"
    if head.startswith(ZIP_MAGIC):
        return "zip"
    if b"\x00" not in head:
        try:
            text = head.decode("utf-8")
        except UnicodeDecodeError:
            # A multi-byte character may be cut at the end of the sample.
            try:
                text = head[:-3].decode("utf-8")
            except UnicodeDecodeError:
                return "binary"
        lowered = text.lstrip().lower()
        if lowered.startswith(("<!doctype html", "<html", "<svg", "<?xml", "<script")):
            return "markup"
        return "text"
    return "binary"


def _safe_name(name: str) -> str:
    base, ext = os.path.splitext(os.path.basename(name or "file"))
    base = get_valid_filename(base)[:120] or "file"
    return f"{base}{ext.lower()}"


def upload(*, actor, task_id, uploaded_file, comment=None) -> TaskAttachment:
    task = get_task(actor, task_id)
    policy.require(actor, "task.attachment.upload", task)
    ensure_editable(task)

    filename = _safe_name(uploaded_file.name)
    ext = os.path.splitext(filename)[1]
    if ext not in ALLOWED:
        raise InvalidInput(details={"file": [f"Files of type '{ext or 'unknown'}' are not allowed."]})
    content_type, expected_kind = ALLOWED[ext]
    max_bytes = settings.ATTACHMENT_MAX_MB * 1024 * 1024
    if uploaded_file.size > max_bytes:
        raise FileTooLarge(f"Files may be at most {settings.ATTACHMENT_MAX_MB} MB.")
    if uploaded_file.size == 0:
        raise InvalidInput(details={"file": ["The file is empty."]})

    uploaded_file.seek(0)
    head = uploaded_file.read(2048)
    if sniff(head) != expected_kind:
        raise InvalidInput(details={"file": ["The file content does not match its extension."]})

    digest = hashlib.sha256()
    uploaded_file.seek(0)
    for chunk in uploaded_file.chunks():
        digest.update(chunk)
    uploaded_file.seek(0)

    with transaction.atomic():
        company = Company.objects.select_for_update().get(pk=task.company_id)
        if company.storage_used_bytes + uploaded_file.size > company.max_storage_mb * 1024 * 1024:
            raise DomainError(
                "The company has reached its storage limit.", code="storage_limit_exceeded", status_code=413
            )
        attachment_id = uuid.uuid4()
        key = f"companies/{task.company_id}/tasks/{task.pk}/{attachment_id}/{filename}"
        stored_key = default_storage.save(key, uploaded_file)
        try:
            attachment = TaskAttachment.objects.create(
                id=attachment_id,
                company_id=task.company_id,
                task=task,
                comment=comment,
                storage_key=stored_key,
                filename=filename,
                content_type=content_type,
                size_bytes=uploaded_file.size,
                sha256=digest.hexdigest(),
                uploaded_by=actor,
            )
            Company.objects.filter(pk=company.pk).update(
                storage_used_bytes=F("storage_used_bytes") + uploaded_file.size
            )
            activity.log(task, actor, "attachment_added", {"filename": filename})
            record(
                actor=actor,
                action="task.attachment.uploaded",
                entity=attachment,
                new_value={
                    "task_id": task.pk,
                    "filename": filename,
                    "size_bytes": uploaded_file.size,
                    "sha256": attachment.sha256,
                },
            )
        except Exception:
            default_storage.delete(stored_key)
            raise
    return attachment


def open_for_download(*, actor, task_id, attachment_id):
    task = get_task(actor, task_id)
    attachment = TaskAttachment.objects.filter(pk=attachment_id, task=task, status=TaskAttachment.State.ACTIVE).first()
    if attachment is None:
        raise NotFound()
    return attachment, default_storage.open(attachment.storage_key, "rb")


def delete(*, actor, task_id, attachment_id) -> None:
    with transaction.atomic():
        task = get_task(actor, task_id)
        ensure_editable(task)
        attachment = (
            TaskAttachment.objects.select_for_update()
            .filter(pk=attachment_id, task=task, status=TaskAttachment.State.ACTIVE)
            .first()
        )
        if attachment is None:
            raise NotFound()
        own = attachment.uploaded_by_id == actor.pk and policy.can(actor, "task.attachment.upload", task)
        if not own and not policy.can(actor, "task.attachment.delete", task):
            raise Forbidden("Only the uploader or a task manager can delete this file.")
        attachment.status = TaskAttachment.State.DELETED
        attachment.save(update_fields=["status", "updated_at"])
        Company.objects.filter(pk=task.company_id).update(
            storage_used_bytes=F("storage_used_bytes") - attachment.size_bytes
        )
        activity.log(task, actor, "attachment_removed", {"filename": attachment.filename})
        record(
            actor=actor,
            action="task.attachment.deleted",
            entity=attachment,
            old_value={"filename": attachment.filename, "size_bytes": attachment.size_bytes},
        )
        key = attachment.storage_key
        transaction.on_commit(lambda: default_storage.delete(key))
