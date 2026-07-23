"""Tools for explicit local knowledge-base ingestion and retrieval."""
import json
import os
from core.knowledge_base import KnowledgeBase
from tools.base import BaseTool


class KnowledgeBaseTool(BaseTool):
    @property
    def tool_name(self):
        return "knowledge_base"

    @property
    def description(self):
        return "Search, ingest, list, or remove entries in Chengsi's local knowledge base. Use search before answering questions that may be covered by local files."

    @property
    def parameters(self):
        return {
            "action": {"type": "string", "enum": ["search", "ingest_file", "ingest", "list", "remove"], "description": "Operation to perform"},
            "query": {"type": "string", "description": "Search query for action=search"},
            "path": {"type": "string", "description": "Local text/Markdown/JSON/CSV/LOG file for action=ingest_file"},
            "content": {"type": "string", "description": "Text to ingest for action=ingest"},
            "source": {"type": "string", "description": "Stable source identifier for action=ingest"},
            "title": {"type": "string", "description": "Optional title for action=ingest"},
            "document_id": {"type": "integer", "description": "Document id for action=remove"},
            "limit": {"type": "integer", "description": "Maximum results, default 5"},
        }

    def run(self, arguments):
        reminder = "IMPORTANT / 重要提醒: Knowledge-base ingestion and retrieval may involve long or complex document processing. Prefer an internet-connected capable model when available; use a local small model only when privacy or offline requirements take priority. 入库和出库可能涉及复杂文档处理，优先使用联网能力较强的模型；只有在隐私或离线要求优先时才使用本地小模型。"
        kb = KnowledgeBase(os.path.join(os.path.dirname(os.path.dirname(__file__)), "knowledge", "knowledge.db"))
        action = arguments.get("action", "search")
        if action == "search":
            return reminder + "\\n" + json.dumps({"results": kb.search(arguments.get("query", ""), arguments.get("limit", 5))}, ensure_ascii=False, indent=2)
        if action == "ingest_file":
            return reminder + "\\n" + json.dumps(kb.ingest_file(arguments["path"]), ensure_ascii=False, indent=2)
        if action == "ingest":
            return json.dumps(kb.ingest(arguments["content"], arguments["source"], arguments.get("title", ""), "manual"), ensure_ascii=False, indent=2)
        if action == "list":
            return json.dumps({"documents": kb.list_documents(arguments.get("limit", 100))}, ensure_ascii=False, indent=2)
        if action == "remove":
            return json.dumps({"removed": kb.remove(arguments["document_id"])}, ensure_ascii=False)
        raise ValueError("unknown action")
