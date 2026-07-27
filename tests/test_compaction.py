import unittest

from main import _compaction_prompt


class CompactionPromptTests(unittest.TestCase):
    def test_recent_user_correction_overrides_obsolete_task(self):
        older = [
            {"role": "user", "content": "Merge the VMware tools and test file transfer."},
            {"role": "assistant", "content": "The VMware consolidation is complete."},
        ]
        recent = [
            {"role": "user", "content": "That was the old task. Adapt workflow.py for single and multiple calibration."},
        ]

        prompt = _compaction_prompt(older, recent)

        self.assertIn("CURRENT TASK:", prompt)
        self.assertIn("OBSOLETE TASKS:", prompt)
        self.assertIn("UNVERIFIED:", prompt)
        self.assertIn("NEXT ACTIONS:", prompt)
        self.assertIn("Merge the VMware tools", prompt)
        self.assertIn("That was the old task", prompt)
        self.assertIn("latest explicit user request", prompt)
        self.assertIn("overrides older goals", prompt)
        self.assertIn("RECENT VERBATIM CONTEXT", prompt)


if __name__ == "__main__":
    unittest.main()
