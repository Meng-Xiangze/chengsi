import csv
import hashlib
import json
import os
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any


class KnowledgeBase:
    """SQLite FTS-backed local document store."""

    SUPPORTED_SUFFIXES = {".txt", ".md", ".json", ".csv", ".log"}

    def __init__(self, db_path: str):
        self.db_path = os.path.abspath(db_path)
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        self._initialize()

    class _ManagedConnection(sqlite3.Connection):
        """Commit or roll back like sqlite's context manager, then close."""

        def __exit__(self, exc_type, exc_value, traceback):
            try:
                return super().__exit__(exc_type, exc_value, traceback)
            finally:
                self.close()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(
            self.db_path,
            timeout=30,
            factory=self._ManagedConnection,
        )
        connection.row_factory = sqlite3.Row
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.executescript("""
                CREATE TABLE IF NOT EXISTS documents (
                    id INTEGER PRIMARY KEY,
                    source TEXT NOT NULL UNIQUE,
                    title TEXT NOT NULL,
                    content TEXT NOT NULL,
                    content_hash TEXT NOT NULL,
                    source_type TEXT NOT NULL DEFAULT 'local',
                    metadata TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE VIRTUAL TABLE IF NOT EXISTS documents_fts USING fts5(
                    title, content, source, content='documents', content_rowid='id'
                );
                CREATE TRIGGER IF NOT EXISTS documents_ai AFTER INSERT ON documents BEGIN
                    INSERT INTO documents_fts(rowid, title, content, source)
                    VALUES (new.id, new.title, new.content, new.source);
                END;
                CREATE TRIGGER IF NOT EXISTS documents_ad AFTER DELETE ON documents BEGIN
                    INSERT INTO documents_fts(documents_fts, rowid, title, content, source)
                    VALUES ('delete', old.id, old.title, old.content, old.source);
                END;
                CREATE TRIGGER IF NOT EXISTS documents_au AFTER UPDATE ON documents BEGIN
                    INSERT INTO documents_fts(documents_fts, rowid, title, content, source)
                    VALUES ('delete', old.id, old.title, old.content, old.source);
                    INSERT INTO documents_fts(rowid, title, content, source)
                    VALUES (new.id, new.title, new.content, new.source);
                END;
            """)

    def ingest(
        self,
        content: str,
        source: str,
        title: str = "",
        source_type: str = "local",
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if not isinstance(content, str) or not content.strip():
            raise ValueError("content must not be empty")
        if not isinstance(source, str) or not source.strip():
            raise ValueError("source must not be empty")
        source = source.strip()
        title = title.strip() or Path(source).name or source
        content_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()
        timestamp = datetime.now().isoformat()
        metadata_json = json.dumps(metadata or {}, ensure_ascii=False)
        with self._connect() as connection:
            existing = connection.execute(
                "SELECT id, content_hash FROM documents WHERE source = ?", (source,)
            ).fetchone()
            if existing and existing["content_hash"] == content_hash:
                return {"id": existing["id"], "source": source, "status": "unchanged"}
            if existing:
                connection.execute(
                    """UPDATE documents SET title=?, content=?, content_hash=?, source_type=?,
                       metadata=?, updated_at=? WHERE id=?""",
                    (title, content, content_hash, source_type, metadata_json, timestamp, existing["id"]),
                )
                return {"id": existing["id"], "source": source, "status": "updated"}
            cursor = connection.execute(
                """INSERT INTO documents
                   (source, title, content, content_hash, source_type, metadata, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (source, title, content, content_hash, source_type, metadata_json, timestamp, timestamp),
            )
            return {"id": cursor.lastrowid, "source": source, "status": "created"}

    def ingest_file(self, path: str) -> dict[str, Any]:
        file_path = Path(path).expanduser().resolve()
        if not file_path.is_file():
            raise FileNotFoundError(f"File not found: {file_path}")
        suffix = file_path.suffix.lower()
        if suffix not in self.SUPPORTED_SUFFIXES:
            raise ValueError(f"Unsupported file type: {suffix}")
        content = file_path.read_text(encoding="utf-8", errors="replace")
        if suffix == ".json":
            try:
                content = json.dumps(json.loads(content), ensure_ascii=False, indent=2)
            except json.JSONDecodeError:
                pass
        elif suffix == ".csv":
            rows = list(csv.reader(content.splitlines()))
            content = "\n".join(" | ".join(cell for cell in row) for row in rows)
        return self.ingest(
            content,
            str(file_path),
            file_path.stem,
            "file",
            {"path": str(file_path), "suffix": suffix},
        )

    @staticmethod
    def _fts_query(query: str) -> str:
        terms = [part.replace('"', '""') for part in query.split() if part.strip()]
        return " OR ".join(f'"{term}"' for term in terms)

    def search(self, query: str, limit: int = 5) -> list[dict[str, Any]]:
        if not isinstance(query, str) or not query.strip():
            return []
        limit = max(1, min(int(limit or 5), 50))
        fts_query = self._fts_query(query)
        with self._connect() as connection:
            try:
                rows = connection.execute(
                    """SELECT d.id, d.source, d.title, d.source_type, d.metadata,
                       snippet(documents_fts, 1, '[', ']', ' ... ', 24) AS snippet,
                       bm25(documents_fts) AS score
                       FROM documents_fts
                       JOIN documents d ON d.id = documents_fts.rowid
                       WHERE documents_fts MATCH ? ORDER BY score LIMIT ?""",
                    (fts_query, limit),
                ).fetchall()
            except sqlite3.OperationalError:
                pattern = f"%{query.strip()}%"
                rows = connection.execute(
                    """SELECT id, source, title, source_type, metadata,
                       substr(content, 1, 500) AS snippet, 0 AS score
                       FROM documents WHERE title LIKE ? OR content LIKE ? OR source LIKE ?
                       ORDER BY updated_at DESC LIMIT ?""",
                    (pattern, pattern, pattern, limit),
                ).fetchall()
        results = []
        for row in rows:
            item = dict(row)
            try:
                item["metadata"] = json.loads(item.get("metadata") or "{}")
            except json.JSONDecodeError:
                item["metadata"] = {}
            results.append(item)
        return results

    def context(self, query: str, limit: int = 5) -> str:
        results = self.search(query, limit)
        if not results:
            return ""
        lines = ["Relevant local knowledge-base excerpts (verify freshness and source quality):"]
        for result in results:
            lines.append(
                f"[{result['id']}] {result['title']} ({result['source']}):\n{result['snippet']}"
            )
        return "\n\n".join(lines)

    def list_documents(self, limit: int = 100) -> list[dict[str, Any]]:
        limit = max(1, min(int(limit or 100), 1000))
        with self._connect() as connection:
            rows = connection.execute(
                """SELECT id, source, title, source_type, metadata, created_at, updated_at,
                   length(content) AS content_length FROM documents
                   ORDER BY updated_at DESC LIMIT ?""",
                (limit,),
            ).fetchall()
        documents = []
        for row in rows:
            item = dict(row)
            try:
                item["metadata"] = json.loads(item.get("metadata") or "{}")
            except json.JSONDecodeError:
                item["metadata"] = {}
            documents.append(item)
        return documents

    def remove(self, document_id: int) -> bool:
        with self._connect() as connection:
            cursor = connection.execute("DELETE FROM documents WHERE id = ?", (int(document_id),))
            return cursor.rowcount > 0
