import os
import json
import shutil
import uuid
from datetime import datetime
from typing import List, Optional, Dict, Any


class SessionManager:
    """Manages chat session persistence as JSON files in a sessions directory."""

    def __init__(self, sessions_dir: str = "sessions", media_dir: Optional[str] = None):
        self.sessions_dir = os.path.abspath(sessions_dir)
        self.media_dir = os.path.abspath(media_dir) if media_dir else None
        os.makedirs(self.sessions_dir, exist_ok=True)
        if self.media_dir:
            os.makedirs(self.media_dir, exist_ok=True)

    @staticmethod
    def _valid_id(session_id: str) -> bool:
        return bool(session_id) and all(char.isalnum() or char in ("_", "-") for char in session_id)

    def _path(self, session_id: str) -> str:
        return os.path.join(self.sessions_dir, f"{session_id}.json")

    def _safe_path(self, session_id: str) -> Optional[str]:
        if not self._valid_id(session_id):
            return None
        path = os.path.abspath(self._path(session_id))
        try:
            if os.path.isfile(path) and os.path.commonpath((path, self.sessions_dir)) == self.sessions_dir:
                return path
        except ValueError:
            pass
        return None

    def create(self, title: str = "New Chat") -> Dict[str, Any]:
        sid = datetime.now().strftime("%Y%m%d_%H%M%S") + "_" + uuid.uuid4().hex[:6]
        session = {
            "id": sid,
            "title": title,
            "created_at": datetime.now().isoformat(),
            "updated_at": datetime.now().isoformat(),
            "messages": [],
            "history": [],
            "token_stats": {"input": 0, "output": 0, "prompt": 0, "eval": 0, "ctx": 0},
        }
        with open(self._path(sid), "w", encoding="utf-8") as f:
            json.dump(session, f, ensure_ascii=False, indent=2)
        return session

    def save(self, session_id: str, messages: List[Dict[str, Any]],
             history: Optional[List[Dict]] = None,
             token_stats: Optional[Dict] = None,
             title: Optional[str] = None) -> bool:
        path = self._safe_path(session_id)
        if not path:
            return False
        try:
            with open(path, "r", encoding="utf-8") as f:
                session = json.load(f)
            # Strip system messages before saving — they are rebuilt on load
            session["messages"] = [m for m in messages if m.get("role") != "system"]
            if history is not None:
                session["history"] = history
            if token_stats is not None:
                session["token_stats"] = token_stats
            session["updated_at"] = datetime.now().isoformat()
            if title:
                session["title"] = title
            elif not session.get("title") or session["title"] == "New Chat":
                for m in messages:
                    if m.get("role") == "user":
                        session["title"] = m["content"][:60]
                        break
            with open(path, "w", encoding="utf-8") as f:
                json.dump(session, f, ensure_ascii=False, indent=2)
            return True
        except Exception:
            return False

    def load(self, session_id: str) -> Optional[Dict[str, Any]]:
        path = self._safe_path(session_id)
        if not path:
            return None
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return None

    def list_all(self) -> List[Dict[str, Any]]:
        sessions = []
        for fname in os.listdir(self.sessions_dir):
            if not fname.endswith(".json"):
                continue
            path = os.path.join(self.sessions_dir, fname)
            try:
                with open(path, "r", encoding="utf-8") as f:
                    s = json.load(f)
                sessions.append({
                    "id": s["id"],
                    "title": s.get("title", "Untitled"),
                    "created_at": s.get("created_at", ""),
                    "updated_at": s.get("updated_at", ""),
                    "message_count": len(s.get("messages", [])),
                })
            except Exception:
                continue
        sessions.sort(key=lambda x: x["updated_at"], reverse=True)
        return sessions

    def delete(self, session_id: str) -> bool:
        path = self._safe_path(session_id)
        if not path:
            return False
        try:
            os.remove(path)
            if self.media_dir:
                media_path = os.path.abspath(os.path.join(self.media_dir, session_id))
                try:
                    if os.path.isdir(media_path) and os.path.commonpath((media_path, self.media_dir)) == self.media_dir:
                        shutil.rmtree(media_path)
                except (OSError, ValueError):
                    pass
            return True
        except Exception:
            return False

    def rename(self, session_id: str, new_title: str) -> bool:
        path = self._safe_path(session_id)
        if not path:
            return False
        try:
            with open(path, "r", encoding="utf-8") as f:
                session = json.load(f)
            session["title"] = new_title
            session["updated_at"] = datetime.now().isoformat()
            with open(path, "w", encoding="utf-8") as f:
                json.dump(session, f, ensure_ascii=False, indent=2)
            return True
        except Exception:
            return False
