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
            {"code_context": tool},
            tool_manager=None,
            native_tools=False,
        )
        self.assertIn('<tool_call>{"action":"code_context","arguments":{"query":"value"}}</tool_call>', prompt)
        self.assertNotIn("tool_name", prompt)
        self.assertIn("- code_context: Search project files.", prompt)
        self.assertIn("query: string, required", prompt)
        self.assertIn("limit: integer, optional", prompt)

    def test_native_prompt_does_not_duplicate_text_tool_protocol(self):
        prompt = main.format_system_prompt({}, native_tools=True)
        self.assertNotIn("<tool_call>", prompt)



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
