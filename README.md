# Chengsi (澄思)

Chengsi is a local intelligent assistant with a desktop WebUI, configurable model providers, a persistent local knowledge base, session history, and an extensible Python tool system. It is designed for users who want an assistant they can run and customize on their own computer.

> Chengsi can execute Python and perform local file operations through tools. The protection checks reduce accidental damage, but they are not a security sandbox. Review enabled tools, use trusted model providers, and keep backups of important data.

## Features

- Local desktop chat interface powered by `pywebview`
- Local Ollama and OpenAI-compatible model providers
- Native function calling for all models — no text-based tool protocols
- 13 discoverable tools: read (text, PDF, DOCX, images, code search), write, edit, bash, ls, python_executor, web search/fetch, knowledge base, image generation, and more
- SQLite FTS5 local knowledge base with user-managed search, ingest, list, and remove operations
- Persistent conversations and generated media
- Image generation through a configured image-capable model
- PDF and DOCX reading with dual text/visual modes — vision models can see rendered pages
- DOCX creation with Markdown-like formatting syntax
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

The script creates `.venv`, installs dependencies, copies `config.example.json` to the private `config.json` when needed, registers the user-level `CHENGSI_HOME` environment variable, adds the installation folder to the user `PATH`, and starts Chengsi. Open a new terminal afterward and run `chengsi` from any directory to start it again.

### Manual Start

```powershell
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
copy config.example.json config.json
python main.py
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
          "vision": true,
          "image_generation": false
        },
        {
          "name": "example-image-model",
          "vision": false,
          "image_generation": true
        }
      ]
    }
  ],
  "default_vision_model": "openai/gpt-5.6-sol",
  "default_image_model": "openai/gpt-image-2",
  "parallel_tools": false,
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
| `vision` | No | Enables image input for the model. Set this only when the chat model accepts image content. Default: `false`. |
| `image_generation` | No | Routes requests made with this selected model to the image generation endpoint. It also makes the model available to the `image_generator` tool. Default: `false`. |
| `tools` | No | Override native tool-calling support. Set `true` or `false` explicitly. Default: auto-detected from provider type. |

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
      "vision": false,
      "image_generation": false
    }
  ]
}
```

Multiple providers and models can be configured in the same `providers` array. Restart Chengsi after editing `config.json`.

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
        |      +--> Image generator, bash, python_executor
        |      +--> read (text, PDF, DOCX, images, search)
        |      +--> write (text + formatted DOCX)
        |      +--> edit (surgical text + DOCX editing)
        |
        +--> Knowledge base (core/knowledge_base.py -> SQLite FTS5)
        |
        +--> Session manager (core/session_manager.py -> sessions/ and media/)
```

### Runtime Flow

1. The WebUI sends a user message through the `pywebview` bridge in `main.py`.
2. `main.py` selects the configured provider and builds the system prompt and tool definitions.
3. The provider streams text, reasoning events, or structured tool calls via native function calling.
4. Tool calls are resolved by `ToolManager`; when `parallel_tools` is enabled, independent calls from one response execute concurrently. Results are returned to the model when another model step is needed.
5. Final responses and UI events are saved by `SessionManager`.
6. Knowledge searches use the local SQLite FTS5 index and are explicitly invoked through the knowledge-base tool.
7. Generated images are moved into a session-specific directory under `media/` and rendered directly in the WebUI.
8. Stop requests cancel immediately via a thread+queue polling mechanism without blocking on stuck streams.

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

### Available Tools (13)

| Category | Tools |
| --- | --- |
| File I/O | `read` — text, PDF, DOCX, images, code search. `write` — create/overwrite files + formatted DOCX. `edit` — precise text replacement. `ls` — directory listing. |
| Execution | `bash` — shell commands (file ops, git, pip). `python_executor` — Python for multi-step logic and data processing. |
| Web | `web_searcher` — DuckDuckGo search. `web_reader` — fetch and extract web page content. |
| Project | `project_test` — syntax, import, and unittest checks. `system_cleaner` — preview/clean temp files and caches. |
| Meta | `knowledge_base` — local document search and management. `chat_exporter` — export sessions as Markdown. `image_generator` — generate images via cloud API. |

Models receive tool descriptions through native function calling — the system prompt stays lean (~260 tokens) and only tools relevant to the task are described. Each tool's `.md` front-matter provides the canonical description sent to models.

Tools execute on the host computer with the permissions of the Chengsi process. `python_executor` can run Python code, `bash` can execute shell commands, and `system_cleaner` can delete selected files. The `core` and `knowledge` directories belonging to the running project are protected, but this protection is not a general-purpose sandbox.

## Local Data and Privacy

Chengsi stores local runtime data in these paths:

| Path | Contents |
| --- | --- |
| `config.json` | Private provider configuration and API keys. |
| `CHENGSI_HOME` | User-level environment variable pointing to the Chengsi installation folder. |
| `sessions/` | Conversation messages, UI event history, and token statistics. |
| `media/` | Generated images and session media. |
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
|-- main.py
|-- config.example.json
|-- config.json           (private, not tracked)
|-- requirements.txt
|-- setup_and_run.bat
|-- chengsi.bat
|-- setup_and_run.sh
|-- skills/               optional SKILL.md capability packages
|-- core/
|   |-- index.html
|   |-- provider.py
|   |-- ollama_provider.py
|   |-- openai_provider.py
|   |-- knowledge_base.py
|   |-- session_manager.py
|   `-- tool_manager.py
|-- tools/
|   |-- base.py
|   |-- TOC.md
|   `-- read.py, write.py, edit.py, bash.py, ls.py, ...
|-- knowledge/            local database at runtime
|-- sessions/             local session data at runtime
`-- media/                generated media at runtime
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
