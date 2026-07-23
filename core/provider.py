import threading
from abc import ABC, abstractmethod
from typing import Any, Iterator


class BaseProvider(ABC):
    """Common lifecycle and configuration for model providers."""

    def __init__(self, config: dict[str, Any] | None = None):
        self.config = dict(config or {})
        self.name = self.config.get("name", self.__class__.__name__)
        self._cancel_event = threading.Event()
        self._resp = None

    @classmethod
    def from_config(cls, config: dict[str, Any]):
        return cls(config)

    @property
    def supports_native_tools(self) -> bool:
        return False

    def cancel(self) -> None:
        self._cancel_event.set()
        response = self._resp
        if response is not None:
            try:
                response.close()
            except Exception:
                pass

    @abstractmethod
    def chat_stream(
        self,
        model: str,
        messages: list[dict],
        tool_defs: list[dict] | None = None,
        **kwargs,
    ) -> Iterator[tuple[str, Any]]:
        raise NotImplementedError
