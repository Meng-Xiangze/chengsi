# -*- coding: utf-8 -*-
"""Unified file reader — text, spreadsheets, images, code search. One tool, all inspection."""
import ast
import base64
import mimetypes
import os
import re
import shutil
from pathlib import Path
from typing import Any

from tools._hashline import anchor, format_lines, revision
from tools._spreadsheet import read_csv, read_xlsx
from tools.base import BaseTool
from core.process_utils import normalize_path, optional_import

PROJECT_ROOT = Path(__file__).resolve().parent.parent
_SKIP_DIRS = {
    ".git", ".hg", ".svn", "__pycache__", ".venv", "venv",
    "node_modules", "assets", "sessions",
}
_TEXT_EXTS = {
    ".py", ".json", ".md", ".txt", ".yaml", ".yml", ".toml", ".cfg",
    ".ini", ".bat", ".sh", ".html", ".css", ".js", ".ts", ".tsx", ".jsx",
    ".xml", ".csv", ".log", ".rst", ".tex", ".svg",
}
_IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp", ".tiff", ".tif"}


class Read(BaseTool):
    """Read text files, view images, or search code — all through one tool."""

    @property
    def tool_name(self) -> str:
        return "read"

    @property
    def description(self) -> str:
        return (
            "Read file contents — text, CSV, XLSX, PDF, DOCX, DOC, images, or search code. "
            "For Python code, mode=outline lists symbols and mode=symbol returns one complete symbol. "
            "Text output includes a revision and stable LINE:HASH anchors for edit operations. "
            "For text/PDF, use offset/limit to paginate. "
            "For images, returns metadata and auto-injects the image for visual analysis. "
            "For search, returns matching lines with file paths, line numbers, and context. "
            "Supports glob, ext, and case_sensitive filters."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "path": {
                "type": "string",
                "description": "File path to read (text, CSV, XLSX, PDF, DOCX, DOC, or image). Required for file mode.",
            },
            "query": {
                "type": "string",
                "description": "Search query or regex. When set, activates code search mode (ignores path).",
            },
            "offset": {
                "type": "integer",
                "description": "Start line, spreadsheet row, PDF page, or DOCX paragraph (1-indexed).",
            },
            "limit": {
                "type": "integer",
                "description": "Max lines/spreadsheet rows (default 200), PDF pages (1), DOCX paragraphs (50), or search results (20).",
            },
            "ext": {
                "type": "string",
                "description": "File extension filter for search mode, e.g. .py or py.",
            },
            "glob": {
                "type": "string",
                "description": "File name glob filter for search, e.g. '*.py' or 'test_*.py'. Overrides ext when set.",
            },
            "case_sensitive": {
                "type": "boolean",
                "description": "Match case in search mode. Default: false (case-insensitive).",
            },
            "mode": {
                "type": "string",
                "enum": ["text", "visual", "outline", "symbol"],
                "description": "text (default); visual for PDF/DOCX/DOC; outline or symbol for Python source.",
            },
            "symbol": {
                "type": "string",
                "description": "Qualified Python symbol for mode=symbol, e.g. AgentRuntime.observe.",
            },
            "sheet_name": {
                "type": "string",
                "description": "Sheet name to read from CSV/XLSX files. When specified, only that sheet is returned instead of all sheets/rows. For xlsx files with multiple sheets, this filters to the named sheet.",
            },
        }

    # ------------------------------------------------------------------ #
    #  Entry
    # ------------------------------------------------------------------ #

    def run(self, arguments: dict[str, Any]) -> str:
        args = arguments or {}
        query = str(args.get("query", "")).strip()

        if query:
            return self._search(query, args)

        raw_path = str(args.get("path", "")).strip()
        if not raw_path:
            return "Error: path or query is required."

        resolved = self._resolve_path(raw_path)
        if not resolved:
            return f"Error: file not found: {raw_path}"

        ext = resolved.suffix.lower()
        if ext == ".csv":
            return read_csv(resolved, args.get("offset", 1), args.get("limit", 200))
        if ext == ".xlsx":
            sheet_name = args.get("sheet_name")
            if sheet_name:
                return read_xlsx(resolved, offset=args.get("offset", 1), limit=args.get("limit", 200), sheet_name=sheet_name)
            else:
                return read_xlsx(resolved, args.get("offset", 1), args.get("limit", 200))
        if ext in _IMAGE_EXTS:
            return self._read_image(resolved, args)
        if ext == ".pdf":
            return self._read_pdf(resolved, args)
        if ext == ".docx":
            return self._read_docx(resolved, args)
        if ext == ".doc":
            return self._read_doc(resolved, args)
        mode = str(args.get("mode", "text")).strip().lower()
        if mode in ("outline", "symbol"):
            if ext != ".py":
                return f"Error: mode={mode} currently supports Python (.py) files only."
            return self._read_python(resolved, args, mode)
        return self._read_text(resolved, args)

    # ------------------------------------------------------------------ #
    #  Read: PDF  (PyMuPDF → text or rendered image)
    # ------------------------------------------------------------------ #

    @staticmethod
    def _read_pdf(filepath: Path, args: dict[str, Any]) -> str:
        mode = str(args.get("mode", "text")).strip().lower()
        if mode == "visual":
            return Read._read_pdf_visual(filepath, args)
        return Read._read_pdf_text(filepath, args)

    @staticmethod
    def _read_pdf_text(filepath: Path, args: dict[str, Any]) -> str:
        """Extract text from PDF. Prefers PyMuPDF (fitz), falls back to pypdf."""
        total_pages = 0
        all_text_parts: list[str] = []

        # Try PyMuPDF first (better text extraction, Chinese support)
        try:
            fitz = optional_import("fitz", "PyMuPDF")
            doc = fitz.open(str(filepath))
            total_pages = len(doc)
            for i in range(total_pages):
                try:
                    all_text_parts.append(doc[i].get_text() or "")
                except Exception:
                    all_text_parts.append("")
            doc.close()
        except ImportError:
            pass
        except Exception:
            # PyMuPDF failed, fall through to pypdf
            all_text_parts = []

        # Fallback to pypdf
        if not all_text_parts:
            try:
                pypdf = optional_import("pypdf")
                from pypdf import PdfReader
                reader = PdfReader(str(filepath))
                total_pages = len(reader.pages)
                for i in range(total_pages):
                    try:
                        all_text_parts.append(reader.pages[i].extract_text() or "")
                    except Exception:
                        all_text_parts.append("")
            except ImportError:
                return (
                    "PDF support requires either PyMuPDF or pypdf. Install with:\n"
                    "  pip install PyMuPDF     (recommended — better extraction, visual mode)\n"
                    "  pip install pypdf       (lightweight fallback)"
                )
            except Exception as e:
                return f"Error opening PDF: {e}"

        if total_pages == 0:
            return "Error: PDF has no pages."

        offset_raw = args.get("offset")
        if offset_raw is not None:
            try:
                page_start = max(1, int(offset_raw))
            except (TypeError, ValueError):
                page_start = 1
        else:
            page_start = 1

        limit_raw = args.get("limit")
        if limit_raw is not None:
            try:
                page_limit = max(1, min(int(limit_raw), 50))
            except (TypeError, ValueError):
                page_limit = 1
        else:
            page_limit = 1

        if page_start > total_pages:
            return f"Error: page {page_start} exceeds document length ({total_pages} pages)."

        page_end = min(page_start + page_limit - 1, total_pages)
        total_chars = sum(len(t) for t in all_text_parts)

        rel = Read._relpath(filepath)
        out: list[str] = []
        out.append(
            f"📄 {rel}  "
            f"(page{'' if page_limit == 1 else 's'} {page_start}–{page_end} of {total_pages}, "
            f"~{total_chars:,} chars total)"
        )

        low_text_hints: list[str] = []
        for i in range(page_start - 1, page_end):
            text = all_text_parts[i]
            char_count = len(text.strip())
            if not text.strip():
                text = "(page contains no extractable text — may be a scanned image)"
                low_text_hints.append(f"Page {i + 1}: no text extracted")
            elif char_count < 120:
                low_text_hints.append(
                    f"Page {i + 1}: only {char_count} chars of text"
                )
            out.append(f"\n── Page {i + 1} ──\n{text}")

        result = "\n".join(out)

        # If any page has very little text, suggest visual mode
        if low_text_hints:
            hint = "\n\n💡 Some pages have little extractable text:\n"
            for h in low_text_hints[:3]:
                hint += f"   • {h}\n"
            hint += (
                "   These may contain tables, figures, formulas, or scanned content.\n"
                "   Use mode=visual with a vision-capable model to read them."
            )
            result += hint

        # 50KB cap — ecosystem standard: say it UP FRONT so the model pages through
        if len(result.encode("utf-8")) > 50_000:
            remaining = total_pages - page_end
            hint = (
                f"⚠️  Output exceeds 50KB; showing pages {page_start}–{page_end} of {total_pages} "
                f"(~{total_chars:,} chars total)."
            )
            if remaining > 0:
                hint += (
                    f"⏩  {remaining} page{'s' if remaining > 1 else ''} remaining — "
                    f"read the rest with offset={page_end + 1} before judging the task."
                )
            else:
                hint += " ✅ End of document reached."
            if total_chars > 15000:
                hint += (
                    f"\n💡 Document is ~{total_chars:,} chars — "
                    "consider a cloud model for full-document analysis."
                )
            result = f"{hint}\n\n" + result[:50000]
        elif page_end < total_pages:
            remaining = total_pages - page_end
            result += (
                f"\n\n📋 {remaining} page{'s' if remaining > 1 else ''} remaining. "
                f"Use offset={page_end + 1} to continue."
            )

        return result

    @staticmethod
    def _read_pdf_visual(filepath: Path, args: dict[str, Any]) -> str:
        """Render PDF page(s) as PNG images for vision models."""
        try:
            fitz = optional_import("fitz", "PyMuPDF")
        except ImportError:
            return (
                "PDF visual mode requires PyMuPDF. Install with:\n"
                "  pip install PyMuPDF"
            )

        try:
            doc = fitz.open(str(filepath))
        except Exception as e:
            return f"Error opening PDF: {e}"

        total_pages = len(doc)
        if total_pages == 0:
            doc.close()
            return "Error: PDF has no pages."

        offset_raw = args.get("offset")
        if offset_raw is not None:
            try:
                page_num = max(1, int(offset_raw))
            except (TypeError, ValueError):
                page_num = 1
        else:
            page_num = 1

        if page_num > total_pages:
            doc.close()
            return f"Error: page {page_num} exceeds document length ({total_pages} pages)."

        limit_raw = args.get("limit")
        if limit_raw is not None:
            try:
                page_limit = max(1, min(int(limit_raw), 5))
            except (TypeError, ValueError):
                page_limit = 1
        else:
            page_limit = 1

        end_page = min(page_num + page_limit - 1, total_pages)

        # Render pages to a temp directory
        import tempfile
        out_dir = Path(tempfile.gettempdir()) / "chengsi_read_pages"
        out_dir.mkdir(parents=True, exist_ok=True)

        stem = filepath.stem
        rendered: list[Path] = []

        for i in range(page_num - 1, end_page):
            page = doc[i]
            # 200 DPI — readable without being huge
            pix = page.get_pixmap(dpi=200)
            out_path = out_dir / f"{stem}_p{i + 1}.png"
            pix.save(str(out_path))
            rendered.append(out_path)

        doc.close()

        if not rendered:
            return "Error: no pages rendered."

        # Metadata header
        rel = Read._relpath(filepath)
        sizes = [os.path.getsize(p) for p in rendered]
        meta_lines = [
            f"📄 {rel}  "
            f"(page{'' if page_limit == 1 else 's'} {page_num}–{end_page} of {total_pages}, "
            f"rendered as image{'' if len(rendered) == 1 else 's'})",
            f"Mode: visual (tables, formulas, figures are visible to vision models)",
        ]

        # For single page: return directly with __IMAGE_PATH__ marker
        if len(rendered) == 1:
            meta = "\n".join(meta_lines)
            return f"{meta}\n__IMAGE_PATH__:{rendered[0]}"

        # For multiple pages: return metadata + first page as image, list the rest
        meta = "\n".join(meta_lines)
        result = meta + "\n"
        for p in rendered:
            result += f"  Image: {p}\n"
        result += (
            f"\n⚠️  Multiple pages rendered. Only page {page_num} is shown below. "
            f"Use offset={page_num + 1} to view the next page.\n"
            f"__IMAGE_PATH__:{rendered[0]}"
        )
        return result

    # ------------------------------------------------------------------ #
    #  Read: DOCX  (python-docx → text, LibreOffice → visual)
    # ------------------------------------------------------------------ #

    @staticmethod
    def _read_docx(filepath: Path, args: dict[str, Any]) -> str:
        mode = str(args.get("mode", "text")).strip().lower()
        if mode == "visual":
            return Read._read_docx_visual(filepath, args)
        return Read._read_docx_text(filepath, args)

    @staticmethod
    def _build_numbering_lookup(doc) -> dict:
        """Build a lookup: (numId, ilvl) -> (format_template, start_value).

        Templates use %1, %2, etc. for level numbers.
        Returns {} if document has no numbering part."""
        lookup: dict = {}
        try:
            num_part = doc.part.numbering_part
            if num_part is None:
                return {}
            root = num_part.element
        except Exception:
            return {}

        from docx.oxml.ns import qn as _qn

        # Map abstractNumId -> {ilvl: (fmt, lvlText, start)}
        abstract_nums: dict = {}
        for abs_elem in root.findall(_qn("w:abstractNum")):
            abs_id = abs_elem.get(_qn("w:abstractNumId"))
            if abs_id is None:
                continue
            levels: dict = {}
            for lvl_elem in abs_elem.findall(_qn("w:lvl")):
                ilvl_str = lvl_elem.get(_qn("w:ilvl"), "0")
                try:
                    ilvl = int(ilvl_str)
                except ValueError:
                    continue
                numFmt = lvl_elem.find(_qn("w:numFmt"))
                fmt = numFmt.get(_qn("w:val")) if numFmt is not None else "decimal"
                lvlText = lvl_elem.find(_qn("w:lvlText"))
                text = lvlText.get(_qn("w:val")) if lvlText is not None else "%1."
                start_elem = lvl_elem.find(_qn("w:start"))
                try:
                    start = int(start_elem.get(_qn("w:val"))) if start_elem is not None else 1
                except (ValueError, TypeError):
                    start = 1
                levels[ilvl] = (fmt, text, start)
            if levels:
                abstract_nums[abs_id] = levels

        # Map numId -> abstractNumId -> levels
        for num_elem in root.findall(_qn("w:num")):
            numId_str = num_elem.get(_qn("w:numId"))
            if numId_str is None:
                continue
            abs_ref = num_elem.find(_qn("w:abstractNumId"))
            if abs_ref is None:
                continue
            abs_id = abs_ref.get(_qn("w:val"))
            if abs_id is None or abs_id not in abstract_nums:
                continue
            for ilvl, spec in abstract_nums[abs_id].items():
                lookup[(numId_str, ilvl)] = spec

        return lookup

    @staticmethod
    def _format_number(counters: dict, numId: str, ilvl: int, lookup: dict) -> str:
        """Compute the displayed number for a list paragraph."""
        key = (numId, ilvl)
        spec = lookup.get(key)
        if spec is None:
            return ""

        fmt, template, start = spec

        # Reset lower-level counters when a higher level appears
        numId_int = int(numId) if numId.isdigit() else hash(numId) & 0xFFFF
        for (nid, lvl), cnt in list(counters.items()):
            if nid == numId_int and lvl > ilvl:
                counters[(nid, lvl)] = start - 1

        # Increment current level counter
        ckey = (numId_int, ilvl)
        counters.setdefault(ckey, start - 1)
        counters[ckey] += 1

        # Build the display text from template
        result = template
        for lvl in range(ilvl + 1):
            lkey = (numId_int, lvl)
            val = counters.get(lkey, 1)
            # Map fmt: decimal -> "1", bullet -> "•", etc.
            lspec = lookup.get((numId, lvl))
            if lspec:
                lfmt = lspec[0]
                if lfmt == "bullet":
                    disp = "•"
                elif lfmt in ("decimal", "lowerLetter", "upperLetter", "lowerRoman", "upperRoman"):
                    disp = str(val)
                else:
                    disp = str(val)
            else:
                disp = str(val)
            result = result.replace(f"%{lvl + 1}", disp)

        return result + " "

    @staticmethod
    def _parse_numPr(para_elem, qn) -> tuple[str | None, int]:
        """Extract (numId, ilvl) from a paragraph's w:numPr, or (None, 0)."""
        pPr = para_elem.find(qn("w:pPr"))
        if pPr is None:
            return None, 0
        numPr = pPr.find(qn("w:numPr"))
        if numPr is None:
            return None, 0
        numId_elem = numPr.find(qn("w:numId"))
        ilvl_elem = numPr.find(qn("w:ilvl"))
        numId = numId_elem.get(qn("w:val")) if numId_elem is not None else None
        try:
            ilvl = int(ilvl_elem.get(qn("w:val"))) if ilvl_elem is not None else 0
        except (ValueError, TypeError):
            ilvl = 0
        return numId, ilvl

    @staticmethod
    def _format_paragraph_xml(para_elem, qn, image_count: int) -> str:
        """Walk <w:r> runs inside a paragraph, add formatting markers.

        Marker conventions:
          **text**  for bold
          *text*   for italic
          ^text^   for superscript
          _text_   for subscript
          [Eq: ...] for OMML equations (Office Math Markup)

        If the paragraph contains a drawing and no text, returns [Embedded image N].
        """
        has_drawing = any(True for _ in para_elem.iter(qn("w:drawing")))

        parts: list[str] = []

        # Walk all children in document order — runs + OMML equations
        for child in para_elem:
            child_tag = child.tag.split("}")[-1] if "}" in child.tag else child.tag

            if child_tag == "r":
                # Standard text run
                bold = None
                italic = None
                superscript = None
                subscript = None

                rpr = child.find(qn("w:rPr"))
                if rpr is not None:
                    b = rpr.find(qn("w:b"))
                    if b is not None:
                        bold = b.get(qn("w:val"), "1") != "0"
                    i = rpr.find(qn("w:i"))
                    if i is not None:
                        italic = i.get(qn("w:val"), "1") != "0"
                    vert = rpr.find(qn("w:vertAlign"))
                    if vert is not None:
                        va = vert.get(qn("w:val"), "")
                        if va == "superscript":
                            superscript = True
                        elif va == "subscript":
                            subscript = True

                run_text = ""
                for t_elem in child.iter(qn("w:t")):
                    if t_elem.text:
                        run_text += t_elem.text

                if not run_text:
                    # Check for embedded objects (MathType, etc.)
                    has_object = child.find(qn("w:object")) is not None
                    if has_object:
                        parts.append(" [Equation] ")
                    continue

                # Apply formatting markers: outer → inner
                if superscript:
                    run_text = "^" + run_text + "^"
                elif subscript:
                    run_text = "_" + run_text + "_"
                if italic:
                    run_text = "*" + run_text + "*"
                if bold:
                    run_text = "**" + run_text + "**"

                parts.append(run_text)

            elif child_tag in ("oMath", "oMathPara"):
                # OMML equation — extract flat text as approximation
                eq_text = "".join(child.itertext()).strip()
                if eq_text:
                    parts.append(f" [Eq: {eq_text}] ")

            elif child_tag == "object":
                # Embedded OLE object (MathType, Excel chart, etc.)
                parts.append(" [Equation] ")

        text = "".join(parts)

        # Image detection
        if has_drawing:
            if not text.strip():
                return f"[Embedded image {image_count + 1}]"

        return text

    @staticmethod
    def _read_docx_text(filepath: Path, args: dict[str, Any]) -> str:
        """Extract paragraphs and tables from a .docx file."""
        try:
            docx = optional_import("docx", "python-docx")
            from docx import Document
        except ImportError:
            return (
                "DOCX support requires the python-docx package. Install with:\n"
                "  pip install python-docx"
            )

        try:
            doc = Document(str(filepath))
        except Exception as e:
            return f"Error opening DOCX: {e}"

        # Collect all paragraphs and table rows into one flat list
        from docx.oxml.ns import qn

        items: list[str] = []
        table_count = 0
        image_count = 0

        # Build numbering context for list paragraphs
        num_lookup = Read._build_numbering_lookup(doc)
        num_counters: dict = {}

        for block in doc.element.body:
            tag = block.tag.split("}")[-1] if "}" in block.tag else block.tag
            if tag == "p":
                # Check for list numbering
                numId, ilvl = Read._parse_numPr(block, qn)
                num_prefix = ""
                if numId is not None and numId in {k[0] for k in num_lookup}:
                    num_prefix = Read._format_number(num_counters, numId, ilvl, num_lookup)

                # Paragraph with formatting markers
                text = Read._format_paragraph_xml(block, qn, image_count)
                if text.startswith("[Embedded image"):
                    image_count += 1
                if num_prefix and text.strip():
                    text = num_prefix + text
                items.append(text)
            elif tag == "tbl":
                # Table — extract as structured text
                table_count += 1
                rows: list[str] = []
                for row_elem in block.iter(qn("w:tr")):
                    cells: list[str] = []
                    for cell_elem in row_elem.iter(qn("w:tc")):
                        cell_parts: list[str] = []
                        for p in cell_elem.iter(qn("w:p")):
                            cell_parts.append(Read._format_paragraph_xml(p, qn, -1))
                        cells.append(" ".join(cell_parts).strip())
                    if cells:
                        rows.append(" | ".join(cells))
                if rows:
                    items.append("[Table " + str(table_count) + "]\n" + "\n".join(rows))

        total_items = len(items)
        if total_items == 0:
            return "Error: DOCX has no extractable paragraphs or tables."

        total_chars = sum(len(it) for it in items)

        offset_raw = args.get("offset")
        if offset_raw is not None:
            try:
                item_start = max(1, int(offset_raw))
            except (TypeError, ValueError):
                item_start = 1
        else:
            item_start = 1

        limit_raw = args.get("limit")
        if limit_raw is not None:
            try:
                item_limit = max(1, min(int(limit_raw), 100))
            except (TypeError, ValueError):
                item_limit = 50
        else:
            item_limit = 50

        if item_start > total_items:
            return f"Error: paragraph {item_start} exceeds document length ({total_items} paragraphs)."

        item_end = min(item_start + item_limit - 1, total_items)

        rel = Read._relpath(filepath)
        out: list[str] = []
        meta_parts = [f"📄 {rel}", f"(paragraphs {item_start}–{item_end} of {total_items}"]
        if table_count:
            meta_parts.append(f", {table_count} table{'s' if table_count > 1 else ''}")
        if image_count:
            meta_parts.append(f", {image_count} embedded image{'s' if image_count > 1 else ''}")
        meta_parts.append(f", ~{total_chars:,} chars total)")
        out.append("".join(meta_parts))

        for i in range(item_start - 1, item_end):
            text = items[i]
            if not text.strip():
                text = "(empty paragraph)"
            if text.startswith("[Table"):
                out.append(f"\n── {text}")
            else:
                out.append(f"\n[{i + 1}] {text}")

        result = "\n".join(out)

        # 50KB cap — ecosystem standard: say it UP FRONT so the model pages through
        if len(result.encode("utf-8")) > 50_000:
            remaining = total_items - item_end
            hint = (
                f"⚠️  Output exceeds 50KB; showing paragraphs {item_start}–{item_end} of {total_items} "
                f"(~{total_chars:,} chars total)."
            )
            if remaining > 0:
                hint += (
                    f"⏩  {remaining} paragraph{'s' if remaining > 1 else ''} remaining — "
                    f"read the rest with offset={item_end + 1} before judging the task."
                )
            else:
                hint += " ✅ End of document reached."
            if total_chars > 15000:
                hint += (
                    f"\n💡 Document is ~{total_chars:,} chars — "
                    "consider a cloud model for full-document analysis."
                )
            result = f"{hint}\n\n" + result[:50000]
        elif item_end < total_items:
            remaining = total_items - item_end
            result += (
                f"\n\n📋 {remaining} paragraph{'s' if remaining > 1 else ''} remaining. "
                f"Use offset={item_end + 1} to continue."
            )

        # Hint if document has images but little text
        if image_count > 0 and total_chars < 2000:
            result += (
                f"\n\n💡 This document contains {image_count} embedded image{'s' if image_count > 1 else ''} "
                f"and only ~{total_chars:,} chars of text. "
                "Use mode=visual to view rendered pages."
            )

        # Disclaimer — formatting markers
        result += (
            "\n\n📝 DOCX formatting: **bold**, *italic*, ^superscript^, _subscript_. "
            "Extracted from document XML; may differ from Word's rendered layout. "
            "Use mode=visual with a vision model to see exact page appearance."
        )

        # ── Extract embedded images for vision ───────────────────
        if image_count > 0:
            image_refs = Read._extract_docx_images(filepath, max_images=3)
            if image_refs:
                result += "\n\n🖼️ Embedded images:\n"
                for idx, img_path in image_refs:
                    result += f"  [{idx}] __IMAGE_PATH__:{img_path}\n"

        return result

    @staticmethod
    def _extract_docx_images(filepath: Path, max_images: int = 3) -> list[tuple[int, Path]]:
        """Extract up to *max_images* embedded images from a DOCX zip.

        Returns a list of (index, temp_file_path) tuples.  The caller is
        responsible for including ``__IMAGE_PATH__:`` markers so the
        vision pipeline picks them up.
        """
        import zipfile, tempfile
        try:
            zf = zipfile.ZipFile(str(filepath))
        except Exception:
            return []

        image_names = [
            n for n in zf.namelist()
            if Path(n).suffix.lower()
            in ('.png', '.jpg', '.jpeg', '.gif', '.bmp', '.webp', '.tiff', '.tif', '.emf', '.wmf')
        ]
        if not image_names:
            zf.close()
            return []

        tmpdir = Path(tempfile.gettempdir()) / "chengsi_docx_images"
        tmpdir.mkdir(parents=True, exist_ok=True)
        stem = filepath.stem
        extracted: list[tuple[int, Path]] = []
        for i in range(min(max_images, len(image_names))):
            entry = image_names[i]
            ext = Path(entry).suffix.lower()
            out = tmpdir / f"{stem}_img{i + 1}{ext}"
            try:
                out.write_bytes(zf.read(entry))
                extracted.append((i + 1, out))
            except Exception:
                pass
        zf.close()
        return extracted

    @staticmethod
    def _read_docx_visual(filepath: Path, args: dict[str, Any]) -> str:
        """Visual mode: try LibreOffice → PDF render, fallback to embedded image extraction."""
        import zipfile, io, tempfile

        # ── Path A: LibreOffice (best — renders entire page layout) ──
        soffice = Read._find_libreoffice()

        if soffice:
            import subprocess as sp
            tmpdir = Path(tempfile.gettempdir()) / "chengsi_docx"
            tmpdir.mkdir(parents=True, exist_ok=True)
            pdf_out = tmpdir / f"{filepath.stem}.pdf"
            try:
                sp.run(
                    [soffice, "--headless", "--convert-to", "pdf",
                     "--outdir", str(tmpdir), str(filepath)],
                    capture_output=True, text=True, timeout=30,
                )
            except Exception:
                pass
            if pdf_out.exists():
                rel = Read._relpath(filepath)
                pdf_result = Read._read_pdf_visual(pdf_out, args)
                return f"📄 {rel}  (DOCX → PDF via LibreOffice → visual)\n{pdf_result}"

        # ── Path B: Extract embedded images from DOCX zip ──
        try:
            import zipfile
            zf = zipfile.ZipFile(str(filepath))
        except Exception as e:
            return f"Error opening DOCX zip: {e}"

        # Find image files in the zip
        image_entries = []
        for name in zf.namelist():
            ext = Path(name).suffix.lower()
            if ext in ('.png', '.jpg', '.jpeg', '.gif', '.bmp', '.webp', '.tiff', '.tif', '.emf', '.wmf'):
                image_entries.append(name)

        if not image_entries:
            zf.close()
            return (
                "No embedded images found in this DOCX, and LibreOffice is not installed.\n"
                "Install LibreOffice for full page-layout rendering:\n"
                "  https://www.libreoffice.org/download/"
            )

        # Determine which image to extract (offset = image index, limit = count)
        offset_raw = args.get("offset")
        if offset_raw is not None:
            try:
                img_start = max(1, int(offset_raw))
            except (TypeError, ValueError):
                img_start = 1
        else:
            img_start = 1

        limit_raw = args.get("limit")
        if limit_raw is not None:
            try:
                img_limit = max(1, min(int(limit_raw), 3))
            except (TypeError, ValueError):
                img_limit = 1
        else:
            img_limit = 1

        if img_start > len(image_entries):
            zf.close()
            return f"Error: image {img_start} exceeds document ({len(image_entries)} embedded images)."

        end_idx = min(img_start + img_limit - 1, len(image_entries))

        tmpdir = Path(tempfile.gettempdir()) / "chengsi_docx_images"
        tmpdir.mkdir(parents=True, exist_ok=True)

        extracted = []
        stem = filepath.stem
        for i in range(img_start - 1, end_idx):
            entry_name = image_entries[i]
            ext = Path(entry_name).suffix.lower()
            out_name = f"{stem}_img{i + 1}{ext}"
            out_path = tmpdir / out_name
            out_path.write_bytes(zf.read(entry_name))
            extracted.append((i + 1, out_path, os.path.getsize(out_path)))

        zf.close()

        if not extracted:
            return "Error: no images extracted."

        rel = Read._relpath(filepath)
        meta = (
            f"📄 {rel}  "
            f"(extracted embedded image{'s' if len(extracted) > 1 else ''} {img_start}–{end_idx} of {len(image_entries)} "
            f"from DOCX)"
        )
        if not soffice:
            meta += "\n💡 LibreOffice not found — showing embedded images. Install LibreOffice for full page rendering."

        if len(extracted) == 1:
            _, path, _ = extracted[0]
            return f"{meta}\n__IMAGE_PATH__:{path}"

        result = meta + "\n"
        for idx, path, size in extracted:
            result += f"  Image {idx}: {path} ({size:,} bytes)\n"
        first = extracted[0][1]
        result += (
            f"\n⚠️  Multiple images extracted. Only image {img_start} is shown below. "
            f"Use offset={img_start + 1} to view the next.\n"
            f"__IMAGE_PATH__:{first}"
        )
        return result

    # ------------------------------------------------------------------ #
    #  Read: DOC  (LibreOffice → docx/text or PDF)
    # ------------------------------------------------------------------ #

    @staticmethod
    def _read_doc(filepath: Path, args: dict[str, Any]) -> str:
        """Read .doc files by converting via LibreOffice to docx (text) or PDF (visual)."""
        mode = str(args.get("mode", "text")).strip().lower()
        if mode == "visual":
            return Read._read_doc_visual(filepath, args)
        return Read._read_doc_text(filepath, args)

    @staticmethod
    def _find_libreoffice() -> str | None:
        """Locate soffice.exe for headless conversions."""
        lo_paths = [
            r"C:\Program Files\LibreOffice\program\soffice.exe",
            r"C:\Program Files (x86)\LibreOffice\program\soffice.exe",
        ]
        for p in lo_paths:
            if os.path.isfile(p):
                return p
        return shutil.which("soffice")

    @staticmethod
    def _read_doc_text(filepath: Path, args: dict[str, Any]) -> str:
        """Convert .doc → .docx via LibreOffice, then parse with python-docx."""
        import subprocess as sp, tempfile

        soffice = Read._find_libreoffice()
        if not soffice:
            return (
                "DOC support requires LibreOffice. Install from https://www.libreoffice.org/\n"
                "After installation, this tool will automatically detect soffice.exe."
            )

        tmpdir = Path(tempfile.gettempdir()) / "chengsi_doc"
        tmpdir.mkdir(parents=True, exist_ok=True)
        docx_out = tmpdir / f"{filepath.stem}.docx"

        rel = Read._relpath(filepath)

        try:
            sp.run(
                [soffice, "--headless", "--convert-to", "docx",
                 "--outdir", str(tmpdir), str(filepath)],
                capture_output=True, text=True, timeout=60,
            )
        except Exception as e:
            return f"Error converting DOC to DOCX via LibreOffice: {e}"

        if not docx_out.exists():
            return "Error: LibreOffice conversion produced no output. The .doc file may be corrupted."

        # Delegate to the existing DOCX text reader
        docx_result = Read._read_docx_text(docx_out, args)
        return f"📄 {rel}  (DOC → DOCX via LibreOffice)\n{docx_result}"

    @staticmethod
    def _read_doc_visual(filepath: Path, args: dict[str, Any]) -> str:
        """Convert .doc → PDF via LibreOffice, then render with PDF visual."""
        import subprocess as sp, tempfile

        soffice = Read._find_libreoffice()
        if not soffice:
            return (
                "DOC visual mode requires LibreOffice. Install from https://www.libreoffice.org/\n"
                "After installation, this tool will automatically detect soffice.exe."
            )

        tmpdir = Path(tempfile.gettempdir()) / "chengsi_doc"
        tmpdir.mkdir(parents=True, exist_ok=True)
        pdf_out = tmpdir / f"{filepath.stem}.pdf"

        rel = Read._relpath(filepath)

        try:
            sp.run(
                [soffice, "--headless", "--convert-to", "pdf",
                 "--outdir", str(tmpdir), str(filepath)],
                capture_output=True, text=True, timeout=60,
            )
        except Exception as e:
            return f"Error converting DOC to PDF via LibreOffice: {e}"

        if not pdf_out.exists():
            return "Error: LibreOffice conversion produced no output. The .doc file may be corrupted."

        pdf_result = Read._read_pdf_visual(pdf_out, args)
        return f"📄 {rel}  (DOC → PDF via LibreOffice → visual)\n{pdf_result}"
    # ------------------------------------------------------------------ #
    #  Read: Python structure
    # ------------------------------------------------------------------ #

    @staticmethod
    def _python_symbols(tree: ast.AST) -> list[tuple[str, ast.AST]]:
        symbols: list[tuple[str, ast.AST]] = []

        def visit(body: list[ast.stmt], prefix: str = "") -> None:
            for node in body:
                if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
                    name = f"{prefix}.{node.name}" if prefix else node.name
                    symbols.append((name, node))
                    if isinstance(node, ast.ClassDef):
                        visit(node.body, name)

        visit(getattr(tree, "body", []))
        return symbols

    @staticmethod
    def _read_python(filepath: Path, args: dict[str, Any], mode: str) -> str:
        try:
            with open(filepath, encoding="utf-8-sig", newline="") as handle:
                text = handle.read()
            tree = ast.parse(text, filename=str(filepath))
        except (OSError, UnicodeError, SyntaxError) as exc:
            return f"Error parsing Python file {filepath}: {exc}"

        symbols = Read._python_symbols(tree)
        rel = Read._relpath(filepath)
        if mode == "outline":
            output = [f"[python outline: {rel} rev: {revision(text)}]"]
            for name, node in symbols:
                kind = "class" if isinstance(node, ast.ClassDef) else "function"
                if isinstance(node, ast.AsyncFunctionDef):
                    kind = "async function"
                output.append(
                    f"{kind} {name} lines {node.lineno}-{getattr(node, 'end_lineno', node.lineno)}"
                )
            if len(output) == 1:
                output.append("[no classes or functions]")
            return "\n".join(output)

        requested = str(args.get("symbol", "")).strip()
        if not requested:
            return "Error: symbol is required when mode=symbol."
        matches = [(name, node) for name, node in symbols if name == requested]
        if not matches and "." not in requested:
            matches = [(name, node) for name, node in symbols if name.rsplit(".", 1)[-1] == requested]
        if len(matches) != 1:
            candidates = ", ".join(name for name, _ in matches[:10]) or "none"
            return f"Error: symbol {requested!r} matched {len(matches)} definitions ({candidates})."
        name, node = matches[0]
        start = node.lineno
        end = getattr(node, "end_lineno", start)
        return f"[python symbol: {name}]\n" + format_lines(text, rel, start, end - start + 1)

    # ------------------------------------------------------------------ #
    #  Read: text
    # ------------------------------------------------------------------ #

    @staticmethod
    def _read_text(filepath: Path, args: dict[str, Any]) -> str:
        try:
            with open(filepath, encoding="utf-8-sig", errors="replace", newline="") as handle:
                text = handle.read()
        except OSError as e:
            return f"Error reading {filepath}: {e}"

        lines = text.splitlines(keepends=True)
        total = len(lines)
        offset_raw = args.get("offset")
        if offset_raw is not None:
            try:
                offset = max(1, int(offset_raw))
            except (TypeError, ValueError):
                offset = 1
        else:
            offset = 1

        limit = 200
        raw_limit = args.get("limit")
        if raw_limit is not None:
            try:
                limit = max(1, min(int(raw_limit), 500))
            except (TypeError, ValueError):
                pass

        # An oversized offset means "read from the end". This keeps pagination
        # idempotent when a previous response reports a stale continuation point.
        if total == 0:
            return format_lines(text, Read._relpath(filepath), 1, 1)
        offset = min(offset, total)
        start = offset - 1
        end = min(start + limit, total)

        rel = Read._relpath(filepath)
        result = format_lines(text, rel, start + 1, end - start)

        # Ecosystem standard: if the file is larger than the cap, say so UP FRONT
        # (before the content) so the model pages through the whole file instead
        # of assuming the first chunk is everything.
        if len(result.encode("utf-8")) > 50_000:
            truncated_at = end
            hint = (
                f"⚠️  File is {total:,} lines, {len(text):,} chars total; showing lines "
                f"{offset:,}-{truncated_at:,} (first ~50KB).\n"
                f"⏩  Content continues! Read the rest with offset={truncated_at + 1} "
                f"until you have seen the ENTIRE file before judging the task."
            )
            result = (
                f"{hint}\n\n"
                f"{result[:50000]}"
            )

        return result

    # ------------------------------------------------------------------ #
    #  Read: image  (preserves exact __IMAGE_PATH__ chain from main.py)
    # ------------------------------------------------------------------ #

    @staticmethod
    def _read_image(filepath: Path, args: dict[str, Any]) -> str:
        action = str(args.get("ext", "")).strip().lower()  # reuse 'ext' as 'action' for images
        if action not in ("info",):
            action = "read"

        file_size = filepath.stat().st_size
        mime, _ = mimetypes.guess_type(str(filepath))
        if not mime:
            mime = "application/octet-stream"

        dimensions = _get_image_dimensions(filepath)
        ext = filepath.suffix.lstrip(".").upper()

        meta_lines = [
            f"File: {Read._relpath(filepath)}",
            f"Format: {ext}",
            f"MIME: {mime}",
            f"Size: {file_size:,} bytes ({file_size / 1024:.1f} KB)",
        ]
        if dimensions:
            meta_lines.append(f"Dimensions: {dimensions[0]}x{dimensions[1]} px")

        if action == "info":
            return "\n".join(meta_lines)

        # read action: metadata + __IMAGE_PATH__ marker
        # The agent loop in main.py detects this marker and injects base64
        # as multimodal content so the model can visually analyze the image.
        meta = "\n".join(meta_lines)
        return f"{meta}\n__IMAGE_PATH__:{filepath}"

    # ------------------------------------------------------------------ #
    #  Search  (ex-code_context logic, preserved exactly)
    # ------------------------------------------------------------------ #

    @staticmethod
    def _search(query: str, args: dict[str, Any]) -> str:
        # case_sensitive flag (default: false)
        case_sensitive = bool(args.get("case_sensitive", False))
        flags = 0 if case_sensitive else re.IGNORECASE

        try:
            pattern = re.compile(query, flags)
            query_mode = "regex"
        except re.error as exc:
            pattern = re.compile(re.escape(query), flags)
            query_mode = f"literal fallback ({exc})"

        try:
            max_results = max(1, min(int(args.get("limit", 20) or 20), 200))
        except (TypeError, ValueError):
            max_results = 20

        # File filter: glob overrides ext (backward compat)
        glob_pat = args.get("glob", "").strip()
        ext_filter = _normalise_extension(args.get("ext")) if not glob_pat else None
        if glob_pat:
            import fnmatch

        # Search root: path param or project root
        raw_path = str(args.get("path", "")).strip()
        search_root = Path(raw_path) if raw_path else PROJECT_ROOT
        search_root = Path(search_root)
        if not search_root.exists():
            search_root = PROJECT_ROOT

        results: list[str] = []
        total_matches = 0

        if search_root.is_file():
            # Single file search
            files_to_search = [(search_root.parent, search_root.name)]
        else:
            # Walk the tree
            file_pairs = []
            for root, dirs, files in os.walk(str(search_root)):
                dirs[:] = [d for d in dirs if d not in _SKIP_DIRS and not d.startswith("self-agent_backup_")]
                for fname in sorted(files, key=str.lower):
                    if ext_filter and not fname.lower().endswith(ext_filter):
                        continue
                    if glob_pat and not fnmatch.fnmatch(fname, glob_pat):
                        continue
                    suffix = os.path.splitext(fname)[1].lower()
                    if suffix and suffix not in _TEXT_EXTS:
                        continue
                    file_pairs.append((root, fname))
            files_to_search = file_pairs

        for root, fname in files_to_search:
            fpath = os.path.join(root, fname)
            try:
                with open(fpath, encoding="utf-8", errors="replace") as handle:
                    file_lines = handle.readlines()
            except (OSError, UnicodeError):
                continue

            for idx, line in enumerate(file_lines):
                if not pattern.search(line):
                    continue
                total_matches += 1
                if len(results) < max_results:
                    start = max(idx - 3, 0)
                    end = min(idx + 4, len(file_lines))
                    context = "".join(
                        "  %s %s|%s\n" % (
                            ">" if row == idx else " ",
                            anchor(row + 1, file_lines[row].rstrip("\n").rstrip("\r")),
                            file_lines[row].rstrip(),
                        )
                        for row in range(start, end)
                    )
                    rel = Read._relpath(Path(fpath))
                    results.append(
                        f"--- {rel}:{idx + 1} ({_find_function_name(file_lines, idx)}) ---\n{context}"
                    )

        if not results:
            return f"No matches found for '{query}'."

        note = ""
        if query_mode.startswith("literal"):
            note = f"; {query_mode}"
        truncated = " (showing first %d)" % max_results if total_matches > max_results else ""
        return f"Found {total_matches} match(es){truncated} for '{query}'{note}:\n\n" + "\n".join(results)

    # ------------------------------------------------------------------ #
    #  Helpers
    # ------------------------------------------------------------------ #

    @staticmethod
    def _resolve_path(raw: str) -> Path | None:
        p = Path(normalize_path(raw))
        if not p.is_absolute():
            p = (PROJECT_ROOT / p).resolve()
        else:
            p = p.resolve()
        return p if p.is_file() else None

    @staticmethod
    def _relpath(filepath: Path) -> str:
        """Return a display path — relative to project if on same drive, else absolute."""
        try:
            return os.path.relpath(filepath, PROJECT_ROOT)
        except ValueError:
            return str(filepath)


def _find_function_name(lines: list[str], lineno: int) -> str:
    for i in range(lineno, max(lineno - 100, -1), -1):
        match = re.match(r"^\s*(async\s+def|def|class)\s+([A-Za-z_]\w*)", lines[i])
        if match:
            return f"{match.group(1)} {match.group(2)}"
    return "-"


def _normalise_extension(value: Any) -> str:
    ext = str(value or "").strip().lower()
    if ext and not ext.startswith("."):
        ext = "." + ext
    return ext


def _get_image_dimensions(filepath: Path) -> tuple[int, int] | None:
    """Return (width, height) if PIL is available, else parse PNG header."""
    try:
        from PIL import Image
        with Image.open(filepath) as img:
            return img.size
    except ImportError:
        pass
    except Exception:
        pass
    try:
        with open(filepath, "rb") as f:
            header = f.read(32)
        if header[:8] == b"\x89PNG\r\n\x1a\n":
            import struct
            w = struct.unpack(">I", header[16:20])[0]
            h = struct.unpack(">I", header[20:24])[0]
            return (w, h)
    except Exception:
        pass
    return None
