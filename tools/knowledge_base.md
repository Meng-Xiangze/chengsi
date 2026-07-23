---
name: knowledge_base
description: Search and explicitly ingest, list, or remove local knowledge-base documents.
parameters:
  action:
    type: string
    description: "Operation: search, ingest_file, ingest, list, or remove"
    required: true
  query:
    type: string
    description: Search text
  path:
    type: string
    description: Local text/Markdown/JSON/CSV/LOG path
  content:
    type: string
    description: Text to ingest
  source:
    type: string
    description: Stable source id
  title:
    type: string
    description: Optional title
  document_id:
    type: string
    description: Id to remove
  limit:
    type: integer
    description: Maximum result count
---

The knowledge base is local SQLite FTS5 storage at knowledge/knowledge.db. Search results include stable [KB:id] references. Ingestion is explicit and idempotent by source plus content hash. Supported documents include PDF, DOCX, XLSX/XLS, PPTX, TXT, Markdown, JSON, CSV, and LOG. Images must use image_reader.

IMPORTANT / 重要提醒: Prefer an internet-connected capable model for knowledge-base ingestion and retrieval when available. Use a local small model only when privacy or offline requirements take priority. 对知识库入库和出库，联网能力较强的模型优先；只有隐私或离线要求优先时才使用本地小模型。
