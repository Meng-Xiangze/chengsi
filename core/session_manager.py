import os
import json
import shutil
import uuid
import tempfile
import threading
from datetime import datetime
from typing import List, Optional, Dict, Any


class SessionManager:
    """Manages chat session persistence as JSON files in a sessions directory."""

    def __init__(self, sessions_dir: str = "sessions", media_dir: Optional[str] = None):
        self.sessions_dir = os.path.abspath(sessions_dir)
        self.media_dir = os.path.abspath(media_dir) if media_dir else None
        self._lock = threading.RLock()
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
            "parent_session_id": "",
            "root_session_id": sid,
            "fork_message_index": None,
            "branch_kind": "root",
            "branches": [],
            "active_branch_id": "root",
        }
        with open(self._path(sid), "w", encoding="utf-8") as f:
            json.dump(session, f, ensure_ascii=False, indent=2)
        return session

    def save(self, session_id: str, messages: List[Dict[str, Any]],
             history: Optional[List[Dict]] = None,
             token_stats: Optional[Dict] = None,
             title: Optional[str] = None,
             metadata: Optional[Dict[str, Any]] = None) -> bool:
        with self._lock:
            return self._save_unlocked(session_id, messages, history, token_stats, title, metadata)

    def _save_unlocked(self, session_id: str, messages: List[Dict[str, Any]],
             history: Optional[List[Dict]] = None,
             token_stats: Optional[Dict] = None,
             title: Optional[str] = None,
             metadata: Optional[Dict[str, Any]] = None) -> bool:
        path = self._safe_path(session_id)
        if not path:
            return False
        try:
            with open(path, "r", encoding="utf-8") as f:
                session = json.load(f)
            persisted_messages = [m for m in messages if m.get("role") != "system"]
            session["messages"] = persisted_messages
            if history is not None:
                session["history"] = history
            if token_stats is not None:
                session["token_stats"] = token_stats
            active_branch_id = str(session.get("active_branch_id") or "root")
            for branch in session.get("branches", []):
                if str(branch.get("id")) != active_branch_id:
                    continue
                branch["messages"] = [dict(item) for item in persisted_messages]
                if history is not None:
                    branch["history"] = [dict(item) for item in history]
                if token_stats is not None:
                    branch["token_stats"] = dict(token_stats)
                branch["updated_at"] = datetime.now().isoformat()
                break
            session["updated_at"] = datetime.now().isoformat()
            if metadata:
                session.update(metadata)
            if title:
                session["title"] = title
            elif not session.get("title") or session["title"] == "New Chat":
                for m in messages:
                    if m.get("role") == "user":
                        session["title"] = m["content"][:60]
                        break
            directory = os.path.dirname(path)
            fd, temp_path = tempfile.mkstemp(prefix=".session-", suffix=".tmp", dir=directory)
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as f:
                    json.dump(session, f, ensure_ascii=False, indent=2)
                    f.flush()
                    os.fsync(f.fileno())
                os.replace(temp_path, path)
            finally:
                if os.path.exists(temp_path):
                    os.remove(temp_path)
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
                    "model": s.get("model", ""),
                    "provider": s.get("provider", ""),
                })
            except Exception:
                continue
        sessions.sort(key=lambda x: x["updated_at"], reverse=True)
        return sessions

    def fork(
        self,
        source_session_id: str,
        title: str = "Branch",
        fork_message_index: Optional[int] = None,
        branch_kind: str = "branch",
        include_history: bool = True,
    ) -> Optional[Dict[str, Any]]:
        source = self.load(source_session_id)
        if not source:
            return None
        branch = self.create(title)
        branch["parent_session_id"] = source_session_id
        branch["root_session_id"] = source.get("root_session_id") or source_session_id
        branch["fork_message_index"] = fork_message_index
        branch["branch_kind"] = branch_kind
        branch["messages"] = list(source.get("messages", []))
        branch["history"] = list(source.get("history", [])) if include_history else []
        branch["token_stats"] = dict(source.get("token_stats", {}))
        self.save(
            branch["id"],
            branch["messages"],
            history=branch["history"],
            token_stats=branch["token_stats"],
            title=title,
            metadata={
                "parent_session_id": source_session_id,
                "root_session_id": source.get("root_session_id") or source_session_id,
                "fork_message_index": fork_message_index,
                "branch_kind": branch_kind,
            },
        )
        return self.load(branch["id"])

    def create_in_session_branch(self, session_id: str, messages: list[dict], history: list[dict], fork_message_index: int, title: str = "Branch") -> Optional[Dict[str, Any]]:
        session = self.load(session_id)
        if not session:
            return None
        branch_id = uuid.uuid4().hex[:10]
        branches = list(session.get("branches", []))
        if not any(item.get("id") == "root" for item in branches):
            branches.insert(0, {
                "id": "root",
                "title": session.get("title", "Chat"),
                "fork_message_index": fork_message_index,
                "messages": list(session.get("messages", [])),
                "history": list(session.get("history", [])),
                "created_at": session.get("created_at", datetime.now().isoformat()),
            })
        branches.append({
            "id": branch_id,
            "title": title,
            "fork_message_index": fork_message_index,
            "messages": [dict(item) for item in messages],
            "history": [dict(item) for item in history],
            "created_at": datetime.now().isoformat(),
        })
        session["branches"] = branches
        session["active_branch_id"] = branch_id
        session["messages"] = [dict(item) for item in messages]
        session["history"] = [dict(item) for item in history]
        path = self._safe_path(session_id)
        if not path:
            return None
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(session, handle, ensure_ascii=False, indent=2)
        return {"id": branch_id, "title": title, "fork_message_index": fork_message_index}

    def switch_in_session_branch(self, session_id: str, branch_id: str) -> Optional[Dict[str, Any]]:
        session = self.load(session_id)
        if not session:
            return None
        branch = next((item for item in session.get("branches", []) if item.get("id") == branch_id), None)
        if not branch:
            return None
        session["active_branch_id"] = branch_id
        session["messages"] = list(branch.get("messages", []))
        session["history"] = list(branch.get("history", []))
        path = self._safe_path(session_id)
        if not path:
            return None
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(session, handle, ensure_ascii=False, indent=2)
        return branch

    def branch_points(self, session_id: str) -> list[Dict[str, Any]]:
        current = self.load(session_id)
        if not current:
            return []
        embedded = current.get("branches", [])
        if embedded:
            groups: dict[int, list[dict]] = {}
            for branch in embedded:
                if isinstance(branch.get("fork_message_index"), int):
                    groups.setdefault(branch["fork_message_index"], []).append(branch)
            points = []
            for fork, items in sorted(groups.items()):
                siblings = [{"id": item["id"], "title": item.get("title", "Branch")} for item in items]
                if not any(item.get("id") == "root" for item in siblings):
                    siblings.insert(0, {"id": "root", "title": current.get("title", "Chat")})
                points.append({"fork_message_index": fork, "siblings": siblings})
            return points
        root = current.get("root_session_id") or session_id
        groups: dict[int, list[dict]] = {}
        for item in self.list_all():
            candidate = self.load(item["id"])
            if not candidate or (candidate.get("root_session_id") or candidate.get("id")) != root:
                continue
            fork = candidate.get("fork_message_index")
            if isinstance(fork, int):
                groups.setdefault(fork, []).append(candidate)
        points = []
        for fork, candidates in groups.items():
            if not any(item.get("id") == root for item in candidates):
                root_session = self.load(root)
                if root_session:
                    candidates.append(root_session)
            candidates.sort(key=lambda item: (item.get("created_at", ""), item.get("id", "")))
            points.append({
                "fork_message_index": fork,
                "siblings": [{"id": item["id"], "title": item.get("title", "Branch")} for item in candidates],
            })
        return sorted(points, key=lambda item: item["fork_message_index"])

    def branch_siblings(self, session_id: str) -> list[Dict[str, Any]]:
        current = self.load(session_id)
        if not current or current.get("fork_message_index") is None:
            return []
        root = current.get("root_session_id") or current.get("parent_session_id") or session_id
        fork_index = current.get("fork_message_index")
        result = []
        for item in self.list_all():
            candidate = self.load(item["id"])
            if not candidate:
                continue
            candidate_root = candidate.get("root_session_id") or candidate.get("id")
            candidate_fork = candidate.get("fork_message_index")
            if candidate_root != root:
                continue
            if candidate_fork == fork_index or (candidate.get("id") == root and candidate_fork is None):
                result.append(candidate)
        if not any(item.get("id") == current.get("id") for item in result):
            result.append(current)
        result.sort(key=lambda item: (item.get("created_at", ""), item.get("id", "")))
        return [{"id": item["id"], "title": item.get("title", "Branch")} for item in result]

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
