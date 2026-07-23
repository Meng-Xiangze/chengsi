# -*- coding: utf-8 -*-
import os
import base64
import mimetypes
from typing import Any, Dict

from tools.base import BaseTool

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
_SUPPORTED_EXT = {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp", ".tiff", ".tif"}


class ImageReader(BaseTool):
    """Read and analyze images on disk. Returns metadata and file path for
    multimodal models to process. The agent loop auto-injects the image
    as multimodal content so the model can actually see it."""

    @property
    def tool_name(self) -> str:
        return "image_reader"

    @property
    def description(self) -> str:
        return (
            "Read an image file from disk. Returns metadata (format, size, dimensions) "
            "and the image path. The system automatically passes the image to the model "
            "for visual analysis. Use this when the user asks to view, analyze, describe, "
            "or read an image, screenshot, photo, or diagram."
        )

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "path": {
                "type": "string",
                "description": "Absolute or relative path to the image file.",
            },
            "action": {
                "type": "string",
                "description": "read (default) or info (metadata only, no image injection).",
            },
        }

    def run(self, arguments: dict) -> str:
        raw_path = arguments.get("path", "")
        if not raw_path:
            return "Error: path is required."

        action = str(arguments.get("action", "read")).strip().lower()

        # Resolve path
        if os.path.isabs(raw_path):
            img_path = raw_path
        else:
            img_path = os.path.abspath(os.path.join(PROJECT_ROOT, raw_path))

        if not os.path.isfile(img_path):
            return f"Error: file not found: {img_path}"

        ext = os.path.splitext(img_path)[1].lower()
        if ext not in _SUPPORTED_EXT:
            return (
                f"Error: unsupported image format '{ext}'. "
                f"Supported: {', '.join(sorted(_SUPPORTED_EXT))}"
            )

        file_size = os.path.getsize(img_path)
        mime, _ = mimetypes.guess_type(img_path)
        if not mime:
            mime = "application/octet-stream"

        dimensions = self._get_dimensions(img_path)

        meta_lines = [
            f"File: {os.path.relpath(img_path, PROJECT_ROOT) if img_path.startswith(PROJECT_ROOT) else img_path}",
            f"Format: {ext.lstrip('.').upper()}",
            f"MIME: {mime}",
            f"Size: {file_size:,} bytes ({file_size / 1024:.1f} KB)",
        ]
        if dimensions:
            meta_lines.append(f"Dimensions: {dimensions[0]}x{dimensions[1]} px")

        if action == "info":
            return "\n".join(meta_lines)

        # read action: return metadata + special marker.
        # The agent loop in main.py detects __IMAGE_PATH__ and injects
        # the actual base64 as multimodal content to the model.
        meta = "\n".join(meta_lines)
        return f"{meta}\n__IMAGE_PATH__:{img_path}"

    @staticmethod
    def _get_dimensions(path: str):
        """Return (width, height) if PIL is available, else parse PNG header."""
        try:
            from PIL import Image
            with Image.open(path) as img:
                return img.size
        except ImportError:
            pass
        except Exception:
            pass
        try:
            with open(path, "rb") as f:
                header = f.read(32)
            if header[:8] == b"\x89PNG\r\n\x1a\n":
                import struct
                w = struct.unpack(">I", header[16:20])[0]
                h = struct.unpack(">I", header[20:24])[0]
                return (w, h)
        except Exception:
            pass
        return None
