import json
from dataclasses import dataclass
from typing import Any


_ERROR_PREFIXES = (
    "error:",
    "tool error:",
    "validation failed:",
    "traceback (most recent call last):",
)
_ERROR_JSON_KEYS = ("error", "errors")


@dataclass(frozen=True)
class ToolOutcome:
    ok: bool
    content: str
    code: str = "ok"
    exit_code: int | None = None
    duration_ms: int | None = None

    def for_model(self) -> str:
        if self.ok:
            return self.content
        return f"Error: {self.content}"


def classify_tool_outcome(result: Any) -> ToolOutcome:
    """Convert an explicit tool result into a model-visible outcome.

    The classifier intentionally does not scan successful plain text for words
    such as FAIL/FAILED/N failed. A read tool may legitimately return source,
    logs, documentation, or tests containing those strings. Tool failures must
    be reported structurally (ToolOutcome/dict) or by the tool runner's explicit
    error prefixes.
    """
    if isinstance(result, ToolOutcome):
        return result
    if isinstance(result, dict):
        ok = result.get("ok")
        if isinstance(ok, bool):
            content = result.get("content", result.get("error", result.get("message", "")))
            return ToolOutcome(
                ok=ok,
                content=str(content),
                code=str(result.get("error_code", result.get("code", "ok" if ok else "tool_error"))),
                exit_code=result.get("exit_code") if isinstance(result.get("exit_code"), int) else None,
                duration_ms=result.get("duration_ms") if isinstance(result.get("duration_ms"), int) else None,
            )
    content = str(result)
    stripped = content.strip()
    lowered = stripped.lower()
    if lowered.startswith(_ERROR_PREFIXES):
        return ToolOutcome(False, content, "tool_error")
    try:
        value = json.loads(stripped)
    except (TypeError, json.JSONDecodeError):
        value = None
    if isinstance(value, dict):
        ok = value.get("ok")
        if isinstance(ok, bool):
            body = value.get("content", value.get("error", value.get("message", content)))
            return ToolOutcome(
                ok=ok,
                content=str(body),
                code=str(value.get("error_code", value.get("code", "ok" if ok else "tool_error"))),
                exit_code=value.get("exit_code") if isinstance(value.get("exit_code"), int) else None,
                duration_ms=value.get("duration_ms") if isinstance(value.get("duration_ms"), int) else None,
            )
        if any(value.get(key) for key in _ERROR_JSON_KEYS):
            return ToolOutcome(False, content, "tool_error")
    return ToolOutcome(True, content)


class AgentRuntime:
    """Tracks progress invariants for one agent turn."""

    def __init__(
        self,
        max_tool_calls: int | None = None,
        max_identical_calls: int = 2,
        max_consecutive_failures: int = 4,
    ):
        self.max_tool_calls = max_tool_calls
        self.max_identical_calls = max_identical_calls
        self.max_consecutive_failures = max_consecutive_failures
        self.tool_calls = 0
        self.consecutive_failures = 0
        self._signatures: dict[str, int] = {}
        self.changed_files = False
        self.verified_after_change = False
        self.verification_reminder_sent = False
        self.active = False

    def snapshot(self) -> dict[str, Any]:
        """Return JSON-safe state for crash recovery and session persistence."""
        return {
            "version": 1,
            "active": self.active,
            "max_tool_calls": self.max_tool_calls,
            "max_identical_calls": self.max_identical_calls,
            "max_consecutive_failures": self.max_consecutive_failures,
            "tool_calls": self.tool_calls,
            "consecutive_failures": self.consecutive_failures,
            "signatures": dict(self._signatures),
            "changed_files": self.changed_files,
            "verified_after_change": self.verified_after_change,
            "verification_reminder_sent": self.verification_reminder_sent,
        }

    @classmethod
    def from_snapshot(cls, snapshot: Any, **defaults) -> "AgentRuntime":
        """Restore a runtime snapshot, tolerating old or malformed session data."""
        data = snapshot if isinstance(snapshot, dict) else {}
        runtime = cls(
            max_tool_calls=data.get("max_tool_calls", defaults.get("max_tool_calls")),
            max_identical_calls=int(data.get("max_identical_calls", defaults.get("max_identical_calls", 2))),
            max_consecutive_failures=int(data.get("max_consecutive_failures", defaults.get("max_consecutive_failures", 4))),
        )
        runtime.active = bool(data.get("active", False))
        runtime.tool_calls = max(0, int(data.get("tool_calls", 0)))
        runtime.consecutive_failures = max(0, int(data.get("consecutive_failures", 0)))
        signatures = data.get("signatures", {})
        if isinstance(signatures, dict):
            runtime._signatures = {
                str(key): max(0, int(value))
                for key, value in signatures.items()
                if isinstance(value, (int, float, str)) and str(value).lstrip("-").isdigit()
            }
        runtime.changed_files = bool(data.get("changed_files", False))
        runtime.verified_after_change = bool(data.get("verified_after_change", False))
        runtime.verification_reminder_sent = bool(data.get("verification_reminder_sent", False))
        return runtime

    @staticmethod
    def _signature(action: str, arguments: dict) -> str:
        return f"{action}:{json.dumps(arguments, ensure_ascii=False, sort_keys=True, default=str)}"

    def allow(self, action: str, arguments: dict) -> tuple[bool, str]:
        signature = self._signature(action, arguments)
        seen = self._signatures.get(signature, 0)
        if seen >= self.max_identical_calls:
            return False, "This exact tool call was already attempted twice. Do not retry it; choose a different approach or report the blocker."
        self.tool_calls += 1
        self._signatures[signature] = seen + 1
        return True, ""

    def allow_batch(self, calls: list[tuple[str, dict]]) -> tuple[bool, str]:
        """Atomically admit or reject a model-emitted tool-call batch."""
        pending = dict(self._signatures)
        for action, arguments in calls:
            signature = self._signature(action, arguments)
            seen = pending.get(signature, 0)
            if seen >= self.max_identical_calls:
                return False, "This exact tool call was already attempted twice. Do not retry it; choose a different approach or report the blocker."
            pending[signature] = seen + 1
        self._signatures = pending
        self.tool_calls += len(calls)
        return True, ""

    def observe(self, action: str, arguments: dict, outcome: ToolOutcome, tool=None) -> tuple[bool, str]:
        if outcome.ok:
            self.consecutive_failures = 0
        else:
            self.consecutive_failures += 1

        mutating = False
        verifying = False
        if tool is not None:
            try:
                mutating = bool(tool.is_mutating(arguments))
            except (AttributeError, TypeError, ValueError):
                pass
            try:
                verifying = bool(tool.is_verification(arguments))
            except (AttributeError, TypeError, ValueError):
                pass

        # Name/argument fallbacks keep older external tools compatible while
        # built-in tools migrate to explicit capabilities.
        if not mutating:
            mutating = (
                (action == "edit" and bool(arguments.get("edits")))
                or (action == "write" and bool(arguments.get("content")))
            )
        if not verifying:
            verifying = action == "project_test"

        if mutating and outcome.ok:
            self.changed_files = True
            self.verified_after_change = False
        elif verifying and outcome.ok:
            self.verified_after_change = True

        if self.consecutive_failures >= self.max_consecutive_failures:
            return False, f"Stopped after {self.consecutive_failures} consecutive tool failures. Report the blocker instead of trying more tools."
        return True, ""

    def needs_verification(self) -> bool:
        return self.changed_files and not self.verified_after_change

    def can_request_verification(self) -> bool:
        return self.needs_verification() and not self.verification_reminder_sent

    def mark_verification_reminder(self) -> None:
        self.verification_reminder_sent = True

