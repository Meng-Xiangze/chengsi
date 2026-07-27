"""Windows clipboard compatibility shim for Chengsi's desktop UI."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path


def _native_clipboard_image():
    from PIL import Image, ImageGrab

    value = ImageGrab.grabclipboard()
    return value if isinstance(value, Image.Image) else None


def _save_image(image, project_root: str, session_id: str = "") -> str:
    media_dir = Path(project_root) / "media" / (session_id or "clipboard")
    media_dir.mkdir(parents=True, exist_ok=True)
    target = media_dir / f"{datetime.now():%Y%m%d_%H%M%S_%f}_clipboard.png"
    image.save(target, format="PNG")
    return str(target.resolve())


def install(app_module) -> None:
    """Add native screenshot fallback without changing Chengsi's core API."""
    original = app_module.WebAPI.get_clipboard_files

    def get_clipboard_files(self):
        result = original(self)
        if result.get("status") == "ok" and result.get("paths"):
            return result

        image = None
        try:
            image = _native_clipboard_image()
            if image is None:
                return result
            path = _save_image(
                image,
                app_module.PROJECT_ROOT,
                app_module.state.current_session_id,
            )
            return {"status": "ok", "paths": [path]}
        except Exception as exc:
            if result.get("status") == "error":
                return result
            return {"status": "error", "msg": f"Could not read clipboard image: {exc}"}
        finally:
            if image is not None:
                image.close()

    app_module.WebAPI.get_clipboard_files = get_clipboard_files
