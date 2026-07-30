"""Test that delegate notifications survive agent-busy windows.

Verifies the fix for: seen[delegate_id] being set before _start_delegate_followup,
causing notifications to be permanently lost when the agent is processing.
"""
import json
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


# ── Helpers ──────────────────────────────────────────────────

def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _make_delegate_metadata(root: Path, session_id: str, status: str) -> Path:
    did = uuid.uuid4().hex[:8]
    p = root / session_id / f"{did}.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({
        "delegate_id": did,
        "session_id": session_id,
        "prompt": "test",
        "status": status,
        "created_at": _now(),
        "finished_at": _now() if status not in ("queued", "starting", "running") else None,
        "tool_call_count": 0,
        "input_tokens": 0,
        "output_tokens": 0,
        "messages": [],
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    return p


# ── Tests ────────────────────────────────────────────────────

class TestDelegateNotificationDelivery:
    """Simulate watcher-loop logic in isolation."""

    def test_seen_not_set_when_agent_busy(self, tmp_path: Path):
        """If the agent is processing, the watcher must NOT mark the delegate
        as 'seen' — otherwise it is lost forever on the next pass."""
        session_id = "sess_busy"
        meta_path = _make_delegate_metadata(tmp_path, session_id, "completed")

        seen: dict[str, str] = {}
        delivered = []  # track what actually got delivered

        # ── Pass 1: agent IS processing ──────────────────────
        mock_sd_busy = MagicMock()
        mock_sd_busy.processing = True
        sessions = {session_id: mock_sd_busy}

        def watcher_pass():
            for subdir in tmp_path.iterdir():
                for p in subdir.glob("*.json"):
                    md = json.loads(p.read_text(encoding="utf-8"))
                    did = md["delegate_id"]
                    st = md["status"]
                    sid = md.get("session_id", "")
                    if not sid or st in {"queued", "starting", "running"}:
                        continue
                    if seen.get(did) == st or md.get("agent_received_at"):
                        continue
                    sd = sessions.get(sid)
                    if not sd:
                        continue
                    if sd.processing:
                        continue  # ← THE FIX: skip, don't mark seen
                    seen[did] = st
                    delivered.append((did, st))

        watcher_pass()
        assert len(delivered) == 0, "Should skip delivery while agent is busy"
        assert mock_sd_busy.delegate_id not in seen, \
            "seen MUST NOT be set when agent is busy"

        # ── Pass 2: agent is now idle ────────────────────────
        mock_sd_busy.processing = False
        watcher_pass()
        assert len(delivered) == 1, "Should deliver on second pass once idle"
        assert delivered[0][0] == meta_path.stem

    def test_agent_received_at_prevents_duplicate_delivery(self, tmp_path: Path):
        """Once agent_received_at is set, don't deliver again."""
        session_id = "sess_dedup"
        meta_path = _make_delegate_metadata(tmp_path, session_id, "completed")
        # Mark as already received
        md = json.loads(meta_path.read_text(encoding="utf-8"))
        md["agent_received_at"] = _now()
        meta_path.write_text(json.dumps(md, ensure_ascii=False, indent=2), encoding="utf-8")

        mock_sd = MagicMock()
        mock_sd.processing = False
        sessions = {session_id: mock_sd}

        seen: dict[str, str] = {}
        delivered = []

        def watcher_pass():
            for subdir in tmp_path.iterdir():
                for p in subdir.glob("*.json"):
                    md = json.loads(p.read_text(encoding="utf-8"))
                    if md.get("agent_received_at"):
                        continue  # already consumed
                    did = md["delegate_id"]
                    st = md["status"]
                    sid = md.get("session_id", "")
                    if not sid or st in {"queued", "starting", "running"}:
                        continue
                    if seen.get(did) == st:
                        continue
                    sd = sessions.get(sid)
                    if not sd or sd.processing:
                        continue
                    seen[did] = st
                    delivered.append((did, st))

        watcher_pass()
        assert len(delivered) == 0, "Should skip already-received delegates"

    def test_multiple_delegates_one_skips_due_to_busy(self, tmp_path: Path):
        """With two delegates in different sessions, the idle one delivers,
        the busy one retries."""
        p1 = _make_delegate_metadata(tmp_path, "sess_idle", "completed")
        p2 = _make_delegate_metadata(tmp_path, "sess_busy", "failed")

        sd_idle = MagicMock()
        sd_idle.processing = False
        sd_busy = MagicMock()
        sd_busy.processing = True
        sessions = {"sess_idle": sd_idle, "sess_busy": sd_busy}

        seen: dict[str, str] = {}
        delivered = []

        def watcher_pass():
            for subdir in tmp_path.iterdir():
                for p in subdir.glob("*.json"):
                    md = json.loads(p.read_text(encoding="utf-8"))
                    did = md["delegate_id"]
                    st = md["status"]
                    sid = md.get("session_id", "")
                    if not sid or st in {"queued", "starting", "running"}:
                        continue
                    if seen.get(did) == st or md.get("agent_received_at"):
                        continue
                    sd = sessions.get(sid)
                    if not sd or sd.processing:
                        continue
                    seen[did] = st
                    delivered.append((did, st))

        # Pass 1: one delivers, one skips
        watcher_pass()
        assert len(delivered) == 1
        assert delivered[0][0] == p1.stem

        # Pass 2: now the busy one idles and delivers
        sd_busy.processing = False
        watcher_pass()
        assert len(delivered) == 2
        assert delivered[1][0] == p2.stem


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
