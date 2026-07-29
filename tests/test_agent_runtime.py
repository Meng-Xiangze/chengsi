import unittest

from core.agent_runtime import AgentRuntime, ToolOutcome


class AgentRuntimeTests(unittest.TestCase):
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
