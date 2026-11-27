"""Bulk employee import from CSV/XLSX: preview, create with invite links, limits and rights."""

import io

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from openpyxl import Workbook

from apps.accounts.models import User
from apps.audit.models import AuditLog
from tests import factories as f

IMPORT = "/api/v1/hr/employees/import/"
PREVIEW = "/api/v1/hr/employees/import/preview/"


@pytest.fixture
def hr(company_a):
    return f.make_user(company_a, "HR", email="hr@acme.test")


def csv_file(text: str, name: str = "people.csv") -> SimpleUploadedFile:
    return SimpleUploadedFile(name, text.encode("utf-8"), content_type="text/csv")


def xlsx_file(rows: list[list]) -> SimpleUploadedFile:
    book = Workbook()
    for r in rows:
        book.active.append(r)
    buf = io.BytesIO()
    book.save(buf)
    return SimpleUploadedFile(
        "people.xlsx", buf.getvalue(), content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )


SHEET = (
    "Email,First Name,Last Name,Job Title\n"
    "Ali.Khan@acme.test,,,Developer\n"
    "sara@acme.test,Sara,Malik,QA\n"
    "not-an-email,Bad,,\n"
    "sara@acme.test,Sara,Again,\n"
    "hr@acme.test,Existing,,\n"
)


def post(client, url, upload):
    return client.post(url, {"file": upload}, format="multipart")


class TestPreview:
    def test_reports_each_row_without_creating(self, hr):
        before = User.objects.count()
        response = post(f.client_for(hr), PREVIEW, csv_file(SHEET))
        assert response.status_code == 200
        body = response.json()
        rows = {r["row"]: r for r in body["rows"]}
        assert rows[2]["status"] == "ready" and rows[2]["email"] == "ali.khan@acme.test"
        assert rows[2]["first_name"] == "Ali" and rows[2]["job_title"] == "Developer"
        assert rows[3]["status"] == "ready"
        assert rows[4]["errors"] == ["Invalid email address."]
        assert rows[5]["errors"] == ["Duplicate email in this sheet."]
        assert rows[6]["errors"] == ["An employee with this email already exists."]
        assert body["summary"]["ready"] == 2 and body["summary"]["error"] == 3 and body["summary"]["total"] == 5
        assert User.objects.count() == before

    def test_bad_files(self, hr):
        client = f.client_for(hr)
        assert post(client, PREVIEW, csv_file("name\nAli\n")).status_code == 400
        assert post(client, PREVIEW, csv_file("email\n")).status_code == 400
        assert post(client, PREVIEW, csv_file("email\na@acme.test\n", name="people.txt")).status_code == 400
        assert client.post(PREVIEW, {}, format="multipart").status_code == 400


class TestImport:
    def test_creates_valid_rows_and_sends_invites(self, hr, mailbox):
        with mailbox():
            response = post(f.client_for(hr), IMPORT, csv_file(SHEET))
        assert response.status_code == 200
        body = response.json()
        assert body["summary"]["created"] == 2 and body["summary"]["error"] == 3 and body["summary"]["failed"] == 0
        ali = User.objects.get(email="ali.khan@acme.test")
        assert ali.status == User.Status.INVITED and ali.first_name == "Ali" and not ali.has_usable_password()
        assert list(ali.user_roles.values_list("role__key", flat=True)) == ["TEAM_MEMBER"]
        assert sorted(m.to[0] for m in mailbox.outbox) == ["ali.khan@acme.test", "sara@acme.test"]
        assert all("accept-invite" in m.body for m in mailbox.outbox)
        assert AuditLog.objects.filter(action="employee.imported").exists()
        assert AuditLog.objects.filter(action="employee.created").count() == 2

    def test_xlsx(self, hr, mailbox):
        upload = xlsx_file([["email", "first_name"], ["new.one@acme.test", "New"], [None, None]])
        with mailbox():
            response = post(f.client_for(hr), IMPORT, upload)
        assert response.status_code == 200 and response.json()["summary"]["created"] == 1
        assert User.objects.get(email="new.one@acme.test").first_name == "New"

    def test_seat_limit_blocks_whole_import(self, hr, company_a):
        company_a.max_users_override = User.objects.filter(company=company_a).count() + 1
        company_a.save()
        response = post(f.client_for(hr), IMPORT, csv_file("email\na@acme.test\nb@acme.test\n"))
        assert response.status_code == 422 and response.json()["error"]["code"] == "user_limit_exceeded"
        assert not User.objects.filter(email__in=["a@acme.test", "b@acme.test"]).exists()

    def test_company_admin_can_import(self, company_a, mailbox):
        admin = f.make_user(company_a, "COMPANY_ADMIN")
        with mailbox():
            response = post(f.client_for(admin), IMPORT, csv_file("email\nfrom.admin@acme.test\n"))
        assert response.status_code == 200 and response.json()["summary"]["created"] == 1

    def test_others_are_forbidden(self, company_a):
        for key in ("TEAM_MEMBER", "MANAGER", "TEAM_LEAD"):
            client = f.client_for(f.make_user(company_a, key))
            assert post(client, IMPORT, csv_file("email\nx@acme.test\n")).status_code == 403
            assert post(client, PREVIEW, csv_file("email\nx@acme.test\n")).status_code == 403
        assert not User.objects.filter(email="x@acme.test").exists()
