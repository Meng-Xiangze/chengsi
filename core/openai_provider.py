import json
from typing import Any

import requests

from core.http_client import HttpClient
from core.json_repair import try_parse_arguments
from core.provider import BaseProvider


class OpenAIProvider(BaseProvider):
    """Provider for OpenAI-compatible chat and image APIs."""

    def __init__(self, config=None):
        super().__init__(config)
        self.http = HttpClient(self.config.get("network_mode", "auto"))

    @property
    def supports_native_tools(self) -> bool:
        return True

    @property
    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        api_key = self.config.get("api_key", "")
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        return headers

    @property
    def _base_url(self) -> str:
        return self.config.get("base_url", "https://api.openai.com/v1").rstrip("/")

    @staticmethod
    def prepare_messages(messages: list[dict], supports_vision: bool = True) -> list[dict]:
        """Normalize multimodal history for the selected model.

        Generated images are stored in history as local file URLs. They are not
        valid remote API image inputs, so keep their accompanying text and drop
        the image part. Only data URLs created for the current vision request
        are forwarded to a vision-capable model.
        """
        prepared = []
        pending_tool_call_ids: set[str] = set()
        for message in messages:
            item = dict(message)
            role = item.get("role")
            if role == "assistant" and item.get("tool_calls"):
                pending_tool_call_ids = {
                    call.get("id") for call in item["tool_calls"] if call.get("id")
                }
            elif role == "tool":
                tool_call_id = item.get("tool_call_id")
                if tool_call_id not in pending_tool_call_ids:
                    continue
                pending_tool_call_ids.discard(tool_call_id)
            else:
                pending_tool_call_ids.clear()

            content = item.get("content")
            if not isinstance(content, list):
                prepared.append(item)
                continue

            text_parts = []
            image_parts = []
            for part in content:
                if not isinstance(part, dict):
                    continue
                if part.get("type") == "text":
                    text = part.get("text", "")
                    if text:
                        text_parts.append(str(text))
                elif part.get("type") == "image_url":
                    image_url = part.get("image_url", {})
                    url = image_url.get("url", "") if isinstance(image_url, dict) else str(image_url)
                    if supports_vision and isinstance(url, str) and url.startswith("data:image/"):
                        image_parts.append({"type": "image_url", "image_url": {"url": url}})

            if image_parts:
                text = "\n".join(text_parts)
                if item.get("role") == "tool":
                    # Keep the OpenAI tool result textual and place the image in
                    # a separate user turn. Many compatible gateways ignore
                    # image parts when they occur inside role=tool content.
                    item["content"] = text
                    prepared.append(item)
                    prepared.append({
                        "role": "user",
                        "content": ([{"type": "text", "text": "Image returned by read:"}] if not text else [{"type": "text", "text": "Image returned by read.\n" + text}]) + image_parts,
                    })
                    continue
                item["content"] = ([{"type": "text", "text": text}] if text else []) + image_parts
            else:
                item["content"] = "\n".join(text_parts)
            prepared.append(item)
        return prepared

    @staticmethod
    def _responses_input(messages: list[dict]) -> list[dict]:
        """Convert Chat Completions history into Responses API input items."""
        items: list[dict] = []
        for message in messages:
            role = message.get("role", "user")
            content = message.get("content", "")
            if role == "tool":
                items.append({
                    "type": "function_call_output",
                    "call_id": message.get("tool_call_id", ""),
                    "output": str(content or ""),
                })
                continue
            if role == "assistant" and message.get("tool_calls"):
                if content:
                    items.append({"role": "assistant", "content": str(content)})
                for call in message.get("tool_calls") or []:
                    function = call.get("function") or {}
                    arguments = function.get("arguments", "{}")
                    if not isinstance(arguments, str):
                        arguments = json.dumps(arguments, ensure_ascii=False, default=str)
                    items.append({
                        "type": "function_call",
                        "call_id": call.get("id", ""),
                        "name": function.get("name", ""),
                        "arguments": arguments,
                    })
                continue
            if isinstance(content, list):
                parts = []
                for part in content:
                    if not isinstance(part, dict):
                        continue
                    if part.get("type") == "text":
                        parts.append({"type": "input_text", "text": str(part.get("text", ""))})
                    elif part.get("type") == "image_url":
                        image_url = part.get("image_url", {})
                        url = image_url.get("url", "") if isinstance(image_url, dict) else str(image_url)
                        if url:
                            parts.append({"type": "input_image", "image_url": url})
                items.append({"role": role, "content": parts})
            else:
                items.append({"role": role, "content": str(content or "")})
        return items

    @staticmethod
    def _responses_tools(tool_defs: list[dict] | None) -> list[dict] | None:
        """Flatten Chat Completions function definitions for Responses API."""
        converted = []
        for definition in tool_defs or []:
            function = definition.get("function") or {}
            if definition.get("type") != "function" or not function.get("name"):
                continue
            converted.append({
                "type": "function",
                "name": function["name"],
                "description": function.get("description", ""),
                "parameters": function.get("parameters", {"type": "object", "properties": {}}),
            })
        return converted or None

    @staticmethod
    def _finish_tool_calls(parts: dict[int, dict]) -> list[dict]:
        calls = []
        for index in sorted(parts):
            part = parts[index]
            raw_arguments = part.get("arguments", "")
            arguments = try_parse_arguments(raw_arguments)
            call = {
                "id": part.get("id") or f"call_{index:02d}",
                "action": part.get("name", ""),
                "arguments": arguments,
            }
            if part.get("parse_error"):
                call["parse_error"] = part["parse_error"]
            calls.append(call)
        return calls

    @staticmethod
    def _decode_sse_line(raw_line: bytes | str) -> str:
        """Decode provider bytes as UTF-8 regardless of a bad gateway charset header."""
        if isinstance(raw_line, bytes):
            return raw_line.decode("utf-8", errors="replace")
        return str(raw_line)

    @staticmethod
    def _response_text(response, limit: int = 1000) -> str:
        """Decode JSON/error bodies consistently when a gateway omits UTF-8 charset."""
        try:
            content = response.content
            if isinstance(content, bytes):
                return content.decode("utf-8", errors="replace")[:limit]
        except Exception:
            pass
        try:
            return str(response.text)[:limit]
        except Exception:
            return ""

    @classmethod
    def _sse_events(cls, response):
        """Yield complete SSE payloads, tolerating missing separators and split JSON."""
        fragments = []

        def complete(value: str) -> bool:
            if value == "[DONE]":
                return True
            try:
                json.loads(value)
                return True
            except json.JSONDecodeError:
                return False

        for raw_line in response.iter_lines(decode_unicode=False):
            line = cls._decode_sse_line(raw_line).rstrip("\r")
            if not line:
                if fragments:
                    yield "".join(fragments)
                    fragments = []
                continue
            if line.startswith(":"):
                continue
            if line.startswith("data:"):
                if fragments:
                    buffered = "".join(fragments)
                    if complete(buffered):
                        yield buffered
                        fragments = []
                fragments.append(line[5:].lstrip())
            elif fragments:
                # Some compatible gateways omit `data:` on a continued JSON fragment.
                fragments.append(line)
        if fragments:
            yield "".join(fragments)

    def chat_stream(self, model: str, messages: list[dict], tool_defs=None, **kwargs):
        fallback_mode = bool(kwargs.get("fallback_mode", False))
        request_api = kwargs.get("request_api", "chat_completions")
        if request_api not in ("chat_completions", "responses"):
            request_api = "chat_completions"
        prepared_messages = self.prepare_messages(messages, kwargs.get("supports_vision", True))
        if fallback_mode:
            bundle = json.dumps({"messages": prepared_messages}, ensure_ascii=False, default=str)
            prepared_messages = [{"role": "user", "content": bundle}]

        if request_api == "responses":
            payload: dict[str, Any] = {
                "model": model,
                "input": self._responses_input(prepared_messages),
                "stream": True,
            }
            response_tools = self._responses_tools(tool_defs) if not fallback_mode else None
            if response_tools:
                payload["tools"] = response_tools
                payload["tool_choice"] = "auto"
            endpoint = "/responses"
        else:
            payload = {
                "model": model,
                "messages": prepared_messages,
                "stream": True,
                "stream_options": {"include_usage": True},
            }
            if tool_defs and not fallback_mode:
                payload["tools"] = tool_defs
                payload["tool_choice"] = "auto"
            endpoint = "/chat/completions"

        external_cancel = kwargs.get("cancel_event")
        self._cancel_event.clear()
        tool_parts: dict[int, dict] = {}
        response_tool_indexes: dict[str, int] = {}
        try:
            response = self.http.post(
                f"{self._base_url}{endpoint}",
                headers=self._headers,
                json=payload,
                timeout=(8, 300),
                stream=True,
            )
            response.raise_for_status()
            self._resp = response
            for data in self._sse_events(response):
                if self._cancel_event.is_set() or (external_cancel and external_cancel.is_set()):
                    response.close()
                    yield "cancelled", None
                    return
                if data == "[DONE]":
                    break
                try:
                    chunk = json.loads(data)
                except json.JSONDecodeError as error:
                    yield "error", f"Provider returned malformed SSE JSON: {error}"
                    continue

                if request_api == "responses":
                    event_type = chunk.get("type", "")
                    if event_type == "response.output_text.delta" and chunk.get("delta"):
                        yield "content", chunk["delta"]
                    elif event_type in ("response.reasoning_summary_text.delta", "response.reasoning_text.delta") and chunk.get("delta"):
                        yield "thinking", chunk["delta"]
                    elif event_type == "response.output_item.added":
                        item = chunk.get("item") or {}
                        if item.get("type") == "function_call":
                            key = str(item.get("id") or item.get("call_id") or chunk.get("output_index", len(tool_parts)))
                            index = int(chunk.get("output_index", len(tool_parts)))
                            response_tool_indexes[key] = index
                            tool_parts[index] = {
                                "id": item.get("call_id") or item.get("id") or f"call_{index:02d}",
                                "name": item.get("name", ""),
                                "arguments": item.get("arguments", ""),
                            }
                    elif event_type == "response.function_call_arguments.delta":
                        key = str(chunk.get("item_id") or chunk.get("call_id") or chunk.get("output_index", 0))
                        index = response_tool_indexes.get(key, int(chunk.get("output_index", 0)))
                        current = tool_parts.setdefault(index, {
                            "id": chunk.get("call_id") or key,
                            "name": chunk.get("name", ""),
                            "arguments": "",
                        })
                        current["arguments"] += str(chunk.get("delta", ""))
                    elif event_type == "response.output_item.done":
                        item = chunk.get("item") or {}
                        if item.get("type") == "function_call":
                            index = int(chunk.get("output_index", 0))
                            tool_parts[index] = {
                                "id": item.get("call_id") or item.get("id") or f"call_{index:02d}",
                                "name": item.get("name", ""),
                                "arguments": item.get("arguments", ""),
                            }
                    elif event_type == "response.completed":
                        usage = (chunk.get("response") or {}).get("usage") or {}
                        if usage:
                            input_tokens = usage.get("input_tokens", 0)
                            output_tokens = usage.get("output_tokens", 0)
                            yield "tokens", {
                                "input": input_tokens, "output": output_tokens,
                                "prompt": input_tokens, "eval": output_tokens, "actual": True,
                            }
                    elif event_type in ("response.failed", "error"):
                        error = (chunk.get("response") or {}).get("error") or chunk.get("error") or chunk
                        yield "error", f"Responses API failed: {json.dumps(error, ensure_ascii=False, default=str)[:1000]}"
                    continue

                usage = chunk.get("usage")
                if usage:
                    input_tokens = usage.get("prompt_tokens", 0)
                    output_tokens = usage.get("completion_tokens", 0)
                    yield "tokens", {
                        "input": input_tokens,
                        "output": output_tokens,
                        "prompt": input_tokens,
                        "eval": output_tokens,
                        "actual": True,
                    }
                choices = chunk.get("choices") or []
                if not choices:
                    continue
                delta = choices[0].get("delta") or {}
                reasoning = delta.get("reasoning_content") or delta.get("reasoning")
                content = delta.get("content")
                if reasoning:
                    yield "thinking", reasoning
                if content:
                    yield "content", content
                for tool_call in delta.get("tool_calls") or []:
                    index = tool_call.get("index", 0)
                    current = tool_parts.setdefault(index, {"id": "", "name": "", "arguments": ""})
                    if tool_call.get("id"):
                        current["id"] = tool_call["id"]
                    function = tool_call.get("function") or {}
                    if function.get("name"):
                        current["name"] += function["name"]
                    if function.get("arguments"):
                        current["arguments"] += function["arguments"]
            if self._cancel_event.is_set() or (external_cancel and external_cancel.is_set()):
                yield "cancelled", None
                return
            if tool_parts:
                calls = self._finish_tool_calls(tool_parts)
                parse_errors = [call.pop("parse_error") for call in calls if call.get("parse_error")]
                if parse_errors:
                    yield "error", "; ".join(parse_errors)
                else:
                    yield "tool_calls", calls
        except requests.exceptions.ProxyError as error:
            if self._cancel_event.is_set():
                yield "cancelled", None
            else:
                yield "error", f"System proxy could not reach provider ({self._base_url}): {error}"
        except requests.exceptions.ConnectTimeout as error:
            if self._cancel_event.is_set():
                yield "cancelled", None
            else:
                yield "error", f"Provider connection timed out ({self._base_url}): {error}"
        except requests.exceptions.ConnectionError as error:
            if self._cancel_event.is_set():
                yield "cancelled", None
            else:
                yield "error", f"Could not connect to OpenAI-compatible provider ({self._base_url}): {error}"
        except requests.exceptions.Timeout as error:
            if self._cancel_event.is_set():
                yield "cancelled", None
            else:
                yield "error", f"Provider response timed out ({self._base_url}): {error}"
        except requests.exceptions.HTTPError as error:
            if self._cancel_event.is_set():
                yield "cancelled", None
            else:
                status = error.response.status_code if error.response is not None else "?"
                body = self._response_text(error.response) if error.response is not None else ""
                yield "error", f"Provider returned HTTP {status}: {body}"
        except Exception as error:
            if self._cancel_event.is_set():
                yield "cancelled", None
            else:
                yield "error", f"Provider request failed: {error}"
        finally:
            self._resp = None

    def generate_image(self, model: str, prompt: str) -> dict[str, str]:
        payload = {"model": model, "prompt": prompt, "size": "1024x1024"}
        response = self.http.post(
            f"{self._base_url}/images/generations",
            headers=self._headers,
            json=payload,
            timeout=(8, 300),
        )
        response.raise_for_status()
        result = response.json()
        entries = result.get("data") or []
        if not entries:
            raise ValueError("Image provider returned no image data")
        entry = entries[0]
        url = entry.get("url")
        if not url and entry.get("b64_json"):
            url = f"data:image/png;base64,{entry['b64_json']}"
        if not url:
            raise ValueError("Image provider response contains neither url nor b64_json")
        output = {"url": url}
        if entry.get("revised_prompt"):
            output["revised_prompt"] = entry["revised_prompt"]
        return output
