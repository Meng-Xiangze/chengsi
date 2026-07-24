import unittest
from unittest.mock import Mock, patch

import requests
from urllib3.exceptions import NewConnectionError

from core.http_client import HttpClient


class HttpClientTests(unittest.TestCase):
    def test_auto_prefers_direct(self):
        client = HttpClient("auto")
        response = Mock()
        with patch.object(client._session("direct"), "request", return_value=response) as direct:
            result = client.get("https://provider.invalid/models", timeout=(1, 1))
        self.assertIs(result, response)
        direct.assert_called_once()
        self.assertEqual(response.chengsi_network_route, "direct")

    def test_auto_falls_back_for_connection_setup_failure(self):
        client = HttpClient("auto")
        connection_error = requests.exceptions.ConnectionError(
            NewConnectionError(None, "connection failed")
        )
        response = Mock()
        with (
            patch.object(client._session("direct"), "request", side_effect=connection_error),
            patch.object(client._session("system_proxy"), "request", return_value=response) as proxy,
        ):
            result = client.post("https://fallback.invalid/chat", json={})
        self.assertIs(result, response)
        proxy.assert_called_once()
        self.assertEqual(response.chengsi_network_route, "system_proxy")

    def test_auto_does_not_retry_read_timeout(self):
        client = HttpClient("auto")
        with (
            patch.object(
                client._session("direct"),
                "request",
                side_effect=requests.exceptions.ReadTimeout("late response"),
            ),
            patch.object(client._session("system_proxy"), "request") as proxy,
        ):
            with self.assertRaises(requests.exceptions.ReadTimeout):
                client.post("https://no-retry.invalid/chat", json={})
        proxy.assert_not_called()

    def test_local_url_always_bypasses_proxy(self):
        client = HttpClient("system_proxy")
        response = Mock()
        with (
            patch.object(client._session("direct"), "request", return_value=response) as direct,
            patch.object(client._session("system_proxy"), "request") as proxy,
        ):
            client.post("http://localhost:11434/api/chat", json={})
        direct.assert_called_once()
        proxy.assert_not_called()

    def test_invalid_mode_is_rejected(self):
        with self.assertRaises(ValueError):
            HttpClient("unknown")


if __name__ == "__main__":
    unittest.main()
