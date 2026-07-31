import json
import unittest
from pathlib import Path

from core.conversation_history import (
    MAX_PERSISTED_EVENTS,
    MAX_UI_CHARS,
    MAX_UI_EVENTS,
    append_event,
    normalize_persisted,
    project_for_ui,
)


class ConversationHistoryTests(unittest.TestCase):
    def test_legacy_telemetry_is_removed_and_ui_projection_is_bounded(self):
        history = []
        for index in range(1000):
            history.append({"type": "tokens", "data": {"input": index}})
            history.append({"type": "tool_result", "data": "x" * 5000})
        normalized = normalize_persisted(history)
        projected, omitted = project_for_ui(normalized)
        self.assertLessEqual(len(normalized), MAX_PERSISTED_EVENTS)
        self.assertLessEqual(len(projected), MAX_UI_EVENTS)
        self.assertLessEqual(sum(len(str(event)) for event in projected), MAX_UI_CHARS + 20_000)
        self.assertGreater(omitted, 0)
        self.assertTrue(all(event["type"] != "tokens" for event in projected))

    def test_runtime_append_drops_non_visible_telemetry(self):
        history = []
        append_event(history, "tokens", {"input": 3})
        append_event(history, "processing_done", {})
        append_event(history, "user", "hello")
        self.assertEqual(history, [{"type": "user", "data": "hello"}])

    def test_real_large_session_projects_without_returning_full_history(self):
        path = Path(__file__).parents[1] / "sessions" / "20260730_195207_9b58f0.json"
        if not path.exists():
            self.skipTest("diagnostic session fixture is not available")
        session = json.loads(path.read_text(encoding="utf-8"))
        projected, omitted = project_for_ui(session.get("history", []))
        self.assertLessEqual(len(projected), MAX_UI_EVENTS)
        self.assertGreater(omitted, 0)


if __name__ == "__main__":
    unittest.main()
