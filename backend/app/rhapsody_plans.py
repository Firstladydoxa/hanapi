"""The 1-year and 2-year Bible reading plans are not in the Word manuscript; admins add them in InDesign each month.
HAN gives them a spreadsheet to fill in (one row per day) and reads it back."""
from __future__ import annotations

import csv
import io
from calendar import monthrange
from datetime import date
from typing import Dict, List, Tuple

HEADERS = ["Day", "Weekday", "Date", "1-Year Bible Reading Plan", "2-Year Bible Reading Plan"]


class PlanFileError(ValueError):
    pass


def build_template(year: int, month: int, existing: Dict[int, Tuple[str, str]] | None = None) -> bytes:
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.worksheet.protection import SheetProtection

    existing = existing or {}
    wb = Workbook()
    ws = wb.active
    ws.title = "Reading plans"
    ws.append(HEADERS)
    for c in ws[1]:
        c.font = Font(bold=True, color="FFFFFF")
        c.fill = PatternFill("solid", fgColor="222222")
        c.alignment = Alignment(wrap_text=True, vertical="center")
    for day in range(1, monthrange(year, month)[1] + 1):
        d = date(year, month, day)
        p1, p2 = existing.get(day, ("", ""))
        ws.append([day, d.strftime("%A"), d.isoformat(), p1, p2])
    for col, w in zip("ABCDE", (7, 13, 12, 46, 46)):
        ws.column_dimensions[col].width = w
    ws.freeze_panes = "A2"
    for row in ws.iter_rows(min_row=2, max_col=3):
        for c in row:
            c.fill = PatternFill("solid", fgColor="EEEEEE")
    guide = wb.create_sheet("Instructions")
    for line in (
        f"Rhapsody of Realities - {date(year, month, 1).strftime('%B %Y')} - Bible reading plans",
        "",
        "1. Fill the two last columns of the 'Reading plans' sheet, one row per day.",
        "2. Write the passages exactly as they should be printed, for example: Genesis 1:1-2:25; Psalm 1:1-6",
        "3. Do not change the Day column or the header row; HAN reads the day number to place each line.",
        "4. Leave a cell empty if a day has no reading; HAN will flag it.",
        "5. Save as .xlsx (or .csv, UTF-8) and upload it on the edition page under 'Bible reading plans'.",
        "6. Uploading again replaces the previous plans and HAN rebuilds the master as a new version.",
    ):
        guide.append([line])
    guide.column_dimensions["A"].width = 100
    guide["A1"].font = Font(bold=True, size=13)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _rows(data: bytes, filename: str) -> List[List[str]]:
    if data[:2] == b"PK":
        from openpyxl import load_workbook
        try:
            ws = load_workbook(io.BytesIO(data), read_only=True, data_only=True).worksheets[0]
            return [["" if v is None else str(v).strip() for v in row] for row in ws.iter_rows(values_only=True)]
        except Exception as exc:
            raise PlanFileError("The spreadsheet could not be read.") from exc
    if filename.lower().endswith((".xls", ".doc")) or data[:4] == b"\xd0\xcf\x11\xe0":
        raise PlanFileError("Old .xls files are not supported. Save the sheet as .xlsx or .csv and upload again.")
    for enc in ("utf-8-sig", "cp1252"):
        try:
            text = data.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    else:
        raise PlanFileError("The file is not a readable spreadsheet.")
    sample = text[:2000]
    delim = ";" if sample.count(";") > sample.count(",") and sample.count(";") > sample.count("\t") else ("\t" if "\t" in sample and "," not in sample else ",")
    return [[c.strip() for c in row] for row in csv.reader(io.StringIO(text), delimiter=delim)]


def parse_plans(data: bytes, filename: str, year: int, month: int) -> Tuple[Dict[int, Tuple[str, str]], List[str]]:
    rows = _rows(data, filename)
    head = next((i for i, r in enumerate(rows) if r and r[0].lower().startswith("day")), None)
    if head is None:
        raise PlanFileError("The first column must be 'Day'. Please use the template HAN provides.")
    cols = [h.lower() for h in rows[head]]
    c1 = next((i for i, h in enumerate(cols) if "1" in h and "year" in h), None)
    c2 = next((i for i, h in enumerate(cols) if "2" in h and "year" in h), None)
    if c1 is None or c2 is None:
        raise PlanFileError("The '1-Year Bible Reading Plan' and '2-Year Bible Reading Plan' columns were not found.")
    last = monthrange(year, month)[1]
    plans: Dict[int, Tuple[str, str]] = {}
    warnings: List[str] = []
    for r in rows[head + 1:]:
        try:
            day = int(float(r[0]))
        except (ValueError, IndexError):
            continue
        if not 1 <= day <= last:
            warnings.append(f"Row for day {day} ignored: this month has {last} days.")
            continue
        get = lambda i: " ".join(r[i].split()) if i < len(r) else ""
        if get(c1) or get(c2):
            plans[day] = (get(c1), get(c2))
    if not any(a or b for a, b in plans.values()):
        raise PlanFileError("The file has no reading plans filled in.")
    empty = [d for d in range(1, last + 1) if d not in plans or not (plans[d][0] and plans[d][1])]
    if empty:
        warnings.append("Missing 1-year or 2-year readings for days: " + ", ".join(map(str, empty)))
    return plans, warnings
