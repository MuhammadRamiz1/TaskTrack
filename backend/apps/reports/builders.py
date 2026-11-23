"""Render a report table as CSV, XLSX or PDF bytes."""

import csv
import io
from datetime import date, datetime

from django.utils import timezone

CONTENT_TYPES = {
    "csv": "text/csv",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "pdf": "application/pdf",
}
FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")


def _cell(value):
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    return value


def _safe_text(value):
    """Neutralise spreadsheet formula injection in user-controlled text (names, titles)."""
    if isinstance(value, str) and value.startswith(FORMULA_PREFIXES):
        return "'" + value
    return value


def to_csv(columns, rows, **_) -> bytes:
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(columns)
    for row in rows:
        writer.writerow([_safe_text(_cell(v)) for v in row])
    return buffer.getvalue().encode("utf-8-sig")  # BOM so Excel opens UTF-8 correctly


def to_xlsx(columns, rows, *, title: str, subtitle: str) -> bytes:
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill

    wb = Workbook()
    ws = wb.active
    ws.title = title[:31]
    ws.append([title])
    ws["A1"].font = Font(bold=True, size=14, color="5B3FB0")
    ws.append([subtitle])
    ws.append([])
    ws.append(columns)
    header_fill = PatternFill("solid", fgColor="EDE7FB")
    for cell in ws[4]:
        cell.font = Font(bold=True)
        cell.fill = header_fill
    for row in rows:
        ws.append([_safe_text(_cell(v)) for v in row])
    for idx, column in enumerate(columns, start=1):
        width = max([len(str(column))] + [len(str(_cell(r[idx - 1]))) for r in rows]) + 2
        ws.column_dimensions[ws.cell(row=4, column=idx).column_letter].width = min(width, 60)
    ws.freeze_panes = "A5"
    out = io.BytesIO()
    wb.save(out)
    return out.getvalue()


def to_pdf(columns, rows, *, title: str, subtitle: str) -> bytes:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    out = io.BytesIO()
    doc = SimpleDocTemplate(
        out, pagesize=landscape(A4), title=title, leftMargin=36, rightMargin=36, topMargin=36, bottomMargin=36
    )
    styles = getSampleStyleSheet()
    table = Table(
        [columns] + [[str(_cell(v)) for v in r] for r in rows] if rows else [columns, ["No data"]], repeatRows=1
    )
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#EDE7FB")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.HexColor("#3B2A78")),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#D8CFF2")),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#FAF8FE")]),
                ("FONTSIZE", (0, 0), (-1, -1), 9),
            ]
        )
    )
    doc.build(
        [
            Paragraph(title, styles["Title"]),
            Paragraph(subtitle, styles["Normal"]),
            Spacer(1, 12),
            table,
        ]
    )
    return out.getvalue()


RENDERERS = {"csv": to_csv, "xlsx": to_xlsx, "pdf": to_pdf}


def render(fmt: str, columns, rows, *, title: str, subtitle: str = "") -> bytes:
    subtitle = subtitle or f"Generated {timezone.now():%Y-%m-%d %H:%M} UTC"
    return RENDERERS[fmt](columns, rows, title=title, subtitle=subtitle)
