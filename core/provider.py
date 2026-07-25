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
            # Force-shutdown the underlying TCP socket so any blocking recv()
            # in the worker thread returns immediately (critical on Windows).
            try:
                raw = response.raw
                fp = raw._fp if hasattr(raw, '_fp') else raw
                sock = fp._sock if hasattr(fp, '_sock') else None
                if sock is None and hasattr(fp, 'fileno'):
                    import socket as _socket
                    sock = _socket.fromfd(fp.fileno(), _socket.AF_INET, _socket.SOCK_STREAM)
                if sock is not None:
                    try:
                        sock.shutdown(2)  # SHUT_RDWR
                    except Exception:
                        pass
                    try:
                        sock.close()
                    except Exception:
                        pass
            except Exception:
                pass
        self._resp = None

    @abstractmethod
    def chat_stream(
        self,
        model: str,
        messages: list[dict],
        tool_defs: list[dict] | None = None,
        **kwargs,
    ) -> Iterator[tuple[str, Any]]:
        raise NotImplementedError
