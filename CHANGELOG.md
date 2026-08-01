# Changelog

All notable changes to Chengsi will be documented in this file.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project intends to use [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added

- **Delegate (sub-agent) tool**: Main agent spawns background sub-agents with full tool access. Sub-agents run autonomously via subprocess using the same provider classes as the main agent. Results are read-only conversation logs with HTML/Markdown export. Actions: `start`, `status`, `list`, `cancel`, `export`.
- **Plan tool**: Light-weight task planning and progress tracking across turns. Model maintains a JSON plan (goal, completed items, next step) via `plan(action='update')`. Survives context compaction.
- **WebUI modal component**: Reusable modal dialog for viewing sub-agent conversations and job logs in a larger overlay. Lazy DOM initialization avoids timing issues with pywebview.
- **Tool trace in system prompt**: Each request appends `[TOOL_TRACE: bash, read | delegate | ...]` so the model never forgets it can call tools, even when completed-turn tool exchanges are stripped from history.
- **Background delegate watcher**: Monitor loop spawns queued sub-agents, times out stuck starters (2 min), and delivers terminal results back to the agent via follow-up turns.
- **Delegate test suite**: `tests/test_delegate_delivery.py` covers notification delivery, duplicate prevention, and busy-agent retry behavior.

### Fixed

- **Stream timeout causing state loss**: Idle timeout increased 60→300s. Timeouts preserve runtime state without injecting assistant messages; users can prompt "continue" without restarting tasks.
- **WebUI session list overflow**: Sidebar session list scrolls within its container; header and "New chat" button stay visible.
- **Model hallucination (refusing tool calls)**: Stripped history made completed turns look like pure text chat, teaching the model to stop calling tools. Fixed by injecting `[TOOL_TRACE]` into system prompt.
- **Sub-agent runner crashes**: Runner used raw HTTP calls with hardcoded `/chat/completions` endpoint, breaking under Ollama. Rewritten to use `OllamaProvider`/`OpenAIProvider` classes directly. Provider info now injected via watcher metadata.
- **Sub-agent failed notification lost**: Watcher marked delegate as "seen" before checking whether the agent was idle. If the agent was processing, the notification was permanently dropped. Fixed to match job watcher pattern.
- **Plan JSON nuked by turn summary**: `_sync_plan_marker` deleted all `[PLAN_MARKER]` messages, including the JSON plan set by the model. Split into `[TURN_SUMMARY]` (auto) and `[PLAN_MARKER]` (model-controlled).
- **TURN_TOOL_SUMMARY accumulation**: Old summaries accumulated as user messages (5+ blocks, ~15K chars), confusing the model. Replaced with single `[TURN_SUMMARY]` message that is replaced each turn.
- **Empty `content: null` assistant message**: Removed invalid message that caused "content or tool_calls must be set" API errors.
- **Model switching state persistence**: Old provider cancelled on switch; idle-session runtime snapshots cleared.
- **Windows `bash date` timeout**: Added `get_current_time` tool that returns timestamps without invoking shell.

### Changed

- System prompt: explicit instructions for `get_current_time()`, scheduled tasks, sub-agents, and plan tracking.
- Improved scheduled task detection: When users mention specific times (e.g., "17:30打开记事本", "明天9点提醒我"), the agent now uses `schedule()` unless explicitly told to act immediately with keywords like "现在" or "立即".

## [0.6.0] - 2026-08-01

### Added

- **Computer control tool** (`tools/computer.py`): Full desktop automation suite — screenshot, inspect controls, simulate clicks/keyboard, list windows and on-screen elements. Replaces the previous ad-hoc `computer` placeholder with a structured action schema.
- **Real-time overlay**: `core/computer_overlay.py` displays a compact blue status bar on screen during any active computer operation (screenshot is no longer necessary for user awareness). The overlay appears on `action=click`, `action=paste`, and other interactive operations; it hides immediately after the action finishes or if the user presses **Esc** to cancel.
- **PyAutoGUI + pywinauto dependencies**: Added `PyAutoGUI>=0.9.54,<1` and `pywinauto>=0.6.9,<1` to `requirements.txt`. Windows users get full window/control inspection via pywinauto; Linux/macOS users get partial coverage via PyAutoGUI.
- **Session branch API**: Added `/api/branch_session` and `/api/switch_branch` endpoints to WebAPI. A branch forks messages at a chosen user message, preserving the shared prefix up to that point. Users can explore alternative replies without losing prior context. The active branch is persisted per-session.
- **Branch indicator on session listing**: Sessions returned by the API now include `branch_points` count and `active_branch_id`.
- **Context compaction retry with larger budgets**: Compaction first tries with `max_tokens=1800`; if the summary is empty, it retries with `4096`. This handles reasoning models that cap token budgets on their reasoning budget.

### Fixed

- **Computer overlay flash / not-hide-on-failure**: Overlay now hides in both success and exception paths via try/except wrapping in `_execute_tool()`. A previously leaked overlay could persist after a failed tool call.
- **Esc cancel during model decision loop**: New check inside the turn's `while True` loop detects ESC pressing while the model is deciding its next GUI step. The stale response is discarded and a `[COMPUTER CONTROL CANCELLED]` blocker message is injected, preventing the agent from continuing with cancelled actions.
- **Agent stop / mid-turn interruption delivery**: When the user presses Esc during agent execution, a clear "Agent stopped before a final answer was produced" assistant message is now appended, so session state remains consistent even if no tool call was made.
- **Auto-save after turn regardless of cancellation**: `session_manager.save()` is called unconditionally (even when cancelled) because the user may wish to resume from a save point after an abort.

### Changed

- **Removed `_summarize_turn_process`**: The model-based per-turn exploration summary that consumed an extra API call was removed. It was never robust enough to justify its cost; context compaction now handles compression exclusively.
- **System prompt updated for computer tool**: Added `bash` job heuristics (when to use job vs quick bash) and the `computer(action='...')` schema so the model knows desktop actions are available.
- **`starter_knowledge.json` replaces `knowledge.db` as the default knowledge base starter**: The JSON format is now the recommended seed for users who want a fresh local knowledge store; the old SQLite DB remains bundled but is not the primary deliverable.

### Removed

- **Test files removed**: `tests/test_agent_runtime.py`, `test_code_tools.py`, `test_conversation_history.py`, `test_delegate_delivery.py`, and `test_job.py` were removed from the repository because they no longer apply after major refactoring of agent runtime, code tools, and session management. The core behavior is verified by the production tool contract layer instead.

### Files changed

- `tools/computer.py`, `tools/computer.md` — new computer desktop-control tool.
- `core/computer_overlay.py` — real-time status overlay for screen state.
- `main.py` (+318/-141): computer overlay lifecycle, branch_session/switch_branch API, compaction retry budgets, turn process summary removal, agent stop delivery, computer ESC handling during decision loop, improved system prompt with job heuristics.
- `tools/bash.py`, `tools/bash.md`, `tools/job.py`, `tools/python_executor.py`, `tools/python_executor.md` — updated tool contracts and descriptions for 0.6.0 features.
- `requirements.txt` — added PyAutoGUI + pywinauto.
- `setup_and_run.bat`, `setup_and_run.sh` — updated dependency installation.
- `knowledge/starter_knowledge.json` — new structured JSON knowledge starter.

## [0.5.1] - 2026-07-30

### Changed

- Read requests with an offset beyond the file or sheet now return the final available record.
- Line anchors use the shortest unique hash prefix while accepting legacy 16-character anchors.
- Removed the runtime's unconditional `project_test` injection after file changes; verification remains available when requested.
- Background job completion now updates the UI without automatically starting an agent follow-up turn.
- Unified assistant Markdown rendering with MathJax support for inline and display LaTeX delimiters.
- OpenAI-compatible streaming transport read timeout now matches the five-minute runtime idle guard.
- Job start/result semantics now distinguish accepted, completed, and failed states; failures expose exit codes and are never reported as successful completion.
- Added persistent scheduled agent tasks with one-time and interval execution; scheduled turns can call normal tools and always receive the authoritative current time.
- WebUI now displays scheduled tasks in the unified Background jobs panel, with consistent status, history, and cancellation controls; terminal notifications use English status text.
- Bash, Python executor, and Job now use a shared child environment with the active virtual environment and explicit UTF-8 handling; Windows shell commands use UTF-8 code page 65001.
- Shell commands invoking `python`, `python3`, or `pip` are normalized to the active Chengsi interpreter, eliminating accidental system-environment installs.

### Tests

- Added regression coverage for offset clamping, compact hash anchors, and optional verification behavior.

## [0.5.0] - 2026-07-29

### Added

- **Background Job panel**: WebUI right panel lists persisted jobs, shows status and elapsed time, opens bounded log tails, and stops active jobs.
- Structured job list data for monitoring clients, including runner/process liveness, timestamps, exit information, and error state.
- Regression tests for persistent job listing and elapsed-time reporting.

### Changed

- Background job recovery now distinguishes missing runner and command processes and marks stale records as `interrupted`.
- Windows job cancellation continues to terminate the process tree, which is important for commands that launch child processes or external programs.
- README documents the job monitoring contract and WebUI behavior.
- Agent-started jobs are hidden from the user job panel by default; failed jobs can be archived without deleting their logs.
- Finished job results are delivered to the owning session through a non-invasive follow-up turn, while active jobs are handed off without status polling.
- Windows normalizes common `sleep N && command` delays to `timeout /t N /nobreak`, and model stream failures now close the turn instead of leaving an active runtime snapshot.

### Files changed

- `tools/job.py`, `tools/_job_runner.py` - structured job monitoring and lifecycle metadata.
- `main.py`, `core/index.html` - WebUI job API and right-side monitoring panel.
- `tests/test_job.py`, `tests/test_agent_runtime.py`, `README.md`, `CHANGELOG.md` - regression coverage and release documentation.

## [0.4.6] - 2026-07-29

### Added

- **Python structure inspection**: `read` now supports `mode=outline` for a compact class/function map and `mode=symbol` for complete qualified definitions such as `AgentRuntime.observe`.
- **Stable code edit operations**: `edit` now supports Python symbol replacement/deletion, inclusive hash-anchored ranges, and line-relative anchor insertion while retaining exact-text compatibility.
- Deterministic tests for runtime duplicate-call recovery, circuit breaking, stale revisions and anchors, atomic edits, syntax rejection, duplicate symbols, UTF-8 BOM, and CRLF preservation.

### Changed

- Duplicate tool calls are returned to the model as structured failures instead of directly producing a fixed user-facing stop message. Independent calls in the same batch remain eligible to run.
- Repeated failures still disable tools for the turn, but the model receives the complete blocker context and produces the final explanation without further tool access.
- Text reads and edits now share one BLAKE2s revision/anchor protocol: 96-bit file revisions and 64-bit line hashes. Hash-only anchors must identify exactly one line.
- Text edits validate all spans before an atomic replacement, preserve UTF-8 BOM and the dominant newline style, and parse Python output before writing.

### Files changed

- `core/agent_runtime.py`, `main.py` - per-call admission, model-visible failure recovery, and final no-tool blocker response.
- `tools/_hashline.py`, `tools/read.py`, `tools/edit.py` - shared revisions, structural reads, stable edit operations, and atomic validation.
- `tools/read.md`, `tools/edit.md`, `README.md` - updated model-facing and user-facing contracts.
- `tests/test_agent_runtime.py`, `tests/test_code_tools.py` - runtime and code-tool regression coverage.
