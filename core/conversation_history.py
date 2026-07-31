"""Bounded persistence and UI projection for conversation events."""

from __future__ import annotations

from typing import Any, Iterable

PERSISTED_EVENT_TYPES = {
    "user",
    "agent",
    "agent_done",
    "tool_call",
    "tool_result",
    "image",
    "background_job_result",
    "delegate_result",
}

MAX_PERSISTED_EVENTS = 400
MAX_UI_EVENTS = 160
MAX_UI_CHARS = 240_000
MAX_EVENT_CHARS = 20_000


def _bounded_value(value: Any, max_chars: int = MAX_EVENT_CHARS) -> Any:
    if isinstance(value, str):
        if len(value) <= max_chars:
            return value
        return value[:max_chars] + "\n[content truncated]"
    if isinstance(value, dict):
        return {str(key): _bounded_value(item, max_chars) for key, item in value.items()}
    if isinstance(value, list):
        return [_bounded_value(item, max_chars) for item in value[:100]]
    return value


def append_event(history: list[dict], event_type: str, data: Any) -> None:
    """Persist one user-visible event while keeping memory and disk bounded."""
    if event_type not in PERSISTED_EVENT_TYPES:
        return
    history.append({"type": event_type, "data": _bounded_value(data)})
    if len(history) > MAX_PERSISTED_EVENTS:
        del history[:-MAX_PERSISTED_EVENTS]


def project_for_ui(
    history: Iterable[dict],
    max_events: int = MAX_UI_EVENTS,
    max_chars: int = MAX_UI_CHARS,
) -> tuple[list[dict], int]:
    """Return a bounded newest-first-fit projection and omitted event count."""
    visible = [event for event in history if event.get("type") in PERSISTED_EVENT_TYPES]
    selected: list[dict] = []
    used = 0
    for event in reversed(visible):
        bounded = {"type": event.get("type"), "data": _bounded_value(event.get("data"))}
        size = len(str(bounded))
        if len(selected) >= max_events or (selected and used + size > max_chars):
            break
        selected.append(bounded)
        used += size
    selected.reverse()
    return selected, max(0, len(visible) - len(selected))


def normalize_persisted(history: Iterable[dict]) -> list[dict]:
    """Migrate legacy telemetry-heavy history to the current persisted form."""
    visible = []
    for event in history:
        event_type = str(event.get("type", ""))
        if event_type in PERSISTED_EVENT_TYPES:
            visible.append({"type": event_type, "data": _bounded_value(event.get("data"))})
    return visible[-MAX_PERSISTED_EVENTS:]
