import base64
import importlib.util
import json
import mimetypes
import os
import re
import sys
import uuid
from pathlib import Path
from typing import Any

import yaml

from core.http_client import HttpClient
from tools.base import BaseTool


class _ToolRegistry:
    """Loads tool documentation and maintains the compact tool catalog."""

    def __init__(self, tools_dir: str):
        self.tools_dir = Path(tools_dir).resolve()
        self.toc_path = self.tools_dir / "TOC.md"
        self._catalog: dict[str, dict[str, Any]] = {}

    @staticmethod
    def _front_matter(text: str) -> dict[str, Any]:
        if not text.startswith("---"):
            return {}
        match = re.match(r"^---\s*\n(.*?)\n---(?:\s*\n|$)", text, re.DOTALL)
        if not match:
            return {}
        try:
            data = yaml.safe_load(match.group(1))
            return data if isinstance(data, dict) else {}
        except yaml.YAMLError:
            return {}

    def refresh(self, tools: dict[str, BaseTool] | None = None) -> dict[str, dict[str, Any]]:
        tools = tools or {}
        catalog = {}
        names = set(tools)
        names.update(path.stem for path in self.tools_dir.glob("*.md") if path.name != "TOC.md")
        for name in sorted(names):
            metadata: dict[str, Any] = {}
            doc_path = self.tools_dir / f"{name}.md"
            if doc_path.is_file():
                try:
                    metadata.update(self._front_matter(doc_path.read_text(encoding="utf-8")))
                except OSError:
                    pass
            tool = tools.get(name)
            if tool is not None:
                # Python is the executable contract. Documentation may enrich the
                # catalog, but stale parameter schemas must never reach the model.
                metadata["name"] = tool.tool_name
                metadata["description"] = metadata.get("description") or tool.description
                metadata["parameters"] = tool.parameters
            if metadata:
                catalog[name] = metadata
        self._catalog = catalog
        return catalog

    def get_catalog(self) -> dict[str, dict[str, Any]]:
        if not self._catalog:
            self.refresh()
        return dict(self._catalog)

    def get(self, name: str) -> dict[str, Any] | None:
        return self.get_catalog().get(name)

    def add_tool_entry(self, name: str, description: str) -> None:
        line = f"- `{name}`: {description.strip()}"
        text = self.toc_path.read_text(encoding="utf-8") if self.toc_path.is_file() else "# Available Tools\n"
        pattern = re.compile(rf"^- `{re.escape(name)}`:.*$", re.MULTILINE)
        if pattern.search(text):
            text = pattern.sub(line, text)
        else:
            text = text.rstrip() + "\n" + line + "\n"
        self.toc_path.write_text(text, encoding="utf-8")
        self._catalog.clear()

    def remove_tool_entry(self, name: str) -> None:
        if not self.toc_path.is_file():
            return
        text = self.toc_path.read_text(encoding="utf-8")
        pattern = re.compile(rf"^- `{re.escape(name)}`:.*(?:\n|$)", re.MULTILINE)
        self.toc_path.write_text(pattern.sub("", text), encoding="utf-8")
        self._catalog.clear()


class ImageGenerationTool(BaseTool):
    """Generate or edit an image through the configured image model.

    Routing logic:
    1. If the currently-active model has ``image_generation: true`` → use it.
    2. Otherwise → fall back to the configured ``default_image_model``.
    """

    def __init__(self, project_root: Path):
        self.project_root = project_root
        self.config_path = project_root / "config.json"

    @property
    def tool_name(self) -> str:
        return "image_generator"

    @property
    def description(self) -> str:
        return "Generate a new image or edit an existing image. Use image_path for an image that should be modified."

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "prompt": {"type": "string", "description": "Exact image generation or editing instruction.", "required": True},
            "image_path": {"type": "string", "description": "Optional absolute path of an existing image to edit."},
        }

    def _load_config(self) -> dict:
        try:
            return json.loads(self.config_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}

    def _current_model_info(self) -> tuple[Any | None, str, dict]:
        """Return (provider, model_name, model_config) for the active model,
        or (None, '', {}) when unavailable."""
        import main as _main
        provider = getattr(_main, "_provider", None)
        model = getattr(_main, "_provider_model", "")
        providers_cfg = getattr(_main, "_providers_cfg", [])
        model_config: dict = {}
        for pcfg in providers_cfg:
            for entry in pcfg.get("models", []):
                name = entry if isinstance(entry, str) else entry.get("name", "")
                if name == model:
                    model_config = entry if isinstance(entry, dict) else {}
                    break
        return provider, model, model_config

    def _resolve_provider_and_model(
        self, config: dict
    ) -> tuple[Any, str]:
        """Pick the right provider+model for image generation.

        1. Current model has ``image_generation: true`` → use it.
        2. Otherwise → use ``default_image_model`` from config.
        """
        provider, current_model, model_config = self._current_model_info()

        # Route 1: current model can generate images
        if (provider is not None and current_model
                and model_config.get("image_generation", False)):
            return provider, current_model

        # Route 2: fall back to default_image_model
        default_spec = config.get("default_image_model", "")
        if default_spec:
            target_prov, target_model = self._parse_default_spec(default_spec)
            from core.ollama_provider import OllamaProvider
            from core.openai_provider import OpenAIProvider
            for pcfg in config.get("providers", []):
                if target_prov and pcfg.get("name", "") != target_prov:
                    continue
                for entry in pcfg.get("models", []):
                    name = entry if isinstance(entry, str) else entry.get("name", "")
                    if name == target_model:
                        if pcfg.get("type", "openai") == "ollama":
                            return OllamaProvider.from_config(pcfg), target_model
                        return OpenAIProvider.from_config(pcfg), target_model

        # Route 3: any model with image_generation=true
        for pcfg in config.get("providers", []):
            for entry in pcfg.get("models", []):
                if isinstance(entry, dict) and entry.get("image_generation"):
                    from core.openai_provider import OpenAIProvider
                    return OpenAIProvider.from_config(pcfg), str(entry.get("name", ""))

        raise RuntimeError("No model with image_generation=true is configured")

    @staticmethod
    def _parse_default_spec(spec: str) -> tuple[str | None, str]:
        if "/" in spec:
            p, m = spec.split("/", 1)
            return p.strip(), m.strip()
        return None, spec.strip()

    @staticmethod
    def _data_url(path: Path) -> str:
        encoded = base64.b64encode(path.read_bytes()).decode("ascii")
        mime = mimetypes.guess_type(str(path))[0] or "image/png"
        return f"data:{mime};base64,{encoded}"

    def run(self, arguments: dict) -> str:
        prompt = str(arguments.get("prompt", "")).strip()
        if not prompt:
            return "Image generation error: prompt is required."

        config = self._load_config()
        provider, model = self._resolve_provider_and_model(config)

        base_url = str(provider.config.get("base_url", "")).rstrip("/")
        http = HttpClient(provider.config.get("network_mode", "auto"))
        headers = {"Authorization": f"Bearer {provider.config.get('api_key', '')}"}
        image_path = str(arguments.get("image_path", "")).strip()
        source = Path(image_path).expanduser().resolve() if image_path else None
        if source and not source.is_file():
            return f"Image generation error: file not found: {source}"
        try:
            if source:
                mime = mimetypes.guess_type(str(source))[0] or "image/png"
                data = {"model": model, "prompt": prompt, "size": "1024x1024"}
                with source.open("rb") as image_file:
                    files = {"image": (source.name, image_file, mime)}
                    response = http.post(f"{base_url}/images/edits", headers=headers, data=data, files=files, timeout=(8, 300))
            else:
                response = http.post(
                    f"{base_url}/images/generations",
                    headers={**headers, "Content-Type": "application/json"},
                    json={"model": model, "prompt": prompt, "size": "1024x1024"},
                    timeout=(8, 300),
                )
            response.raise_for_status()
            entries = (response.json().get("data") or [])
            if not entries:
                raise RuntimeError("image provider returned no image data")
            item = entries[0]
            url = item.get("url") or (f"data:image/png;base64,{item['b64_json']}" if item.get("b64_json") else "")
            if not url:
                raise RuntimeError("image provider returned neither url nor b64_json")
            media_dir = self.project_root / "media" / "generated"
            media_dir.mkdir(parents=True, exist_ok=True)
            output = media_dir / f"image_{uuid.uuid4().hex}.png"
            if url.startswith("data:"):
                output.write_bytes(base64.b64decode(url.split(",", 1)[1]))
            else:
                download = http.get(url, timeout=(8, 120))
                download.raise_for_status()
                output.write_bytes(download.content)
            artifact = json.dumps({
                "path": str(output.resolve()),
                "filename": output.name,
                "operation": "edit" if source else "generate",
            }, ensure_ascii=False)
            return f"__GENERATED_IMAGE__:{artifact}\n__IMAGE_PATH__:{output.resolve()}"
        except Exception as error:
            return f"Image generation error: {error}"


class ToolManager:
    """Discovers and instantiates BaseTool implementations from a directory."""

    def __init__(self, tools_dir: str):
        self.tools_dir = Path(tools_dir).resolve()
        self.project_root = self.tools_dir.parent
        self.registry = _ToolRegistry(str(self.tools_dir))

    def _load_module(self, path: Path):
        module_name = f"tools.{path.stem}"
        importlib.invalidate_caches()
        sys.modules.pop(module_name, None)
        spec = importlib.util.spec_from_file_location(module_name, path)
        if spec is None or spec.loader is None:
            raise ImportError(f"Could not create module spec for {path}")
        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        spec.loader.exec_module(module)
        return module

    def load_tools(self) -> dict[str, BaseTool]:
        tools: dict[str, BaseTool] = {"image_generator": ImageGenerationTool(self.project_root)}
        for path in sorted(self.tools_dir.glob("*.py")):
            if path.name == "base.py" or path.name.startswith("_"):
                continue
            try:
                module = self._load_module(path)
                candidates = []
                for value in vars(module).values():
                    if (
                        isinstance(value, type)
                        and issubclass(value, BaseTool)
                        and value is not BaseTool
                        and value.__module__ == module.__name__
                    ):
                        candidates.append(value)
                for tool_class in candidates:
                    tool = tool_class()
                    tools[tool.tool_name] = tool
            except Exception as error:
                print(f"Warning: failed to load tool {path.name}: {error}", file=sys.stderr)
        self.registry.refresh(tools)
        return tools
