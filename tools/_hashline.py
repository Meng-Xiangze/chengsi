"""Hash-anchored text helpers shared by code reading and editing tools."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass


_REF_PATTERN = re.compile(r"^(?:(\d+):)?([0-9a-fA-F]{4})$")


@dataclass(frozen=True)
class TextLayout:
    lines: list[str]
    newline: str
    final_newline: bool


def line_hash(content: str) -> str:
    return hashlib.blake2s(content.encode("utf-8"), digest_size=2).hexdigest()


def revision(text: str) -> str:
    return hashlib.blake2s(text.encode("utf-8"), digest_size=6).hexdigest()


def anchor(line_number: int, content: str) -> str:
    return f"{line_number}:{line_hash(content)}"


def parse_anchor(value: object) -> tuple[int | None, str]:
    """Parse anchor. Accepts 'LINE:HASH' or just 'HASH'."""
    match = _REF_PATTERN.fullmatch(str(value or "").strip())
    if not match:
        raise ValueError(f"invalid anchor {value!r}; expected LINE:HASH or HASH, for example 12:a4f0 or a4f0")
    line_str = match.group(1)
    line_number = int(line_str) if line_str else None
    return line_number, match.group(2).lower()


def validate_anchor(lines: list[str], value: object) -> int:
    """Validate anchor against file content. If no line number, search by hash."""
    line_number, expected_hash = parse_anchor(value)

    # If line number provided, use it for fast lookup
    if line_number is not None:
        if line_number < 1 or line_number > len(lines):
            raise ValueError(f"anchor {value} is outside the current file")
        actual_hash = line_hash(lines[line_number - 1])
        if actual_hash != expected_hash:
            raise ValueError(
                f"stale anchor {value}; current anchor is {line_number}:{actual_hash}. Re-read the file."
            )
        return line_number - 1

    # No line number: search by hash
    for idx, line in enumerate(lines):
        if line_hash(line) == expected_hash:
            return idx

    raise ValueError(
        f"hash {expected_hash} not found in file. Content may have changed. Re-read the file."
    )


def split_text(text: str) -> TextLayout:
    raw_lines = text.splitlines(keepends=True)
    newline_counts = {"\r\n": 0, "\n": 0, "\r": 0}
    lines = []
    final_newline = False
    for raw in raw_lines:
        if raw.endswith("\r\n"):
            ending = "\r\n"
            body = raw[:-2]
        elif raw.endswith("\n"):
            ending = "\n"
            body = raw[:-1]
        elif raw.endswith("\r"):
            ending = "\r"
            body = raw[:-1]
        else:
            ending = ""
            body = raw
        if ending:
            newline_counts[ending] += 1
        lines.append(body)
        final_newline = bool(ending)
    newline = max(newline_counts, key=newline_counts.get) if any(newline_counts.values()) else "\n"
    return TextLayout(lines, newline, final_newline)


def join_text(lines: list[str], newline: str, final_newline: bool) -> str:
    if not lines:
        return ""
    text = newline.join(lines)
    return text + newline if final_newline else text


def replacement_lines(content: object) -> list[str]:
    value = "" if content is None else str(content)
    if not value:
        return []
    return value.replace("\r\n", "\n").replace("\r", "\n").split("\n")


def format_lines(text: str, path: str, offset: int = 1, limit: int = 400) -> str:
    layout = split_text(text)
    total = len(layout.lines)
    start = max(1, offset)
    end = min(total, start + max(1, limit) - 1)
    header = f"[file: {path} rev: {revision(text)} lines: {total} showing: {start}-{end}]"
    output = [header, "[format: LINE:HASH|content; copy anchors exactly for edit operations]"]
    output.extend(
        f"{anchor(index, layout.lines[index - 1])}|{layout.lines[index - 1]}"
        for index in range(start, end + 1)
    )
    if end < total:
        output.append(f"[truncated: read again with offset={end + 1}]")
    return "\n".join(output)
