import json
import os
import tempfile
import unittest

from core.ollama_provider import OllamaProvider
from core.openai_provider import OpenAIProvider
from core.session_manager import SessionManager
from main import _split_compaction_messages


class CompactionTests(unittest.TestCase):
    def test_split_keeps_tool_call_and_results_together(self):
        conversation = [
            {"role": "user", "content": "old request"},
            {"role": "assistant", "content": "old answer"},
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {"id": "call_1", "type": "function", "function": {"name": "first", "arguments": "{}"}},
                    {"id": "call_2", "type": "function", "function": {"name": "second", "arguments": "{}"}},
                ],
            },
            {"role": "tool", "tool_call_id": "call_1", "content": "first result"},
            {"role": "tool", "tool_call_id": "call_2", "content": "second result"},
            {"role": "assistant", "content": "used both results"},
            {"role": "user", "content": "next request"},
            {"role": "assistant", "content": "next answer"},
            {"role": "user", "content": "latest request"},
        ]

        older, recent = _split_compaction_messages(conversation, keep_count=6)

        self.assertEqual(older, conversation[:2])
        self.assertEqual(recent, conversation[2:])
        self.assertEqual(recent[0]["role"], "assistant")
        self.assertIn("tool_calls", recent[0])

    def test_ollama_provider_normalizes_tool_call_arguments(self):
        messages = [{
            "role": "assistant",
            "content": None,
            "tool_calls": [{
                "id": "call_1",
                "type": "function",
                "function": {"name": "read", "arguments": '{"query":"AgentRuntime"}'},
            }],
        }]

        prepared = OllamaProvider.prepare_messages(messages)

        self.assertEqual(
            prepared[0]["tool_calls"][0]["function"]["arguments"],
            {"query": "AgentRuntime"},
        )

    def test_openai_provider_drops_orphaned_tool_results(self):
        messages = [
            {"role": "system", "content": "instructions"},
            {"role": "user", "content": "[COMPACTED CONTEXT]\nSummary"},
            {"role": "tool", "tool_call_id": "removed_call", "content": "orphaned result"},
            {"role": "assistant", "content": "previous answer"},
            {"role": "user", "content": "continue"},
        ]

        prepared = OpenAIProvider.prepare_messages(messages)

        self.assertEqual([message["role"] for message in prepared], ["system", "user", "assistant", "user"])
        self.assertNotIn("orphaned result", [message.get("content") for message in prepared])

    def test_openai_provider_keeps_parallel_tool_results(self):
        messages = [
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {"id": "call_1", "type": "function", "function": {"name": "first", "arguments": "{}"}},
                    {"id": "call_2", "type": "function", "function": {"name": "second", "arguments": "{}"}},
                ],
            },
            {"role": "tool", "tool_call_id": "call_1", "content": "first result"},
            {"role": "tool", "tool_call_id": "call_2", "content": "second result"},
            {"role": "assistant", "content": "done"},
        ]

        prepared = OpenAIProvider.prepare_messages(messages)

        self.assertEqual(prepared, messages)

    def test_compacted_context_survives_session_save_and_load(self):
        with tempfile.TemporaryDirectory() as sessions_dir:
            manager = SessionManager(sessions_dir)
            session = manager.create()
            summary = {"role": "user", "content": "[COMPACTED CONTEXT]\nDurable facts"}

            self.assertTrue(manager.save(session["id"], [summary, {"role": "user", "content": "continue"}]))
            loaded = manager.load(session["id"])

            self.assertIsNotNone(loaded)
            self.assertEqual(loaded["messages"][0], summary)

    def test_runtime_snapshot_survives_session_save_and_load(self):
        with tempfile.TemporaryDirectory() as sessions_dir:
            manager = SessionManager(sessions_dir)
            session = manager.create()
            runtime = {"version": 1, "active": True, "tool_calls": 2, "signatures": {"read:{}": 1}}

            self.assertTrue(manager.save(
                session["id"],
                [{"role": "user", "content": "continue"}],
                token_stats={"runtime": runtime},
            ))
            loaded = manager.load(session["id"])

            self.assertEqual(loaded["token_stats"]["runtime"], runtime)

    def test_old_session_without_runtime_snapshot_is_valid(self):
        with tempfile.TemporaryDirectory() as sessions_dir:
            manager = SessionManager(sessions_dir)
            session = manager.create()
            self.assertTrue(manager.save(session["id"], [{"role": "user", "content": "old"}], token_stats={"input": 1}))

            loaded = manager.load(session["id"])

            self.assertNotIn("runtime", loaded["token_stats"])


if __name__ == "__main__":
    unittest.main()
