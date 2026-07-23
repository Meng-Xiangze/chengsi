---
name: chat_exporter
description: Export a chat session as Markdown. Provide session_id (or leave empty to export the current session).
parameters:
  session_id:
    type: string
    description: "Session ID to export (e.g. '20260721_213533_9933c4'). Leave empty for current session."
examples:
  - action: chat_exporter
    arguments:
      session_id: "20260721_213533_9933c4"
usage_notes:
  - Reads the session JSON file from sessions/ directory.
  - Only session_id parameter is needed.
  - The returned Markdown includes user messages, tool calls/results, and agent responses.
  - Tool results are truncated to 2000 characters.
  - Useful for sharing conversation logs or feeding context to other LLMs.
---
