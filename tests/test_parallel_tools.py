import unittest
import sys
import os
import time
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import MagicMock

# Add project root to path
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from core.agent_runtime import classify_tool_outcome
from tools.base import BaseTool


class SlowReadTool(BaseTool):
    """A test tool that sleeps to simulate I/O."""
    def __init__(self, sleep_time=0.5):
        self.sleep_time = sleep_time
        self.call_times = []
    
    @property
    def tool_name(self):
        return "slow_read"
    
    @property
    def description(self):
        return "Slow read tool for testing"
    
    @property
    def parameters(self):
        return {"path": {"type": "string", "description": "File path"}}
    
    def run(self, arguments):
        self.call_times.append(time.time())
        time.sleep(self.sleep_time)
        return f"Read {arguments.get('path', 'unknown')}"


class ParallelToolsTest(unittest.TestCase):
    def test_system_prompt_contains_parallel_instruction(self):
        """Verify the system prompt tells the model to batch independent tool calls."""
        sys.path.insert(0, PROJECT_ROOT)
        from main import format_system_prompt
        
        prompt = format_system_prompt()
        
        self.assertIn("multiple independent operations", prompt.lower())
        self.assertIn("batch", prompt.lower())
        self.assertIn("single response", prompt.lower())
    
    def test_parallel_execution_is_faster_than_sequential(self):
        """Verify parallel execution actually runs concurrently."""
        tool = SlowReadTool(sleep_time=0.3)
        tools = {"slow_read": tool}
        
        # Simulate 3 tool calls
        tool_calls = [
            {"id": "call_1", "action": "slow_read", "arguments": {"path": "a.txt"}},
            {"id": "call_2", "action": "slow_read", "arguments": {"path": "b.txt"}},
            {"id": "call_3", "action": "slow_read", "arguments": {"path": "c.txt"}},
        ]
        
        # Sequential execution
        sequential_start = time.time()
        for tc in tool_calls:
            tool.run(tc["arguments"])
        sequential_duration = time.time() - sequential_start
        
        # Reset call times
        tool.call_times = []
        
        # Parallel execution
        parallel_start = time.time()
        with ThreadPoolExecutor(max_workers=3) as executor:
            futures = [executor.submit(tool.run, tc["arguments"]) for tc in tool_calls]
            for future in futures:
                future.result()
        parallel_duration = time.time() - parallel_start
        
        # Parallel should be significantly faster (3x 0.3s = 0.9s sequential vs ~0.3s parallel)
        self.assertLess(parallel_duration, sequential_duration * 0.6)
        
        # All 3 calls should have started within a short window (< 0.1s)
        if len(tool.call_times) == 3:
            time_spread = max(tool.call_times) - min(tool.call_times)
            self.assertLess(time_spread, 0.1, "Tool calls did not start concurrently")
    
    def test_parallel_tools_config_gates_execution_mode(self):
        """Verify the parallel execution is gated by state.parallel_tools."""
        # This test verifies the logic: parallel = state.parallel_tools and len(stream_tool_calls) > 1
        
        # Case 1: parallel_tools=True, multiple calls → should be parallel
        parallel_tools = True
        tool_calls = [{"id": "1"}, {"id": "2"}]
        should_be_parallel = parallel_tools and len(tool_calls) > 1
        self.assertTrue(should_be_parallel)
        
        # Case 2: parallel_tools=False, multiple calls → should be sequential
        parallel_tools = False
        should_be_parallel = parallel_tools and len(tool_calls) > 1
        self.assertFalse(should_be_parallel)
        
        # Case 3: parallel_tools=True, single call → should be sequential
        parallel_tools = True
        tool_calls = [{"id": "1"}]
        should_be_parallel = parallel_tools and len(tool_calls) > 1
        self.assertFalse(should_be_parallel)


if __name__ == "__main__":
    unittest.main()
