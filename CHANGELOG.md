# Changelog

All notable changes to Chengsi will be documented in this file.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project intends to use [Semantic Versioning](https://semver.org/).

## [Unreleased]

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
