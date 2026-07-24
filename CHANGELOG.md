# Changelog

All notable changes to Chengsi will be documented in this file.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project intends to use [Semantic Versioning](https://semver.org/).

## [Unreleased]

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
