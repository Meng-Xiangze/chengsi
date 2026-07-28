# Changelog

All notable changes to Chengsi will be documented in this file.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project intends to use [Semantic Versioning](https://semver.org/).

## [Unreleased]

## [0.4.2] - 2026-07-28

### Added

- **CSV/XLSX file tools**: `read`, `write`, and `edit` now support `.csv` and `.xlsx`. Reads paginate spreadsheet rows and label worksheets; writes accept CSV-style rows plus optional `[Sheet: name]` sections; edits replace or delete a value only when `oldText` identifies exactly one complete cell.
- **One-turn process summaries**: after each tool batch, Chengsi can call the active model to produce a concise factual handoff containing findings, changed files, failures, unresolved questions, and the next action. The note is available only to subsequent inner steps of the same user turn and is filtered before the next user message, so it does not become permanent context.
- **Manual fallback request mode**: Settings now provides a fallback switch for provider compatibility incidents. While enabled, the current request disables tools and sends the prepared conversation as one JSON bundle inside a single text-only user message; no provider-error text parsing is performed.
- **Dependency installation preference**: Settings and `config.json` now expose `auto_install_dependencies` (default `false`). Optional spreadsheet support may run `python -m pip install openpyxl` when enabled; otherwise the tool returns an explicit installation instruction.
- Added `openpyxl` to standard requirements for first-party XLSX support.

### Changed

- Updated the WebUI settings dialog, example configuration, README architecture/configuration/tool tables, and tool Markdown catalog for the new modes.

### Files changed

- `main.py` — settings state/API, one-turn summary lifecycle, fallback-mode routing.
- `core/index.html` — Settings dialog and fallback/dependency toggles.
- `core/openai_provider.py` — text-only JSON-bundle fallback payload.
- `core/ollama_provider.py` — text-only JSON-bundle fallback payload.
- `tools/_spreadsheet.py` — shared CSV/XLSX read, write, edit, and optional dependency helpers.
- `tools/read.py`, `tools/write.py`, `tools/edit.py` — spreadsheet dispatch and schemas.
- `tools/read.md`, `tools/write.md`, `tools/edit.md`, `tools/TOC.md` — tool documentation.
- `requirements.txt`, `config.example.json`, `README.md`, `CHANGELOG.md` — dependency, settings, user documentation, and release notes.

## [0.4.1] - 2026-07-27

### Changed

- **Context management rewritten**: removed the fixed 24-message working window (`_MAX_WORKING_MESSAGES`). The model now receives the full conversation history by default — no silent truncation.
- **Tool-call intermediate cleanup**: completed-turn tool-call and tool-result messages are now stripped from the model request on each new user turn. Within a single agent turn (inner loop) the model still sees all tool calls and results; when the user sends a new message (outer loop), previous-turn intermediates are removed and only user messages and assistant text responses remain. This prevents context pollution and saves tokens without losing substantive conversation content.

## [0.4.0] - 2026-07-27

### Fixed

- **Streaming agent checkpoints**: normal model content is now emitted to the UI as `agent_delta` chunks while the provider is still streaming, and the existing thinking/tool/result events remain incremental. The agent loop still waits for complete tool-call arguments before executing a tool, then immediately resumes the next model step.
- **Ordered assistant message segments**: the WebUI now ends the current streamed assistant bubble at each tool call and starts a new bubble after the tool result, preserving the agent's actual speaking and action order instead of merging the entire turn into one message.
- **Clipboard attachments**: pasting an image into the message box saves it under the Chengsi `media` directory and attaches the local path for model inspection. Files copied from Windows Explorer are now read from the native clipboard and added as attachments with `Ctrl+V`. Clipboard content remains out of the chat JSON and uses the existing attachment path flow.
- **Clipboard dependency bootstrap**: setup now installs and verifies `pywin32`, including `win32clipboard` and `win32con`, so Windows Explorer file paste works in newly created and existing virtual environments.
- **Copy chat messages**: user and assistant message bubbles now expose a Copy action that copies the original message text to the system clipboard.
- **Empty model response**: provider responses that return no content and no tool calls are now detected and surfaced as an explicit error rather than silently advancing the agent loop with an empty assistant turn.

### Changed

- **Short progress guidance**: the system prompt now asks for brief progress checkpoints and immediate action when the next step is clear, without requesting or exposing long private reasoning.

- **Portable Windows setup bootstrap**: `setup_and_run.bat` now creates the project-local virtual environment with the current user's `py -3` or `python` launcher, with an optional `CHENGSI_PYTHON` override, instead of depending on any developer-specific Python installation path. It also detects and rebuilds virtual environments copied from another computer, and the global launcher delegates to the same self-repair path.
- **Windows dependency self-check**: setup now verifies that pip and all required runtime modules are available before starting Chengsi, restores pip with `ensurepip` when necessary, retries PyPI installation with explicit trusted hosts after certificate-time failures, and verifies imports after installation.
- **Windows WebView2 prerequisite**: setup now checks registry and common installation paths for Microsoft Edge WebView2 Runtime, attempts `winget`, and falls back to downloading and silently running the official Evergreen x64 installer when absent, preventing `pywebview` from silently falling back to the legacy MSHTML renderer.
- **Task-safe context compaction**: compaction now includes the recent verbatim context in addition to older history, treats the latest explicit user request as authoritative, records later corrections as obsolete tasks, separates verified facts from unverified claims, and requires concrete next actions. This prevents an old completed task from replacing a newer task after repeated compaction and debugging cycles.
- **Compaction regression coverage**: added a deterministic test ensuring a recent user correction overrides an obsolete task in the generated handoff prompt.

## [0.3.2-rc.1] - 2026-07-27

### Changed

- **Pi-style tool loop safety**: removed the fixed 20-call hard stop. Agent runs now rely on targeted protections: exact-call repetition limits, explicit consecutive tool failures, cancellation, bounded tool output, and working-context compaction.
- **Atomic tool batches**: a model-emitted batch is admitted in full or rejected in full. Parallel tools still execute concurrently, but final tool-result messages are appended to model context together and in the model's original call order.
- **Structured tool outcomes**: tool results can report `ok`, `error_code`, `exit_code`, and `duration_ms`. `bash` now reports nonzero exit codes structurally. Generic result handling no longer infers failure from words such as `FAIL`, `FAILED (` or `N failed` inside otherwise successful file or command output.
- **Tool lifecycle telemetry**: execution now emits `tool_execution_start` and `tool_execution_end` events with call identity, status, error code, and duration while preserving the existing user-visible tool call/result events.

### Fixed

- Successful reads of source files, logs, documentation, and test fixtures containing failure phrases no longer trip the consecutive-failure circuit breaker.
- Rejected parallel batches no longer execute or consume duplicate-call accounting for only a subset of sibling calls.
- `project_test` failures remain explicit structured verification failures after removal of generic text-content failure heuristics.

## [0.3.1] - 2026-01-26

### Changed

- **Token efficiency — tool result wrapper removed**: `ToolOutcome.for_model()` no longer prefixes every result with `[TOOL_RESULT status=ok code=...]`. Success results pass through unchanged; only errors get an `Error: ` prefix. Saves ~50 chars per tool call.
- **Token efficiency — knowledge base context retrieved once per turn**: KB context is now fetched before the tool-call loop instead of re-retrieved and re-appended to the system prompt on every iteration. Eliminates redundant system prompt growth during multi-tool turns.
- **Token efficiency — tighter agent loop limits**: reduced `_MAX_TOOL_CALLS` 30→20 and `_MAX_WORKING_MESSAGES` 48→24, shrinking the maximum context window per turn and encouraging earlier context compaction.
- **Token efficiency — compact tool parameter descriptions**: trimmed verbose parameter `description` strings across `read`, `edit`, `write`, `web_reader`, `knowledge_base`, `system_cleaner`, and `python_executor` tool definitions. Total tool definitions payload reduced ~30%.
- **Parallel tool calls actually triggered**: added explicit instruction to the system prompt directing the model to batch independent operations into a single multi-tool-call response. The parallel execution infrastructure (`parallel_tools: true`, `ThreadPoolExecutor`) already existed but was never exercised because the model was never told it could emit multiple tool calls at once. Verified with `tests/test_parallel_tools.py` confirming concurrent execution when multiple tool calls are issued.

### Fixed

- **JSON repair fallback (json_repair)**: added `core/json_repair.py` module with deterministic JSON repair inserted before all `json.loads` calls in Ollama/OpenAI providers. Handles common JSON formatting errors from local models (Fable, Qwen, etc.): unclosed strings/brackets, trailing commas, single quotes, Unicode curly quotes, markdown code fences. Core `_balance` algorithm scans once to complete missing closures, ensuring at least valid closed JSON objects are returned to the model instead of silently discarding arguments due to parse failures (resulting in `{}`).

## [0.3.0] - 2026-07-25

### Added

- **Unified `read` tool**: single tool for text files, PDF, DOCX, images, and code search. Supports `offset`/`limit` pagination, `glob`/`ext`/`case_sensitive` search filters, and dual text/visual modes for PDF and DOCX.
- **`write` tool**: create or overwrite text files and formatted DOCX with Markdown-like syntax (`**bold**`, `*italic*`, `^superscript^`, `_subscript_`, `{size:N}`, `{color:...}`, headings, lists, tables, images).
- **`edit` tool**: precise file editing with exact-text anchors. Supports replace, insert_before, insert_after, delete, prepend, and append operations. Works on both text files and DOCX paragraphs.
- **`bash` tool**: execute shell commands (cmd on Windows, bash on Linux/Mac) with 60s timeout. Prefer for file ops, git, and one-shot terminal tasks.
- **`ls` tool**: list directory contents with file sizes and types.
- **DOCX read support**: text extraction with formatting markers, numbered list reconstruction from `word/numbering.xml`, table extraction, MathType equation placeholders, embedded image counting, and visual mode (LibreOffice page render or zip image extraction).
- **PDF read support**: per-page text extraction via PyMuPDF (primary) or pypdf (fallback), and visual mode rendering pages at 200 DPI for vision models.
- **Auto image description**: non-vision models automatically route images to the configured default vision model for one-shot description.
- **Default model conventions**: `provider/model` format in `config.json` (`default_vision_model`, `default_image_model`) to avoid cross-provider name collisions.
- **Stream cancel responsiveness**: thread+queue wrapper (`_iter_stream_with_cancel`) polls cancel event every 0.15s instead of blocking on generator iteration.
- **Operation spinners**: the WebUI shows a spinner during context compaction and chat export to indicate active processing.
- **Parallel tool execution**: optional concurrent execution of multiple tool calls from a single model response, with iOS-style toggle switch in the WebUI. Preflight (permission checks) runs sequentially; independent tools execute in a thread pool (up to 6 workers); observe steps run sequentially in original call order. Defaults to off (`parallel_tools: false`).

### Changed

- **Tool consolidation**: reduced from 14 to 13 tools by removing redundancy. `read` replaces `image_reader` + `code_context`; `edit` replaces `code_editor`; standalone `grep`, `file_deleter`, `tool_creator`, and `tool_info` removed as their functionality is covered by other tools.
- **System prompt simplified**: tool descriptions are now exclusively delivered through native function calling — the system prompt no longer embeds tool lists or text-call protocols.
- **`system_cleaner` simplified**: reduced from 8 parameters to 2 (`target_type`, `dry_run`), code reduced from 290 to 130 lines.
- **`python_executor` and `bash` descriptions**: clear mutual cross-references so models can route to the right tool (bash for file ops/git/one-shots, python_executor for multi-step logic/data processing).
- **`build_tool_defs`**: uses `.md` front-matter descriptions as the primary source, falling back to `.py` tool class descriptions. Descriptions stay concise (~100-200 chars).
- **Stop behavior**: cancel immediately returns to the user instead of waiting for a stuck stream producer. Stop markers saved to conversation history for clean reload.

### Removed

- `code_editor` — replaced by `edit`
- `code_context` — merged into `read`
- `image_reader` — merged into `read`
- `web_search_read` — models can chain `web_searcher` → `web_reader` natively
- `grep` — merged into `read` (search mode with `glob`/`case_sensitive`)
- `file_deleter` — `bash rm` covers file deletion
- `tool_creator` — `write` covers tool file creation
- `tool_info` — `read` covers tool documentation reading
- Legacy text-based tool call protocol (`_legacy_tool_prompt`, `_parse_tool_call_json`) — all models now use native function calling
- `user_requested_tool_creation` and `_turn_tools` filtering

### Fixed

- **Numbered lists in DOCX**: counters now tracked per `(numId, ilvl)` from `word/numbering.xml`, supporting decimal and bullet formats across 9 nesting levels.
- **MathType equations in DOCX**: `<w:object>` elements detected and represented as `[Equation]` placeholders instead of being silently dropped.
- **YAML front-matter parsing**: colons in description values no longer break YAML parsing in tool `.md` files.
- **Stop marker persistence**: `*[stopped]*` messages saved to conversation so reloaded sessions show the correct end state.
- **Qwen3 thinking + tools → empty output**: Ollama provider now detects when Qwen-based models emit tool calls as raw text inside ` ` blocks instead of native `tool_calls` (Ollama #10976). When a response produces thinking text but zero `content` and zero native `tool_calls`, the provider scans the accumulated thinking buffer for `<tool_call>...</tool_call>` blocks and extracts them, supporting both Hermes-style JSON (`{"name":"...","arguments":{...}}`) and Qwen-Coder XML (`<function=name><parameter=k>v</parameter></function>`) formats. Thinking remains enabled (`think: true`) so the model retains full reasoning quality; the extraction is a pure safety net that only activates when the model would otherwise produce nothing.
## [0.2.0] - 2026-07-24

### Added

- Add durable agent runtime snapshots, tool budgets, duplicate-call protection, failure circuit breaking, and post-edit verification requirements.
- Add Markdown skill discovery and direct `/tool` and `/knowledge` resource commands.
- Add safe file deletion, project unittest execution, richer web tools, attachment folders, and multimodal image handling.
- Add regression coverage for runtime recovery, provider tool-call chains, compaction, resource commands, and executable tool schemas.

### Changed

- Use Python tool schemas as the executable source of truth while keeping Markdown documentation descriptive.
- Improve the chat UI with attachment chips, folder selection, operation spinners, Markdown tables, and math formatting.
- Allow any model configured with `tools: false` to use a documented text tool-call protocol without model-specific handling.
- Preserve native Ollama tool-call history and normalize arguments for consecutive calls.

### Fixed

- Close knowledge-base SQLite connections reliably on Windows.
- Drop orphaned OpenAI tool results after context changes.
- Make system cleanup safer and restore explicit tool capability metadata.

## [0.1.2] - 2026-07-24

### Added

- Register `CHENGSI_HOME` and the installation directory in the user environment during Windows setup.
- Add a `chengsi.bat` launcher for starting Chengsi from any directory.

### Changed

- Windows setup now supports repeatable launches after installation without changing to the project directory.

## [0.1.1] - 2026-07-24

### Added

- Configurable `auto`, `direct`, and `system_proxy` network modes for online providers.
- Content-verified line anchors and file revisions for atomic source edits.
- Regression tests for network fallback and hash-anchored editing.

### Changed

- Local Ollama traffic always bypasses desktop HTTP proxies.
- Tool usage is discovered from tool documentation instead of being embedded in the system prompt.
- Python tool execution now runs in an isolated non-interactive child process with captured output.

### Fixed

- Online provider access when a VPN or unusable desktop proxy is enabled.
- Child command output and interactive prompts leaking into Chengsi's background console.
- Stale, overlapping, or ambiguous source edits modifying the wrong content.

## [0.1.0] - 2026-07-23

Initial public preview.
