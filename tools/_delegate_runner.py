"""Detached delegate agent runner - runs a sub-agent turn in a subprocess.

Spawned by the delegate watcher loop. Uses the same provider classes as the
main agent (OllamaProvider / OpenAIProvider) so protocol details stay consistent.
"""

import argparse
import json
import os
import sys
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.stderr.reconfigure(encoding="utf-8", errors="replace")

MAX_DELEGATE_TURNS = 30
MAX_TRANSIENT_RETRIES = 30


def _is_transient_provider_error(error_text: str) -> bool:
    text = str(error_text or "").lower()
    permanent = (
        "http 400", "http 401", "http 403", "http 404", "model not found",
        "invalid api key", "invalid model", "malformed sse json", "invalid request",
    )
    if any(marker in text for marker in permanent):
        return False
    transient = (
        "could not connect", "connection", "timed out", "timeout", "network",
        "protocolerror", "502", "503", "504", "readtimeout", "connecttimeout",
        "connection reset", "connection aborted",
    )
    return any(marker in text for marker in transient)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _write_metadata(path: Path, updates: dict) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        data = {}
    data.update(updates)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, path)
    return data


def _build_tool_defs(tool_manager) -> list[dict] | None:
    tools = tool_manager.load_tools()
    if not tools:
        return None
    defs = []
    for name, tool in tools.items():
        meta = tool_manager.registry.get(name) if hasattr(tool_manager, 'registry') else None
        desc = ""
        raw_params = None
        if meta:
            raw_params = meta.get("parameters")
            desc = meta.get("description", "")
        if not desc:
            desc = getattr(tool, "description", name)
        if not isinstance(raw_params, dict):
            raw_params = getattr(tool, "parameters", None)
        params = {"type": "object", "properties": {}, "required": []}
        if raw_params and isinstance(raw_params, dict):
            clean_props = {}
            for key, spec in raw_params.items():
                if not isinstance(spec, dict):
                    clean_props[key] = spec
                    continue
                cleaned = {k: v for k, v in spec.items() if k not in ("required", "default")}
                clean_props[key] = cleaned
            params["properties"] = clean_props
            params["required"] = [
                key for key, spec in raw_params.items()
                if isinstance(spec, dict) and spec.get("required", False)
            ]
        defs.append({
            "type": "function",
            "function": {"name": name, "description": desc, "parameters": params},
        })
    return defs if defs else None


def _build_system_prompt(tool_manager) -> str:
    tools = tool_manager.load_tools()
    tool_names = sorted(tools.keys()) if tools else []
    tool_list = ", ".join(tool_names)
    return f"""You are Chengsi (澄思), a pragmatic agent with local tools.
Complete the task assigned to you. Use available tools instead of giving instructions.
Inspect before editing. Never claim success when tool output contains errors.
If an attempt fails, change approach; never repeat the same call more than twice.
Be concise: return a tool call or the final answer.
Available tools: {tool_list}
To get the current date/time, use get_current_time() instead of bash date."""


def run_delegate(metadata_path: str) -> int:
    path = Path(metadata_path)
    metadata = json.loads(path.read_text(encoding="utf-8"))

    delegate_id = metadata["delegate_id"]
    prompt = metadata["prompt"]
    session_id = metadata.get("session_id", "")

    # ── Provider setup (use the same provider classes as the main agent) ──
    from core.tool_manager import ToolManager
    from core.agent_runtime import AgentRuntime, classify_tool_outcome

    provider_cfg = metadata.get("__provider_cfg", {})
    provider_type = metadata.get("__provider_type") or provider_cfg.get("type") or "ollama"
    if not provider_cfg:
        raise RuntimeError("Delegate has no provider configuration checkpoint; refusing to run with an empty provider config.")

    if provider_type == "ollama":
        from core.ollama_provider import OllamaProvider
        provider = OllamaProvider(provider_cfg)
    else:
        from core.openai_provider import OpenAIProvider
        provider = OpenAIProvider(provider_cfg)

    active_model = metadata.get("__model", "")
    if not active_model:
        raise RuntimeError("Delegate has no model checkpoint.")
    if isinstance(active_model, dict):
        active_model = active_model.get("name", str(active_model))

    # ── Tools ──
    tools_dir = os.path.join(PROJECT_ROOT, "tools")
    tool_manager = ToolManager(tools_dir)
    available_tools = tool_manager.load_tools()
    tool_defs = _build_tool_defs(tool_manager)

    messages = [
        {"role": "system", "content": _build_system_prompt(tool_manager)},
        {"role": "user", "content": prompt},
    ]

    _write_metadata(path, {
        "status": "running",
        "started_at": _now(),
        "model": active_model,
        "provider": provider_type,
    })

    runtime = AgentRuntime(max_tool_calls=30)
    runtime.active = True
    total_input_tokens = 0
    total_output_tokens = 0
    transient_retries = 0

    try:
        for turn in range(MAX_DELEGATE_TURNS):
            if not runtime.active:
                break

            stream = provider.chat_stream(
                active_model,
                messages,
                tool_defs=tool_defs if runtime.active else None,
            )

            full_content = ""
            stream_tool_calls: list[dict] = []
            transient_failure = False
            stream_error_text = ""

            for kind, chunk in stream:
                if kind == "content" and chunk:
                    full_content += str(chunk)
                elif kind == "tool_calls" and chunk:
                    for tc in chunk:
                        stream_tool_calls.append({
                            "id": tc.get("id", f"call_{len(stream_tool_calls)}"),
                            "function": {
                                "name": tc.get("action", ""),
                                "arguments": json.dumps(
                                    tc.get("arguments", {}), ensure_ascii=False
                                ),
                            },
                        })
                elif kind == "tokens" and isinstance(chunk, dict):
                    total_input_tokens += chunk.get("prompt", chunk.get("input", 0))
                    total_output_tokens += chunk.get("eval", chunk.get("output", 0))
                elif kind in ("error", "cancelled"):
                    error_text = f"Provider {kind}: {chunk}"
                    if kind == "error" and _is_transient_provider_error(error_text) and transient_retries < MAX_TRANSIENT_RETRIES:
                        transient_retries += 1
                        delay = min(60, 2 ** min(transient_retries - 1, 5))
                        transient_failure = True
                        stream_error_text = error_text
                        _write_metadata(path, {
                            "status": "paused",
                            "error": error_text,
                            "resume_after": _now(),
                            "messages": messages,
                            "tool_call_count": runtime.tool_calls,
                            "input_tokens": total_input_tokens,
                            "output_tokens": total_output_tokens,
                        })
                        time.sleep(delay)
                        _write_metadata(path, {"status": "running", "error": ""})
                        break
                    _write_metadata(path, {
                        "status": "failed",
                        "error": error_text,
                        "finished_at": _now(),
                        "messages": messages,
                        "tool_call_count": runtime.tool_calls,
                        "input_tokens": total_input_tokens,
                        "output_tokens": total_output_tokens,
                    })
                    return 1

            if transient_failure:
                # The checkpoint in messages is intact; restart the same model
                # step after backoff. No assistant message was appended.
                continue

            # A non-empty model response proves the provider is reachable
            # again. Keep the retry budget consecutive rather than task-wide.
            if full_content or stream_tool_calls:
                transient_retries = 0

            if not full_content and not stream_tool_calls:
                _write_metadata(path, {
                    "status": "failed",
                    "error": "Model returned empty response.",
                    "finished_at": _now(),
                    "messages": messages,
                    "tool_call_count": runtime.tool_calls,
                    "input_tokens": total_input_tokens,
                    "output_tokens": total_output_tokens,
                })
                return 1

            # ── Handle tool calls ──
            if stream_tool_calls:
                assistant_msg: dict = {
                    "role": "assistant",
                    "content": full_content or None,
                    "tool_calls": stream_tool_calls,
                }
                messages.append(assistant_msg)

                for tc in stream_tool_calls:
                    tool_name = tc["function"]["name"]
                    try:
                        tool_args = json.loads(tc["function"]["arguments"])
                    except json.JSONDecodeError:
                        tool_args = {}

                    tool = available_tools.get(tool_name)
                    if tool is None:
                        messages.append({
                            "role": "tool",
                            "content": f"Tool not found: {tool_name}",
                            "tool_call_id": tc["id"],
                        })
                        continue

                    allowed, reason = runtime.allow(tool_name, tool_args)
                    if not allowed:
                        messages.append({
                            "role": "tool",
                            "content": reason,
                            "tool_call_id": tc["id"],
                        })
                        continue

                    if tool_name in {"system_cleaner", "job", "schedule", "delegate", "plan"}:
                        tool_args = dict(tool_args)
                        tool_args["_session_id"] = session_id

                    try:
                        result = tool.run(tool_args)
                        content = result if isinstance(result, str) else json.dumps(
                            result, ensure_ascii=False, default=str
                        )
                    except Exception as exc:
                        content = f"Tool error: {exc}"

                    messages.append({
                        "role": "tool",
                        "content": content,
                        "tool_call_id": tc["id"],
                    })

                _write_metadata(path, {
                    "messages": messages,
                    "tool_call_count": runtime.tool_calls,
                    "input_tokens": total_input_tokens,
                    "output_tokens": total_output_tokens,
                })
                continue  # next turn

            # ── No tool calls = final answer ──
            if full_content:
                messages.append({"role": "assistant", "content": full_content})
            runtime.active = False
            break

        # ── Done ──
        status = "completed"
        summary = ""
        for msg in reversed(messages):
            if msg.get("role") == "assistant" and msg.get("content"):
                content = str(msg["content"])
                if len(content) > 50:
                    summary = content[:800]
                break

        _write_metadata(path, {
            "status": status,
            "error": "",
            "summary": summary,
            "finished_at": _now(),
            "messages": messages,
            "tool_call_count": runtime.tool_calls,
            "input_tokens": total_input_tokens,
            "output_tokens": total_output_tokens,
        })
        return 0

    except Exception as exc:
        _write_metadata(path, {
            "status": "failed",
            "error": f"{type(exc).__name__}: {exc}",
            "finished_at": _now(),
            "messages": messages,
            "tool_call_count": runtime.tool_calls,
            "input_tokens": total_input_tokens,
            "output_tokens": total_output_tokens,
        })
        traceback.print_exc(file=sys.stderr)
        return 1


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("metadata", help="Path to delegate metadata JSON")
    args = parser.parse_args()
    return run_delegate(args.metadata)


if __name__ == "__main__":
    raise SystemExit(main())
