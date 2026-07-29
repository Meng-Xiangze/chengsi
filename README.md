# Chengsi (澄思)

**Version 0.4.6**

Chengsi is a local intelligent assistant with a desktop WebUI, configurable model providers, a persistent local knowledge base, session history, and an extensible Python tool system. It is designed for users who want an assistant they can run and customize on their own computer.

> Chengsi can execute Python and perform local file operations through tools. The protection checks reduce accidental damage, but they are not a security sandbox. Review enabled tools, use trusted model providers, and keep backups of important data.

## Features

- Local desktop chat interface powered by `pywebview`
- Local Ollama and OpenAI-compatible model providers
- Native function calling for all models — no text-based tool protocols
- 14 discoverable tools: read (text, CSV, XLSX, PDF, DOCX, images, code search, Python outlines/symbols), write, edit (symbol, hash-range, and exact-text operations), bash, job, ls, python_executor, web_searcher, web_reader, knowledge_base, chat_exporter, system_cleaner, project_test, and image_generator
- SQLite FTS5 local knowledge base with user-managed search, ingest, list, and remove operations
- Persistent conversations and generated media
- Image generation through a configured image-capable model
- PDF and DOCX reading with dual text/visual modes — vision models can see rendered pages
- DOCX creation with Markdown-like formatting syntax
- CSV/XLSX reading, creation, and exact-cell editing through the standard file tools
- One-turn process summaries preserve factual exploration across inner tool loops and expire before the next user turn
- User-controlled text-only fallback requests and optional automatic pip installation in Settings
- Per-model Chat Completions or Responses API selection for OpenAI-compatible aggregators
- Persistent background jobs for commands that run for minutes or hours, with status, log, list, and cancel operations
- Tool failures and duplicate-call limits are returned to the model for recovery; independent calls in the same batch continue, while repeated failures still trigger a tool-execution circuit breaker
- Stable code editing with file revisions, 64-bit line anchors, atomic writes, Python symbol replacement, and syntax validation
- Progress-based model-stream protection: five minutes without an event stops a stalled request, but active turns have no total duration limit
- Day and night themes
- Optional parallel tool execution — run independent tools concurrently
- **Qwen/Ollama thinking safety net**: when Qwen-based models emit tool calls as raw text inside ` ` blocks instead of native function calls (a known Ollama interaction), the provider automatically extracts and executes them — thinking stays on so the model keeps its full reasoning quality
- Responsive cancel: stops immediately without waiting for stuck streams

Knowledge-base records are user-managed. Use the `knowledge_base` tool to search, ingest text or supported local files, list documents, and remove selected records. The bundled `knowledge/knowledge.db` contains the project's starter knowledge and is included for release; do not edit the SQLite file directly.

## Requirements

- Python 3.10 or newer
- Windows 10/11 recommended
- Ollama for the default local configuration, or an OpenAI-compatible API
- Internet access only when using online providers or web-connected tools

## Tips for Local Models

Chengsi's default configuration uses Ollama with Qwen3 8B, a capable but resource-constrained local model. To get the best results:

- **Go step by step.** Ask for one clear action at a time ("read README.md", "list the tools/ directory") rather than bundling multiple complex tasks into a single message.
- **Break down complex tasks.** Instead of "build a complete Snake game and launch it," start with "create a snake.py file with the game loop" and iterate from there.
- **Be specific about file paths.** Say "put it on my Desktop at C:\\Users\\...\\Desktop" rather than "put it on the desktop."
- **Use `bash` for install commands directly.** "pip install pygame" is more effective than describing the need for pygame and hoping the model infers the command.
- **Watch the token counter** in the top bar. When context exceeds ~20K tokens with small models, reasoning quality degrades noticeably. Use the ↧ compact button to reclaim space.
- **Thinking stays on.** The Ollama provider keeps `think: true` so the model reasons before acting. If the model ever produces thinking text but fails to emit a tool call, Chengsi automatically scans the thinking buffer and extracts any tool calls it finds — this works around a known Ollama interaction with Qwen models.

## Quick Start

### Windows

1. Install [Python 3.10+](https://www.python.org/downloads/).
2. Install [Ollama](https://ollama.com/) and pull the default model:

```powershell
ollama pull qwen3:8b
```

3. Clone the repository and enter it:

```powershell
git clone https://github.com/Meng-Xiangze/chengsi
cd Chengsi
```

4. Double-click `setup_and_run.bat`.

The script creates a project-local `.venv`, installs dependencies, verifies the required runtime modules, checks for Microsoft Edge WebView2 Runtime, copies `config.example.json` to the private `config.json` when needed, registers the user-level `CHENGSI_HOME` environment variable pointing to the installation directory, adds that directory to the user `PATH`, and starts Chengsi via `chengsi.bat`. WebView2 is required for the modern Windows interface; the installer checks common installation locations, attempts `winget`, and then downloads and runs the official Evergreen x64 installer when it is missing. It automatically detects Python using the Windows launcher (`py -3`) or `python`; it does not depend on the installer's username or Python location. Set `CHENGSI_PYTHON` to an explicit Python executable path only when automatic detection fails. After setup completes, open a new terminal and run `chengsi` from any directory to start it again.

### Manual Start

```powershell
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
copy config.example.json config.json
python launcher.py
```

### macOS and Linux

```bash
git clone https://github.com/Meng-Xiangze/chengsi
cd Chengsi
chmod +x setup_and_run.sh
ollama pull qwen3:8b
./setup_and_run.sh
```

Windows is the primary tested platform. macOS and Linux may require extra `pywebview` system packages, and desktop integration or local system tools may behave differently. See the [pywebview installation guide](https://pywebview.flowrl.com/guide/installation.html).

## Configuration

Chengsi reads `config.json` from the project root. The setup scripts create it from `config.example.json`. Keep `config.json` private because it may contain API keys.

### Complete Structure

```json
{
  "providers": [
    {
      "type": "ollama",
      "name": "Local Ollama",
      "base_url": "http://localhost:11434/api",
      "models": [
        {
          "name": "qwen3:8b",
          "vision": false,
          "image_generation": false
        }
      ]
    },
    {
      "type": "openai",
      "name": "OpenAI-compatible Provider",
      "api_key": "sk-example-replace-me",
      "base_url": "https://api.example.com/v1",
      "models": [
        {
          "name": "example-chat-model",
          "request_api": "chat_completions",
          "vision": true,
          "image_generation": false
        },
        {
          "name": "example-image-model",
          "request_api": "chat_completions",
          "vision": false,
          "image_generation": true
        }
      ]
    }
  ],
  "default_vision_model": "openai/gpt-5.6-sol",
  "default_image_model": "openai/gpt-image-2",
  "parallel_tools": false,
  "fallback_mode": false,
  "auto_install_dependencies": false,
  "show_thinking": true,
  "theme": "day"
}
```

### Top-Level Fields

| Field | Type | Meaning |
| --- | --- | --- |
| `providers` | array | Ordered list of model providers shown in the model selector. |
| `default_vision_model` | string | `provider/model` identifier for auto image description. Non-vision models route images here. |
| `default_image_model` | string | `provider/model` identifier used by the `image_generator` tool. |
| `show_thinking` | boolean | Shows model reasoning/status events in a collapsed UI section when available. |
| `parallel_tools` | boolean | When true, independent tool calls from a single assistant response execute concurrently. Default: `false`. |
| `fallback_mode` | boolean | Sends the request as one text-only JSON bundle and disables tools. Use manually after a provider rejects structured messages. Default: `false`. |
| `auto_install_dependencies` | boolean | Allows optional features to run `python -m pip install` when their module is missing. Default: `false`. |
| `theme` | string | Initial interface theme: `day` or `night`. |

### Provider Fields

| Field | Required | Meaning |
| --- | --- | --- |
| `type` | Yes | Provider adapter. Supported values are `ollama` and `openai`. |
| `name` | Yes | Human-readable provider name shown in the UI. |
| `base_url` | Yes | Provider API root. Ollama normally uses `http://localhost:11434/api`; OpenAI-compatible services commonly use a URL ending in `/v1`. |
| `api_key` | OpenAI-compatible only | Bearer token sent to the provider. Use a fake placeholder in public examples. |
| `network_mode` | No | Online connection policy: `auto` (default, direct first with safe system-proxy fallback), `direct`, or `system_proxy`. Local Ollama always connects directly. |
| `models` | Yes | Models available under this provider. Each entry may be a string or a model object. Objects are recommended. |

### Model Fields

| Field | Required | Meaning |
| --- | --- | --- |
| `name` | Yes | Exact model identifier accepted by the provider. |
| `request_api` | OpenAI-compatible chat models | Request endpoint and streaming protocol for this exact model. Use `chat_completions` for `/chat/completions` or `responses` for `/responses`. If omitted, Chengsi uses `chat_completions` for backward compatibility. |
| `vision` | No | Enables image input for the model. Set this only when the chat model accepts image content. Default: `false`. |
| `image_generation` | No | Routes requests made with this selected model to the image generation endpoint. It also makes the model available to the `image_generator` tool. Default: `false`. |
| `tools` | No | Override native tool-calling support. Set `true` or `false` explicitly. Default: auto-detected from provider type. |

`request_api` is deliberately model-level rather than provider-level. Aggregators can route models behind one base URL to unrelated upstream vendors, so each model states its own request contract without inheritance or ambiguous provider defaults.

The same provider can therefore contain models using different APIs:

```json
{
  "type": "openai",
  "name": "Aggregator",
  "api_key": "sk-example",
  "base_url": "https://api.example.com/v1",
  "models": [
    {
      "name": "vendor-a-model",
      "request_api": "chat_completions",
      "vision": false,
      "image_generation": false
    },
    {
      "name": "vendor-b-model",
      "request_api": "responses",
      "vision": false,
      "image_generation": false
    }
  ]
}
```

The Settings dialog edits this field on the currently selected model. Fallback request mode is separate: it JSON-packs the conversation into one text message, disables tools, and sends that text through the selected model's `request_api`.

`vision` and `image_generation` describe different capabilities. A model can analyze images without generating them, and an image generation model does not automatically support chat or image analysis.

Provider model names and capabilities vary by service. The names above are examples, not a claim that a specific provider offers them. Confirm the exact identifier and endpoint in your provider documentation.

### Local Ollama Example

```json
{
  "type": "ollama",
  "name": "Local Qwen",
  "base_url": "http://localhost:11434/api",
  "models": [
    {
      "name": "qwen3:8b",
      "vision": false,
      "image_generation": false
    }
  ]
}
```

### OpenAI-Compatible Example

```json
{
  "type": "openai",
  "name": "My API Provider",
  "api_key": "sk-example-replace-me",
  "base_url": "https://api.example.com/v1",
  "network_mode": "auto",
  "models": [
    {
      "name": "example-model",
      "request_api": "chat_completions",
      "vision": false,
      "image_generation": false
    }
  ]
}
```

Multiple providers and models can be configured in the same `providers` array. The Settings dialog can change `request_api` for the currently selected OpenAI-compatible model and writes the choice directly into that model object. Restart Chengsi after other manual edits to `config.json`.

In `auto` mode, Chengsi bypasses desktop/VPN HTTP proxies first and falls back to the system proxy only when connection establishment fails before any HTTP response is received. It never retries after a response or streamed data begins. `direct` bypasses HTTP/SOCKS environment and Windows proxy settings, but a VPN using TUN or global routing may still intercept traffic at the operating-system route layer.

## Architecture

```text
WebUI (core/index.html)
        |
        v
WebView API and agent loop (main.py)
        |
        +--> Provider adapters (core/provider.py)
        |      +--> Ollama (core/ollama_provider.py)
        |      +--> OpenAI-compatible (core/openai_provider.py)
        |
        +--> Tool manager (core/tool_manager.py)
        |      +--> 13 auto-discovered tools in tools/
        |      +--> built-in image_generator
        |      +--> read (text, CSV, XLSX, PDF, DOCX, images, search)
        |      +--> write (text, CSV, XLSX + formatted DOCX)
        |      +--> edit (surgical text/DOCX + exact spreadsheet cells)
        |
        +--> Knowledge base (core/knowledge_base.py -> SQLite FTS5)
        |
        +--> Session manager (core/session_manager.py -> sessions/ and media/)
```

### Runtime Flow

1. The WebUI sends a user message through the `pywebview` bridge in `main.py`.
2. `main.py` selects the configured provider and builds the system prompt and tool definitions.
3. OpenAI-compatible models use their configured `request_api`: Chat Completions streams `/chat/completions` events, while Responses streams `/responses` output, reasoning, usage, and function-call events. Ollama continues to use its native chat endpoint.
4. Tool calls are resolved by `ToolManager`; when `parallel_tools` is enabled, independent calls from one response execute concurrently. After tool batches, a short-lived model summary records concrete exploration for the next inner step and is removed before the next user turn. Summary requests stop after 30 seconds without progress and are skipped on failure.
5. Model streams use a five-minute inactivity timeout, not a five-minute turn limit. Every provider event resets the timer, so active multi-step turns may continue as long as needed.
6. Commands expected to run for minutes or hours use the detached `job` tool. Jobs continue outside the conversation worker, persist metadata and logs across Chengsi restarts, and stop only when they finish, fail, or are explicitly cancelled.
7. Final responses and UI events are saved by `SessionManager`.
8. Knowledge searches use the local SQLite FTS5 index and are explicitly invoked through the knowledge-base tool.
9. Generated images are moved into a session-specific directory under `media/` and rendered directly in the WebUI.
10. Stop requests cancel active model streams immediately via a thread+queue polling mechanism without blocking on stuck streams.

### Main Components

| Path | Responsibility |
| --- | --- |
| `main.py` | Application state, WebView bridge, configuration, agent loop, event streaming, and tool orchestration. |
| `core/index.html` | Complete desktop WebUI, including session navigation, model selection, chat rendering, tools, and image display. |
| `core/provider.py` | Abstract provider contract. |
| `core/ollama_provider.py` | Ollama chat streaming and tool-call conversion. |
| `core/openai_provider.py` | OpenAI-compatible SSE chat streaming, image generation, and image auto-description. |
| `core/tool_manager.py` | Tool auto-discovery from `tools/*.py`, metadata catalog from `.md` front-matter, and execution support. |
| `core/knowledge_base.py` | SQLite FTS5 document ingestion, search, listing, and removal. |
| `core/session_manager.py` | Session persistence, titles, history, token statistics, and media cleanup. |
| `tools/` | Extensible local tools and their Markdown documentation. |

## Tools

Chengsi automatically discovers tools from Python files in the `tools/` directory. Each tool inherits from `tools.base.BaseTool` and implements `tool_name`, `description`, `parameters`, and `run(arguments)`.

### Available Tools (14)

| Category | Tools |
| --- | --- |
| File I/O | `read` — text, CSV, XLSX, PDF, DOCX, images, code search. `write` — create/overwrite text, CSV, XLSX, and formatted DOCX. `edit` — precise text/DOCX edits and exact-cell spreadsheet replacement. `ls` — directory listing. |
| Execution | `bash` — bounded foreground shell commands (file ops, git, pip). `python_executor` — bounded foreground Python for multi-step logic and data processing. `job` — persistent background commands with status, logs, list, and explicit cancellation. |
| Web | `web_searcher` — DuckDuckGo search. `web_reader` — fetch and extract web page content. |
| Project | `project_test` — syntax, import, and unittest checks. `system_cleaner` — preview/clean temp files and caches. |
| Meta | `knowledge_base` — local document search and management. `chat_exporter` — export sessions as Markdown. `image_generator` — generate images via cloud API. |

Models receive tool descriptions through native function calling — the system prompt stays lean (~260 tokens) and only tools relevant to the task are described. Each tool's `.md` front-matter provides the canonical description sent to models.

Tools execute on the host computer with the permissions of the Chengsi process. `python_executor` and `bash` are bounded foreground tools. Use `job start` for a command expected to run longer than a normal tool call; it returns a `job_id` immediately, writes combined output to a log, and can be inspected in later turns with `job status` or `job logs`. A quiet background job is not killed automatically, because scientific calculations may legitimately produce no output for long periods. Use `job cancel` only when termination is intended. `system_cleaner` can delete selected files. The `core` and `knowledge` directories belonging to the running project are protected, but this protection is not a general-purpose sandbox.

## Local Data and Privacy

Chengsi stores local runtime data in these paths:

| Path | Contents |
| --- | --- |
| `config.json` | Private provider configuration and API keys. |
| `CHENGSI_HOME` | User-level environment variable pointing to the Chengsi installation folder. |
| `sessions/` | Conversation messages, UI event history, and token statistics. |
| `media/` | Generated images and session media. |
| `%LOCALAPPDATA%/Chengsi/jobs/` on Windows or `~/.chengsi/jobs/` elsewhere | Persistent background-job metadata and combined stdout/stderr logs. |
| `knowledge/knowledge.db` | Local knowledge-base documents and search index. |

These paths are ignored by Git where appropriate. Online providers receive the conversation and tool context sent to them. Local operation does not imply that all enabled providers or tools are offline.

Before sharing logs or issue reports, remove API keys, personal paths, conversation content, generated images, and private knowledge-base material.

## Security Notes

- Use only trusted model providers and tools.
- Review tool calls before enabling the project in an environment containing sensitive data.
- Back up important files before testing file-management tools.
- Do not expose the local WebUI or provider credentials to untrusted networks.
- Treat model output and downloaded knowledge as untrusted content.
- Report security issues privately rather than posting exploit details in a public issue.

## Project Layout

```text
Chengsi/
|-- main.py               core agent loop and WebView bridge
|-- launcher.py           entry point with clipboard compatibility layer
|-- clipboard_compat.py   Windows clipboard workaround for pywebview
|-- config.example.json   template configuration
|-- config.json           (private, not tracked)
|-- requirements.txt
|-- setup_and_run.bat     Windows first-time setup and launch
|-- chengsi.bat           Windows daily-use launcher
|-- setup_and_run.sh      macOS/Linux setup and launch
|-- skills/               optional SKILL.md capability packages
|-- core/
|   |-- index.html        WebUI
|   |-- provider.py       provider abstraction
|   |-- ollama_provider.py
|   |-- openai_provider.py
|   |-- knowledge_base.py SQLite FTS5 knowledge store
|   |-- session_manager.py
|   `-- tool_manager.py   tool discovery and execution
|-- tools/
|   |-- base.py           tool base class
|   |-- TOC.md            tool reference
|   `-- 13 tool modules: read, write, edit, bash, job, ls, python_executor,
|                        web_searcher, web_reader, knowledge_base,
|                        chat_exporter, system_cleaner, project_test,
|                        image_generator (provided by tool_manager)
|-- tests/                unit tests
|-- knowledge/            SQLite database at runtime (private)
|-- sessions/             conversation history at runtime (private)
`-- media/                generated images at runtime (private)
```

## Development Checks

```powershell
python -m compileall -q .
python -c "import main"
python -m unittest discover -s tests -v
```

For a release, also test setup from a clean clone, start the WebUI, send a normal chat message, run a harmless tool, search the knowledge base, generate an image, reload a session, and confirm that private runtime files remain untracked.

## Known Limitations

- Windows is the primary tested platform.
- Tool protection checks reduce common accidents but do not provide OS-level isolation.
- Provider compatibility depends on each service's implementation of chat streaming, tool calls, vision, and image APIs.
- Linux and macOS desktop behavior has not been comprehensively tested.
- DOCX text extraction uses XML parsing; complex layouts may differ from Word's rendered appearance. Use `mode=visual` with a vision model for exact page rendering.

## License

Chengsi is licensed under the [Apache License 2.0](LICENSE). It permits commercial use, modification, distribution, and private use subject to its terms, including preservation of required license and notice information. The license applies to this open-source repository; separately developed commercial products, branding, customer deployments, and private modules may use separate terms.