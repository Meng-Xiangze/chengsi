"""Shared CSV/XLSX parsing, rendering, writing, and cell editing helpers."""

from __future__ import annotations

import csv
import io
from pathlib import Path
from typing import Any

from core.process_utils import optional_import


def read_csv(path: Path, offset: int = 1, limit: int = 200) -> str:
    with path.open("r", encoding="utf-8-sig", errors="replace", newline="") as handle:
        rows = list(csv.reader(handle))
    return render_rows(path.name, rows, offset, limit)


def read_xlsx(path: Path, offset: int = 1, limit: int = 200, sheet_name: str | None = None) -> str:
    try:
        openpyxl = optional_import("openpyxl", "openpyxl")
    except ImportError as error:
        return f"XLSX support requires openpyxl. Enable automatic dependency installation in Settings or run: pip install openpyxl\n{error}"
    workbook = openpyxl.load_workbook(path, read_only=True, data_only=False)
    try:
        all_sheets = [(ws.title, ws.max_row) for ws in workbook.worksheets]

        if sheet_name:
            # ── Specific sheet requested ──────────────────────────
            for ws in workbook.worksheets:
                if ws.title == sheet_name:
                    rows = [["" if value is None else str(value) for value in row]
                            for row in ws.iter_rows(values_only=True)]
                    return render_rows(f"{path.name} :: {sheet_name}", rows, offset, limit)
            return f"Error: sheet '{sheet_name}' not found in {path.name}. Available sheets: {', '.join(s[0] for s in all_sheets)}"

        # ── No sheet specified: show index + first sheet data ─────
        lines = [f"📊 {path.name} — {len(all_sheets)} sheet(s):"]
        for name, rows in all_sheets:
            lines.append(f"  • {name}  ({rows} rows)")
        lines.append("")

        if all_sheets:
            first_name = all_sheets[0][0]
            lines.append(f"Showing first sheet: {first_name}")
            for ws in workbook.worksheets:
                if ws.title == first_name:
                    rows = [["" if value is None else str(value) for value in row]
                            for row in ws.iter_rows(values_only=True)]
                    lines.append(render_rows(f"{path.name} :: {first_name}", rows, offset, limit))
                    break
            if len(all_sheets) > 1:
                other_names = [s[0] for s in all_sheets[1:]]
                lines.append(f"\n💡 Other sheets: {', '.join(other_names)}. Use sheet_name= to select.")

        return "\n".join(lines)
    finally:
        workbook.close()


def render_rows(label: str, rows: list[list[str]], offset: int, limit: int) -> str:
    start = max(1, int(offset or 1))
    count = max(1, min(int(limit or 200), 1000))
    if rows:
        start = min(start, len(rows))
    selected = rows[start - 1:start - 1 + count]
    output = [f"# {label} ({len(rows)} rows)", "[format: ROW | comma-separated cells]"]
    for number, row in enumerate(selected, start=start):
        stream = io.StringIO()
        csv.writer(stream, lineterminator="").writerow(row)
        output.append(f"{number} | {stream.getvalue()}")
    if start - 1 + count < len(rows):
        output.append(
            f"⏩ {len(rows) - (start - 1 + count)} more rows — "
            f"read the rest with offset={start + count} before judging the task."
        )
    else:
        output.append("✅ End of table reached.")
    return "\n".join(output)


def parse_content(content: str) -> list[tuple[str, list[list[str]]]]:
    """Parse CSV text, with optional `[Sheet: name]` sections for XLSX."""
    sections: list[tuple[str, list[str]]] = []
    current_name = "Sheet1"
    current_lines: list[str] = []
    for line in content.splitlines():
        stripped = line.strip()
        if stripped.lower().startswith("[sheet:") and stripped.endswith("]"):
            if current_lines or sections:
                sections.append((current_name, current_lines))
            current_name = stripped[7:-1].strip() or f"Sheet{len(sections) + 1}"
            current_lines = []
        else:
            current_lines.append(line)
    sections.append((current_name, current_lines))
    parsed = []
    for name, lines in sections:
        rows = list(csv.reader(lines)) if lines else []
        parsed.append((name, rows))
    return parsed


def write_csv(path: Path, content: str) -> str:
    sections = parse_content(content)
    rows = sections[0][1]
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        csv.writer(handle).writerows(rows)
    return f"Written {path} ({len(rows)} rows)"


def write_xlsx(path: Path, content: str) -> str:
    try:
        openpyxl = optional_import("openpyxl", "openpyxl")
    except ImportError as error:
        return f"XLSX support requires openpyxl. Enable automatic dependency installation in Settings or run: pip install openpyxl\n{error}"
    workbook = openpyxl.Workbook()
    workbook.remove(workbook.active)
    sections = parse_content(content)
    used: set[str] = set()
    row_count = 0
    for index, (name, rows) in enumerate(sections, start=1):
        safe_name = (name or f"Sheet{index}")[:31]
        base = safe_name
        suffix = 2
        while safe_name in used:
            safe_name = f"{base[:28]}_{suffix}"
            suffix += 1
        used.add(safe_name)
        sheet = workbook.create_sheet(safe_name)
        for row in rows:
            sheet.append(row)
            row_count += 1
    workbook.save(path)
    return f"Written {path} ({len(sections)} sheet(s), {row_count} rows)"


def edit_csv(path: Path, edits: list[dict]) -> str:
    with path.open("r", encoding="utf-8-sig", errors="replace", newline="") as handle:
        rows = list(csv.reader(handle))
    changed = _edit_cells([("CSV", rows)], edits)
    if isinstance(changed, str):
        return changed
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        csv.writer(handle).writerows(rows)
    return f"Edited {path}: {changed} cell(s) changed."


def edit_xlsx(path: Path, edits: list[dict]) -> str:
    try:
        openpyxl = optional_import("openpyxl", "openpyxl")
    except ImportError as error:
        return f"XLSX support requires openpyxl. Enable automatic dependency installation in Settings or run: pip install openpyxl\n{error}"
    workbook = openpyxl.load_workbook(path)
    sheets = []
    for sheet in workbook.worksheets:
        rows = [[cell.value for cell in row] for row in sheet.iter_rows()]
        sheets.append((sheet.title, rows))
    changed = _edit_cells(sheets, edits)
    if isinstance(changed, str):
        workbook.close()
        return changed
    for sheet_name, rows in sheets:
        sheet = workbook[sheet_name]
        for row_index, row in enumerate(rows, start=1):
            for column_index, value in enumerate(row, start=1):
                sheet.cell(row_index, column_index).value = value
    workbook.save(path)
    workbook.close()
    return f"Edited {path}: {changed} cell(s) changed."


def _edit_cells(sheets: list[tuple[str, list[list[Any]]]], edits: list[dict]) -> int | str:
    pending = []
    for index, edit in enumerate(edits):
        op = edit.get("op", "replace")
        if op not in ("replace", "delete"):
            return f"Error: spreadsheet edits[{index}] supports only replace or delete."
        old = str(edit.get("oldText", ""))
        matches = []
        for sheet_name, rows in sheets:
            for row_index, row in enumerate(rows):
                for column_index, value in enumerate(row):
                    if str("" if value is None else value) == old:
                        matches.append((sheet_name, row_index, column_index, row))
        if len(matches) != 1:
            return f"Error: edits[{index}] oldText must match exactly one cell; found {len(matches)} matches for {old!r}."
        pending.append((matches[0][3], matches[0][2], "" if op == "delete" else edit.get("newText", "")))
    for row, column_index, value in pending:
        row[column_index] = value
    return len(pending)
