"""Bulk employee import from a CSV or XLSX sheet.

Each valid row goes through ``employees.create`` with ``send_invite=True``, so every
check (permissions, seat limit, roles, audit) and the invite email are the same as
creating one employee by hand. Passwords are never generated or emailed: people set
their own through the invite link.
"""

from __future__ import annotations

import csv
import io
import re
from dataclasses import dataclass, field

from django.core.exceptions import ValidationError
from django.core.validators import validate_email
from django.db import transaction

from apps.audit.services import record
from apps.common.exceptions import DomainError, InvalidInput, Unprocessable
from apps.companies.services import seats_in_use
from apps.rbac import policy

from ..models import User
from . import employees

MAX_ROWS = 500
MAX_BYTES = 2 * 1024 * 1024
LIMITS = {"email": 254, "first_name": 100, "last_name": 100, "job_title": 120}
ALIASES = {
    "email": "email",
    "email_address": "email",
    "e_mail": "email",
    "first_name": "first_name",
    "firstname": "first_name",
    "name": "first_name",
    "last_name": "last_name",
    "lastname": "last_name",
    "surname": "last_name",
    "job_title": "job_title",
    "title": "job_title",
    "designation": "job_title",
}


@dataclass
class Row:
    row: int
    email: str = ""
    first_name: str = ""
    last_name: str = ""
    job_title: str = ""
    status: str = "ready"  # ready | error | created | failed
    errors: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "row": self.row,
            "email": self.email,
            "first_name": self.first_name,
            "last_name": self.last_name,
            "job_title": self.job_title,
            "status": self.status,
            "errors": self.errors,
        }


def _header(value) -> str:
    return ALIASES.get(re.sub(r"[^a-z0-9]+", "_", str(value or "").strip().lower()).strip("_"), "")


def _cell(value) -> str:
    return "" if value is None else str(value).strip()


def _read_table(uploaded) -> list[list]:
    if uploaded.size > MAX_BYTES:
        raise InvalidInput(details={"file": ["The file is larger than 2 MB."]})
    name = (uploaded.name or "").lower()
    data = uploaded.read()
    if name.endswith(".csv"):
        try:
            text = data.decode("utf-8-sig")
        except UnicodeDecodeError as exc:
            raise InvalidInput(details={"file": ["Save the CSV with UTF-8 encoding."]}) from exc
        return list(csv.reader(io.StringIO(text)))
    if name.endswith(".xlsx"):
        from openpyxl import load_workbook

        try:
            book = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
        except Exception as exc:  # openpyxl raises several unrelated types for bad files
            raise InvalidInput(details={"file": ["This is not a readable Excel file."]}) from exc
        try:
            return [list(r) for r in book.worksheets[0].iter_rows(values_only=True)]
        finally:
            book.close()
    raise InvalidInput(details={"file": ["Upload a .xlsx or .csv file."]})


def _first_name_from(email: str) -> str:
    local = email.split("@", 1)[0]
    part = next((p for p in re.split(r"[._\-+0-9]+", local) if p), local)
    return part[:1].upper() + part[1:]


def parse(uploaded) -> list[Row]:
    table = [r for r in _read_table(uploaded) if any(_cell(c) for c in r)]
    if not table:
        raise InvalidInput(details={"file": ["The sheet is empty."]})
    columns = [_header(h) for h in table[0]]
    if "email" not in columns:
        raise InvalidInput(details={"file": ["The first row must have an 'email' column."]})
    body = table[1:]
    if not body:
        raise InvalidInput(details={"file": ["The sheet has no rows below the header."]})
    if len(body) > MAX_ROWS:
        raise InvalidInput(details={"file": [f"At most {MAX_ROWS} rows per import."]})

    rows, seen = [], set()
    for i, values in enumerate(body, start=2):  # spreadsheet row numbers, header is row 1
        row = Row(row=i)
        for col, value in zip(columns, values, strict=False):
            if col and not getattr(row, col):
                setattr(row, col, _cell(value))
        row.email = row.email.lower()
        try:
            validate_email(row.email)
        except ValidationError:
            row.errors.append("Invalid email address." if row.email else "Email is missing.")
        if row.email and row.email in seen:
            row.errors.append("Duplicate email in this sheet.")
        seen.add(row.email)
        if not row.first_name and not row.errors:
            row.first_name = _first_name_from(row.email)
        for name, limit in LIMITS.items():
            if len(getattr(row, name)) > limit:
                row.errors.append(f"{name.replace('_', ' ').capitalize()} is longer than {limit} characters.")
        rows.append(row)

    candidates = [r.email for r in rows if not r.errors]
    existing = set(User.objects.filter(email__in=candidates).values_list("email", flat=True))
    for row in rows:
        if row.email in existing:
            row.errors.append("An employee with this email already exists.")
        if row.errors:
            row.status = "error"
    return rows


def _summary(actor: User, rows: list[Row]) -> dict:
    company = actor.company
    counts = {s: sum(r.status == s for r in rows) for s in ("ready", "error", "created", "failed")}
    return {
        "total": len(rows),
        **counts,
        "seats_available": max(company.max_users - seats_in_use(company), 0),
    }


def preview(*, actor: User, uploaded) -> dict:
    policy.require(actor, "employee.create")
    policy.require(actor, "employee.invite")
    rows = parse(uploaded)
    return {"summary": _summary(actor, rows), "rows": [r.as_dict() for r in rows]}


def run(*, actor: User, uploaded) -> dict:
    """Create every valid row; invalid rows are reported and skipped."""
    policy.require(actor, "employee.create")
    policy.require(actor, "employee.invite")
    rows = parse(uploaded)
    ready = [r for r in rows if r.status == "ready"]
    company = actor.company
    free = company.max_users - seats_in_use(company)
    if len(ready) > free:
        raise Unprocessable(
            f"Only {max(free, 0)} seats are free on the company plan, but the sheet has {len(ready)} new employees.",
            code="user_limit_exceeded",
            details={"max_users": company.max_users, "seats_available": max(free, 0), "requested": len(ready)},
        )
    for row in ready:
        data = {
            "email": row.email,
            "first_name": row.first_name,
            "last_name": row.last_name,
            "job_title": row.job_title,
            "send_invite": True,
        }
        try:
            with transaction.atomic():
                employees.create(actor=actor, data=data)
            row.status = "created"
        except DomainError as exc:
            row.status = "failed"
            row.errors.append(_message(exc))

    summary = _summary(actor, rows)
    record(
        actor=actor,
        action="employee.imported",
        entity=company,
        new_value={k: summary[k] for k in ("total", "created", "failed", "error")},
    )
    return {"summary": summary, "rows": [r.as_dict() for r in rows]}


def _message(exc: DomainError) -> str:
    details = getattr(exc, "details", None)
    if isinstance(details, dict):
        flat = [str(m) for msgs in details.values() for m in (msgs if isinstance(msgs, list) else [msgs])]
        if flat:
            return " ".join(flat)
    return str(getattr(exc, "message", "") or exc)
