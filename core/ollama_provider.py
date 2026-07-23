import json

import requests

from core.provider import BaseProvider


class OllamaProvider(BaseProvider):
    """Provider for local Ollama models."""

    @property
    def supports_native_tools(self) -> bool:
        return True

    @staticmethod
    def prepare_messages(messages: list[dict]) -> list[dict]:
        converted = []
        for message in messages:
            new_message = dict(message)
            content = new_message.get("content", "")
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
                        # Local file URLs are generated-image history, not valid
                        # Ollama image inputs. Keep the accompanying text only.
                        if isinstance(url, str) and url.startswith("data:image/") and "," in url:
                            images.append(url.split(",", 1)[1])
                new_message["content"] = "\n".join(text_parts) if text_parts else ""
                if images:
                    new_message["images"] = images
            if new_message.get("role") == "tool":
                new_message["role"] = "user"
                if new_message.get("content"):
                    new_message["content"] = f"TOOL_RESULT: {new_message['content']}"
            new_message.pop("tool_calls", None)
            new_message.pop("tool_call_id", None)
            converted.append(new_message)

        merged = []
        for message in converted:
            if message.get("role") == "user" and merged and merged[-1].get("role") == "user":
                previous = merged[-1].get("content", "")
                current = message.get("content", "")
                merged[-1]["content"] = f"{previous}\n{current}" if previous else current
                if "images" in message:
                    merged[-1]["images"] = merged[-1].get("images", []) + message["images"]
            else:
                merged.append(message)
        return merged

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

    def chat_stream(self, model: str, messages: list[dict], tool_defs=None, **kwargs):
        base_url = self.config.get("base_url", "http://localhost:11434/api")
        url = f"{base_url.rstrip('/')}/chat"
        payload = {"model": model, "messages": self.prepare_messages(messages), "stream": True}
        if tool_defs:
            payload["tools"] = self._convert_tool_defs(tool_defs)

        external_cancel = kwargs.get("cancel_event")
        self._cancel_event.clear()
        try:
            response = requests.post(url, json=payload, timeout=300, stream=True)
            response.raise_for_status()
            self._resp = response
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
                    yield "thinking", thinking
                if content:
                    yield "content", content
                if tool_calls:
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
                            "id": f"call_{len(calls):02d}",
                            "action": function.get("name", ""),
                            "arguments": arguments,
                        })
                    yield "tool_calls", calls
                if chunk.get("done"):
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
        except requests.exceptions.ConnectionError:
            yield "error", f"Could not connect to Ollama ({base_url}); make sure Ollama is running"
        except requests.exceptions.Timeout:
            yield "error", f"Ollama request timed out ({base_url}); the model may still be loading"
        except requests.exceptions.HTTPError as error:
            status = error.response.status_code if error.response is not None else "?"
            body = ""
            if error.response is not None:
                try:
                    body = error.response.text[:500]
                except Exception:
                    pass
            yield "error", f"Ollama returned HTTP {status}: {body}"
        except Exception as error:
            yield "error", f"Ollama request failed: {error}"
        finally:
            self._resp = None
