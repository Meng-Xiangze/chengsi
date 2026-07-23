import base64
import html
import json
import mimetypes
import os
from datetime import datetime
from pathlib import Path

from tools.base import BaseTool

PROJECT_ROOT = Path(__file__).resolve().parent.parent


class ChatExporter(BaseTool):
    @property
    def tool_name(self) -> str:
        return "chat_exporter"

    @property
    def description(self) -> str:
        return "Export a chat session as a standalone HTML file with embedded images. Provide the session_id."

    @property
    def parameters(self) -> dict:
        return {
            "session_id": {
                "type": "string",
                "description": "Session ID to export (e.g. '20260721_213533_9933c4').",
            }
        }

    @staticmethod
    def _image_data_url(source: str) -> str:
        """Return a self-contained data URL for an on-disk generated image."""
        if not source:
            return ""
        try:
            source = source.removeprefix("file:///").replace("/", os.sep)
            image_path = Path(source)
            if not image_path.is_absolute():
                image_path = PROJECT_ROOT / image_path
            image_path = image_path.resolve()
            media_root = (PROJECT_ROOT / "media").resolve()
            if not image_path.is_file() or media_root not in image_path.parents:
                return ""
            mime_type = mimetypes.guess_type(image_path.name)[0] or "image/png"
            encoded = base64.b64encode(image_path.read_bytes()).decode("ascii")
            return f"data:{mime_type};base64,{encoded}"
        except (OSError, ValueError):
            return ""

    @staticmethod
    def _text_block(value) -> str:
        return f'<div class="message-text">{html.escape(str(value))}</div>'

    def _event_html(self, event: dict) -> str:
        event_type = event.get("type", "")
        data = event.get("data", "")

        if event_type == "user":
            return (
                '<article class="message user-message">'
                '<div class="message-label">You</div>'
                f"{self._text_block(data)}"
                "</article>"
            )

        if event_type == "agent_done":
            return (
                '<article class="message assistant-message">'
                '<div class="message-label">Chengsi</div>'
                f"{self._text_block(data)}"
                "</article>"
            )

        if event_type == "image" and isinstance(data, dict):
            image_url = self._image_data_url(data.get("path") or data.get("url", ""))
            caption = data.get("revised_prompt") or data.get("text") or "Generated image"
            image_html = (
                f'<img class="generated-image" src="{image_url}" alt="Generated image">'
                if image_url
                else '<div class="image-missing">Generated image is no longer available.</div>'
            )
            return (
                '<article class="message assistant-message image-message">'
                '<div class="message-label">Chengsi</div>'
                f'<div class="image-frame">{image_html}</div>'
                f'<div class="image-caption">{html.escape(str(caption))}</div>'
                "</article>"
            )

        if event_type == "tool_call":
            name = data if isinstance(data, str) else data.get("action", "tool")
            arguments = data if isinstance(data, str) else data.get("arguments", {})
            details = json.dumps(arguments, ensure_ascii=False, indent=2) if isinstance(arguments, dict) else str(arguments)
            return (
                '<details class="tool-message"><summary>Tool call: '
                f"{html.escape(str(name))}</summary><pre>{html.escape(details)}</pre></details>"
            )

        if event_type == "tool_result":
            return (
                '<details class="tool-message"><summary>Tool result</summary>'
                f"<pre>{html.escape(str(data)[:4000])}</pre></details>"
            )

        return ""

    def _format_html(self, history: list[dict], title: str, session_id: str) -> str:
        messages = "\n".join(self._event_html(event) for event in history)
        escaped_title = html.escape(title)
        exported_at = datetime.now().strftime("%Y-%m-%d %H:%M")
        return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{escaped_title} - Chengsi</title>
<style>
:root {{ --bg:#ffffff; --surface:#f7f8fa; --surface-alt:#f1f5f9; --border:#dce2e8; --text:#172033; --dim:#64748b; --blue:#1677e8; --cyan:#11aee8; }}
* {{ box-sizing:border-box; }}
body {{ margin:0; background:var(--bg); color:var(--text); font:14px/1.6 system-ui,-apple-system,"Segoe UI",sans-serif; }}
header {{ border-bottom:1px solid var(--border); background:#fff; }}
.header-inner {{ max-width:960px; margin:0 auto; padding:18px 24px; display:flex; align-items:center; gap:12px; }}
.mark {{ width:28px; height:28px; border-radius:7px; display:grid; place-items:center; color:#fff; font-weight:800; background:linear-gradient(135deg,var(--blue),var(--cyan)); }}
.brand {{ font-weight:700; }}
.session-title {{ color:var(--dim); overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }}
main {{ max-width:840px; margin:0 auto; padding:30px 24px 48px; }}
.message {{ max-width:720px; margin:0 0 22px; }}
.message-label {{ margin:0 0 6px; color:var(--dim); font-size:12px; font-weight:650; }}
.message-text {{ white-space:pre-wrap; overflow-wrap:anywhere; padding:13px 16px; border:1px solid var(--border); border-radius:8px; background:var(--surface); }}
.user-message {{ margin-left:auto; }}
.user-message .message-label {{ text-align:right; }}
.user-message .message-text {{ background:#eaf4ff; border-color:#c9e1fb; }}
.assistant-message .message-text {{ background:#fff; }}
.image-message {{ max-width:640px; }}
.image-frame {{ padding:8px; border:1px solid var(--border); border-radius:8px; background:#fff; }}
.generated-image {{ display:block; width:100%; height:auto; border-radius:5px; }}
.image-caption {{ margin-top:8px; color:var(--dim); font-size:12px; white-space:pre-wrap; overflow-wrap:anywhere; }}
.image-missing {{ padding:28px; color:var(--dim); text-align:center; background:var(--surface); border-radius:5px; }}
.tool-message {{ max-width:720px; margin:0 0 14px; border:1px solid var(--border); border-radius:7px; background:var(--surface); color:var(--dim); }}
.tool-message summary {{ padding:9px 12px; cursor:pointer; font-size:12px; }}
pre {{ margin:0; padding:0 12px 12px; white-space:pre-wrap; overflow-wrap:anywhere; font:12px/1.5 ui-monospace,SFMono-Regular,Consolas,monospace; }}
footer {{ border-top:1px solid var(--border); color:var(--dim); font-size:12px; }}
.footer-inner {{ max-width:960px; margin:0 auto; padding:14px 24px; }}
@media (max-width:600px) {{ main {{ padding:20px 14px 32px; }} .header-inner {{ padding:14px; }} .message {{ max-width:100%; }} }}
</style>
</head>
<body>
<header><div class="header-inner"><div class="mark">CS</div><div class="brand">Chengsi</div><div class="session-title">{escaped_title}</div></div></header>
<main>{messages}</main>
<footer><div class="footer-inner">Exported {exported_at} · Session {html.escape(session_id)}</div></footer>
</body>
</html>"""

    def run(self, arguments: dict) -> str:
        session_id = arguments.get("session_id", "").strip()
        if not session_id:
            return "Error: session_id is required."

        session_path = PROJECT_ROOT / "sessions" / f"{session_id}.json"
        if not session_path.is_file():
            return f"Error: Session '{session_id}' not found."

        try:
            session = json.loads(session_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            return f"Error reading session: {exc}"

        return self._format_html(session.get("history", []), session.get("title", session_id), session_id)
