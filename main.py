import sys, os, json, time, threading, queue, re, signal, subprocess, base64, shutil
from concurrent.futures import ThreadPoolExecutor, as_completed

from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import unquote, urlparse

# ── Project Path Setup ──────────────────────────────────────────────
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
if PROJECT_ROOT not in sys.path:
    sys.path.append(PROJECT_ROOT)

from core.agent_runtime import AgentRuntime, ToolOutcome, classify_tool_outcome
from core.tool_manager import ToolManager
from core.session_manager import SessionManager
from core.knowledge_base import KnowledgeBase

# Clean up stderr to prevent warnings from polluting the Agent's view
class FilteredStderr:
    def __init__(self, original_stderr):
        self.original_stderr = original_stderr
    def write(self, data):
        if "RuntimeWarning" not in data and "DeprecationWarning" not in data:
            self.original_stderr.write(data)
    def flush(self):
        self.original_stderr.flush()

sys.stderr = FilteredStderr(sys.stderr)
if hasattr(sys.stdout, 'reconfigure'):
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    except:
        pass


# ══════════════════════════════════════════════════════════════════════
#  1. AGENT STATE — per-session singleton bridging engine ↔ UI
# ══════════════════════════════════════════════════════════════════════

class SessionData:
    """Per-session runtime state."""
    def __init__(self):
        self.messages: list[dict] = []
        self.history: list[dict] = []
        self.prompt_tokens: int = 0
        self.eval_tokens: int = 0
        self.input_tokens: int = 0
        self.output_tokens: int = 0
        self.processing: bool = False
        self.cancel = threading.Event()
        self.event_queue: queue.Queue = queue.Queue()
        self.compressed_prompt_base: int = 0
        self.compressed_context_size: int = 0
        self.ctx_tokens: int = 0
        self.runtime_snapshot: dict = {}
        self._active_provider = None


class AgentState:
    """Global state for SSE-driven web UI and agent engine."""
    def __init__(self):
        self.sessions: dict[str, SessionData] = {}
        self.name: str = "Chengsi (澄思)"
        self.show_thinking: bool = True
        self.theme: str = "day"
        self.parallel_tools: bool = False
        self.fallback_mode: bool = False
        self.auto_install_dependencies: bool = False
        self.interface_mode: str = "web"
        self.current_session_id: str = ""
        self.knowledge_base = None

    def get(self, session_id: str = "") -> SessionData | None:
        return self.sessions.get(session_id or self.current_session_id)

    def ensure(self, session_id: str) -> SessionData:
        if session_id not in self.sessions:
            self.sessions[session_id] = SessionData()
        return self.sessions[session_id]

    def emit(self, event_type: str, data, session_id: str = ""):
        """Record event to per-session queue + history."""
        session_id = session_id or self.current_session_id
        sd = self.sessions.get(session_id)
        if not sd:
            return
        if event_type not in ("thinking", "thinking_delta", "agent_delta"):
            sd.history.append({"type": event_type, "data": data})
        payload = {
            "timestamp": datetime.now().strftime("%H:%M:%S"),
            "type": event_type,
            "data": data,
            "session_id": session_id,
        }
        sd.event_queue.put(json.dumps(payload))

    def cli_print(self, event_type: str, data):
        """Print to terminal in CLI mode."""
        prefix_map = {
            "user":       "You",
            "agent":      "Agent",
            "thinking":   "...",
            "tool_call":  "🔧 Tool Call",
            "tool_result":"📋 Result",
        }
        prefix = prefix_map.get(event_type, event_type)
        print(f"[{prefix}]: {data}")


state = AgentState()


# ══════════════════════════════════════════════════════════════════════
#  2. CONFIG HELPERS
# ══════════════════════════════════════════════════════════════════════

def load_config(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def discover_skills() -> list[dict[str, str]]:
    """Discover lightweight SKILL.md summaries without loading full instructions."""
    skills_root = Path(PROJECT_ROOT) / "skills"
    if not skills_root.is_dir():
        return []
    skills = []
    for path in sorted(skills_root.glob("*/SKILL.md")):
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            continue
        name_match = re.search(r"^name:\s*(.+?)\s*$", text, re.MULTILINE)
        description_match = re.search(r"^description:\s*(.+?)\s*$", text, re.MULTILINE)
        name = (name_match.group(1).strip().strip('\\\"') if name_match else path.parent.name)
        description = description_match.group(1).strip().strip('\\\"') if description_match else ""
        if description:
            skills.append({"name": name, "description": description, "path": str(path)})
    return skills


def _skills_prompt() -> str:
    skills = discover_skills()
    if not skills:
        return ""
    lines = ["Available local skills (read the SKILL.md file only when relevant):"]
    lines.extend(f"- {item['name']}: {item['description']}" for item in skills)
    return "\n".join(lines)


# ══════════════════════════════════════════════════════════════════════
#  3. MODEL PROVIDER
# ══════════════════════════════════════════════════════════════════════

from core.ollama_provider import OllamaProvider
from core.openai_provider import OpenAIProvider


PROVIDER_MAP = {
    "ollama": OllamaProvider,
    "openai": OpenAIProvider,
}


def init_providers(config: dict) -> tuple[list[dict], dict[str, str]]:
    """Load provider configs from config.json. Supports new & legacy format.

    Returns (providers_list, model_to_provider_map).
    """
    providers_raw = config.get("providers")
    if providers_raw and isinstance(providers_raw, list):
        return providers_raw, {}

    # Legacy format: single Ollama provider from top-level keys
    return [
        {
            "type": "ollama",
            "name": "Local Ollama",
            "base_url": config.get("ollama_base_url", "http://localhost:11434/api"),
            "models": config.get("models", []),
        }
    ], {}


def _model_config(model_entry) -> tuple[str, dict]:
    """Normalize legacy string and object model configuration entries."""
    if isinstance(model_entry, dict):
        name = str(model_entry.get("name", "")).strip()
        return name, model_entry
    return str(model_entry).strip(), {}


def _get_model_capabilities(providers_cfg: list[dict], provider_idx: int, model: str) -> dict:
    """Return configured capabilities for a provider/model pair."""
    if not 0 <= provider_idx < len(providers_cfg):
        return {}
    for entry in providers_cfg[provider_idx].get("models", []):
        name, capabilities = _model_config(entry)
        if name == model:
            return capabilities
    return {}


def _model_request_api(model_config: dict | None) -> str:
    """Return the explicit request API for an OpenAI-compatible model."""
    value = str((model_config or {}).get("request_api", "chat_completions")).strip()
    return value if value in ("chat_completions", "responses") else "chat_completions"


def _get_provider_model_capabilities(providers_cfg: list[dict], provider, model: str) -> dict:
    """Return capabilities for an active provider/model pair."""
    provider_name = getattr(provider, "name", "")
    for idx, pcfg in enumerate(providers_cfg):
        if pcfg.get("name", "") == provider_name:
            capabilities = _get_model_capabilities(providers_cfg, idx, model)
            if capabilities:
                return capabilities
    return {}


def build_model_choices(providers_cfg: list[dict]) -> list[tuple[str, str, str]]:
    """Return list of (label, provider_idx, model_name)."""
    choices = []
    for idx, pcfg in enumerate(providers_cfg):
        ptype = pcfg.get("type", "ollama")
        pname = pcfg.get("name", ptype)
        for entry in pcfg.get("models", []):
            model, _ = _model_config(entry)
            if model:
                choices.append((f"[{pname}] {model}", str(idx), model))
    return choices


# ══════════════════════════════════════════════════════════════════════
#  4. SYSTEM PROMPT BUILDER
# ══════════════════════════════════════════════════════════════════════

def format_system_prompt(available_tools: dict = None, tool_manager=None,
                         failure_alert: str | None = None, native_tools: bool = False) -> str:
    p = """You are Chengsi (澄思), a pragmatic agent with local tools and a knowledge base.
Complete the user's task. When asked to act, use an available tool instead of giving instructions.
Inspect before editing when needed. Validate results when the user asks for checks or when the task itself requires verification; do not run project_test by default. Never claim success when tool output contains errors.
For background jobs, always report completion, failure, interruption, or cancellation when notified. Set job.start auto_followup=true only when the user's original request explicitly asks for work to continue automatically after completion (for example, generate a report from the finished scan); otherwise leave it false and only notify the user.
If an attempt fails, change approach; never repeat the same call more than twice.
Keep a concise task state and emit brief progress checkpoints when useful: what you found, what you are doing next, or what is blocked. Do not write a long preamble; act as soon as the next action is clear. Return only a tool call, a necessary clarification, or the final answer.
Do not create a new tool unless the user explicitly asks for a reusable tool. Do not modify Chengsi's own core/ directory or main.py; other projects may be modified when requested.
Use the knowledge base or web only when the answer needs external facts, freshness, or citations; do not browse for routine local work.
When multiple independent operations can proceed simultaneously (e.g., reading several files, searching several paths), issue them as a batch of tool calls in a single response.

Important: To get the current date/time, use get_current_time() instead of 'bash date' (which hangs on Windows). Use bash only for actual shell operations.

For scheduled/delayed tasks: When the user mentions a specific time (e.g., "17:30打开记事本", "明天9点提醒我", "10分钟后..."), use schedule() to create a timed task. Do NOT execute immediately unless the user explicitly says "现在" or "立即".

For long or complex sub-tasks: Use delegate(action='start', prompt='...') to spawn a background sub-agent that has full tool access (bash, read, write, edit, web_searcher, python_executor, etc.). The sub-agent runs autonomously and reports results back. This is ideal for multi-step research, large data processing, code audits, or any task that would take many turns. Check sub-agent status with delegate(action='status', delegate_id='...') or list all with delegate(action='list'). You (the main agent) stay available for the user while the sub-agent works.

For task tracking: Use plan(action='show') to read current progress and plan(action='update', goal='...', next='...', done=[...]) to keep your plan current. This prevents you from losing context across many turns. The plan is compact — just goal, completed items, and next step."""
    if failure_alert:
        p += f"\nExecution alert: {failure_alert}. Stop retrying and report the blocker or choose a materially different approach."

    skills = _skills_prompt()
    if skills:
        p += "\n\n" + skills
    p += "\n\nControl commands handled directly by Chengsi: /tool list, /tool reload, /knowledge list, /knowledge search <query>, /knowledge add <file-or-folder>."
    return p


# ══════════════════════════════════════════════════════════════════════
#  5. AGENT LOOP (shared by CLI & Web modes)
# ══════════════════════════════════════════════════════════════════════

# Pi-style runtime safety uses targeted guards instead of a fixed per-turn
# tool-count wall: identical-call protection, real consecutive failures,
# cancellation, truncation, and context management remain active.
_MAX_TOOL_CALLS = None


def _emit(event_type: str, data, session_id: str = ""):
    if state.interface_mode == "web":
        state.emit(event_type, data, session_id=session_id)
    else:
        state.cli_print(event_type, data)


# ─── Tool output truncation ──────────────────────────────────────────
_MAX_TOOL_OUTPUT_CHARS = 3000

def _store_full_output(session_id: str, content: str) -> str:
    """Save full tool output to a temp file, return the file path."""
    import tempfile
    safe_name = session_id.replace("/", "_").replace("\\", "_")
    path = os.path.join(tempfile.gettempdir(), f"chengsi_out_{safe_name}.txt")
    try:
        with open(path, "w", encoding="utf-8", errors="replace") as f:
            f.write(content)
    except Exception:
        pass
    return path

def _truncate_output(result: str, session_id: str) -> str:
    """Keep the start and diagnostic tail; store the complete output as an artifact."""
    result = str(result)
    if len(result) <= _MAX_TOOL_OUTPUT_CHARS:
        return result
    file_path = _store_full_output(session_id, result)
    head_size = _MAX_TOOL_OUTPUT_CHARS // 2
    tail_size = _MAX_TOOL_OUTPUT_CHARS - head_size
    omitted = len(result) - head_size - tail_size
    note = (
        f"\n\n--- [OUTPUT TRUNCATED] {omitted} middle chars omitted ---\n"
        f"Full output: {file_path}\n\n"
    )
    return result[:head_size] + note + result[-tail_size:]


def _strip_thinking_prefix(text: str) -> str:
    """Remove model reasoning/thinking prefixes that leak into content.

    Some models include their chain-of-thought in the content field.
    Patterns handled:
      - <thinking>...</thinking> blocks
      - English: 'The user wants...', 'I need to...', 'Let me...', 'Plan:', 'Step N:'
      - Internal narration such as 'The user wants...', 'I need to...', 'Let me...', 'Plan:', or 'Steps:'
      - Numbered reasoning steps: '1. **Identify...**:', 'Step 1:', 'Plan:'
      - Markdown reasoning: lines starting with '**word**: ...' or '- **word**: ...'
    """
    if not text:
        return text
    cleaned = text

    # 1. Strip private reasoning blocks that some local models place in content.
    cleaned = re.sub(r'<(?:thinking|think)>.*?</(?:thinking|think)>\s*', '', cleaned, flags=re.DOTALL | re.IGNORECASE)
    # Handle an unterminated block at the end of a streamed response.
    cleaned = re.sub(r'<(?:thinking|think)>.*$', '', cleaned, flags=re.DOTALL | re.IGNORECASE)

    # 2. Strip leading English thinking patterns (first paragraph)
    en_pattern = re.match(
        r'^(?:\s*\n)*'
        r'(?:The user wants?.*?\n\n'
        r'|I need to.*?\n\n'
        r'|Let me.*?\n\n'
        r'|Based on.*?\n\n'
        r'|My (?:previous )?(?:thought|plan|task).*?\n\n'
        r'|The user (?:is |said ).*?\n\n'
        r'|Plan:\s*\n'
        r'|First step:.*?\n\n)'
        , cleaned, re.DOTALL)
    if en_pattern:
        cleaned = cleaned[en_pattern.end():]

    # 3. Strip leading Chinese thinking patterns (first paragraph)
    zh_pattern = re.match(
        r'^(?:\s*\n)*'
        r'(?:用户想要.*?\n\n'
        r'|我需要.*?\n\n'
        r'|让我.*?\n\n'
        r'|根据.*?分析.*?\n\n'
        r'|用户的请求.*?\n\n'
        r'|我之前的.*?\n\n'
        r'|Plan:\s*\n'
        r'|First,.*?\n\n)'
        , cleaned, re.DOTALL)
    if zh_pattern:
        cleaned = cleaned[zh_pattern.end():]

    # 4. Strip numbered reasoning steps at the start:
    #    "1. **Identify...**:\n..." or "Step 1: ...\n"
    #    Keep stripping as long as we see numbered/bold reasoning lines
    step_pattern = re.compile(
        r'^(?:\s*\n)*'
        r'(?:'
        r'(?:\d+\.\s+\*\*.*?\*\*:.*?\n'   # "1. **Word**: description"
        r'|Step\s+\d+:.*?\n'                # "Step 1: do X"
        r'|\*\*.*?\*\*:\s*\n'              # "**Plan**:\n"
        r'|Plan:\s*\n'                       # "Plan:\n"
        r')'
        r'(?:\s*\n)*'                       # optional blank lines between steps
        r')+'
        , re.MULTILINE)
    m = step_pattern.match(cleaned)
    if m:
        cleaned = cleaned[m.end():]

    # 5. Strip leading markdown reasoning blocks:
    #    "- **Action**: do something\n- **Reason**: because..."
    bullet_pattern = re.compile(
        r'^(?:\s*\n)*'
        r'(?:-\s+\*\*.*?\*\*:.*?\n)+'
        r'\s*\n*'
        , re.MULTILINE)
    m = bullet_pattern.match(cleaned)
    if m:
        cleaned = cleaned[m.end():]

    # 6. If nothing left after stripping, return original (safety)
    return cleaned.strip() or text.strip()


def _provider_messages(provider, messages: list[dict]) -> list[dict]:
    """Return the exact message shape that a provider sends to its API."""
    prepare = getattr(provider, "prepare_messages", None)
    return prepare(messages) if callable(prepare) else messages


def _estimate_ctx_tokens(messages: list[dict], model: str = "", provider=None) -> int:
    """Estimate tokens using the provider's final outbound message shape."""
    messages = _provider_messages(provider, messages) if provider else messages
    try:
        import tiktoken
        try:
            enc = tiktoken.encoding_for_model(model) if model else tiktoken.get_encoding("cl100k_base")
        except Exception:
            enc = tiktoken.get_encoding("cl100k_base")
        total = 2  # reply priming
        for m in messages:
            total += 4  # per-message overhead
            content = m.get("content", "")
            if isinstance(content, list):
                content = json.dumps(content, ensure_ascii=False)
            if isinstance(content, str):
                total += len(enc.encode(content))
            # Count tool_calls arguments if present
            for tc in m.get("tool_calls", []):
                func = tc.get("function", {})
                for v in func.values():
                    if isinstance(v, str):
                        total += len(enc.encode(v))
        return max(1, total)
    except ImportError:
        text = json.dumps(messages, ensure_ascii=False)
        return max(1, len(text) // 4)


def build_tool_defs(tool_manager, available_tools: dict) -> list[dict] | None:
    if not available_tools:
        return None
    defs = []
    for name, tool in available_tools.items():
        meta = tool_manager.registry.get(name) if (tool_manager and hasattr(tool_manager, 'registry')) else None
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


def _is_native(provider, model_config: dict | None = None) -> bool:
    """Return native tool support, allowing explicit per-model overrides."""
    if isinstance(model_config, dict) and "tools" in model_config:
        return bool(model_config.get("tools"))
    return getattr(provider, "supports_native_tools", False)


def _verification_tool_outcome(action: str, result: str) -> ToolOutcome | None:
    """Return a structured failure only for tools whose job is verification."""
    if action != "project_test":
        return None
    failed = bool(re.search(
        r"(?:^|\n)\s*(?:FAIL\b|FAILED\s*\(|\[[^\]]+\]\s*(?:FAIL\b|.*?[1-9]\d*\s+failed\b))",
        result,
        re.IGNORECASE,
    ))
    return ToolOutcome(
        ok=not failed,
        content=result,
        code="verification_failed" if failed else "ok",
    )


def _execute_tool(action: str, args: dict, available_tools: dict, session_id: str, tool_call_id: str | None = None):
    if action in {"system_cleaner", "job", "schedule", "delegate", "plan"} and isinstance(args, dict):
        args = dict(args)
        args["_session_id"] = session_id
    started = time.time()
    call_id = tool_call_id or f"{action}-{int(started * 1000)}"
    _emit("tool_execution_start", {"tool_call_id": call_id, "tool_name": action, "arguments": args}, session_id=session_id)
    _emit("tool_call", {"action": action, "arguments": args}, session_id=session_id)
    if action not in available_tools:
        names = ", ".join(sorted(available_tools)) or "none"
        err = f"Unknown tool '{action}'. Available tools: {names}"
        outcome = ToolOutcome(False, err, "unknown_tool", duration_ms=int((time.time() - started) * 1000))
        _emit("tool_execution_end", {
            "tool_call_id": call_id,
            "tool_name": action,
            "ok": False,
            "code": outcome.code,
            "duration_ms": outcome.duration_ms,
            "content": err,
        }, session_id=session_id)
        return outcome
    _emit("thinking", f"Executing {action}...", session_id=session_id)
    try:
        result = available_tools[action].run(args)
        structured = classify_tool_outcome(result)
        if isinstance(result, (dict, ToolOutcome)):
            truncated = _truncate_output(structured.content, session_id)
            outcome = ToolOutcome(
                ok=structured.ok,
                content=truncated,
                code=structured.code,
                exit_code=structured.exit_code,
                duration_ms=structured.duration_ms,
            )
        else:
            result = _publish_generated_image(result, session_id)
            truncated = _truncate_output(result, session_id)
            outcome = _verification_tool_outcome(action, str(truncated)) or classify_tool_outcome(truncated)
    except Exception as e:
        outcome = ToolOutcome(False, f"Tool error: {e}", "tool_error")
    outcome = ToolOutcome(
        ok=outcome.ok,
        content=outcome.content,
        code=outcome.code,
        exit_code=outcome.exit_code,
        duration_ms=int((time.time() - started) * 1000),
    )
    _emit("tool_execution_end", {
        "tool_call_id": call_id,
        "tool_name": action,
        "ok": outcome.ok,
        "code": outcome.code,
        "duration_ms": outcome.duration_ms,
        "content": outcome.content,
    }, session_id=session_id)
    return outcome


_IMAGE_MARKER = "__IMAGE_PATH__:"
_GENERATED_IMAGE_MARKER = "__GENERATED_IMAGE__:"


def _publish_generated_image(result, session_id: str) -> str:
    """Archive a generated-image tool artifact and emit the standard UI event."""
    text = str(result)
    marker = re.search(r"^__GENERATED_IMAGE__:(\{.*\})$", text, re.MULTILINE)
    if not marker:
        return text
    try:
        artifact = json.loads(marker.group(1))
        source = Path(str(artifact.get("path", ""))).expanduser().resolve()
        if not source.is_file():
            raise FileNotFoundError(source)
        media_dir = (Path(PROJECT_ROOT) / "media" / session_id).resolve()
        media_dir.mkdir(parents=True, exist_ok=True)
        filename = Path(str(artifact.get("filename") or source.name)).name
        target = media_dir / filename
        if source != target:
            if target.exists():
                target = media_dir / f"{target.stem}_{datetime.now().strftime('%H%M%S_%f')}{target.suffix}"
            shutil.move(str(source), str(target))
        operation = artifact.get("operation", "generate")
        label = "Image edited" if operation == "edit" else "Image generated"
        data = {
            "url": target.as_uri(),
            "path": str(target),
            "filename": target.name,
            "text": label,
        }
        _emit("image", data, session_id=session_id)
        return f"{label} successfully. Saved to {target}\n{_IMAGE_MARKER}{target}"
    except Exception as error:
        return f"Image artifact error: {error}"


def _auto_describe_image(img_path: str) -> str:
    """One-shot: send image to the default vision model and return its description."""
    spec = _default_vision_model
    if not spec:
        return "(auto-describe unavailable: no default_vision_model configured)"

    # Parse "provider/model" or bare "model"
    if "/" in spec:
        target_prov, target_model = spec.split("/", 1)
        target_prov = target_prov.strip()
        target_model = target_model.strip()
    else:
        target_prov, target_model = None, spec.strip()

    # Find the provider + model for the default vision model
    vision_provider_cfg = None
    vision_model_name = None
    for pcfg in _providers_cfg:
        if target_prov and pcfg.get("name", "") != target_prov:
            continue
        for entry in pcfg.get("models", []):
            mn = entry if isinstance(entry, str) else entry.get("name", "")
            if mn == target_model:
                vision_provider_cfg = pcfg
                vision_model_name = mn
                break
        if vision_provider_cfg:
            break

    if not vision_provider_cfg:
        who = f"'{spec}'" if not target_prov else f"'{target_model}' in provider '{target_prov}'"
        return f"(auto-describe: default vision model {who} not found in config)"

    # Build provider
    ptype = vision_provider_cfg.get("type", "openai")
    try:
        if ptype == "openai":
            from core.openai_provider import OpenAIProvider
            client = OpenAIProvider.from_config(vision_provider_cfg)
        elif ptype == "ollama":
            from core.ollama_provider import OllamaProvider
            client = OllamaProvider.from_config(vision_provider_cfg)
        else:
            return f"(auto-describe: unsupported provider type '{ptype}')"
    except Exception as e:
        return f"(auto-describe: failed to init provider — {e})"

    # Build multimodal message
    try:
        import base64, mimetypes
        ext = os.path.splitext(img_path)[1].lower()
        mime_map = {
            ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
            ".gif": "image/gif", ".bmp": "image/bmp", ".webp": "image/webp",
        }
        mime = mime_map.get(ext, "image/png")
        with open(img_path, "rb") as f:
            b64 = base64.b64encode(f.read()).decode("ascii")
        data_uri = f"data:{mime};base64,{b64}"
    except Exception as e:
        return f"(auto-describe: failed to encode image — {e})"

    messages = [
        {"role": "system", "content": "You are an image analyst. Describe the image briefly and factually in 2-4 sentences. Note any text, tables, diagrams, charts, or key visual elements. Reply in English."},
        {"role": "user", "content": [
            {"type": "text", "text": "Describe this image concisely."},
            {"type": "image_url", "image_url": {"url": data_uri}},
        ]},
    ]

    try:
        description_parts: list[str] = []
        vision_model_config = {}
        for entry in vision_provider_cfg.get("models", []):
            name, config = _model_config(entry)
            if name == vision_model_name:
                vision_model_config = config
                break
        for event_type, data in client.chat_stream(
            vision_model_name,
            messages,
            request_api=_model_request_api(vision_model_config),
        ):
            if event_type == "content":
                description_parts.append(data)
            elif event_type == "error":
                return f"(auto-describe error: {data})"
    except Exception as e:
        return f"(auto-describe error: {e})"

    desc = "".join(description_parts).strip()
    return desc if desc else "(auto-describe: no description returned)"


def _model_supports_vision(model_config: dict) -> bool:
    """Whether image input is enabled for this model in config.json."""
    return bool(model_config.get("vision", False))


def _inject_image_content(message: dict, supports_vision: bool = True) -> dict:
    """Detect __IMAGE_PATH__ marker in tool/user message content and convert
    to multimodal content format so the model can actually see the image.
    If the model doesn't support vision, auto-route to the default vision model."""
    content = message.get("content", "")
    if not isinstance(content, str) or _IMAGE_MARKER not in content:
        return message

    # Split: text before marker, then the marker line
    parts = content.split(_IMAGE_MARKER, 1)
    text_part = parts[0].rstrip("\n")
    img_path = parts[1].strip()

    if not os.path.isfile(img_path):
        return message

    # Model doesn't support vision — auto-route to default vision model
    if not supports_vision:
        description = _auto_describe_image(img_path)
        new_msg = dict(message)
        new_msg["content"] = text_part + f"\n\n[Image analysis by default vision model]:\n{description}"
        return new_msg

    try:
        import base64
        ext = os.path.splitext(img_path)[1].lower()
        mime_map = {
            ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
            ".gif": "image/gif", ".bmp": "image/bmp", ".webp": "image/webp",
            ".tiff": "image/tiff", ".tif": "image/tiff",
        }
        mime = mime_map.get(ext, "image/png")

        # Compress large images to avoid timeout — target ~100KB max
        try:
            from PIL import Image
            import io
            img = Image.open(img_path)
            # Skip palette images without alpha
            if img.mode not in ("RGB", "RGBA"):
                img = img.convert("RGB")
            # Resize if either dimension > 800px
            if max(img.size) > 800:
                img.thumbnail((800, 800), Image.LANCZOS)
            buf = io.BytesIO()
            save_kw = {"format": "JPEG", "quality": 60} if ext in (".jpg", ".jpeg") else {"format": "PNG"}
            img.save(buf, **save_kw)
            b64 = base64.b64encode(buf.getvalue()).decode("ascii")
            mime = "image/jpeg" if ext in (".jpg", ".jpeg") else "image/png"
        except ImportError:
            # No PIL — send raw, hope for the best
            with open(img_path, "rb") as f:
                b64 = base64.b64encode(f.read()).decode("ascii")

        data_uri = f"data:{mime};base64,{b64}"
    except Exception:
        return message

    new_msg = dict(message)
    content_parts = []
    if text_part:
        content_parts.append({"type": "text", "text": text_part})
    content_parts.append({
        "type": "image_url",
        "image_url": {"url": data_uri},
    })
    new_msg["content"] = content_parts
    return new_msg


def _image_prompt_with_history(messages: list[dict]) -> str:
    """Flatten this conversation into context for image APIs, which accept only one prompt."""
    latest_user_index = next(
        (i for i in range(len(messages) - 1, -1, -1) if messages[i].get("role") == "user"),
        None,
    )
    if latest_user_index is None:
        return ""

    def text_from_content(content) -> str:
        if isinstance(content, str):
            return content.strip()
        if isinstance(content, list):
            return "\n".join(
                part.get("text", "").strip()
                for part in content
                if isinstance(part, dict) and part.get("type") == "text"
            ).strip()
        return ""

    current_request = text_from_content(messages[latest_user_index].get("content", ""))
    context = []
    for message in messages[1:latest_user_index]:
        role = message.get("role")
        if role not in ("user", "assistant"):
            continue
        text = text_from_content(message.get("content", ""))
        if text:
            context.append(f"{role.capitalize()}: {text}")

    if not context:
        return current_request

    # Keep the latest request intact and bound context so long chats remain accepted by image APIs.
    history = "\n".join(context)
    max_history_chars = 24000
    if len(history) > max_history_chars:
        history = "[Earlier conversation omitted]\n" + history[-max_history_chars:]
    return (
        "Use the following conversation as context for the requested image. "
        "Preserve relevant subjects, constraints, and visual decisions from it.\n\n"
        f"Conversation context:\n{history}\n\n"
        f"Current image request:\n{current_request}"
    )


def _split_compaction_messages(conversation: list[dict], keep_count: int = 6) -> tuple[list[dict], list[dict]]:
    """Split history without orphaning tool results from their assistant call."""
    recent_start = max(0, len(conversation) - keep_count)
    while recent_start > 0 and conversation[recent_start].get("role") == "tool":
        recent_start -= 1
    return conversation[:recent_start], conversation[recent_start:]


def _compaction_prompt(older: list[dict], recent: list[dict]) -> str:
    """Build a task-safe compaction prompt with recent user intent in view.

    The older transcript contains historical facts, while the recent transcript
    contains the authoritative task state. Keeping these sections separate
    prevents an old completed task from replacing a newer user correction.
    """
    def format_messages(messages: list[dict]) -> str:
        return "\n\n".join(
            f"[{message.get('role', 'unknown')}] {json.dumps(message, ensure_ascii=False)}"
            for message in messages
        )

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

OLDER TRANSCRIPT (historical evidence):
""" + format_messages(older) + "\n\nRECENT VERBATIM CONTEXT (authoritative; read this last):\n" + format_messages(recent)


def _build_request_messages(messages: list[dict]) -> list[dict]:
    """Build model request messages by stripping tool-call intermediates
    from completed turns while keeping the current turn intact.

    Within one agent turn (inner loop), tool calls and their results must
    be visible so the model can continue. When a new user message starts
    the next turn (outer loop), previous-turn tool intermediates are noise
    and are removed — but a compact [TOOL_TRACE] is appended to the system
    prompt so the model never forgets that tool calling is normal.
    """
    if not messages:
        return messages

    # Find the last real user message (skip synthetic [BRACKET] markers)
    last_user_idx = None
    for i in range(len(messages) - 1, -1, -1):
        if messages[i].get("role") == "user":
            content = str(messages[i].get("content", ""))
            if content.strip() and not content.startswith("["):
                last_user_idx = i
                break

    if last_user_idx is None:
        return list(messages)

    system = messages[:1] if messages and messages[0].get("role") == "system" else []
    previous = messages[len(system):last_user_idx]   # completed turns
    current = messages[last_user_idx:]                # current turn onwards

    # Collect tool traces from completed turns
    turn_tools: list[list[str]] = []  # one list per turn
    pending_tools: list[str] = []
    for msg in previous:
        role = msg.get("role")
        if role == "user":
            content = str(msg.get("content", ""))
            if not content.startswith("["):
                # Real user message: flush previous turn's tools
                if pending_tools:
                    turn_tools.append(pending_tools)
                    pending_tools = []
        elif role == "assistant" and msg.get("tool_calls"):
            for tc in msg["tool_calls"]:
                name = tc.get("function", {}).get("name", "")
                if name and name not in pending_tools:
                    pending_tools.append(name)
    if pending_tools:
        turn_tools.append(pending_tools)

    cleaned = list(system)
    for msg in previous:
        role = msg.get("role")
        if role == "user":
            content = str(msg.get("content", ""))
            if not content.startswith("[TURN_PROCESS_SUMMARY]"):
                cleaned.append(msg)
        elif role == "assistant":
            if msg.get("tool_calls"):
                continue
            cleaned.append(msg)
        # tool messages are skipped

    cleaned.extend(current)

    # Inject compact tool trace into system prompt so the model remembers
    # that calling tools is the expected behavior.
    if turn_tools and cleaned and cleaned[0].get("role") == "system":
        traces = [", ".join(tools[:8]) for tools in turn_tools[-5:]]
        trace_block = "\n\n[TOOL_TRACE: " + " | ".join(traces) + "]"
        base = cleaned[0]["content"]
        # Strip any previous tool trace
        idx = base.find("\n\n[TOOL_TRACE:")
        if idx >= 0:
            base = base[:idx]
        cleaned[0]["content"] = base + trace_block

    return cleaned


# ─── Stream wrapper: thread+queue for responsive cancel ─────────────
_STREAM_POLL_SEC = 0.15


class StreamIdleTimeout(TimeoutError):
    """Raised when a model stream produces no usable event for too long."""


def _iter_stream_with_cancel(gen, cancel_event, idle_timeout: float | None = None, on_idle_timeout=None):
    """Wrap a generator so cancellation and idle streams stay responsive.

    ``idle_timeout`` measures time since the last provider event, not total turn
    duration. Long-running turns remain valid while they continue to progress.
    """
    q = queue.Queue()
    done = threading.Event()
    last_progress = time.monotonic()

    def producer():
        try:
            for item in gen:
                q.put(('v', item))
            q.put(('done', None))
        except Exception as e:
            q.put(('err', e))
        finally:
            done.set()

    t = threading.Thread(target=producer, daemon=True)
    t.start()
    try:
        while True:
            try:
                msg = q.get(timeout=_STREAM_POLL_SEC)
            except queue.Empty:
                if cancel_event.is_set():
                    return  # consumer detected cancel
                if idle_timeout is not None and time.monotonic() - last_progress >= idle_timeout:
                    if on_idle_timeout is not None:
                        try:
                            on_idle_timeout()
                        except Exception:
                            pass
                    raise StreamIdleTimeout(f"Model stream made no progress for {int(idle_timeout)} seconds.")
                continue
            typ = msg[0]
            if typ == 'done':
                return
            elif typ == 'err':
                raise msg[1]
            elif typ == 'v':
                last_progress = time.monotonic()
                yield msg[1]
    finally:
        # Producer cleanup must never delay the agent turn. A provider may leave
        # a socket thread unwinding after it has already emitted its final event.
        # Cancellation also returns immediately by design.
        if not done.is_set():
            # Leave the daemon producer to unwind in the background.
            pass


def _turn_tools(available_tools: dict, messages: list[dict]) -> dict:
    """Return the set of tools available this turn."""
    return dict(available_tools)


def _append_knowledge_context(messages: list[dict], context: str) -> list[dict]:
    """Add retrieved context without violating chat-template role ordering."""
    if not context or not messages:
        return messages
    if messages[0].get("role") != "system":
        return messages
    updated = list(messages)
    system = dict(updated[0])
    system["content"] = f"{system.get('content', '')}\n\n{context}".strip()
    updated[0] = system
    return updated


def _summarize_turn_process(provider, model: str, tool_records: list[dict], cancel_event, supports_vision: bool, request_api: str = "chat_completions") -> str:
    """Compress current-turn exploration for the next inner model step only."""
    if not tool_records or cancel_event.is_set():
        return ""
    source = json.dumps(tool_records, ensure_ascii=False, default=str)
    # Small tool batches are already visible in the current request. Avoid an
    # extra model round-trip until the handoff would materially reduce context.
    if len(tool_records) < 3 and len(source) < 12000:
        return ""
    prompt = (
        "Summarize this current-turn tool exploration for the next agent step. "
        "Record only concrete findings, changed files, failures, unresolved questions, and the next useful action. "
        "Do not expose hidden reasoning and do not add facts. Return concise plain text.\n\n" + source[-30000:]
    )
    summary = ""
    try:
        stream = provider.chat_stream(
            model,
            [{"role": "system", "content": "You create short-lived factual agent handoff notes."},
             {"role": "user", "content": prompt}],
            tool_defs=None,
            supports_vision=supports_vision,
            cancel_event=cancel_event,
            request_api=request_api,
        )
        for kind, chunk in _iter_stream_with_cancel(
            stream, cancel_event, idle_timeout=30, on_idle_timeout=provider.cancel
        ):
            if kind == "content":
                summary += str(chunk)
            elif kind in ("error", "cancelled"):
                return ""
    except Exception:
        return ""
    return summary.strip()[:6000]


def _build_plan_summary(records: list[dict]) -> str:
    """Build a compact plan entry from the current turn's tool calls, suitable for
    the PLAN_MARKER block that persists across turns."""
    if not records:
        return ""
    lines = ["## Recent"]
    seen = set()
    for r in records[-5:]:  # last 5 tool calls only
        tool = r.get('tool', '?')
        args = r.get('arguments', {})
        ok = "ok" if r.get('ok') else "FAIL"
        # One-line summary per tool
        if tool == 'bash':
            cmd = str(args.get('command', '')).strip().replace('\n', '; ')[:60]
            lines.append(f"- bash({cmd}): {ok}")
        elif tool == 'read':
            p = str(args.get('path', '?'))[:60]
            lines.append(f"- read({p}): {ok}")
        elif tool == 'write':
            p = str(args.get('path', '?'))[:60]
            lines.append(f"- write({p}): {ok}")
        elif tool == 'edit':
            p = str(args.get('path', '?'))[:60]
            lines.append(f"- edit({p}): {ok}")
        elif tool == 'delegate':
            a = str(args.get('action', '?'))
            p = str(args.get('prompt', ''))[:40]
            lines.append(f"- delegate({a} {p}): {ok}")
        elif tool == 'web_search':
            q = str(args.get('query', ''))[:50]
            lines.append(f"- search({q}): {ok}")
        else:
            lines.append(f"- {tool}: {ok}")
    # Total stats
    ok_count = sum(1 for r in records if r.get('ok'))
    if len(records) > 5:
        lines.insert(1, f"({ok_count}/{len(records)} tools ok, showing last 5)")
    else:
        lines.insert(1, f"({ok_count}/{len(records)} tools ok)")
    return "\n".join(lines)


def _sync_plan_marker(sd, records: list[dict]) -> None:
    """Replace any existing TURN_SUMMARY message with an updated one.

    Uses [TURN_SUMMARY] prefix (NOT [PLAN_MARKER]) to avoid nuking
    the JSON plan that the model sets via plan(action='update').
    """
    new_plan = _build_plan_summary(records)
    # Only delete our own [TURN_SUMMARY] markers, never [PLAN_MARKER]
    sd.messages = [
        m for m in sd.messages
        if not str(m.get("content", "")).startswith("[TURN_SUMMARY]")
    ]
    # Also clean up legacy [TURN_TOOL_SUMMARY] markers
    sd.messages = [
        m for m in sd.messages
        if not str(m.get("content", "")).startswith("[TURN_TOOL_SUMMARY]")
    ]
    if new_plan:
        # Insert right after the plan marker (if any), or after system prompt
        insert_at = 2 if (
            len(sd.messages) >= 2
            and sd.messages[1].get("content", "").startswith("[PLAN_MARKER]")
        ) else (1 if sd.messages and sd.messages[0].get("role") == "system" else 0)
        marker = "[TURN_SUMMARY]\n" + new_plan + "\n[/TURN_SUMMARY]"
        sd.messages.insert(insert_at, {"role": "user", "content": marker})


# ─── (Removed: _format_persistent_turn_summary / _append_persistent_turn_summary) ───


def process_agent_turn(provider, model: str, available_tools: dict, tool_manager: ToolManager, session_id: str = "", model_config: dict | None = None, fallback_mode: bool = False, transient_context: str = ""):
    sd = state.get(session_id)
    if sd is None or sd.cancel.is_set():
        return

    model_config = model_config or {}
    native_tools = _is_native(provider, model_config) and not fallback_mode
    turn_tools = _turn_tools(available_tools, sd.messages) if not fallback_mode else {}
    tool_defs = build_tool_defs(tool_manager, turn_tools) if native_tools else None
    # Refresh on every turn so model switches, reloads, and legacy sessions use
    # the protocol and tool catalog for the active model.
    system_prompt = format_system_prompt(
        turn_tools,
        tool_manager=tool_manager,
        native_tools=native_tools,
    )
    if sd.messages and sd.messages[0].get("role") == "system":
        sd.messages[0]["content"] = system_prompt
    else:
        sd.messages.insert(0, {"role": "system", "content": system_prompt})
    supports_vision = _model_supports_vision(model_config)
    request_api = _model_request_api(model_config)
    request_messages = None
    runtime = AgentRuntime.from_snapshot(
        sd.runtime_snapshot if sd.runtime_snapshot.get("active") else {},
        max_tool_calls=_MAX_TOOL_CALLS,
    )
    runtime.active = True
    turn_tool_records: list[dict] = []
    turn_process_summary = ""
    last_summary_record_count = 0
    last_summary_source_size = 0
    terminal_tool_blocker = ""

    def persist_runtime_snapshot() -> None:
        sd.runtime_snapshot = runtime.snapshot()
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

    # Image-capable models use the dedicated image endpoint. Non-image models stay
    # on the normal chat/tool path; their provider sanitizes image history as needed.
    if isinstance(provider, OpenAIProvider) and model_config.get("image_generation", False):
        try:
            prompt = _image_prompt_with_history(sd.messages)
            if not prompt:
                raise ValueError("No image generation request found")
            result = provider.generate_image(model, prompt)
            source_url = result["url"]
            media_dir = Path(PROJECT_ROOT) / "media" / session_id
            media_dir.mkdir(parents=True, exist_ok=True)
            filename = f"image_{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}.png"
            image_path = media_dir / filename
            if source_url.startswith("data:"):
                encoded = source_url.split(",", 1)[1]
                image_path.write_bytes(base64.b64decode(encoded))
            else:
                response = provider.http.get(source_url, timeout=(8, 120))
                response.raise_for_status()
                image_path.write_bytes(response.content)
            local_path = image_path.resolve()
            result["url"] = local_path.as_uri()
            result["path"] = str(local_path)
            result["filename"] = filename
            saved_location = f"saved to {local_path}"
            sd.messages.append({"role": "assistant", "content": [
                {"type": "text", "text": saved_location},
                {"type": "image_url", "image_url": {"url": result["url"]}},
            ]})
            # The image event renders the complete assistant reply, including saved_location.
            # Avoid a second agent_done event, which previously duplicated the reply and could
            # be interpreted by the WebUI as an unclassified request result.
            _emit("image", {**result, "text": saved_location}, session_id=session_id)
        except Exception as e:
            error = f"Image generation failed: {e}"
            # Keep failures visible in the UI, but never feed synthetic system errors
            # back into the next model request as conversation content.
            _emit("agent_done", error, session_id=session_id)
        return

    # Retrieve knowledge base context once per turn (not every tool-call iteration)
    kb_context = ""
    if getattr(state, "knowledge_base", None):
        user_text = next((m.get("content", "") for m in reversed(sd.messages) if m.get("role") == "user"), "")
        if isinstance(user_text, str):
            kb_context = state.knowledge_base.context(user_text)

    try:
        while True:
            if sd.cancel.is_set():
                return

            _emit("thinking", "Analyzing...", session_id=session_id)

            full_thinking = ""
            full_content = ""
            provider_prompt_seen = False
            stream_tool_calls = None
            stream_error = None

            request_messages = _build_request_messages(sd.messages)
            if transient_context:
                request_messages.append({
                    "role": "user",
                    "content": transient_context + "\nThis is transient background status. Decide how to communicate with the user; do not treat it as a new user request.",
                })
            if turn_process_summary:
                request_messages.append({
                    "role": "user",
                    "content": "[TURN_PROCESS_SUMMARY]\n" + turn_process_summary + "\nThis note expires when the current user turn ends.",
                })
            if kb_context:
                request_messages = _append_knowledge_context(request_messages, kb_context)

            stream_gen = provider.chat_stream(
                model,
                request_messages,
                tool_defs=None if terminal_tool_blocker else tool_defs,
                supports_vision=supports_vision,
                cancel_event=sd.cancel,
                fallback_mode=fallback_mode,
                request_api=request_api,
            )
            try:
                for kind, chunk in _iter_stream_with_cancel(
                    stream_gen, sd.cancel, idle_timeout=300, on_idle_timeout=provider.cancel
                ):
                    if kind == "error":
                        stream_error = chunk
                        break
                    elif kind == "cancelled":
                        _emit("thinking", "Cancelled by user.", session_id=session_id)
                        stop_msg = "\n\n*[stopped]*"
                        # Save stop marker to messages so conversation is properly closed on reload
                        sd.messages.append({"role": "assistant", "content": stop_msg})
                        _emit("agent_done", stop_msg, session_id=session_id)
                        return
                    elif kind == "thinking":
                        full_thinking += chunk
                        _emit("thinking_delta", full_thinking, session_id=session_id)
                    elif kind == "content":
                        full_content += chunk
                        # Forward normal answer text immediately so the UI can show
                        # progress while the provider is still streaming.
                        _emit("agent_delta", chunk, session_id=session_id)
                    elif kind == "tool_calls":
                        stream_tool_calls = chunk
                    elif kind == "tokens":
                        # Count provider-reported usage for the actual requests. The
                        # latest prompt usage is also the authoritative current ctx.
                        input_tokens = chunk.get("input", chunk.get("prompt", 0))
                        output_tokens = chunk.get("output", chunk.get("eval", 0))
                        sd.input_tokens += input_tokens
                        sd.output_tokens += output_tokens
                        sd.prompt_tokens = sd.input_tokens
                        sd.eval_tokens = sd.output_tokens
                        if chunk.get("actual", False):
                            sd.ctx_tokens = chunk.get("prompt", 0)
                            provider_prompt_seen = True
                        elif not provider_prompt_seen:
                            sd.ctx_tokens = _estimate_ctx_tokens(sd.messages, model, provider)
                        _emit("tokens", {
                            "input": sd.input_tokens,
                            "output": sd.output_tokens,
                            "prompt": sd.prompt_tokens,
                            "eval": sd.eval_tokens,
                            "ctx": sd.ctx_tokens,
                            "compressed_prompt_base": sd.compressed_prompt_base,
                            "compressed_context_size": sd.compressed_context_size,
                        }, session_id=session_id)
            except StreamIdleTimeout as error:
                stream_error = str(error)

            if stream_error:
                # For idle timeouts during long thinking, preserve runtime state so the
                # user can prompt the agent to continue. For genuine connection failures,
                # still close the turn to prevent infinite retry loops.
                error_text = str(stream_error).strip() or "Model stream ended without a response."
                is_timeout = "made no progress" in error_text
                
                if not is_timeout:
                    # Real connection error - close the turn
                    runtime.active = False
                    sd.runtime_snapshot = runtime.snapshot()
                
                message = f"后台模型请求未能完成：{error_text}"
                if is_timeout:
                    # Add timeout as system context, not assistant message,
                    # so the model can resume when user prompts "continue".
                    _emit("thinking", f"⚠️ {message}", session_id=session_id)
                else:
                    # Real error - add as assistant message to close the turn
                    sd.messages.append({"role": "assistant", "content": message})
                
                _emit("agent_done", message, session_id=session_id)
                return

            # Connection may have been closed externally by cancel_stream(); catch that here
            if sd.cancel.is_set():
                stop_msg = "\n\n*[stopped]*"
                sd.messages.append({"role": "assistant", "content": stop_msg})
                _emit("agent_done", stop_msg, session_id=session_id)
                return

            # Thinking is diagnostic-only. Never parse it as a tool call or include it
            # in the user-visible answer: it may quote prompts, source code, or examples
            # containing literal <tool_call> tags.
            full_response = full_content

            # ── NATIVE TOOL CALLS (OpenAI-compatible) ──
            if stream_tool_calls:
                native_tc_list = [
                    {
                        "id": tc["id"],
                        "type": "function",
                        "function": {
                            "name": tc["action"],
                            "arguments": json.dumps(tc["arguments"], ensure_ascii=False),
                        },
                    }
                    for tc in stream_tool_calls
                ]
                assistant_msg = {"role": "assistant", "content": full_content or None, "tool_calls": native_tc_list}
                sd.messages.append(assistant_msg)

                # Admit calls independently. A duplicate is returned to the model
                # as a failed tool result, while unrelated calls in the same batch
                # can still run.
                admissions = runtime.allow_each([
                    (tc["action"], tc["arguments"]) for tc in stream_tool_calls
                ])
                preflight: list[tuple[dict, bool, str]] = [
                    (tc, allowed, reason)
                    for tc, (allowed, reason) in zip(stream_tool_calls, admissions)
                ]

                # ── Execute (parallel or sequential) ──
                parallel = state.parallel_tools and len(stream_tool_calls) > 1
                outcomes: dict[str, object] = {}  # tc_id -> ToolOutcome

                if parallel:
                    _emit("thinking", f"Running {len(stream_tool_calls)} tools in parallel...", session_id=session_id)
                    with ThreadPoolExecutor(max_workers=min(len(stream_tool_calls), 6)) as ex:
                        futures_map: dict[Any, str] = {}
                        for tc, allowed, _ in preflight:
                            if allowed:
                                fut = ex.submit(_execute_tool, tc["action"], tc["arguments"], turn_tools, session_id, tc["id"])
                                futures_map[fut] = tc["id"]
                        for fut in as_completed(futures_map):
                            try:
                                outcomes[futures_map[fut]] = fut.result()
                            except Exception as exc:
                                outcomes[futures_map[fut]] = classify_tool_outcome(f"Tool error: {exc}")
                else:
                    for tc, allowed, _ in preflight:
                        if allowed:
                            outcomes[tc["id"]] = _execute_tool(tc["action"], tc["arguments"], turn_tools, session_id, tc["id"])

                # ── Observe and build messages in original order ──
                stop_reason = ""
                background_job_started = False
                for tc, allowed, reason in preflight:
                    if not allowed:
                        outcome = ToolOutcome(False, reason, "duplicate_call")
                    else:
                        outcome = outcomes.get(tc["id"])
                        if outcome is None:
                            outcome = ToolOutcome(False, "Tool execution was skipped.", "tool_skipped")
                    should_continue, obs_reason = runtime.observe(
                        tc["action"], tc["arguments"], outcome, turn_tools.get(tc["action"])
                    )
                    persist_runtime_snapshot()
                    if not should_continue:
                        stop_reason = obs_reason
                    visible_result = re.sub(rf"\n?{re.escape(_IMAGE_MARKER)}.*$", "", outcome.content, flags=re.DOTALL).strip()
                    _emit("tool_result", visible_result, session_id=session_id)
                    tool_msg = _inject_image_content({
                        "role": "tool",
                        "tool_call_id": tc["id"],
                        "content": outcome.for_model(),
                    }, supports_vision=supports_vision)
                    sd.messages.append(tool_msg)
                    turn_tool_records.append({
                        "tool": tc["action"],
                        "arguments": tc["arguments"],
                        "ok": outcome.ok,
                        "result": visible_result[:8000],
                    })
                    if (
                        tc["action"] == "job"
                        and tc["arguments"].get("action") == "start"
                        and outcome.ok
                        and re.search(r"status:\s*(?:starting|running)", visible_result, re.IGNORECASE)
                    ):
                        background_job_started = True

                if background_job_started and not stop_reason:
                    # A started job is event-driven. Do not let the model poll
                    # status/logs in the same turn; the watcher will provide the
                    # terminal result in a separate follow-up turn.
                    terminal_tool_blocker = (
                        "The background job was only accepted and started; it is NOT complete. "
                        "Do not claim that the requested work is finished. Do not call job status, logs, "
                        "or list in this turn. End with a concise statement that the job is running and "
                        "wait for the explicit completion event. If that event reports failed, report failure "
                        "and the exit code, never success."
                    )
                    sd.messages.append({"role": "user", "content": "[BACKGROUND JOB HANDOFF] " + terminal_tool_blocker})
                    continue

                if stop_reason:
                    # The runtime owns the safety boundary, not the user-facing
                    # diagnosis. Disable further tools and let the model read the
                    # failed tool results before deciding what to report or ask.
                    terminal_tool_blocker = stop_reason
                    sd.messages.append({
                        "role": "user",
                        "content": (
                            "[RUNTIME TOOL BLOCKER] Further tool execution is disabled for this turn: "
                            f"{stop_reason}\nRead the tool errors above and respond to the user with the best "
                            "next step, required clarification, or concrete blocker. Do not emit another tool call."
                        ),
                    })
                    continue
                source_size = len(json.dumps(turn_tool_records, ensure_ascii=False, default=str))
                new_record_count = len(turn_tool_records) - last_summary_record_count
                new_source_size = source_size - last_summary_source_size
                should_summarize = (
                    len(turn_tool_records) >= 3
                    and (
                        last_summary_record_count == 0
                        or new_record_count >= 4
                        or new_source_size >= 16000
                    )
                )
                if should_summarize:
                    _emit("thinking", "Summarizing tool progress...", session_id=session_id)
                    candidate_summary = _summarize_turn_process(
                        provider, model, turn_tool_records, sd.cancel, supports_vision, request_api
                    )
                    if candidate_summary:
                        turn_process_summary = candidate_summary
                    last_summary_record_count = len(turn_tool_records)
                    last_summary_source_size = source_size
                continue
            clean_response = re.sub(r"<tool_call>.*?</tool_call>", "", full_response, flags=re.DOTALL).strip()
            if not clean_response:
                # Model produced nothing (no content, no tool calls). Inject a
                # one-time nudge so the next iteration tries again instead of
                # silently exiting — prevents "no response" dead-ends mid-task.
                if not getattr(runtime, "_no_response_retried", False):
                    runtime._no_response_retried = True
                    # Do NOT append assistant message with content=None - violates OpenAI API spec
                    sd.messages.append({
                        "role": "user",
                        "content": "[RUNTIME] No response was produced. Please continue with the current task — use a tool call or provide an answer.",
                    })
                    continue
                clean_response = full_response.strip() or "(empty response)"
            # Strip thinking/reasoning that leaked into content
            clean_response = _strip_thinking_prefix(clean_response)
            sd.messages.append({"role": "assistant", "content": clean_response})
            _sync_plan_marker(sd, turn_tool_records)
            _emit("agent_done", clean_response, session_id=session_id)
            return

    except Exception as e:
        import traceback
        err = f"Agent error: {e}\n{traceback.format_exc()}"
        _emit("tool_result", err, session_id=session_id)
        if sd:
            sd.messages.append({"role": "user", "content": err})
        raise

# ══════════════════════════════════════════════════════════════════════
#  6. WEB UI — pywebview standalone window
# ══════════════════════════════════════════════════════════════════════

# Global refs set at startup; used by WebAPI
_provider = None
_provider_model = ""
_provider_name = ""
_current_provider_cfg: dict = {}
_providers_cfg: list[dict] = []
_default_vision_model = ""
_available_tools: dict = {}
_tool_manager: ToolManager | None = None
_session_manager: SessionManager | None = None


def _job_metadata_root():
    from tools.job import _job_root
    return _job_root()


def _schedule_metadata_root():
    from tools.schedule import _schedule_root
    return _schedule_root()


def _run_due_schedules() -> None:
    """Start due scheduled prompts when their target session is idle."""
    now = datetime.now().astimezone()
    try:
        for path in _schedule_metadata_root().glob("*.json"):
            try:
                metadata = json.loads(path.read_text(encoding="utf-8"))
                if metadata.get("status") != "scheduled":
                    continue
                run_at = datetime.fromisoformat(str(metadata.get("run_at", "")))
                if run_at > now:
                    continue
                session_id = str(metadata.get("session_id", ""))
                sd = state.sessions.get(session_id)
                if not sd or sd.processing or not _provider or not _tool_manager:
                    continue
                interval = metadata.get("interval_seconds")
                if interval:
                    next_run = run_at
                    while next_run <= now:
                        next_run += timedelta(seconds=int(interval))
                    metadata["run_at"] = next_run.isoformat()
                else:
                    metadata["status"] = "completed"
                metadata["last_run_at"] = now.isoformat()
                path.write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
                context = (
                    "[SCHEDULED_TASK]\n"
                    "This is an explicitly scheduled user task. Perform the requested work now using normal tools. "
                    "Report the actual result to the user. Do not create another schedule unless the prompt explicitly asks for it.\n"
                    f"Scheduled prompt: {metadata.get('prompt', '')}"
                )
                _start_session_worker(session_id, context)
            except (OSError, ValueError, TypeError, json.JSONDecodeError):
                continue
    except OSError:
        pass


def _schedule_watcher_loop() -> None:
    while True:
        _run_due_schedules()
        time.sleep(1.0)


def _delegate_metadata_root():
    from tools.delegate import _delegate_root
    return _delegate_root()


def _run_queued_delegates() -> None:
    """Pick up queued delegate tasks and spawn subprocess runners."""
    import subprocess as sp
    try:
        root = _delegate_metadata_root()
        if not root.exists():
            return
        for session_dir in root.iterdir():
            if not session_dir.is_dir():
                continue
            for path in session_dir.glob("*.json"):
                try:
                    metadata = json.loads(path.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError):
                    continue
                if metadata.get("status") != "queued":
                    continue
                # Write "starting" FIRST to prevent duplicate spawns by later
                # watcher iterations, then spawn the subprocess.
                metadata["status"] = "starting"
                # Pass active provider/model so the runner uses the same backend
                metadata["__provider"] = _provider_name
                metadata["__model"] = _provider_model
                metadata["__provider_cfg"] = _current_provider_cfg
                metadata["__provider_type"] = _current_provider_cfg.get("type", "ollama")
                path.write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
                runner = os.path.join(PROJECT_ROOT, "tools", "_delegate_runner.py")
                sp.Popen(
                    [sys.executable, runner, str(path)],
                    creationflags=sp.CREATE_NO_WINDOW if os.name == "nt" else 0,
                )
    except OSError:
        pass


def _delegate_watcher_loop() -> None:
    """Watch for queued delegates (spawn), stuck starters (timeout), and finished delegates (notify)."""
    import datetime as dt
    seen: dict[str, str] = {}
    while True:
        _run_queued_delegates()
        try:
            root = _delegate_metadata_root()
            now = dt.datetime.now(dt.timezone.utc)
            for session_dir in root.iterdir():
                if not session_dir.is_dir():
                    continue
                for path in session_dir.glob("*.json"):
                    try:
                        metadata = json.loads(path.read_text(encoding="utf-8"))
                    except (OSError, json.JSONDecodeError):
                        continue
                    delegate_id = str(metadata.get("delegate_id", path.stem))
                    status = str(metadata.get("status", ""))
                    session_id = str(metadata.get("session_id", ""))

                    # Timeout stuck "starting" delegates (runner crashed silently)
                    if status == "starting":
                        created = metadata.get("created_at", "")
                        if created:
                            try:
                                created_dt = dt.datetime.fromisoformat(created.replace("Z", "+00:00"))
                                if (now - created_dt).total_seconds() > 120:
                                    metadata["status"] = "failed"
                                    metadata["error"] = "Sub-agent runner did not start within 2 minutes (possible import error or crash)."
                                    metadata["finished_at"] = now.isoformat()
                                    path.write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
                                    status = "failed"
                            except (ValueError, TypeError):
                                pass

                    if not session_id or status in {"queued", "starting", "running"}:
                        continue
                    if seen.get(delegate_id) == status or metadata.get("agent_received_at"):
                        continue
                    sd = state.sessions.get(session_id)
                    if not sd:
                        continue
                    # Only deliver once the agent is idle. If busy, retry next pass.
                    if sd.processing:
                        continue
                    # Mark seen only AFTER we confirm delivery will happen.
                    # Avoids the bug where seen is set but followup is skipped
                    # because the agent was processing — losing the notification forever.
                    seen[delegate_id] = status
                    _emit("delegate_result", {
                        "delegate_id": delegate_id,
                        "status": status,
                        "session_id": session_id,
                        "summary": metadata.get("summary", "")[:300],
                        "prompt": metadata.get("prompt", "")[:200],
                        "tool_call_count": metadata.get("tool_call_count", 0),
                        "input_tokens": metadata.get("input_tokens", 0),
                        "output_tokens": metadata.get("output_tokens", 0),
                    }, session_id=session_id)
                    _start_delegate_followup(session_id)
        except OSError:
            pass
        time.sleep(1.5)


def _consume_job_notifications(session_id: str) -> list[dict]:
    """Claim finished jobs for a session so the next user turn can process them."""
    if not session_id:
        return []
    notifications = []
    try:
        root = _job_metadata_root()
        for path in sorted(root.glob("*.json"), reverse=True):
            try:
                metadata = json.loads(path.read_text(encoding="utf-8"))
                if metadata.get("session_id") != session_id:
                    continue
                if metadata.get("status") in {"starting", "running"} or metadata.get("agent_received_at"):
                    continue
                metadata["agent_received_at"] = datetime.now().astimezone().isoformat()
                path.write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
                notifications.append(metadata)
            except (OSError, ValueError, json.JSONDecodeError):
                continue
    except OSError:
        return []
    return notifications


def _format_job_notifications(jobs: list[dict]) -> str:
    lines = [
        "[BACKGROUND_JOB_RESULTS]",
        "A background job has a terminal result. First report its actual status to the user. Continue processing, generate a report, or perform a follow-up action only when the original request explicitly asked for it.",
    ]
    for job in jobs:
        status = job.get("status", "unknown")
        lines.append(f"job_id: {job.get('job_id', '')}")
        lines.append(f"status: {status}, exit_code: {job.get('exit_code', '')}, elapsed_seconds: {job.get('elapsed_seconds', '')}")
        lines.append(f"command: {job.get('command', '')}")
        if job.get("error"):
            lines.append(f"error: {job['error']}")
        lines.append("Use job action=logs if the output is needed before deciding what to do.")
    return "\n".join(lines)


def _consume_delegate_notifications(session_id: str) -> list[dict]:
    """Claim completed delegates for a session so the next turn can process them."""
    if not session_id:
        return []
    notifications = []
    try:
        root = _delegate_metadata_root()
        session_dir = root / session_id
        if not session_dir.exists():
            return []
        for path in sorted(session_dir.glob("*.json"), reverse=True):
            try:
                metadata = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if metadata.get("status") in {"queued", "starting", "running"}:
                continue
            if metadata.get("agent_received_at"):
                continue
            metadata["agent_received_at"] = datetime.now().astimezone().isoformat()
            path.write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
            notifications.append(metadata)
    except OSError:
        return []
    return notifications


def _format_delegate_notifications(delegates: list[dict]) -> str:
    lines = [
        "[SUBAGENT_RESULTS]",
        "A delegated sub-agent has finished. Summarize its result to the user in your own words. Only continue processing or perform follow-up actions if the original request explicitly asked for it.",
    ]
    for d in delegates:
        lines.append(f"delegate_id: {d.get('delegate_id', '')}")
        lines.append(f"status: {d.get('status', 'unknown')}")
        lines.append(f"task: {d.get('prompt', '')}")
        lines.append(f"tool_calls: {d.get('tool_call_count', 0)}")
        if d.get("summary"):
            lines.append(f"summary: {d['summary']}")
        if d.get("error"):
            lines.append(f"error: {d['error']}")
        lines.append(f"Use delegate(action='status', delegate_id='{d.get('delegate_id', '')}') to check details.")
    return "\n".join(lines)


def _start_delegate_followup(session_id: str):
    """Give finished delegate results to one autonomous agent follow-up turn."""
    sd = state.sessions.get(session_id)
    if not sd or sd.processing or not _provider or not _tool_manager:
        return {"status": "skipped"}
    pending = _consume_delegate_notifications(session_id)
    if not pending:
        return {"status": "skipped"}
    return _start_session_worker(session_id, _format_delegate_notifications(pending))


def _start_session_worker(session_id: str, transient_context: str = ""):
    """Run an agent turn for an already prepared session."""
    sd = state.sessions.get(session_id)
    if not sd or sd.processing or not _provider or not _tool_manager:
        return {"status": "skipped"}
    turn_provider = _provider
    turn_model = _provider_model
    turn_model_config = _get_provider_model_capabilities(_providers_cfg, turn_provider, turn_model)
    turn_fallback_mode = state.fallback_mode

    def worker():
        completed = False
        sd._active_provider = turn_provider
        try:
            sd.processing = True
            process_agent_turn(turn_provider, turn_model, _available_tools, _tool_manager, session_id=session_id, model_config=turn_model_config, fallback_mode=turn_fallback_mode, transient_context=transient_context)
            completed = True
        except Exception as error:
            _emit("agent_done", f"Agent Error: {error}", session_id=session_id)
        finally:
            sd._active_provider = None
            sd.processing = False
            if completed:
                sd.runtime_snapshot = {}
            _emit("processing_done", {"cancelled": sd.cancel.is_set()}, session_id=session_id)
            sd.cancel.clear()
            if _session_manager and session_id in state.sessions:
                _session_manager.save(
                    session_id, sd.messages, history=list(sd.history),
                    token_stats={"input": sd.input_tokens, "output": sd.output_tokens,
                                 "prompt": sd.prompt_tokens, "eval": sd.eval_tokens,
                                 "ctx": sd.ctx_tokens, "runtime": sd.runtime_snapshot},
                )

    threading.Thread(target=worker, daemon=True).start()
    return {"status": "ok", "session_id": session_id}


def _start_background_followup(session_id: str):
    """Give finished job results directly to one autonomous agent follow-up."""
    sd = state.sessions.get(session_id)
    if not sd or sd.processing:
        return {"status": "skipped"}
    pending = _consume_job_notifications(session_id)
    if not pending:
        return {"status": "skipped"}
    return _start_session_worker(session_id, _format_job_notifications(pending))


def _job_watcher_loop() -> None:
    """Deliver newly finished internal jobs without interrupting user turns."""
    seen: dict[str, str] = {}
    try:
        for path in _job_metadata_root().glob("*.json"):
            try:
                metadata = json.loads(path.read_text(encoding="utf-8"))
                seen[str(metadata.get("job_id", path.stem))] = str(metadata.get("status", ""))
            except (OSError, ValueError, json.JSONDecodeError):
                continue
    except OSError:
        pass
    while True:
        try:
            root = _job_metadata_root()
            for path in root.glob("*.json"):
                try:
                    metadata = json.loads(path.read_text(encoding="utf-8"))
                    job_id = str(metadata.get("job_id", path.stem))
                    status = str(metadata.get("status", ""))
                    session_id = str(metadata.get("session_id", ""))
                    if not session_id or status in {"starting", "running"}:
                        continue
                    if seen.get(job_id) == status or metadata.get("agent_received_at"):
                        continue
                    sd = state.sessions.get(session_id)
                    if not sd or sd.processing:
                        # Leave the job unclaimed. The active user turn may still
                        # be finishing; the next watcher pass will deliver it.
                        continue
                    seen[job_id] = status
                    _emit("background_job_result", {
                        "job_id": job_id,
                        "status": status,
                        "session_id": session_id,
                        "auto_followup": bool(metadata.get("auto_followup", False)),
                    }, session_id=session_id)
                    # Every terminal job is first surfaced as a notification. Only
                    # an explicit auto_followup decision made when the job was
                    # started may trigger one autonomous result-processing turn.
                    if metadata.get("auto_followup", False):
                        _start_background_followup(session_id)
                except (OSError, ValueError, json.JSONDecodeError):
                    continue
        except OSError:
            pass
        time.sleep(1.0)


def _refresh_runtime_tools() -> dict:
    """Reload Python tools and refresh system prompts for idle sessions."""
    global _available_tools
    if not _tool_manager:
        return {}
    _available_tools = _tool_manager.load_tools()
    model_config = _get_provider_model_capabilities(_providers_cfg, _provider, _provider_model)
    native = _is_native(_provider, model_config)
    for session in state.sessions.values():
        if session.messages and not session.processing:
            session.messages[0] = {
                "role": "system",
                "content": format_system_prompt(
                    _available_tools,
                    tool_manager=_tool_manager,
                    native_tools=native,
                ),
            }
    return _available_tools


def handle_control_command(command: str, session_id: str = "") -> str:
    """Handle pi-like resource commands without spending a model turn."""
    parts = command.split(maxsplit=2)
    area = parts[0].lower()
    action = parts[1].lower() if len(parts) > 1 else "list"
    argument = parts[2].strip() if len(parts) > 2 else ""

    if area == "/tool":
        if action == "list":
            names = sorted(_available_tools)
            return "Available tools:\n" + "\n".join(f"- {name}" for name in names)
        if action == "reload":
            tools = _refresh_runtime_tools()
            return f"Tools reloaded ({len(tools)}): {', '.join(sorted(tools))}"
        return "Usage: /tool list | /tool reload"

    if area == "/knowledge":
        if not state.knowledge_base:
            return "Knowledge base is not initialized."
        if action == "list":
            documents = state.knowledge_base.list_documents()
            if not documents:
                return "Knowledge base is empty."
            return "Knowledge documents:\n" + "\n".join(
                f"- [{item['id']}] {item['title']} ({item['source']})"
                for item in documents
            )
        if action == "search":
            if not argument:
                return "Usage: /knowledge search <query>"
            results = state.knowledge_base.search(argument)
            if not results:
                return "No matching knowledge-base documents."
            return "\n\n".join(
                f"[{item['id']}] {item['title']} ({item['source']})\n{item['snippet']}"
                for item in results
            )
        if action == "add":
            if not argument:
                return "Usage: /knowledge add <file-or-folder>"
            path = Path(argument.strip('\\\"')).expanduser().resolve()
            if path.is_file():
                return json.dumps(state.knowledge_base.ingest_file(str(path)), ensure_ascii=False)
            if path.is_dir():
                results = []
                for item in sorted(path.rglob("*")):
                    if item.is_file() and item.suffix.lower() in KnowledgeBase.SUPPORTED_SUFFIXES:
                        try:
                            results.append(state.knowledge_base.ingest_file(str(item)))
                        except (OSError, ValueError) as exc:
                            results.append({"source": str(item), "status": "error", "error": str(exc)})
                return json.dumps({"path": str(path), "count": len(results), "items": results}, ensure_ascii=False)
            return f"Path not found: {path}"
        return "Usage: /knowledge list | /knowledge search <query> | /knowledge add <file-or-folder>"

    return "Unknown control command."


class WebAPI:
    """API exposed to JavaScript via pywebview."""

    def get_models(self):
        choices = build_model_choices(_providers_cfg)
        return {"choices": [
            {"index": idx, "label": label,
             "provider": _providers_cfg[int(pidx)].get("name", ""),
             "model": model_name,
             "selected": model_name == _provider_model and _providers_cfg[int(pidx)].get("name", "") == getattr(_provider, "name", "")}
            for idx, (label, pidx, model_name) in enumerate(choices)
        ]}

    def set_theme(self, theme: str):
        if theme not in ("day", "night"):
            return {"status": "error", "msg": "Invalid theme."}
        try:
            config_path = os.path.join(PROJECT_ROOT, "config.json")
            config = load_config(config_path)
            config["theme"] = theme
            with open(config_path, "w", encoding="utf-8") as f:
                json.dump(config, f, ensure_ascii=False, indent=4)
            state.theme = theme
            return {"status": "ok", "theme": theme}
        except (OSError, json.JSONDecodeError) as exc:
            return {"status": "error", "msg": f"Could not save theme: {exc}"}

    def get_theme(self):
        return {"theme": state.theme}

    def get_settings(self):
        model_config = _get_provider_model_capabilities(_providers_cfg, _provider, _provider_model)
        is_openai = isinstance(_provider, OpenAIProvider)
        return {
            "fallback_mode": state.fallback_mode,
            "auto_install_dependencies": state.auto_install_dependencies,
            "request_api": _model_request_api(model_config) if is_openai else "",
            "request_api_available": is_openai,
            "request_api_model": _provider_model if is_openai else "",
        }

    def set_settings(self, fallback_mode: bool, auto_install_dependencies: bool, request_api: str = "chat_completions"):
        try:
            config_path = os.path.join(PROJECT_ROOT, "config.json")
            config = load_config(config_path)
            config["fallback_mode"] = bool(fallback_mode)
            config["auto_install_dependencies"] = bool(auto_install_dependencies)
            if isinstance(_provider, OpenAIProvider):
                if request_api not in ("chat_completions", "responses"):
                    return {"status": "error", "msg": "Invalid request API."}
                provider_name = getattr(_provider, "name", "")
                updated = False
                for provider_config in config.get("providers", []):
                    if provider_config.get("name", "") != provider_name:
                        continue
                    for model_index, entry in enumerate(provider_config.get("models", [])):
                        name, model_config = _model_config(entry)
                        if name != _provider_model:
                            continue
                        explicit = dict(model_config) if isinstance(entry, dict) else {"name": name}
                        explicit["request_api"] = request_api
                        provider_config["models"][model_index] = explicit
                        updated = True
                        break
                    if updated:
                        break
                if not updated:
                    return {"status": "error", "msg": "Selected model was not found in config.json."}
                for provider_config in _providers_cfg:
                    if provider_config.get("name", "") != provider_name:
                        continue
                    for model_index, entry in enumerate(provider_config.get("models", [])):
                        name, model_config = _model_config(entry)
                        if name == _provider_model:
                            explicit = dict(model_config) if isinstance(entry, dict) else {"name": name}
                            explicit["request_api"] = request_api
                            provider_config["models"][model_index] = explicit
                            break
            with open(config_path, "w", encoding="utf-8") as f:
                json.dump(config, f, ensure_ascii=False, indent=4)
            state.fallback_mode = bool(fallback_mode)
            state.auto_install_dependencies = bool(auto_install_dependencies)
            return {"status": "ok", **self.get_settings()}
        except (OSError, json.JSONDecodeError) as exc:
            return {"status": "error", "msg": f"Could not save settings: {exc}"}

    def get_parallel_tools(self):
        return {"parallel_tools": state.parallel_tools}

    def set_parallel_tools(self, enabled: bool):
        try:
            config_path = os.path.join(PROJECT_ROOT, "config.json")
            config = load_config(config_path)
            config["parallel_tools"] = enabled
            with open(config_path, "w", encoding="utf-8") as f:
                json.dump(config, f, ensure_ascii=False, indent=4)
            state.parallel_tools = enabled
            return {"status": "ok", "parallel_tools": enabled}
        except (OSError, json.JSONDecodeError) as exc:
            return {"status": "error", "msg": f"Could not save: {exc}"}

    def select_model(self, idx: int):
        global _provider, _provider_model
        # Model switching is global for new requests, but must not be blocked by
        # another session that is currently generating. Each worker captures its
        # provider/model when the request starts, so an idle session can switch
        # models while a different session continues streaming.
        choices = build_model_choices(_providers_cfg)
        if not isinstance(idx, int) or not 0 <= idx < len(choices):
            return {"status": "error", "msg": "Invalid model selection."}
        _, pidx, model_name = choices[idx]
        pcfg = _providers_cfg[int(pidx)]
        provider_cls = PROVIDER_MAP.get(pcfg.get("type"))
        if not provider_cls:
            return {"status": "error", "msg": f"Unsupported provider type: {pcfg.get('type', '')}"}
        
        # Cancel any pending requests from the old provider before switching
        if _provider and hasattr(_provider, 'cancel'):
            try:
                _provider.cancel()
            except Exception:
                pass
        
        # Create fresh provider instance with clean state
        _provider = provider_cls.from_config(pcfg)
        _provider_model = model_name
        _provider_name = pcfg.get("name", "")
        _current_provider_cfg = dict(pcfg)
        
        # Clear error states in all idle sessions to allow retries with new provider
        for session_id, sd in state.sessions.items():
            if not sd.processing:
                # Reset runtime error flags so sessions can retry with the new model
                if hasattr(sd, 'runtime_snapshot') and sd.runtime_snapshot:
                    sd.runtime_snapshot = {}
        
        return {"status": "ok", "provider": _provider.name, "model": model_name}

    def choose_attachments(self, kind: str = "files"):
        """Open a native picker; folders are valid attachment endpoints."""
        try:
            import webview
            if kind == "folder":
                selected = webview.windows[0].create_file_dialog(webview.FOLDER_DIALOG)
            else:
                selected = webview.windows[0].create_file_dialog(
                    webview.OPEN_DIALOG,
                    allow_multiple=True,
                )
            if not selected:
                return {"status": "ok", "paths": []}
            if isinstance(selected, (str, os.PathLike)):
                selected = [selected]
            paths = [str(Path(item).expanduser().resolve()) for item in selected]
            if kind == "folder":
                paths = [path if path.endswith(os.sep) else path + os.sep for path in paths]
            return {"status": "ok", "paths": paths}
        except Exception as exc:
            return {"status": "error", "msg": f"Could not choose attachment: {exc}"}

    def get_clipboard_files(self):
        """Read file paths copied in Windows Explorer from the native clipboard."""
        try:
            import win32clipboard
            import win32con
            win32clipboard.OpenClipboard()
            try:
                if not win32clipboard.IsClipboardFormatAvailable(win32con.CF_HDROP):
                    return {"status": "ok", "paths": []}
                paths = win32clipboard.GetClipboardData(win32con.CF_HDROP)
            finally:
                win32clipboard.CloseClipboard()
            return {"status": "ok", "paths": [str(Path(path).expanduser().resolve()) for path in paths]}
        except ImportError:
            return {"status": "error", "msg": "Windows clipboard support requires pywin32."}
        except Exception as exc:
            return {"status": "error", "msg": f"Could not read clipboard files: {exc}"}

    def save_clipboard_image(self, data_url: str, filename: str = "clipboard.png", session_id: str = ""):
        """Save a pasted clipboard image inside the current session media folder."""
        try:
            if not isinstance(data_url, str) or not data_url.startswith("data:image/") or "," not in data_url:
                return {"status": "error", "msg": "Clipboard data is not an image."}
            header, encoded = data_url.split(",", 1)
            if ";base64" not in header:
                return {"status": "error", "msg": "Clipboard image data is not base64 encoded."}
            raw = base64.b64decode(encoded, validate=True)
            if not raw or len(raw) > 25 * 1024 * 1024:
                return {"status": "error", "msg": "Clipboard image is empty or too large."}
            extension = {"image/png": ".png", "image/jpeg": ".jpg", "image/gif": ".gif", "image/webp": ".webp", "image/bmp": ".bmp"}.get(header[5:].split(";", 1)[0], ".png")
            safe_name = Path(filename or "clipboard").name
            if not Path(safe_name).suffix.lower() in {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp"}:
                safe_name += extension
            media_dir = (Path(PROJECT_ROOT) / "media" / (session_id or "clipboard")).resolve()
            media_dir.mkdir(parents=True, exist_ok=True)
            target = media_dir / f"{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}_{safe_name}"
            target.write_bytes(raw)
            return {"status": "ok", "path": str(target), "filename": target.name}
        except (ValueError, OSError) as exc:
            return {"status": "error", "msg": f"Could not save clipboard image: {exc}"}

    def chat(self, message: str):
        """Handle user message: create session immediately, start worker, don't block."""
        if not message.strip():
            return {"status": "error"}

        # Keep lightweight slash commands out of the model loop.
        if message.strip().startswith(("/tool", "/knowledge")):
            sid = state.current_session_id
            if not sid and _session_manager:
                sid = _session_manager.create()["id"]
                state.current_session_id = sid
            result = handle_control_command(message.strip(), sid)
            return {"status": "ok", "session_id": sid, "handled": True, "result": result}

        # Create session immediately
        sid = state.current_session_id
        if not sid or not _session_manager:
            session = _session_manager.create()
            sid = session["id"]
            state.current_session_id = sid

        sd = state.ensure(sid)
        if not sd.messages:
            model_config = _get_provider_model_capabilities(_providers_cfg, _provider, _provider_model)
            native = _is_native(_provider, model_config)
            sd.messages = [{"role": "system", "content": format_system_prompt(_available_tools, tool_manager=_tool_manager, native_tools=native)}]
        sd.messages.append({"role": "user", "content": message})
        _emit("user", message, session_id=sid)

        # Save immediately to disk — user message must survive session switching
        if _session_manager:
            _session_manager.save(
                sid, sd.messages,
                history=list(sd.history),
                token_stats={
                "input": sd.input_tokens,
                "output": sd.output_tokens,
                "prompt": sd.prompt_tokens,
                "eval": sd.eval_tokens,
                "ctx": sd.ctx_tokens,
                "compressed_prompt_base": sd.compressed_prompt_base,
                "compressed_context_size": sd.compressed_context_size,
            },
            )

        # Don't start a second worker if this session is already processing
        if sd.processing:
            return {"status": "ok", "session_id": sid}

        # Snapshot the selected model for this turn. Do not read the globals from
        # inside the worker: another idle session may switch models meanwhile.
        turn_provider = _provider
        turn_model = _provider_model
        turn_model_config = _get_provider_model_capabilities(_providers_cfg, turn_provider, turn_model)

        turn_fallback_mode = state.fallback_mode

        def worker():
            completed = False
            sd._active_provider = turn_provider
            try:
                sd.processing = True
                process_agent_turn(turn_provider, turn_model, _available_tools, _tool_manager, session_id=sid, model_config=turn_model_config, fallback_mode=turn_fallback_mode)
                completed = True
            except Exception as e:
                import traceback
                err = f"Agent Error: {e}\n{traceback.format_exc()}"
                _emit("agent_done", err, session_id=sid)
            finally:
                sd._active_provider = None
                sd.processing = False
                if completed:
                    sd.runtime_snapshot = {}
                _emit("processing_done", {"cancelled": sd.cancel.is_set()}, session_id=sid)
                sd.cancel.clear()
                # Auto-save after turn (skip if session was deleted)
                if _session_manager and sid in state.sessions and not sd.cancel.is_set():
                    _session_manager.save(
                        sid, sd.messages,
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

        threading.Thread(target=worker, daemon=True).start()
        return {"status": "ok", "session_id": sid}

    def cancel_stream(self, session_id: str):
        """Cancel an in-progress stream for the given session."""
        sd = state.sessions.get(session_id)
        if sd:
            sd.cancel.set()
            # Use the exact provider instance that is running this session
            # (not the global _provider, which may have changed due to model switch)
            active = sd._active_provider
            if active:
                active.cancel()
        return {"status": "ok"}

    def save_generated_image(self, source_path: str, filename: str = ""):
        """Show a Save As dialog and copy a generated image to the chosen path."""
        try:
            path = Path(source_path)
            if not path.is_file():
                return {"status": "error", "msg": "Generated image file was not found."}
            media_root = (Path(PROJECT_ROOT) / "media").resolve()
            if media_root not in path.resolve().parents:
                return {"status": "error", "msg": "Only generated images can be saved."}

            name = Path(filename).name or path.name
            try:
                import tkinter as tk
                from tkinter import filedialog
                root = tk.Tk()
                root.withdraw()
                root.attributes("-topmost", True)
                destination = filedialog.asksaveasfilename(
                    parent=root,
                    title="Save generated image",
                    initialfile=name,
                    defaultextension=path.suffix or ".png",
                    filetypes=[("PNG image", "*.png"), ("JPEG image", "*.jpg;*.jpeg"), ("All files", "*.*")],
                )
                root.destroy()
            except Exception as exc:
                return {"status": "error", "msg": f"Could not open save dialog: {exc}"}

            if not destination:
                return {"status": "cancelled"}
            destination = Path(destination)
            shutil.copy2(path, destination)
            return {"status": "ok", "path": str(destination)}
        except OSError as exc:
            return {"status": "error", "msg": f"Could not save image: {exc}"}

    def get_generated_image_data(self, source_path: str):
        """Return a local generated image as a data URI for the embedded WebView."""
        try:
            path = Path(source_path).expanduser().resolve()
            if not path.is_file():
                return {"status": "error", "msg": "Image file does not exist."}
            if path.stat().st_size > 25 * 1024 * 1024:
                return {"status": "error", "msg": "Image is too large to display in the WebView."}
            mime = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp"}.get(path.suffix.lower(), "application/octet-stream")
            data = base64.b64encode(path.read_bytes()).decode("ascii")
            return {"status": "ok", "url": f"data:{mime};base64,{data}", "path": str(path)}
        except OSError as exc:
            return {"status": "error", "msg": f"Could not load image: {exc}"}

    def open_attachment(self, source_path: str):
        """Open a file or folder in the operating system's default handler."""
        try:
            path = Path(source_path).expanduser().resolve()
            if not path.exists():
                return {"status": "error", "msg": "Attachment does not exist."}
            if sys.platform == "win32":
                os.startfile(str(path))
            elif sys.platform == "darwin":
                subprocess.Popen(["open", str(path)])
            else:
                subprocess.Popen(["xdg-open", str(path)])
            return {"status": "ok"}
        except OSError as exc:
            return {"status": "error", "msg": f"Could not open attachment: {exc}"}

    def open_generated_image(self, source_path: str):
        """Open the local image in the operating system's default viewer."""
        try:
            path = Path(source_path)
            if not path.is_file():
                return {"status": "error", "msg": "Generated image file was not found."}
            media_root = (Path(PROJECT_ROOT) / "media").resolve()
            if media_root not in path.resolve().parents:
                return {"status": "error", "msg": "Only generated images can be opened."}
            os.startfile(str(path.resolve()))
            return {"status": "ok"}
        except OSError as exc:
            return {"status": "error", "msg": f"Could not open image: {exc}"}

    def get_schedules(self):
        """Return scheduled agent tasks for the current WebUI session."""
        try:
            from tools.schedule import Schedule
            result = Schedule().run({"action": "list", "_session_id": state.current_session_id})
            return {"status": "ok", "schedules": result.get("schedules", [])}
        except Exception as exc:
            return {"status": "error", "msg": f"Could not load schedules: {exc}", "schedules": []}

    def cancel_schedule(self, schedule_id: str):
        """Cancel a scheduled agent task from the WebUI."""
        try:
            from tools.schedule import Schedule
            result = Schedule().run({
                "action": "cancel",
                "schedule_id": schedule_id,
                "_session_id": state.current_session_id,
            })
            return {"status": "ok" if result.get("ok") else "error", "msg": result.get("content", "")}
        except Exception as exc:
            return {"status": "error", "msg": f"Could not cancel schedule: {exc}"}

    def get_jobs(self, include_history: bool = False):
        """Return active or explicitly requested historical jobs for the WebUI."""
        try:
            from tools.job import Job
            result = Job().run({"action": "list", "include_history": bool(include_history), "_visible_only": True})
            return {
                "status": "ok",
                "jobs": result.get("jobs", []),
                "active": result.get("active", []),
                "attention": result.get("attention", []),
            }
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            return {"status": "error", "msg": f"Could not load jobs: {exc}", "jobs": []}

    def cancel_job(self, job_id: str):
        """Cancel a running background job from the WebUI."""
        try:
            from tools.job import Job
            result = Job().run({"action": "cancel", "job_id": job_id})
            return {"status": "ok" if result.get("ok") else "error", "msg": result.get("content", "")}
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            return {"status": "error", "msg": str(exc)}

    def archive_job(self, job_id: str):
        """Archive an obsolete failed job while retaining it in history."""
        try:
            from tools.job import Job
            result = Job().run({"action": "archive", "job_id": job_id})
            return {"status": "ok" if result.get("ok") else "error", "msg": result.get("content", "")}
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            return {"status": "error", "msg": str(exc)}

    def get_job_logs(self, job_id: str, tail_lines: int = 80):
        """Return a bounded log tail for an individual background job."""
        try:
            from tools.job import Job
            result = Job().run({"action": "logs", "job_id": job_id, "tail_lines": tail_lines})
            return {"status": "ok" if result.get("ok") else "error", "content": result.get("content", "")}
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            return {"status": "error", "msg": str(exc)}

    # ── Delegate (sub-agent) management ─────────────────────────

    def get_delegates(self, session_id: str):
        """Return all delegate tasks for a session."""
        try:
            from tools.delegate import Delegate
            result = Delegate().run({"action": "list", "_session_id": session_id})
            return {"status": "ok" if result.get("ok") else "error", "delegates": result.get("delegates", [])}
        except Exception as exc:
            return {"status": "error", "msg": str(exc), "delegates": []}

    def get_delegate_detail(self, delegate_id: str, session_id: str):
        """Return full detail for a delegate, including conversation messages."""
        try:
            from tools.delegate import Delegate, _delegate_root
            tool = Delegate()
            metadata_path = tool._find_path(delegate_id, session_id)
            if metadata_path is None:
                return {"status": "error", "msg": "Delegate not found."}
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
            return {
                "status": "ok",
                "delegate_id": metadata.get("delegate_id"),
                "prompt": metadata.get("prompt", ""),
                "delegate_status": metadata.get("status", "unknown"),
                "created_at": metadata.get("created_at", ""),
                "started_at": metadata.get("started_at", ""),
                "finished_at": metadata.get("finished_at", ""),
                "error": metadata.get("error", ""),
                "summary": metadata.get("summary", ""),
                "tool_call_count": metadata.get("tool_call_count", 0),
                "input_tokens": metadata.get("input_tokens", 0),
                "output_tokens": metadata.get("output_tokens", 0),
                "messages": metadata.get("messages", []),
            }
        except Exception as exc:
            return {"status": "error", "msg": str(exc)}

    def cancel_delegate(self, delegate_id: str, session_id: str):
        """Cancel a running or queued delegate."""
        try:
            from tools.delegate import Delegate
            result = Delegate().run({"action": "cancel", "delegate_id": delegate_id, "_session_id": session_id})
            return {"status": "ok" if result.get("ok") else "error", "msg": result.get("content", "")}
        except Exception as exc:
            return {"status": "error", "msg": str(exc)}

    def export_delegate(self, delegate_id: str, session_id: str, fmt: str = "html"):
        """Export a delegate's conversation as HTML or Markdown."""
        try:
            from tools.delegate import Delegate
            result = Delegate().run({
                "action": "export",
                "delegate_id": delegate_id,
                "format": fmt,
                "_session_id": session_id,
            })
            return {
                "status": "ok" if result.get("ok") else "error",
                "msg": result.get("content", ""),
                "export_path": result.get("export_path", ""),
            }
        except Exception as exc:
            return {"status": "error", "msg": str(exc)}

    def get_events(self, session_id: str):
        """Drain and return events from the given session's queue."""
        events = []
        sd = state.sessions.get(session_id)
        if not sd:
            return events
        while not sd.event_queue.empty():
            try:
                events.append(json.loads(sd.event_queue.get_nowait()))
            except queue.Empty:
                break
        return events

    # ── Session management ──────────────────────────────────────

    def get_current_session(self):
        return {"session_id": state.current_session_id}

    def new_session(self):
        """Create a new session and switch to it."""
        if not _session_manager:
            return {"status": "error", "msg": "Session manager not initialized"}
        session = _session_manager.create()
        state.current_session_id = session["id"]
        model_config = _get_provider_model_capabilities(_providers_cfg, _provider, _provider_model)
        native = _is_native(_provider, model_config)
        state.ensure(session["id"]).messages = [{"role": "system", "content": format_system_prompt(_available_tools, tool_manager=_tool_manager, native_tools=native)}]
        return {"status": "ok", "session": session}

    def list_sessions(self):
        if not _session_manager:
            return []
        return _session_manager.list_all()

    def load_session(self, session_id: str):
        """Load a session by ID. Prefers in-memory state (source of truth while alive)."""
        if not _session_manager:
            return {"status": "error", "msg": "Session manager not initialized"}

        sd = state.sessions.get(session_id)

        # ── Case A: in-memory SessionData exists → it's the latest state ──
        if sd and sd.messages:
            # Drain stale events from queue (they're already captured in history)
            while not sd.event_queue.empty():
                try:
                    sd.event_queue.get_nowait()
                except queue.Empty:
                    break
            state.current_session_id = session_id
            disk_session = _session_manager.load(session_id) or {
                "id": session_id, "title": "Chat",
                "created_at": "", "updated_at": "",
                "token_stats": {"prompt": 0, "eval": 0},
            }
            return {
                "status": "ok",
                "session": disk_session,
                "history": sd.history,
                "input_tokens": sd.input_tokens,
                "output_tokens": sd.output_tokens,
                "prompt_tokens": sd.prompt_tokens,
                "eval_tokens": sd.eval_tokens,
                "ctx": sd.ctx_tokens or _estimate_ctx_tokens(sd.messages, _provider_model, _provider),
                "compressed_prompt_base": sd.compressed_prompt_base,
                "compressed_context_size": sd.compressed_context_size,
                "runtime": sd.runtime_snapshot,
                "processing": sd.processing,
            }

        # ── Case B: no in-memory state → load from disk (fresh start) ──
        session = _session_manager.load(session_id)
        if not session:
            return {"status": "error", "msg": "Session not found"}
        sd = state.ensure(session_id)
        model_config = _get_provider_model_capabilities(_providers_cfg, _provider, _provider_model)
        native = _is_native(_provider, model_config)
        # The session file is the canonical transcript. Provider-specific cleanup
        # belongs in prepare_messages(), immediately before the API request.
        disk_messages = [m for m in session.get("messages", []) if m.get("role") != "system"]
        sd.messages = [{"role": "system", "content": format_system_prompt(_available_tools, tool_manager=_tool_manager, native_tools=native)}] + disk_messages
        sd.history = list(session.get("history", []))
        stats = session.get("token_stats", {})
        sd.input_tokens = stats.get("input", stats.get("prompt", 0))
        sd.output_tokens = stats.get("output", stats.get("eval", 0))
        sd.prompt_tokens = sd.input_tokens
        sd.eval_tokens = sd.output_tokens
        sd.compressed_prompt_base = stats.get("compressed_prompt_base", 0)
        sd.compressed_context_size = stats.get("compressed_context_size", 0)
        sd.runtime_snapshot = stats.get("runtime", {}) if isinstance(stats.get("runtime", {}), dict) else {}
        sd.ctx_tokens = stats.get("ctx", 0) or _estimate_ctx_tokens(sd.messages, _provider_model, _provider)
        state.current_session_id = session_id
        return {
            "status": "ok",
            "session": session,
            "history": sd.history,
            "input_tokens": sd.input_tokens,
            "output_tokens": sd.output_tokens,
            "prompt_tokens": sd.prompt_tokens,
            "eval_tokens": sd.eval_tokens,
            # Keep ctx on the same definition as live token events: current request context.
            "ctx": sd.ctx_tokens,
            "compressed_prompt_base": stats.get("compressed_prompt_base", 0),
            "compressed_context_size": stats.get("compressed_context_size", 0),
            "runtime": sd.runtime_snapshot,
            "processing": sd.processing,
        }

    def delete_session(self, session_id: str):
        """Cancel processing, delete session file, clean up."""
        if not _session_manager:
            return {"status": "error"}
        # Cancel any in-progress processing
        sd = state.sessions.get(session_id)
        if sd:
            sd.cancel.set()
        ok = _session_manager.delete(session_id)
        # Clean up in-memory state
        state.sessions.pop(session_id, None)
        if state.current_session_id == session_id:
            state.current_session_id = ""
        return {"status": "ok" if ok else "error"}

    def rename_session(self, session_id: str, title: str):
        if not _session_manager:
            return {"status": "error"}
        ok = _session_manager.rename(session_id, title)
        return {"status": "ok" if ok else "error"}

    def compact_context(self, session_id: str):
        """Summarize older turns with the active model while preserving recent context."""
        if not _session_manager:
            return {"status": "error", "msg": "Session manager not initialized"}
        sd = state.sessions.get(session_id)
        if not sd or not sd.messages:
            return {"status": "error", "msg": "Session is empty or not loaded"}
        if sd.processing:
            return {"status": "error", "msg": "Wait until the current response finishes"}
        if not _provider or not _provider_model:
            return {"status": "error", "msg": "No active model"}

        system = sd.messages[0] if sd.messages and sd.messages[0].get("role") == "system" else {"role": "system", "content": "You summarize conversation context."}
        conversation = sd.messages[1:] if sd.messages and sd.messages[0].get("role") == "system" else sd.messages[:]
        # Keep the latest turns verbatim; summarize only when there is enough history.
        keep_count = 6
        if len(conversation) <= keep_count + 2:
            return {"status": "error", "msg": "Context is already short; nothing to compact"}
        older, recent = _split_compaction_messages(conversation, keep_count)
        # Snapshot context size BEFORE compaction
        pre_compact_ctx = _estimate_ctx_tokens(sd.messages, _provider_model, _provider)
        summary_prompt = _compaction_prompt(older, recent)
        summary = ""
        error = None
        try:
            for kind, chunk in _provider.chat_stream(
                _provider_model,
                [
                    {"role": "system", "content": "You are a precise conversation compression service. Return only a factual summary."},
                    {"role": "user", "content": summary_prompt},
                ],
                tool_defs=None,
            ):
                if kind == "content": summary += str(chunk)
                elif kind == "error": error = str(chunk)
            if error: return {"status": "error", "msg": error}
            if not summary.strip(): return {"status": "error", "msg": "Model returned an empty summary"}
        except Exception as exc:
            return {"status": "error", "msg": f"Compaction failed: {exc}"}

        # Persist the summary as conversation context. SessionManager intentionally
        # removes system prompts because they are rebuilt when a session is loaded.
        compact_marker = {"role": "user", "content": "[COMPACTED CONTEXT]\n" + summary.strip()}

        # Use the same estimator as live context statistics for both snapshots.
        new_messages = [system, compact_marker] + recent
        new_est = _estimate_ctx_tokens(new_messages, _provider_model, _provider)
        saved = max(0, pre_compact_ctx - new_est)
        pct = int(saved / pre_compact_ctx * 100) if pre_compact_ctx else 0
        sd.messages = new_messages
        sd.compressed_prompt_base = pre_compact_ctx
        sd.compressed_context_size = new_est
        sd.ctx_tokens = new_est

        _session_manager.save(
            session_id, sd.messages[1:], history=list(sd.history),
            token_stats={
                "input": sd.input_tokens,
                "output": sd.output_tokens,
                "prompt": sd.prompt_tokens,
                "eval": sd.eval_tokens,
                "ctx": sd.ctx_tokens,
                "compressed_prompt_base": sd.compressed_prompt_base,
                "compressed_context_size": sd.compressed_context_size,
            },
        )
        _emit("agent_done",
            f"Context compacted successfully: {pre_compact_ctx:,} → {new_est:,} tokens "
            f"(saved {saved:,}, {pct}% reduction). "
            f"Compressed {len(older)} older messages, keeping {len(recent)} recent.",
            session_id=session_id)
        # Also emit token refresh so UI counters update
        _emit("tokens", {
            "input": sd.input_tokens,
            "output": sd.output_tokens,
            "prompt": sd.prompt_tokens,
            "eval": sd.eval_tokens,
            "ctx": sd.ctx_tokens,
            "compressed_prompt_base": sd.compressed_prompt_base,
            "compressed_context_size": sd.compressed_context_size,
        }, session_id=session_id)
        return {"status": "ok", "summary": summary.strip(), "removed_messages": len(older), "kept_messages": len(recent),
                "tokens_before": pre_compact_ctx, "tokens_after": new_est, "tokens_saved": saved, "reduction_percent": pct}

    def export_session(self, session_id: str):
        """Export the current session through a native save dialog."""
        from tools.chat_exporter import ChatExporter

        try:
            md = ChatExporter().run({"session_id": session_id})
            if not md or md.startswith("Error"):
                return {"status": "error", "msg": md or "Nothing to export."}

            import tkinter as tk
            from tkinter import filedialog
            root = tk.Tk()
            root.withdraw()
            root.attributes("-topmost", True)
            filename = filedialog.asksaveasfilename(
                parent=root,
                title="Export Chengsi chat",
                defaultextension=".html",
                initialfile=f"session-{session_id}.html",
                filetypes=[("HTML files", "*.html"), ("All files", "*.*")],
            )
            root.destroy()
            if not filename:
                return {"status": "cancelled"}
            Path(filename).write_text(md, encoding="utf-8")
            return {"status": "ok", "path": filename}
        except Exception as exc:
            return {"status": "error", "msg": f"Export failed: {exc}"}


# ══════════════════════════════════════════════════════════════════════
#  7. CLI MODE
# ══════════════════════════════════════════════════════════════════════

def run_cli(provider, model: str, available_tools: dict, tool_manager: ToolManager, model_config: dict | None = None):
    sid = "cli-session"
    sd = state.ensure(sid)
    state.current_session_id = sid
    model_config = model_config or {}
    native = _is_native(provider, model_config)
    sd.messages = [{"role": "system", "content": format_system_prompt(available_tools, tool_manager=tool_manager, native_tools=native)}]

    pname = provider.name if hasattr(provider, 'name') else "provider"
    print(f"\n--- [{pname}] {model} ---")
    print("Type 'exit' to quit.\n")

    try:
        while True:
            user_input = input("You: ").strip()
            if user_input.lower() in ("exit", "quit", "out"):
                break
            if not user_input:
                continue
            if user_input.startswith(("/tool", "/knowledge")):
                print(handle_control_command(user_input, sid))
                continue

            sd.messages.append({"role": "user", "content": user_input})
            _emit("user", user_input)
            process_agent_turn(provider, model, available_tools, tool_manager, session_id=sid, model_config=model_config)
    except KeyboardInterrupt:
        print("\nSession ended.")


# ══════════════════════════════════════════════════════════════════════
#  8. ENTRY POINT
# ══════════════════════════════════════════════════════════════════════

def _init_provider_from_cfg(providers_cfg: list[dict]) -> tuple:
    """Initialize the first configured provider with its first model.

    Returns (provider_instance, model_name) or (None, None).
    """
    if not providers_cfg:
        return None, None
    pcfg = providers_cfg[0]
    provider_cls = PROVIDER_MAP.get(pcfg.get("type", "ollama"))
    if not provider_cls:
        print(f"Unknown provider type: {pcfg.get('type')}")
        return None, None
    provider = provider_cls.from_config(pcfg)
    entries = pcfg.get("models", [])
    model = _model_config(entries[0])[0] if entries else None
    return provider, model


def main():
    config_path = os.path.join(PROJECT_ROOT, "config.json")
    if not os.path.exists(config_path):
        print("Error: config.json not found.")
        return

    config = load_config(config_path)
    state.show_thinking = config.get("show_thinking", True)
    state.theme = config.get("theme", "day")
    state.parallel_tools = config.get("parallel_tools", False)
    state.fallback_mode = config.get("fallback_mode", False)
    state.auto_install_dependencies = config.get("auto_install_dependencies", False)
    if state.theme not in ("day", "night"):
        state.theme = "day"
    state.interface_mode = "web"

    providers_cfg, _ = init_providers(config)
    if not providers_cfg:
        print("Error: no providers configured in config.json")
        return

    tool_manager = ToolManager(os.path.join(PROJECT_ROOT, "tools"))
    available_tools = tool_manager.load_tools()
    state.knowledge_base = KnowledgeBase(os.path.join(PROJECT_ROOT, "knowledge", "knowledge.db"))

    print("=== Agent System Initialized ===")
    print(f"Available Tools: {list(available_tools.keys())}")
    print(f"Interface Mode: {state.interface_mode}")
    print("================================\n")

    # ── Initial model ───────────────────────────────────────────────
    # Provider and model switching are available directly in the web UI.
    selected_provider, selected_model = _init_provider_from_cfg(providers_cfg)
    if selected_model:
        pname = selected_provider.name if hasattr(selected_provider, 'name') else "provider"
        print(f"Using default [{pname}] {selected_model}; change it in the web interface.")

    if selected_provider is None or selected_model is None:
        print("No model selected. Exiting.")
        return

    pname = selected_provider.name if hasattr(selected_provider, 'name') else "provider"
    print(f"\nUsing [{pname}] {selected_model}\n")

    # ── Route to the chosen interface ────────────────────────────
    if state.interface_mode == "web":
        import webview

        # Store globals for WebAPI
        global _provider, _provider_model, _providers_cfg, _available_tools, _tool_manager, _session_manager, _default_vision_model
        _provider = selected_provider
        _provider_model = selected_model
        _providers_cfg = providers_cfg
        _default_vision_model = config.get("default_vision_model", "")
        _available_tools = available_tools
        _tool_manager = tool_manager
        _session_manager = SessionManager(
            os.path.join(PROJECT_ROOT, "sessions"),
            os.path.join(PROJECT_ROOT, "media"),
        )
        threading.Thread(target=_job_watcher_loop, name="chengsi-job-watcher", daemon=True).start()
        threading.Thread(target=_schedule_watcher_loop, name="chengsi-schedule-watcher", daemon=True).start()
        threading.Thread(target=_delegate_watcher_loop, name="chengsi-delegate-watcher", daemon=True).start()

        # Don't create session at startup — created on first message or loaded from sidebar

        # Kill any stale process on port 5000
        try:
            result = subprocess.run(
                ["netstat", "-aon"], capture_output=True, text=True, creationflags=0x08000000
            )
            for line in result.stdout.splitlines():
                if ":5000" in line and "LISTENING" in line:
                    pid = line.strip().split()[-1]
                    subprocess.run(["taskkill", "/F", "/PID", pid],
                                   capture_output=True, creationflags=0x08000000)
        except Exception:
            pass

        api = WebAPI()
        # Load the standalone HTML file

        window = webview.create_window(
            "Chengsi",
            url=os.path.join(PROJECT_ROOT, "core", "index.html"),
            js_api=api,
            width=780,
            height=650,
            min_size=(500, 400),
        )

        # Hide console + set window icon after GUI starts
        def startup():
            import time, ctypes
            time.sleep(0.5)
            for _ in range(3):
                try:
                    hwnd = ctypes.windll.kernel32.GetConsoleWindow()
                    if hwnd:
                        ctypes.windll.user32.ShowWindow(hwnd, 0)
                        break
                except Exception:
                    pass
                time.sleep(0.3)
            # Set window icon via native handle
            try:
                import ctypes
                ico = ctypes.windll.user32.LoadImageW(0,
                    os.path.join(PROJECT_ROOT, "assets", "chengsi.ico"),
                    1, 0, 0, 0x00000010)
                if ico and window.native:
                    ctypes.windll.user32.SendMessageW(
                        window.native.Handle.ToInt32(), 0x0080, 0, ico)
            except Exception:
                pass

        webview.start(debug=False, func=startup)
    else:
        run_cli(selected_provider, selected_model, available_tools, tool_manager)


if __name__ == "__main__":
    main()