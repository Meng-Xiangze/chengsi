"""Bounded context compression with plan preservation and input sanitization."""

from __future__ import annotations

import json
from typing import Any


MAX_COMPACTION_INPUT_CHARS = 42_000
MAX_MESSAGE_CONTENT_CHARS = 6_000


def sanitize_for_compaction(messages: list[dict], max_chars: int) -> str:
    """Remove images, truncate tool results, bound total characters."""
    formatted = []
    used = 0
    for message in messages:
        safe = dict(message)
        content = safe.get("content", "")
        if isinstance(content, list):
            safe_parts = []
            for part in content:
                if not isinstance(part, dict):
                    continue
                item = dict(part)
                if item.get("type") == "image_url":
                    item["image_url"] = "[image omitted from compaction]"
                elif isinstance(item.get("text"), str):
                    item["text"] = item["text"][:4000]
                safe_parts.append(item)
            safe["content"] = safe_parts
        elif isinstance(content, str) and len(content) > MAX_MESSAGE_CONTENT_CHARS:
            safe["content"] = content[:MAX_MESSAGE_CONTENT_CHARS] + "\n[message truncated for compaction]"
        line = f"[{safe.get('role', 'unknown')}] {json.dumps(safe, ensure_ascii=False, default=str)}"
        if used + len(line) > max_chars:
            formatted.append("[remaining messages omitted to bound compaction input]")
            break
        formatted.append(line)
        used += len(line) + 2
    return "\n\n".join(formatted)


def build_compaction_prompt(older: list[dict], recent: list[dict]) -> str:
    """Build task-safe compaction prompt with bounded input."""
    return """Compress this agent conversation into a durable context summary.

This is a state handoff, not a general recap. Follow these rules strictly:
1. The latest explicit user request in RECENT VERBATIM CONTEXT is CURRENT TASK and overrides older goals.
2. Later user corrections, including statements that a task is old or wrong, invalidate that older task. Put it under OBSOLETE TASKS.
3. Separate facts confirmed by tool results from assumptions. Put unverified claims under UNVERIFIED.
4. Preserve exact paths, filenames, commands, errors, completed changes, and unfinished work when they affect the current task.
5. Never declare a task complete merely because a related subtask succeeded.
6. End with concrete NEXT ACTIONS for the current task. Do not ask the next agent to repeat completed or obsolete work.

Return only Chinese or the conversation's main language, using exactly these headings:
CURRENT TASK:
COMPLETED:
OBSOLETE TASKS:
UNVERIFIED:
BLOCKERS:
NEXT ACTIONS:

OLDER TRANSCRIPT (historical evidence; bounded):
""" + sanitize_for_compaction(older, 24000) + "\n\nRECENT VERBATIM CONTEXT (authoritative; read this last; bounded):\n" + sanitize_for_compaction(recent, 18000)


def preserve_plan_markers(conversation: list[dict]) -> tuple[list[dict], list[dict]]:
    """Extract plan markers so they survive compaction unchanged."""
    plan_messages = [
        message for message in conversation
        if str(message.get("content", "")).startswith("[PLAN_MARKER]")
    ]
    filtered = [
        message for message in conversation
        if not str(message.get("content", "")).startswith("[PLAN_MARKER]")
    ]
    return filtered, plan_messages


def split_compaction_messages(conversation: list[dict], keep_count: int = 6) -> tuple[list[dict], list[dict]]:
    """Split history without orphaning tool results from their assistant call."""
    recent_start = max(0, len(conversation) - keep_count)
    while recent_start > 0 and conversation[recent_start].get("role") == "tool":
        recent_start -= 1
    return conversation[:recent_start], conversation[recent_start:]
