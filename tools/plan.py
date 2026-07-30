"""
Tool: plan — Light-weight task planning and progress tracking.

Replaces TURN_TOOL_SUMMARY with a compact PLAN_MARKER that the model
can read and update explicitly. The marker is the single anchor for
cross-turn memory; it never accumulates stale copies.
"""

from __future__ import annotations
import json
from typing import Any

from tools.base import BaseTool


class Plan(BaseTool):
    @property
    def tool_name(self) -> str:
        return "plan"

    @property
    def description(self) -> str:
        return (
            "Track task progress across turns. Use this to remember what you are doing, "
            "what you have completed, and what to do next. Actions: show, update, done, clear.\n"
            "- show: read the current plan\n"
            "- update: set the plan content (overwrites). Provide 'goal' and 'next' strings, "
            "plus optional 'done' (list of completed items) and 'notes' (list of constraints/findings).\n"
            "- done: mark the current goal as complete (optionally with a final note)\n"
            "- clear: wipe the plan"
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "action": {
                "type": "string",
                "enum": ["show", "update", "done", "clear"],
                "description": "Which plan operation to perform",
                "required": True,
            },
            "goal": {
                "type": "string",
                "description": "One-line current goal (for update action)",
            },
            "next": {
                "type": "string",
                "description": "One-line next action (for update action)",
            },
            "done": {
                "type": "array",
                "items": {"type": "string"},
                "description": "List of completed items (for update action)",
            },
            "notes": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Key findings or constraints (for update action)",
            },
            "final_note": {
                "type": "string",
                "description": "Final summary when marking done",
            },
        }

    def run(self, arguments: dict[str, Any]) -> str:
        action = str(arguments.get("action", "show")).strip().lower()
        session_id = str(arguments.get("_session_id", ""))
        if not session_id:
            return "Error: no session context available for plan tracking."

        goal = str(arguments.get("goal", ""))
        nxt = str(arguments.get("next", ""))
        done = arguments.get("done", None)
        notes = arguments.get("notes", None)
        final_note = str(arguments.get("final_note", ""))

        # Access session state via the global state singleton
        from main import state
        sd = state.sessions.get(session_id)
        if sd is None:
            return f"Session {session_id} not found."

        if action == "show":
            plan = self._read_plan(sd)
            if not plan:
                return "No plan set yet. Use plan(action='update') to create one."
            return self._format_plan(plan)

        if action == "clear":
            sd.messages = [m for m in sd.messages
                          if not str(m.get("content", "")).startswith("[PLAN_MARKER]")]
            self._save(sd, session_id)
            return "Plan cleared."

        if action == "done":
            plan = self._read_plan(sd) or {}
            if not plan:
                return "No plan to complete."
            plan["status"] = "done"
            if final_note:
                plan.setdefault("notes", []).append(f"DONE: {final_note}")
            self._write_plan(sd, plan)
            self._save(sd, session_id)
            msg = f"Goal marked done: {plan.get('goal', '')}"
            if final_note:
                msg += f"\nNote: {final_note}"
            return msg

        if action == "update":
            plan = self._read_plan(sd) or {}
            if goal:
                plan["goal"] = goal
            if nxt:
                plan["next"] = nxt
            if done is not None:
                plan["done"] = done
            if notes is not None:
                plan["notes"] = notes
            plan["status"] = "active"
            self._write_plan(sd, plan)
            self._save(sd, session_id)
            return "Plan updated:\n" + self._format_plan(plan)

        return f"Unknown plan action: {action}"

    # ── helpers ──

    def _read_plan(self, sd) -> dict | None:
        for m in sd.messages:
            content = str(m.get("content", ""))
            if content.startswith("[PLAN_MARKER]"):
                try:
                    start = content.find("{")
                    end = content.rfind("}")
                    if start >= 0 and end > start:
                        return json.loads(content[start:end + 1])
                except (json.JSONDecodeError, ValueError):
                    pass
                return {"raw": content.replace("[PLAN_MARKER]", "").replace("[/PLAN_MARKER]", "").strip()}
        return None

    def _write_plan(self, sd, plan: dict) -> None:
        sd.messages = [m for m in sd.messages
                      if not str(m.get("content", "")).startswith("[PLAN_MARKER]")]
        insert_at = 1 if sd.messages and sd.messages[0].get("role") == "system" else 0
        marker = "[PLAN_MARKER]\n" + json.dumps(plan, ensure_ascii=False, indent=2) + "\n[/PLAN_MARKER]"
        sd.messages.insert(insert_at, {"role": "user", "content": marker})

    def _format_plan(self, plan: dict) -> str:
        lines = []
        if plan.get("goal"):
            lines.append(f"Goal: {plan['goal']}")
        if plan.get("status"):
            lines.append(f"Status: {plan['status']}")
        if plan.get("done"):
            lines.append("Completed:")
            for item in plan["done"]:
                lines.append(f"  ✓ {item}")
        if plan.get("next"):
            lines.append(f"Next: {plan['next']}")
        if plan.get("notes"):
            lines.append("Notes:")
            for n in plan["notes"]:
                lines.append(f"  • {n}")
        return "\n".join(lines) if lines else str(plan)

    def _save(self, sd, session_id: str) -> None:
        from main import _session_manager, state
        if _session_manager and session_id in state.sessions:
            _session_manager.save(
                session_id,
                sd.messages,
                history=list(sd.history),
                token_stats={
                    "input": sd.input_tokens,
                    "output": sd.output_tokens,
                    "prompt": sd.prompt_tokens,
                    "eval": sd.eval_tokens,
                    "ctx": sd.ctx_tokens,
                    "compressed_prompt_base": sd.compressed_prompt_base,
                    "compressed_context_size": sd.compressed_context_size,
                    "runtime": sd.runtime_snapshot,
                },
            )
