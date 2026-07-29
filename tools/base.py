from abc import ABC, abstractmethod
from typing import Any, Dict, List
import os
import sys

# Keep every tool and child process on a predictable UTF-8 text boundary.
os.environ.setdefault("PYTHONUTF8", "1")
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

class BaseTool(ABC):
    """
    All tools must inherit from this class.
    This defines the interface that the Agent will use to understand and call the tool.
    """

    @property
    @abstractmethod
    def tool_name(self) -> str:
        """Unique name of the tool."""
        pass

    @property
    @abstractmethod
    def description(self) -> str:
        """Detailed description of what the tool does, used by the Agent to decide usage."""
        pass

    @property
    @abstractmethod
    def parameters(self) -> Dict[str, Any]:
        """
        A dictionary describing the expected input parameters. 
        Should follow a JSON Schema-like structure for easy parsing by LLM.
        Example: {'code': {'type': 'string', 'description': 'Python code to execute'}}
        """
        pass

    @abstractmethod
    def run(self, arguments: Dict[str, Any]) -> str:
        """
        The actual logic of the tool.
                Arguments are passed as a dictionary.
        Returns: The result of the execution as a string.
        """
        pass

    def is_mutating(self, arguments: Dict[str, Any]) -> bool:
        """Whether a successful call changes project or user files."""
        return False

    def is_verification(self, arguments: Dict[str, Any]) -> bool:
        """Whether a successful call verifies the current project state."""
        return False

    def __repr__(self):
        return f"<{self.__class__.__name__} (name={self.tool_name})>"
