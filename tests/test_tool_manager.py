import unittest
from pathlib import Path

from core.tool_manager import ToolManager


class ToolManagerTests(unittest.TestCase):
    def test_registry_uses_executable_tool_parameters(self):
        root = Path(__file__).resolve().parents[1]
        manager = ToolManager(str(root / "tools"))
        tools = manager.load_tools()

        self.assertIn("write", tools)
        self.assertIn("web_reader", tools)
        self.assertIn("web_searcher", tools)
        for name, tool in tools.items():
            metadata = manager.registry.get(name)
            self.assertIsNotNone(metadata, name)
            self.assertEqual(metadata["parameters"], tool.parameters, name)

    def test_removed_system_cleaner_categories_are_not_exposed(self):
        root = Path(__file__).resolve().parents[1]
        manager = ToolManager(str(root / "tools"))
        parameters = manager.load_tools()["system_cleaner"].parameters

        self.assertNotIn("custom", parameters["target_types"]["items"]["enum"])
        self.assertNotIn("logs", parameters["target_types"]["items"]["enum"])


if __name__ == "__main__":
    unittest.main()
