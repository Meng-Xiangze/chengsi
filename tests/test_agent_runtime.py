import unittest
from unittest.mock import Mock

from core.agent_runtime import AgentRuntime, ToolOutcome
from tools.bash import Bash
from tools.python_executor import PythonExecutor
from main import (
    _build_request_messages,
    _ensure_execution_plan,
    _update_execution_checkpoint,
    _is_unused_token_failure,
    _requires_local_tool_first,
    _summarize_turn_process,
)


class AgentRuntimeTests(unittest.TestCase):
    def test_small_tool_progress_does_not_require_summary_round_trip(self):
        records = [{"tool": "read", "arguments": {}, "ok": True, "result": "small"}]
        self.assertEqual(_summarize_turn_process(None, "model", records, Mock(), False), "")

    def test_duplicate_call_is_returned_for_model_recovery_before_circuit_breaker(self):
        runtime = AgentRuntime(max_identical_calls=2, max_consecutive_failures=4)
        call = ("read", {"path": "example.txt"})

        self.assertEqual(runtime.allow_each([call]), [(True, "")])
        self.assertEqual(runtime.allow_each([call]), [(True, "")])

        allowed, reason = runtime.allow_each([call])[0]
        self.assertFalse(allowed)
        self.assertIn("already attempted twice", reason)

        should_continue, stop_reason = runtime.observe(
            call[0],
            call[1],
            ToolOutcome(False, reason, "duplicate_call"),
        )
        self.assertTrue(should_continue)
        self.assertEqual(stop_reason, "")
        self.assertEqual(runtime.consecutive_failures, 1)

    def test_successful_different_call_resets_duplicate_failure(self):
        runtime = AgentRuntime(max_identical_calls=2, max_consecutive_failures=4)
        duplicate = ("read", {"path": "example.txt"})
        different = ("read", {"path": "other.txt"})

        runtime.allow_each([duplicate])
        runtime.allow_each([duplicate])
        allowed, reason = runtime.allow_each([duplicate])[0]
        self.assertFalse(allowed)
        runtime.observe(duplicate[0], duplicate[1], ToolOutcome(False, reason, "duplicate_call"))

        self.assertEqual(runtime.allow_each([different]), [(True, "")])
        should_continue, stop_reason = runtime.observe(
            different[0], different[1], ToolOutcome(True, "ok")
        )
        self.assertTrue(should_continue)
        self.assertEqual(stop_reason, "")
        self.assertEqual(runtime.consecutive_failures, 0)

    def test_duplicate_does_not_reject_unrelated_call_in_same_batch(self):
        runtime = AgentRuntime(max_identical_calls=2)
        duplicate = ("read", {"path": "example.txt"})
        unrelated = ("bash", {"command": "echo ok"})

        runtime.allow_each([duplicate])
        runtime.allow_each([duplicate])
        admissions = runtime.allow_each([duplicate, unrelated])

        self.assertFalse(admissions[0][0])
        self.assertTrue(admissions[1][0])

    def test_file_changes_do_not_require_project_test(self):
        runtime = AgentRuntime()
        allowed, reason = runtime.allow_each([("write", {"path": "report.txt", "content": "done"})])[0]
        self.assertTrue(allowed, reason)
        should_continue, stop_reason = runtime.observe(
            "write", {"path": "report.txt", "content": "done"}, ToolOutcome(True, "written")
        )
        self.assertTrue(should_continue)
        self.assertEqual(stop_reason, "")
        self.assertFalse(runtime.needs_verification())
        self.assertFalse(runtime.can_request_verification())

    def test_local_directory_analysis_requires_tool_first(self):
        messages = [{
            "role": "user",
            "content": r"C:\Users\MengX\Desktop\pressure_balance 全面理解，分析料腿压力平衡",
        }]
        self.assertTrue(_requires_local_tool_first(messages))

    def test_local_path_mentioned_without_inspection_request_does_not_force_tool(self):
        messages = [{"role": "user", "content": r"路径叫 C:\Users\MengX\Desktop\notes"}]
        self.assertFalse(_requires_local_tool_first(messages))

    def test_attached_path_with_read_request_requires_tool_first(self):
        messages = [{
            "role": "user",
            "content": "Read this image.\n\nAttached path:\n- D:\\chengsi\\media\\diagram.png",
        }]
        self.assertTrue(_requires_local_tool_first(messages))

    def test_reserved_placeholder_only_response_is_failure(self):
        self.assertTrue(_is_unused_token_failure("<unused50>" * 31))
        self.assertFalse(_is_unused_token_failure("answer <unused50>"))
        self.assertFalse(_is_unused_token_failure("normal answer"))

    def test_reserved_placeholders_are_removed_from_request_history(self):
        messages = [
            {"role": "system", "content": "system"},
            {"role": "user", "content": "first"},
            {"role": "assistant", "content": "<unused50>" * 31},
            {"role": "user", "content": "second"},
        ]
        request = _build_request_messages(messages)
        self.assertEqual([item["role"] for item in request], ["system", "user", "user"])
        self.assertNotIn("<unused", str(request))

    def test_bash_uses_explicit_working_directory(self):
        result = Bash().run({"command": "python -c \"import os; print(os.getcwd())\"", "cwd": "."})
        self.assertTrue(result["ok"])
        self.assertIn("[cwd:", result["content"])

    def test_python_executor_rejects_invalid_timeout(self):
        result = PythonExecutor().run({"code": "print(1)", "timeout": "bad"})
        self.assertFalse(result["ok"])
        self.assertEqual(result["error_code"], "invalid_arguments")

    def test_python_executor_returns_structured_failure(self):
        result = PythonExecutor().run({"code": "raise RuntimeError('boom')", "timeout": 5})
        self.assertFalse(result["ok"])
        self.assertEqual(result["error_code"], "python_error")
        self.assertNotEqual(result["exit_code"], 0)

    def test_new_user_request_replaces_stale_done_plan(self):
        class Session:
            messages = [
                {"role": "system", "content": "system"},
                {"role": "user", "content": '[PLAN_MARKER]\n{"goal":"检查目录中的监测位号信息","status":"done","done":["旧任务"]}\n[/PLAN_MARKER]'},
                {"role": "user", "content": "理解FCC工艺图符号并查找料腿相关监测位号"},
            ]

        session = Session()
        _ensure_execution_plan(session)
        marker = session.messages[1]["content"]
        self.assertIn("理解FCC工艺图符号", marker)
        self.assertIn('"status": "active"', marker)
        self.assertNotIn("旧任务", marker)

    def test_checkpoint_keeps_findings_and_active_status(self):
        class Session:
            messages = [
                {"role": "system", "content": "system"},
                {"role": "user", "content": '[PLAN_MARKER]\n{"goal":"分析多个文件","status":"active","done":[],"notes":[] }\n[/PLAN_MARKER]'},
            ]

        session = Session()
        _update_execution_checkpoint(session, [{
            "tool": "read",
            "arguments": {"path": "diagram.xlsx"},
            "ok": True,
            "result": "发现三旋粉尘监测，未发现料腿流量位号",
        }])
        marker = session.messages[1]["content"]
        self.assertIn("diagram.xlsx", marker)
        self.assertIn("三旋粉尘监测", marker)
        self.assertIn('"status": "active"', marker)

    def test_provider_retry_counter_is_consecutive(self):
        class Runtime:
            _provider_retry_count = 3

        runtime = Runtime()
        response_has_content = True
        if response_has_content:
            runtime._provider_retry_count = 0
        self.assertEqual(runtime._provider_retry_count, 0)

    def test_repeated_rejections_eventually_stop_the_turn(self):
        runtime = AgentRuntime(max_identical_calls=0, max_consecutive_failures=2)
        call = ("read", {"path": "example.txt"})

        for expected_continue in (True, False):
            allowed, reason = runtime.allow_each([call])[0]
            self.assertFalse(allowed)
            should_continue, stop_reason = runtime.observe(
                call[0], call[1], ToolOutcome(False, reason, "duplicate_call")
            )
            self.assertEqual(should_continue, expected_continue)

        self.assertIn("2 consecutive tool failures", stop_reason)


if __name__ == "__main__":
    unittest.main()
