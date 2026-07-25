import unittest

from core.agent_runtime import AgentRuntime, classify_tool_outcome
from tools.base import BaseTool
from core.ollama_provider import OllamaProvider


class AgentRuntimeTests(unittest.TestCase):
    def test_blocks_third_identical_call(self):
        runtime = AgentRuntime(max_identical_calls=2)
        arguments = {"path": "sample.py"}

        self.assertTrue(runtime.allow("edit", arguments)[0])
        self.assertTrue(runtime.allow("edit", arguments)[0])
        allowed, reason = runtime.allow("edit", arguments)

        self.assertFalse(allowed)
        self.assertIn("already attempted twice", reason)

    def test_tool_budget_is_a_hard_stop(self):
        runtime = AgentRuntime(max_tool_calls=2)

        self.assertTrue(runtime.allow("first", {})[0])
        self.assertTrue(runtime.allow("second", {})[0])
        self.assertFalse(runtime.allow("third", {})[0])

    def test_runtime_snapshot_restores_budget_and_signatures(self):
        runtime = AgentRuntime(max_tool_calls=3, max_identical_calls=1)
        runtime.active = True
        self.assertTrue(runtime.allow("read", {"path": "a.py"})[0])
        snapshot = runtime.snapshot()

        restored = AgentRuntime.from_snapshot(snapshot)

        self.assertTrue(restored.active)
        self.assertFalse(restored.allow("read", {"path": "a.py"})[0])
        self.assertTrue(restored.allow("other", {})[0])
        self.assertTrue(restored.allow("third", {})[0])
        self.assertFalse(restored.allow("fourth", {})[0])

    def test_consecutive_failures_trip_circuit_breaker(self):
        runtime = AgentRuntime(max_consecutive_failures=2)
        failure = classify_tool_outcome("Error: invalid arguments")

        self.assertTrue(runtime.observe("one", {}, failure)[0])
        should_continue, reason = runtime.observe("two", {}, failure)

        self.assertFalse(should_continue)
        self.assertIn("2 consecutive", reason)

    def test_success_resets_failure_streak(self):
        runtime = AgentRuntime(max_consecutive_failures=2)

        runtime.observe("one", {}, classify_tool_outcome("Error: failed"))
        runtime.observe("two", {}, classify_tool_outcome("OK"))
        should_continue, _ = runtime.observe("three", {}, classify_tool_outcome("Error: failed"))

        self.assertTrue(should_continue)

    def test_file_change_requires_project_test(self):
        runtime = AgentRuntime()
        runtime.observe(
            "edit",
            {"path": "sample.py", "edits": [{"oldText": "x", "newText": "y"}]},
            classify_tool_outcome("OK: updated sample.py"),
        )

        self.assertTrue(runtime.needs_verification())
        runtime.observe("project_test", {"scope": "all"}, classify_tool_outcome("All checks passed"))
        self.assertFalse(runtime.needs_verification())

    def test_explicit_tool_capabilities_drive_verification_state(self):
        class MutatingTool(BaseTool):
            @property
            def tool_name(self):
                return "custom_writer"

            @property
            def description(self):
                return "custom writer"

            @property
            def parameters(self):
                return {}

            def is_mutating(self, arguments):
                return True

            def run(self, arguments):
                return "changed"

        class VerificationTool(MutatingTool):
            @property
            def tool_name(self):
                return "custom_check"

            def is_mutating(self, arguments):
                return False

            def is_verification(self, arguments):
                return True

        runtime = AgentRuntime()
        writer = MutatingTool()
        checker = VerificationTool()
        runtime.observe("custom_writer", {}, classify_tool_outcome("changed"), writer)
        self.assertTrue(runtime.needs_verification())
        runtime.observe("custom_check", {}, classify_tool_outcome("passed"), checker)
        self.assertFalse(runtime.needs_verification())

    def test_classifies_plain_json_and_stderr_errors(self):
        self.assertFalse(classify_tool_outcome('{"error": "missing path"}').ok)
        self.assertFalse(classify_tool_outcome("--- STDOUT ---\n\n--- STDERR ---\nTraceback").ok)
        self.assertFalse(classify_tool_outcome("[syntax] 10 passed, 1 failed.").ok)
        self.assertTrue(classify_tool_outcome("No matches found").ok)

    def test_ollama_preserves_native_tool_call_chain(self):
        messages = [
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [{
                    "id": "call_01",
                    "type": "function",
                    "function": {"name": "project_test", "arguments": {"scope": "all"}},
                }],
            },
            {"role": "tool", "tool_call_id": "call_01", "content": "All checks passed"},
        ]

        self.assertEqual(OllamaProvider.prepare_messages(messages), messages)


if __name__ == "__main__":
    unittest.main()
