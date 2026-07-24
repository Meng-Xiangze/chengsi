"""Shared HTTP transport with explicit proxy behavior and safe route fallback."""

from __future__ import annotations

import threading
import time
from urllib.parse import urlparse

import requests


_VALID_MODES = {"auto", "direct", "system_proxy"}
_ROUTE_CACHE: dict[str, tuple[str, float]] = {}
_ROUTE_CACHE_LOCK = threading.Lock()
_ROUTE_CACHE_TTL = 15 * 60


def _origin(url: str) -> str:
    parsed = urlparse(url)
    return f"{parsed.scheme.lower()}://{parsed.netloc.lower()}"


def _is_local_url(url: str) -> bool:
    host = (urlparse(url).hostname or "").lower()
    return host in {"localhost", "127.0.0.1", "::1"}


def _exception_names(error: Exception) -> set[str]:
    names = set()
    current: BaseException | None = error
    seen: set[int] = set()
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        names.add(type(current).__name__)
        next_error = current.__cause__ or current.__context__
        if next_error is None and getattr(current, "args", None):
            next_error = next(
                (item for item in current.args if isinstance(item, BaseException)),
                None,
            )
        current = next_error
    return names


def _can_retry_route(error: Exception) -> bool:
    """Return whether connection setup failed before an HTTP response existed."""
    if isinstance(error, requests.exceptions.ConnectTimeout):
        return True
    if isinstance(error, requests.exceptions.ProxyError):
        return True
    if not isinstance(error, requests.exceptions.ConnectionError):
        return False
    # A generic ConnectionError can also mean that a POST was accepted and the
    # response body later broke. Retry only urllib3's explicit setup failures.
    return bool(
        _exception_names(error)
        & {"NameResolutionError", "NewConnectionError", "ProxyError"}
    )


class HttpClient:
    """HTTP client that isolates local services and handles optional system proxies.

    Online providers default to ``auto``: direct first, then the system proxy only
    when connection establishment fails before an HTTP response exists. The last
    successful route is cached to avoid paying the failed-route delay each time.
    """

    def __init__(self, network_mode: str = "auto"):
        mode = str(network_mode or "auto").strip().lower()
        if mode not in _VALID_MODES:
            raise ValueError(
                f"Invalid network_mode {network_mode!r}; expected auto, direct, or system_proxy"
            )
        self.network_mode = mode
        self._local = threading.local()

    def _session(self, route: str) -> requests.Session:
        attribute = f"{route}_session"
        session = getattr(self._local, attribute, None)
        if session is None:
            session = requests.Session()
            session.trust_env = route == "system_proxy"
            setattr(self._local, attribute, session)
        return session

    @staticmethod
    def _cached_route(url: str) -> str | None:
        key = _origin(url)
        now = time.monotonic()
        with _ROUTE_CACHE_LOCK:
            entry = _ROUTE_CACHE.get(key)
            if not entry:
                return None
            route, expires_at = entry
            if expires_at <= now:
                _ROUTE_CACHE.pop(key, None)
                return None
            return route

    @staticmethod
    def _cache_route(url: str, route: str) -> None:
        with _ROUTE_CACHE_LOCK:
            _ROUTE_CACHE[_origin(url)] = (route, time.monotonic() + _ROUTE_CACHE_TTL)

    def _routes(self, url: str) -> list[str]:
        if _is_local_url(url) or self.network_mode == "direct":
            return ["direct"]
        if self.network_mode == "system_proxy":
            return ["system_proxy"]
        cached = self._cached_route(url)
        if cached:
            alternative = "system_proxy" if cached == "direct" else "direct"
            return [cached, alternative]
        return ["direct", "system_proxy"]

    def request(self, method: str, url: str, **kwargs) -> requests.Response:
        routes = self._routes(url)
        last_error: Exception | None = None
        for index, route in enumerate(routes):
            try:
                response = self._session(route).request(method, url, **kwargs)
                if self.network_mode == "auto" and not _is_local_url(url):
                    self._cache_route(url, route)
                setattr(response, "chengsi_network_route", route)
                return response
            except requests.exceptions.RequestException as error:
                last_error = error
                has_alternative = index + 1 < len(routes)
                if not has_alternative or not _can_retry_route(error):
                    error.args = (*error.args, f"network route: {route}")
                    raise
        assert last_error is not None
        raise last_error

    def get(self, url: str, **kwargs) -> requests.Response:
        return self.request("GET", url, **kwargs)

    def post(self, url: str, **kwargs) -> requests.Response:
        return self.request("POST", url, **kwargs)
