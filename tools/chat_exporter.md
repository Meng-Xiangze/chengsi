---
name: chat_exporter
description: "Export or list chat sessions. action='export' saves HTML to Desktop; action='list' shows all sessions with titles."
parameters:
  action:
    type: string
    enum: [export, list]
    description: "'export' (default) or 'list' to browse."
  session_id:
    type: string
    description: "Optional — defaults to active session for export."
examples:
  - action: chat_exporter
    arguments: {}
    note: "Exports current session to Desktop"
  - action: chat_exporter
    arguments: {action: list}
    note: "Lists all saved sessions with titles"
usage_notes:
  - action='list' shows session IDs with titles, dates, and message counts.
  - action='export' saves self-contained HTML with embedded images to Desktop.
  - session_id is optional — omit to export the current conversation.
---
