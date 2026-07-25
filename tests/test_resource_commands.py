import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import main
from core.knowledge_base import KnowledgeBase


class ProviderCapabilityTests(unittest.TestCase):
    def test_model_can_disable_provider_native_tools(self):
        provider = type("Provider", (), {"supports_native_tools": True})()
        self.assertFalse(main._is_native(provider, {"tools": False}))
        self.assertTrue(main._is_native(provider, {}))

    def test_non_native_prompt_describes_text_tool_protocol_and_schema(self):
        tool = type("Tool", (), {
            "description": "Search project files.",
            "parameters": {
                "query": {"type": "string", "description": "Search term.", "required": True},
                "limit": {"type": "integer", "description": "Maximum results."},
            },
        })()
        prompt = main.format_system_prompt(
            {"read": tool},
            tool_manager=None,
            native_tools=False,
        )
        self.assertIn('<tool_call>{"action":"read","arguments":{"query":"value"}}</tool_call>', prompt)
        self.assertNotIn("tool_name", prompt)
        self.assertIn("- read: Search project files.", prompt)
        self.assertIn("query: string, required", prompt)
        self.assertIn("limit: integer, optional", prompt)
        self.assertIn("use an available tool instead of giving instructions", prompt)
        self.assertIn("verify the end state afterward", prompt)

    def test_native_prompt_does_not_duplicate_text_tool_protocol(self):
        prompt = main.format_system_prompt({}, native_tools=True)
        self.assertNotIn("<tool_call>", prompt)
        self.assertIn("use an available tool instead of giving instructions", prompt)
        self.assertIn("verify the end state afterward", prompt)

    def test_knowledge_context_stays_inside_the_first_system_message(self):
        messages = [
            {"role": "system", "content": "Agent rules"},
            {"role": "user", "content": "Find this"},
        ]
        result = main._append_knowledge_context(messages, "Retrieved facts")
        self.assertEqual([message["role"] for message in result], ["system", "user"])
        self.assertIn("Retrieved facts", result[0]["content"])
        self.assertEqual(messages[0]["content"], "Agent rules")


class ResourceCommandTests(unittest.TestCase):
    def test_discover_skills_reads_summary_only(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            skill = root / "skills" / "demo" / "SKILL.md"
            skill.parent.mkdir(parents=True)
            skill.write_text(
                "---\nname: demo\ndescription: Read project notes when relevant.\n---\n\nFull instructions.\n",
                encoding="utf-8",
            )
            with patch.object(main, "PROJECT_ROOT", temp):
                skills = main.discover_skills()
                prompt = main._skills_prompt()
            self.assertEqual(len(skills), 1)
            self.assertEqual(skills[0]["name"], "demo")
            self.assertIn("Read project notes", prompt)
            self.assertNotIn("Full instructions", prompt)

    def test_tool_list_command_does_not_call_model(self):
        with patch.object(main, "_available_tools", {"read": object(), "write": object()}):
            result = main.handle_control_command("/tool list")
        self.assertIn("- read", result)
        self.assertIn("- write", result)

    def test_unknown_tool_result_lists_real_tools(self):
        with patch.object(main, "_emit"):
            outcome = main._execute_tool("read", {}, {"read": object(), "python_executor": object()}, "test")
        self.assertFalse(outcome.ok)
        self.assertIn("Available tools: python_executor, read", outcome.content)

    def test_legacy_tool_call_preserves_braces_inside_code_arguments(self):
        response = (
            'I will create the file. '
            '<tool_call>{"action":"edit","arguments":{"path":"snake.py",'
            '"content":"if value == {\\"x\\": 1}:\\n    print(value)"}}</tool_call>'
        )
        request, before, after = main._extract_legacy_tool_call(response)
        self.assertEqual(request["action"], "edit")
        self.assertEqual(request["arguments"]["content"], 'if value == {"x": 1}:\n    print(value)')
        self.assertEqual(before, "I will create the file. ")
        self.assertEqual(after, "")

    def test_legacy_tool_call_requires_closing_tag(self):
        request, _, error = main._extract_legacy_tool_call(
            '<tool_call>{"action":"read","arguments":{"query":"x"}}'
        )
        self.assertIsNone(request)
        self.assertIn("Missing", error)

    def test_legacy_turn_recovers_from_one_malformed_tool_call(self):
        class Provider:
            supports_native_tools = False

            def __init__(self):
                self.calls = 0

            def chat_stream(self, model, messages, tool_defs=None, **kwargs):
                self.calls += 1
                if self.calls == 1:
                    yield "content", '<tool_call>{"action":"writer","arguments":{"text":"broken"}'
                elif self.calls == 2:
                    self.assert_retry_feedback(messages)
                    yield "content", '<tool_call>{"action":"writer","arguments":{"text":"ok"}}</tool_call>'
                else:
                    yield "content", "Finished."

            @staticmethod
            def assert_retry_feedback(messages):
                assert "Tool call format error" in messages[-1]["content"]

        class Tool:
            description = "Write text."
            parameters = {"text": {"type": "string", "required": True}}

            def __init__(self):
                self.calls = []

            def run(self, arguments):
                self.calls.append(arguments)
                return "written"

        session_id = "legacy-recovery-test"
        session = main.state.ensure(session_id)
        session.messages = [{"role": "user", "content": "Write it"}]
        tool = Tool()
        try:
            main.process_agent_turn(
                Provider(), "legacy", {"writer": tool}, None,
                session_id=session_id, model_config={"tools": False},
            )
            self.assertEqual(tool.calls, [{"text": "ok"}])
            self.assertEqual(session.messages[-1], {"role": "assistant", "content": "Finished."})
            self.assertFalse(any(
                "<tool_call>" in str(message.get("content", ""))
                for message in session.messages
                if message.get("role") == "assistant"
            ))
        finally:
            main.state.sessions.pop(session_id, None)

    def test_knowledge_add_and_search_command(self):
        with tempfile.TemporaryDirectory() as temp:
            source = Path(temp) / "notes.md"
            source.write_text("Runtime snapshots preserve failed tasks.", encoding="utf-8")
            db = Path(temp) / "knowledge.db"
            kb = KnowledgeBase(str(db))
            with patch.object(main.state, "knowledge_base", kb):
                added = main.handle_control_command(f"/knowledge add {source}")
                found = main.handle_control_command("/knowledge search snapshots")
            self.assertIn("created", added)
            self.assertIn("Runtime", found)
            self.assertIn("snapshots", found)
            del kb


if __name__ == "__main__":
    unittest.main()
