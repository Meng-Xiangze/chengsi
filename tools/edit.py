# -*- coding: utf-8 -*-
"""Edit tool — precise file editing with exact-text anchors.

For text files: replace, insert, delete, prepend, append.
For .docx: find paragraph by text, replace with formatting markers."""

import os
import re
from pathlib import Path
from typing import Any

from tools.base import BaseTool
from tools._spreadsheet import edit_csv, edit_xlsx

_VALID_OPS = {"replace", "delete", "insert_before", "insert_after", "prepend", "append"}
_OP_ALIASES = {"add_before": "insert_before", "add_after": "insert_after", "remove": "delete"}


class Edit(BaseTool):
    """Surgical file editing with exact-text anchors."""

    @property
    def tool_name(self) -> str:
        return "edit"

    @property
    def description(self) -> str:
        return (
            "Precise file editing with exact-text anchors. "
            "Operations: replace (default), insert_before, insert_after, delete, prepend, append. "
            "Aliases: remove=delete, add_before=insert_before, add_after=insert_after. "
            "For CSV/XLSX: oldText must match one complete cell and replace/delete edits are supported. "
            "For .docx: matches paragraph text; newText supports **bold** *italic* ^super^ _sub_ "
            "{size:N} {color:...} markers. "
            "Multiple edits applied atomically; overlapping edits rejected."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "path": {
                "type": "string",
                "description": "File path to edit.",
            },
            "edits": {
                "type": "array",
                "description": (
                    "List of edits. Each: {oldText: 'anchor text', newText: 'replacement', op: 'replace'}. "
                    "op defaults to 'replace'. prepend/append need no oldText. "
                    "delete needs no newText. "
                    "oldText must be unique and non-overlapping. "
                    "For CSV/XLSX: oldText matches one complete cell; use replace or delete. "
                    "For .docx: oldText matches paragraph text."
                ),
                "items": {
                    "type": "object",
                    "properties": {
                        "oldText": {
                            "type": "string",
                            "description": "Text to find (anchor). Must be unique. Not needed for prepend/append.",
                        },
                        "newText": {
                            "type": "string",
                            "description": "Replacement or inserted text. Not needed for delete.",
                        },
                        "op": {
                            "type": "string",
                            "enum": sorted(_VALID_OPS),
                            "description": "Operation. Default: replace.",
                        },
                    },
                },
            },
            "revision": {
                "type": "string",
                "description": "Optional. If set, edit is rejected when file content hash differs (stale-file guard).",
            },
        }

    # ------------------------------------------------------------------ #
    #  Entry
    # ------------------------------------------------------------------ #

    def run(self, arguments: dict[str, Any]) -> str:
        args = arguments or {}
        raw_path = str(args.get("path", "")).strip()
        raw_edits = args.get("edits", [])
        rev = str(args.get("revision", "")).strip() or None

        if not raw_path:
            return "Error: path is required."
        if not raw_edits or not isinstance(raw_edits, list):
            return "Error: edits must be a list of edit objects."

        path = Path(raw_path)
        if not path.exists():
            return f"Error: file not found: {path}"

        # Normalise operations
        edits: list[dict] = []
        for ei, e in enumerate(raw_edits):
            if not isinstance(e, dict):
                return f"Error: edits[{ei}] must be an object."
            op = str(e.get("op", "replace")).strip().lower()
            op = _OP_ALIASES.get(op, op)
            if op not in _VALID_OPS:
                return f"Error: edits[{ei}] invalid op {op!r}. Valid: {', '.join(sorted(_VALID_OPS))}."
            old = str(e.get("oldText", ""))
            new = str(e.get("newText", ""))
            if op not in ("prepend", "append") and not old:
                return f"Error: edits[{ei}] ({op}) requires oldText as anchor."
            if op == "delete":
                new = ""
            if op != "delete" and op not in ("prepend", "append") and not new:
                return f"Error: edits[{ei}] (replace) requires newText."
            edits.append({"op": op, "oldText": old, "newText": new})

        ext = path.suffix.lower()

        try:
            if ext == ".docx":
                return self._edit_docx(path, edits)
            if ext == ".csv":
                return edit_csv(path, edits)
            if ext == ".xlsx":
                return edit_xlsx(path, edits)
            return self._edit_text(path, edits, rev)
        except Exception as exc:
            return f"Error editing {path}: {exc}"

    def is_mutating(self, arguments: dict[str, Any]) -> bool:
        return True

    # ------------------------------------------------------------------ #
    #  Text-file engine
    # ------------------------------------------------------------------ #

    @staticmethod
    def _revision(text: str) -> str:
        """Short content hash for stale-file detection."""
        import hashlib
        return hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]

    @staticmethod
    def _edit_text(path: Path, edits: list[dict], rev: str | None) -> str:
        original = path.read_text(encoding="utf-8")
        text = original

        # Revision guard
        if rev and Edit._revision(original) != rev:
            return (
                f"Error: stale revision. File has changed since revision {rev}. "
                f"Re-read the file to get the current revision."
            )

        # Validate anchors: each oldText must exist exactly once
        # Track which edits need anchor validation
        anchors: list[tuple[int, str]] = []  # (edit_index, oldText)
        for ei, edit in enumerate(edits):
            if edit["op"] in ("prepend", "append"):
                continue
            old = edit["oldText"]
            count = text.count(old)
            if count == 0:
                return (
                    f"Error: edits[{ei}] oldText not found: {old[:120]!r}"
                )
            if count > 1:
                return (
                    f"Error: edits[{ei}] oldText appears {count} times — must be unique. "
                    f"Add more context."
                )

        # Compute spans for replace/delete/insert operations
        # Insert ops don't consume text, they just need a position
        spans: list[dict] = []  # {start, end, edit_index}
        for ei, edit in enumerate(edits):
            op = edit["op"]
            if op in ("prepend", "append"):
                continue
            old = edit["oldText"]
            start = text.index(old)
            if op == "delete":
                end = start + len(old)
            elif op == "replace":
                end = start + len(old)
            elif op == "insert_before":
                end = start  # insert at start position
            elif op == "insert_after":
                start = start + len(old)
                end = start
            spans.append({"start": start, "end": end, "ei": ei, "op": op})

        # Check for overlapping *consuming* edits (replace/delete)
        consuming = [s for s in spans if s["op"] in ("replace", "delete")]
        for i in range(len(consuming)):
            for j in range(i + 1, len(consuming)):
                a, b = consuming[i], consuming[j]
                if not (a["end"] <= b["start"] or b["end"] <= a["start"]):
                    return (
                        f"Error: edits[{a['ei']}] and edits[{b['ei']}] overlap. "
                        f"Merge them into a single edit."
                    )

        # Apply in reverse order (end-to-start) to preserve positions
        ordered = sorted(spans, key=lambda s: s["start"], reverse=True)
        changed = 0

        for s in ordered:
            edit = edits[s["ei"]]
            op = edit["op"]
            new = edit["newText"]
            if op == "replace":
                text = text[: s["start"]] + new + text[s["end"] :]
            elif op == "delete":
                text = text[: s["start"]] + text[s["end"] :]
            elif op == "insert_before":
                text = text[: s["start"]] + new + text[s["start"] :]
            elif op == "insert_after":
                text = text[: s["start"]] + new + text[s["start"] :]
            changed += 1

        # prepend / append
        for ei, edit in enumerate(edits):
            if edit["op"] == "prepend":
                text = edit["newText"] + text
                changed += 1
            elif edit["op"] == "append":
                text = text + edit["newText"]
                changed += 1

        path.write_text(text, encoding="utf-8")
        old_lines = original.count("\n") + 1
        new_lines = text.count("\n") + 1
        return (
            f"Edited {path}: {changed} operation(s). "
            f"Lines: {old_lines} → {new_lines}"
            + ("" if not rev else f" rev={Edit._revision(text)}")
        )

    # ------------------------------------------------------------------ #
    #  DOCX engine
    # ------------------------------------------------------------------ #

    @staticmethod
    def _strip_markers(text: str) -> str:
        """Strip inline formatting markers: **bold** → bold, _sub_ → sub, etc."""
        # Order matters: ** before *, _ before others
        text = re.sub(r'\*\*(.+?)\*\*', r'\1', text)
        text = re.sub(r'\*(.+?)\*', r'\1', text)
        text = re.sub(r'\^(.+?)\^', r'\1', text)
        text = re.sub(r'_(.+?)_', r'\1', text)
        return text

    @staticmethod
    def _body_idx(body, child) -> int:
        """Find the index of an lxml child element in the body. Returns -1 if not found."""
        for i, c in enumerate(body):
            if c is child:
                return i
        return -1

    @staticmethod
    def _edit_docx(path: Path, edits: list[dict]) -> str:
        try:
            from docx import Document
        except ImportError:
            return "DOCX editing requires python-docx. Install with:\n  pip install python-docx"

        from tools.write import Write
        from tools.read import Read
        from docx.oxml.ns import qn

        doc = Document(str(path))

        # Build a map: formatted_text → paragraph_element
        # Use the same formatter as read tool so models see consistent text
        para_map: dict[str, object] = {}  # formatted_text → paragraph
        para_list: list = []  # (formatted_text, paragraph)
        for block in doc.element.body:
            tag = block.tag.split("}")[-1] if "}" in block.tag else block.tag
            if tag == "p":
                formatted = Read._format_paragraph_xml(block, qn, -1)
                para_map[formatted.strip()] = block
                para_list.append((formatted.strip(), block))

        # Also build plain-text map for fallback
        plain_map: dict[str, object] = {}
        for para in doc.paragraphs:
            plain_map[para.text.strip()] = para._element

        found_count = 0
        for ei, edit in enumerate(edits):
            op = edit["op"]
            old = edit["oldText"].strip()
            new = edit["newText"]

            if op in ("prepend", "append"):
                # Insert paragraph at beginning or end
                if op == "prepend":
                    first = doc.element.body.find(
                        "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}p"
                    )
                    p_elem = doc.element.body.makeelement(
                        "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}p", {}
                    )
                    if first is not None:
                        idx = Edit._body_idx(doc.element.body, first)
                        doc.element.body.insert(idx, p_elem)
                    else:
                        doc.element.body.append(p_elem)
                    para = doc.paragraphs[0] if doc.paragraphs else doc.add_paragraph()
                    Write._add_formatted_run(para, new)
                else:
                    para = doc.add_paragraph()
                    Write._add_formatted_run(para, new)
                found_count += 1
                continue

            if op in ("replace", "delete", "insert_before", "insert_after"):
                # Try formatted-text match first (what model sees from read tool)
                # Then fall back to plain text (para.text)
                old_stripped = old.strip()
                matched_elem = para_map.get(old_stripped)
                if matched_elem is None:
                    matched_elem = plain_map.get(old_stripped)

                if matched_elem is None and op != "insert_before":
                    return f"Error: edits[{ei}] no paragraph matches: {old[:120]!r}"

                if op == "delete":
                    # Remove paragraph from document body
                    doc.element.body.remove(matched_elem)
                    found_count += 1
                elif op == "replace":
                    # Clear and rebuild — need the paragraph object, not just the element
                    # Find the python-docx Paragraph wrapping this element
                    target_para = None
                    for p in doc.paragraphs:
                        if p._element is matched_elem:
                            target_para = p
                            break
                    if target_para is not None:
                        target_para.clear()
                        Write._add_formatted_run(target_para, new)
                    else:
                        # Fallback: clear the element's runs manually
                        for r in matched_elem.findall(qn("w:r")):
                            matched_elem.remove(r)
                        # Add a temporary paragraph to get the run, then move it
                        temp_p = doc.add_paragraph()
                        Write._add_formatted_run(temp_p, new)
                        # Move runs from temp
                        for r in list(temp_p._element.findall(qn("w:r"))):
                            temp_p._element.remove(r)
                            matched_elem.append(r)
                        # Remove temp
                        doc.element.body.remove(temp_p._element)
                    found_count += 1
                elif op == "insert_before":
                    new_p = doc.element.body.makeelement(
                        "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}p", {}
                    )
                    idx = Edit._body_idx(doc.element.body, matched_elem)
                    if idx < 0:
                        return f"Error: edits[{ei}] cannot find anchor paragraph in document."
                    doc.element.body.insert(idx, new_p)
                    # Add formatted content to the new paragraph
                    # Use python-docx paragraph wrapping the new element
                    temp_para = doc.add_paragraph()
                    Write._add_formatted_run(temp_para, new)
                    # Move runs
                    for r in list(temp_para._element.findall(qn("w:r"))):
                        temp_para._element.remove(r)
                        new_p.append(r)
                    doc.element.body.remove(temp_para._element)
                    found_count += 1
                elif op == "insert_after":
                    new_p = doc.element.body.makeelement(
                        "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}p", {}
                    )
                    idx = Edit._body_idx(doc.element.body, matched_elem)
                    if idx < 0:
                        return f"Error: edits[{ei}] cannot find anchor paragraph in document."
                    doc.element.body.insert(idx + 1, new_p)
                    temp_para = doc.add_paragraph()
                    Write._add_formatted_run(temp_para, new)
                    for r in list(temp_para._element.findall(qn("w:r"))):
                        temp_para._element.remove(r)
                        new_p.append(r)
                    doc.element.body.remove(temp_para._element)
                    found_count += 1

        doc.save(str(path))
        return f"Edited {path}: {found_count} paragraph operation(s) applied."
