import json
import re

import requests

from core.http_client import HttpClient
from core.provider import BaseProvider


class OllamaProvider(BaseProvider):
    """Provider for local Ollama models."""

    def __init__(self, config=None):
        super().__init__(config)
        # Local model traffic must never be sent to a VPN or desktop proxy.
        self.http = HttpClient("direct")

    @property
    def supports_native_tools(self) -> bool:
        return True

    @staticmethod
    def prepare_messages(messages: list[dict]) -> list[dict]:
        prepared = []
        for message in messages:
            item = dict(message)
            content = item.get("content", "")
            if isinstance(content, list):
                text_parts = []
                images = []
                for part in content:
                    if not isinstance(part, dict):
                        continue
                    part_type = part.get("type", "")
                    if part_type == "text":
                        text_parts.append(part.get("text", ""))
                    elif part_type == "image_url":
                        url = part.get("image_url", {})
                        if isinstance(url, dict):
                            url = url.get("url", "")
                        if isinstance(url, str) and url.startswith("data:image/") and "," in url:
                            images.append(url.split(",", 1)[1])
                item["content"] = "\n".join(text_parts) if text_parts else ""
                if images:
                    item["images"] = images
            if item.get("role") == "assistant" and item.get("tool_calls"):
                normalized_calls = []
                for tool_call in item["tool_calls"]:
                    call = dict(tool_call)
                    function = dict(call.get("function") or {})
                    arguments = function.get("arguments", {})
                    if isinstance(arguments, str):
                        try:
                            function["arguments"] = json.loads(arguments)
                        except json.JSONDecodeError:
                            function["arguments"] = {}
                    call["function"] = function
                    normalized_calls.append(call)
                item["tool_calls"] = normalized_calls
            prepared.append(item)
        return prepared

    @staticmethod
    def _convert_tool_defs(tool_defs: list[dict]) -> list[dict]:
        result = []
        for definition in tool_defs:
            function = definition.get("function", {})
            result.append({
                "type": "function",
                "function": {
                    "name": function.get("name", ""),
                    "description": function.get("description", ""),
                    "parameters": function.get("parameters", {}),
                },
            })
        return result

    @staticmethod
    def _extract_tool_calls_from_thinking(thinking_text: str) -> list[dict] | None:
        """Scan accumulated thinking text for tool-call blocks that the model
        emitted as raw text instead of native tool_calls.

        Supports two formats:
        - Hermes JSON:  <tool_call>{"name": "...", "arguments": {...}}</tool_call>
        - Qwen XML:     <tool_call><function=name><parameter=k>v</parameter>...</function></tool_call>

        Returns None if no tool calls found (caller should NOT inject empty content).
        """
        blocks = re.findall(r'<tool_call>\s*(.*?)\s*</tool_call>', thinking_text, re.DOTALL)
        if not blocks:
            return None

        calls = []
        for idx, block in enumerate(blocks):
            block = block.strip()
            if not block:
                continue
            # 1) Try Hermes-style JSON
            if block.startswith('{'):
                try:
                    data = json.loads(block)
                    calls.append({
                        "id": f"extracted_{idx}",
                        "action": str(data.get("name", data.get("function", ""))),
                        "arguments": data.get("arguments", data.get("parameters", {})),
                    })
                    continue
                except (json.JSONDecodeError, ValueError):
                    pass
            # 2) Try Qwen-Coder XML
            func_match = re.search(r'<function=(\w+)>(.*?)</function>', block, re.DOTALL)
            if func_match:
                action = func_match.group(1)
                args = {}
                for pm in re.finditer(r'<parameter=(\w+)>\s*(.*?)\s*</parameter>', block, re.DOTALL):
                    args[pm.group(1)] = pm.group(2).strip()
                calls.append({"id": f"extracted_{idx}", "action": action, "arguments": args})
        return calls if calls else None

    def chat_stream(self, model: str, messages: list[dict], tool_defs=None, **kwargs):
        base_url = self.config.get("base_url", "http://localhost:11434/api")
        url = f"{base_url.rstrip('/')}/chat"
        payload = {"model": model, "messages": self.prepare_messages(messages), "stream": True}
        if tool_defs:
            payload["tools"] = self._convert_tool_defs(tool_defs)
        # Explicitly enable thinking — Ollama defaults to true for Qwen but being
        # explicit avoids any version-specific default changes.
        payload["think"] = True

        external_cancel = kwargs.get("cancel_event")
        self._cancel_event.clear()
        try:
            response = self.http.post(url, json=payload, timeout=(3, 300), stream=True)
            response.raise_for_status()
            self._resp = response

            thinking_buffer = ""
            had_native_tool_calls = False
            content_produced = False

            for line in response.iter_lines():
                if self._cancel_event.is_set() or (external_cancel and external_cancel.is_set()):
                    response.close()
                    yield "cancelled", None
                    return
                if not line:
                    continue
                chunk = json.loads(line)
                message = chunk.get("message", {})
                thinking = message.get("thinking")
                content = message.get("content")
                tool_calls = message.get("tool_calls")
                if thinking:
                    thinking_buffer += thinking
                    yield "thinking", thinking
                if content:
                    content_produced = True
                    yield "content", content
                if tool_calls:
                    had_native_tool_calls = True
                    calls = []
                    for tool_call in tool_calls:
                        function = tool_call.get("function", {})
                        arguments = function.get("arguments", {})
                        if isinstance(arguments, str):
                            try:
                                arguments = json.loads(arguments)
                            except Exception:
                                arguments = {}
                        calls.append({
                            "id": tool_call.get("id") or f"call_{len(calls):02d}",
                            "action": function.get("name", ""),
                            "arguments": arguments,
                        })
                    yield "tool_calls", calls
                if chunk.get("done"):
                    # ── Safe mode: Qwen3/Qwen3.5 may emit tool calls inside thinking
                    #     text instead of as native tool_calls (Ollama #10976).
                    #     When the model produced nothing useful, scan thinking for
                    #     <tool_call> blocks and extract them. ──
                    if not had_native_tool_calls and not content_produced and thinking_buffer.strip():
                        extracted = self._extract_tool_calls_from_thinking(thinking_buffer)
                        if extracted:
                            had_native_tool_calls = True
                            yield "content", ""
                            yield "tool_calls", extracted
                    prompt_tokens = chunk.get("prompt_eval_count", 0)
                    eval_tokens = chunk.get("eval_count", 0)
                    if prompt_tokens or eval_tokens:
                        yield "tokens", {
                            "input": prompt_tokens,
                            "output": eval_tokens,
                            "prompt": prompt_tokens,
                            "eval": eval_tokens,
                            "actual": True,
                        }

            # After loop, check if cancelled
            if self._cancel_event.is_set() or (external_cancel and external_cancel.is_set()):
                yield "cancelled", None
                return

        except requests.exceptions.ConnectionError:
            if self._cancel_event.is_set():
                yield "cancelled", None
            else:
                yield "error", f"Could not connect to Ollama ({base_url}); make sure Ollama is running"
        except requests.exceptions.Timeout:
            if self._cancel_event.is_set():
                yield "cancelled", None
            else:
                yield "error", f"Ollama request timed out ({base_url}); the model may still be loading"
        except requests.exceptions.HTTPError as error:
            if self._cancel_event.is_set():
                yield "cancelled", None
            else:
                status = error.response.status_code if error.response is not None else "?"
                body = ""
                if error.response is not None:
                    try:
                        body = error.response.text[:500]
                    except Exception:
                        pass
                yield "error", f"Ollama returned HTTP {status}: {body}"
        except Exception as error:
            if self._cancel_event.is_set():
                yield "cancelled", None
            else:
                yield "error", f"Ollama request failed: {error}"
        finally:
            self._resp = None
