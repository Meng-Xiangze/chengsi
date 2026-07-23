from abc import ABC, abstractmethod
from typing import Any, Dict, List

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

    def __repr__(self):
        return f"<{self.__class__.__name__} (name={self.tool_name})>"
