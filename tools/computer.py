# -*- coding: utf-8 -*-
"""Windows desktop observation and input control."""
from __future__ import annotations

import os
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from tools.base import BaseTool
from core.process_utils import optional_import

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SCREENSHOT_DIR = PROJECT_ROOT / "media" / "computer"


class Computer(BaseTool):
    """Observe the desktop and control mouse, keyboard, and top-level windows."""

    @property
    def tool_name(self) -> str:
        return "computer"

    @property
    def description(self) -> str:
        return (
            "Operate Windows through UI Automation first. Start with windows, activate the target, "
            "inspect controls, then use focus_control, invoke, or set_value. Use coordinate mouse "
            "actions only when the application exposes no usable controls, and verify with a screenshot. "
            "Coordinates use physical screen pixels. A blue border shows active control; Esc "
            "cancels and requires asking the user what to do next. Available on Windows only."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "action": {
                "type": "string",
                "enum": [
                    "screenshot", "screen_size", "position", "windows", "activate_window",
                    "controls", "inspect_control", "read_control", "focus_control",
                    "invoke", "set_value", "toggle", "select", "expand", "collapse",
                    "scroll_into_view", "window_state",
                    "move", "click", "double_click", "right_click", "drag", "scroll",
                    "type", "key", "hotkey", "key_down", "key_up", "wait", "sequence",
                ],
                "description": "Desktop operation to perform.",
            },
            "x": {"type": "integer", "description": "Screen x coordinate in pixels."},
            "y": {"type": "integer", "description": "Screen y coordinate in pixels."},
            "to_x": {"type": "integer", "description": "Drag destination x coordinate."},
            "to_y": {"type": "integer", "description": "Drag destination y coordinate."},
            "text": {"type": "string", "description": "Text to type, key name, window query, or control query."},
            "window": {"type": "string", "description": "Distinctive window title fragment for UI Automation."},
            "handle": {"type": "integer", "description": "Preferred exact window handle returned by windows."},
            "control_type": {"type": "string", "description": "Optional UI Automation type. Use text for Edit or Document controls."},
            "automation_id": {"type": "string", "description": "Exact UI Automation ID; preferred over a fuzzy text query."},
            "match": {"type": "string", "enum": ["contains", "exact"], "description": "Text matching mode; defaults to contains."},
            "index": {"type": "integer", "description": "Zero-based match index from the current controls result."},
            "value": {"type": "string", "description": "Value for set_value or state for window_state: minimize, maximize, or restore."},
            "keys": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Keys for hotkey, for example [\"ctrl\", \"s\"].",
            },
            "amount": {"type": "integer", "description": "Scroll clicks; positive scrolls up, negative down."},
            "seconds": {"type": "number", "description": "Duration for move, drag, wait, or typing interval."},
            "button": {"type": "string", "enum": ["left", "middle", "right"], "description": "Mouse button."},
            "region": {
                "type": "array",
                "items": {"type": "integer"},
                "description": "Screenshot region [left, top, width, height]. Omit for the full virtual desktop.",
            },
            "steps": {
                "type": "array",
                "items": {"type": "object"},
                "description": "For action=sequence, 1-20 ordered computer action objects. Use this to combine deterministic click/type/key/wait steps in one call.",
            },
        }

    @staticmethod
    def _pyautogui():
        if os.name != "nt":
            raise RuntimeError("computer is available on Windows only")
        try:
            pyautogui = optional_import("pyautogui")
        except ImportError as error:
            raise RuntimeError(
                "computer requires PyAutoGUI. Install it with: python -m pip install pyautogui"
            ) from error
        pyautogui.FAILSAFE = True
        pyautogui.PAUSE = 0.08
        return pyautogui

    @staticmethod
    def _integer(arguments: dict[str, Any], name: str) -> int:
        if name not in arguments:
            raise ValueError(f"{name} is required")
        return int(arguments[name])

    @staticmethod
    def _duration(arguments: dict[str, Any], default: float = 0.0, maximum: float = 30.0) -> float:
        return max(0.0, min(float(arguments.get("seconds", default)), maximum))

    @staticmethod
    def _virtual_screen_bounds() -> tuple[int, int, int, int]:
        import win32api
        import win32con
        left = win32api.GetSystemMetrics(win32con.SM_XVIRTUALSCREEN)
        top = win32api.GetSystemMetrics(win32con.SM_YVIRTUALSCREEN)
        width = win32api.GetSystemMetrics(win32con.SM_CXVIRTUALSCREEN)
        height = win32api.GetSystemMetrics(win32con.SM_CYVIRTUALSCREEN)
        return left, top, left + width, top + height

    @classmethod
    def _point(cls, arguments: dict[str, Any], x_name: str = "x", y_name: str = "y") -> tuple[int, int]:
        x, y = cls._integer(arguments, x_name), cls._integer(arguments, y_name)
        left, top, right, bottom = cls._virtual_screen_bounds()
        if not left <= x < right or not top <= y < bottom:
            raise ValueError(
                f"({x}, {y}) is outside the virtual desktop "
                f"[{left}, {top}, {right - left}, {bottom - top}]"
            )
        return x, y

    @staticmethod
    def _paste_text(gui, text: str) -> None:
        """Paste Unicode text while restoring the user's text clipboard."""
        try:
            import win32clipboard
            import win32con
        except ImportError as error:
            raise RuntimeError("Unicode typing requires pywin32") from error

        previous_text = None
        had_text = False
        win32clipboard.OpenClipboard()
        try:
            if win32clipboard.IsClipboardFormatAvailable(win32con.CF_UNICODETEXT):
                previous_text = win32clipboard.GetClipboardData(win32con.CF_UNICODETEXT)
                had_text = True
            win32clipboard.EmptyClipboard()
            win32clipboard.SetClipboardText(text, win32con.CF_UNICODETEXT)
        finally:
            win32clipboard.CloseClipboard()

        try:
            gui.hotkey("ctrl", "v")
            time.sleep(0.08)
        finally:
            win32clipboard.OpenClipboard()
            try:
                win32clipboard.EmptyClipboard()
                if had_text:
                    win32clipboard.SetClipboardText(previous_text or "", win32con.CF_UNICODETEXT)
            finally:
                win32clipboard.CloseClipboard()

    @staticmethod
    def _normalize_key(key: Any) -> str:
        value = str(key).strip().lower().replace("_", "").replace("-", "")
        aliases = {
            "return": "enter", "del": "delete", "ins": "insert",
            "pgup": "pageup", "prior": "pageup", "pgdn": "pagedown", "next": "pagedown",
            "bksp": "backspace", "back": "backspace", "spacebar": "space",
            "control": "ctrl", "ctl": "ctrl", "windows": "win", "super": "win",
            "leftarrow": "left", "arrowleft": "left", "rightarrow": "right", "arrowright": "right",
            "uparrow": "up", "arrowup": "up", "downarrow": "down", "arrowdown": "down",
            "esc": "escape", "prtsc": "printscreen", "prtscr": "printscreen", "prntscrn": "printscreen",
        }
        return aliases.get(value, value)

    @staticmethod
    def _virtual_key(key: str) -> int:
        import ctypes
        vk_names = {
            "backspace": 0x08, "tab": 0x09, "enter": 0x0D, "shift": 0x10,
            "ctrl": 0x11, "alt": 0x12, "pause": 0x13, "capslock": 0x14,
            "escape": 0x1B, "space": 0x20, "pageup": 0x21, "pagedown": 0x22,
            "end": 0x23, "home": 0x24, "left": 0x25, "up": 0x26,
            "right": 0x27, "down": 0x28, "printscreen": 0x2C, "insert": 0x2D,
            "delete": 0x2E, "win": 0x5B, "apps": 0x5D, "numlock": 0x90,
            "scrolllock": 0x91, "volumemute": 0xAD, "volumedown": 0xAE, "volumeup": 0xAF,
            "nexttrack": 0xB0, "prevtrack": 0xB1, "stop": 0xB2, "playpause": 0xB3,
        }
        for number in range(1, 25):
            vk_names[f"f{number}"] = 0x6F + number
        vk = vk_names.get(key)
        if vk is None and len(key) == 1:
            vk = ctypes.windll.user32.VkKeyScanW(ord(key)) & 0xFF
        if not vk or vk == 0xFF:
            raise ValueError(f"unsupported key: {key}")
        return vk

    @classmethod
    def _send_keys(cls, keys: list[str], release: bool = True, key_up_only: bool = False) -> None:
        import ctypes
        from ctypes import wintypes
        user32 = ctypes.windll.user32
        ulong_ptr = wintypes.WPARAM
        class MOUSEINPUT(ctypes.Structure):
            _fields_ = [("dx", wintypes.LONG), ("dy", wintypes.LONG), ("mouseData", wintypes.DWORD), ("dwFlags", wintypes.DWORD), ("time", wintypes.DWORD), ("dwExtraInfo", ulong_ptr)]
        class KEYBDINPUT(ctypes.Structure):
            _fields_ = [("wVk", wintypes.WORD), ("wScan", wintypes.WORD), ("dwFlags", wintypes.DWORD), ("time", wintypes.DWORD), ("dwExtraInfo", ulong_ptr)]
        class HARDWAREINPUT(ctypes.Structure):
            _fields_ = [("uMsg", wintypes.DWORD), ("wParamL", wintypes.WORD), ("wParamH", wintypes.WORD)]
        class INPUT_UNION(ctypes.Union):
            _fields_ = [("mi", MOUSEINPUT), ("ki", KEYBDINPUT), ("hi", HARDWAREINPUT)]
        class INPUT(ctypes.Structure):
            _fields_ = [("type", wintypes.DWORD), ("union", INPUT_UNION)]
        events = []
        ordered = list(reversed(keys)) if key_up_only else keys + (list(reversed(keys)) if release else [])
        for position, key in enumerate(ordered):
            vk = cls._virtual_key(key)
            key_up = key_up_only or (release and position >= len(keys))
            flags = 0x0002 if key_up else 0
            events.append(INPUT(1, INPUT_UNION(ki=KEYBDINPUT(vk, 0, flags, 0, 0))))
        array = (INPUT * len(events))(*events)
        sent = user32.SendInput(len(events), array, ctypes.sizeof(INPUT))
        if sent != len(events):
            raise RuntimeError(f"SendInput sent {sent} of {len(events)} keyboard events")

    @staticmethod
    def _uia_controls(arguments: dict[str, Any]):
        try:
            from pywinauto import Desktop
        except ImportError as error:
            raise RuntimeError("UI Automation requires pywinauto. Install dependencies from requirements.txt") from error
        window_query = str(arguments.get("window", "")).strip()
        raw_handle = arguments.get("handle")
        if raw_handle is None and not window_query:
            raise ValueError("handle or window is required for UI Automation")
        desktop = Desktop(backend="uia")
        if raw_handle is not None:
            handle = int(raw_handle)
            windows = [item for item in desktop.windows() if int(item.handle) == handle]
        else:
            windows = [item for item in desktop.windows() if window_query.casefold() in item.window_text().casefold()]
        if len(windows) != 1:
            titles = [item.window_text() for item in windows[:20]]
            raise ValueError(f"window query matched {len(windows)} windows: {titles}")
        root = windows[0]
        query = str(arguments.get("text", "")).strip().casefold()
        automation_id_query = str(arguments.get("automation_id", "")).strip().casefold()
        exact = str(arguments.get("match", "contains")).strip().lower() == "exact"
        control_type = str(arguments.get("control_type", "")).strip().casefold()
        accepted_types = {"edit", "document"} if control_type in {"text", "textbox", "textinput"} else ({control_type} if control_type else set())
        matches = []
        for control in root.descendants():
            info = control.element_info
            name = str(getattr(info, "name", "") or control.window_text())
            kind = str(getattr(info, "control_type", ""))
            automation_id = str(getattr(info, "automation_id", ""))
            if query:
                candidates = (name.casefold(), automation_id.casefold())
                if exact and query not in candidates:
                    continue
                if not exact and not any(query in candidate for candidate in candidates):
                    continue
            if automation_id_query and automation_id.casefold() != automation_id_query:
                continue
            if accepted_types and kind.casefold() not in accepted_types:
                continue
            matches.append((control, name, kind, automation_id))
        return root, matches

    @staticmethod
    def _pattern_names(control) -> list[str]:
        patterns = []
        for name, attribute in (
            ("invoke", "iface_invoke"), ("value", "iface_value"), ("toggle", "iface_toggle"),
            ("select", "iface_selection_item"), ("expand", "iface_expand_collapse"),
            ("scroll_item", "iface_scroll_item"), ("range_value", "iface_range_value"),
        ):
            try:
                if getattr(control, attribute) is not None:
                    patterns.append(name)
            except Exception:
                pass
        # Base UIAWrapper exposes select/expand/collapse callables on every
        # control, so only trust them on specialized wrappers (e.g. ComboBox).
        from pywinauto.controls.uiawrapper import UIAWrapper
        if type(control) is UIAWrapper:
            return patterns
        for name, method in (("select_value", "select"), ("expand_wrapper", "expand"), ("collapse_wrapper", "collapse")):
            if callable(getattr(control, method, None)) and name not in patterns:
                patterns.append(name)
        return patterns

    @classmethod
    def _control_snapshot(cls, control, name: str, kind: str, automation_id: str) -> dict[str, Any]:
        info = control.element_info
        try:
            rect = control.rectangle()
            rectangle = [rect.left, rect.top, rect.right, rect.bottom]
        except Exception:
            rectangle = []
        snapshot: dict[str, Any] = {
            "type": kind or "Control",
            "name": name,
            "automation_id": automation_id,
            "rect": rectangle,
            "enabled": bool(getattr(info, "enabled", False)),
            "visible": bool(getattr(info, "visible", False)),
            "patterns": cls._pattern_names(control),
        }
        try:
            snapshot["value"] = str(control.iface_value.CurrentValue)
        except Exception:
            pass
        try:
            snapshot["toggle_state"] = int(control.iface_toggle.CurrentToggleState)
        except Exception:
            pass
        try:
            snapshot["selected"] = bool(control.iface_selection_item.CurrentIsSelected)
        except Exception:
            pass
        try:
            snapshot["expand_state"] = int(control.iface_expand_collapse.CurrentExpandCollapseState)
        except Exception:
            pass
        return snapshot

    @staticmethod
    def _windows() -> list[dict[str, Any]]:
        try:
            import win32gui
        except ImportError as error:
            raise RuntimeError("window operations require pywin32") from error

        windows: list[dict[str, Any]] = []

        def collect(hwnd, _extra):
            if not win32gui.IsWindowVisible(hwnd):
                return
            title = win32gui.GetWindowText(hwnd).strip()
            if not title or title.startswith("ChengsiComputerOverlay"):
                return
            left, top, right, bottom = win32gui.GetWindowRect(hwnd)
            windows.append({
                "handle": hwnd,
                "title": title,
                "rect": [left, top, right, bottom],
            })

        win32gui.EnumWindows(collect, None)
        return windows

    def _screenshot(self, arguments: dict[str, Any]) -> str:
        if os.name != "nt":
            raise RuntimeError("computer is available on Windows only")
        from PIL import ImageGrab
        left, top, right, bottom = self._virtual_screen_bounds()
        raw_region = arguments.get("region")
        if raw_region is None:
            capture_box = (left, top, right, bottom)
        else:
            if not isinstance(raw_region, list) or len(raw_region) != 4:
                raise ValueError("region must be [left, top, width, height]")
            region_left, region_top, width, height = (int(value) for value in raw_region)
            if width <= 0 or height <= 0:
                raise ValueError("region width and height must be positive")
            capture_box = (region_left, region_top, region_left + width, region_top + height)
            if capture_box[0] < left or capture_box[1] < top or capture_box[2] > right or capture_box[3] > bottom:
                raise ValueError(f"region is outside the virtual desktop [{left}, {top}, {right - left}, {bottom - top}]")
        SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)
        path = SCREENSHOT_DIR / f"screen_{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}.png"
        image = ImageGrab.grab(bbox=capture_box, all_screens=True)
        image.save(path)
        width, height = image.size
        return (
            f"Screenshot captured: {width}x{height} pixels; screen origin "
            f"({capture_box[0]}, {capture_box[1]})\n__IMAGE_PATH__:{path.resolve()}"
        )

    @staticmethod
    def _cancelled(arguments: dict[str, Any]) -> bool:
        try:
            from core.computer_overlay import is_cancelled
            return is_cancelled(str(arguments.get("_session_id", "")))
        except Exception:
            return False

    def run(self, arguments: dict[str, Any]) -> str | dict[str, Any]:
        arguments = arguments or {}
        action = str(arguments.get("action", "")).strip().lower()
        if not action:
            return {"ok": False, "content": "action is required", "error_code": "invalid_arguments"}

        try:
            if self._cancelled(arguments):
                return {
                    "ok": False,
                    "content": "The user pressed Esc and cancelled computer control.",
                    "error_code": "user_cancelled",
                }
            if action == "sequence":
                steps = arguments.get("steps")
                if not isinstance(steps, list) or not 1 <= len(steps) <= 20:
                    raise ValueError("steps must contain 1-20 action objects")
                results = []
                for index, step in enumerate(steps, 1):
                    if isinstance(step, str):
                        try:
                            import json
                            step = json.loads(step)
                        except (ValueError, TypeError, json.JSONDecodeError):
                            raise ValueError(
                                f"step {index} must be an object, not a string. "
                                "Pass steps as JSON objects without quoting them."
                            )
                    if not isinstance(step, dict):
                        raise ValueError(f"step {index} must be an object")
                    nested_action = str(step.get("action", "")).strip().lower()
                    if nested_action in {"", "sequence", "screenshot", "windows"}:
                        raise ValueError(f"step {index} has unsupported sequence action: {nested_action or '(empty)'}")
                    nested = dict(step)
                    nested["_session_id"] = arguments.get("_session_id", "")
                    result = self.run(nested)
                    outcome = result if isinstance(result, dict) else {"ok": True, "content": str(result)}
                    if outcome.get("ok") is False:
                        return {
                            "ok": False,
                            "content": f"Sequence stopped at step {index} ({nested_action}): {outcome.get('content', '')}",
                            "error_code": outcome.get("error_code", "tool_error"),
                        }
                    results.append(f"{index}. {nested_action}: {outcome.get('content', result)}")
                return "Sequence completed:\n" + "\n".join(results)
            if action == "screenshot":
                return self._screenshot(arguments)
            if action == "windows":
                windows = self._windows()
                lines = [
                    f"{item['handle']} | {item['rect']} | {item['title']}"
                    for item in windows[:100]
                ]
                return f"Visible windows ({len(windows)}):\n" + ("\n".join(lines) or "(none)")
            if action in {"controls", "inspect_control", "read_control", "focus_control", "invoke", "set_value", "toggle", "select", "expand", "collapse", "scroll_into_view"}:
                _root, matches = self._uia_controls(arguments)
                if action == "controls":
                    lines = []
                    for index, (control, name, kind, automation_id) in enumerate(matches[:200]):
                        snapshot = self._control_snapshot(control, name, kind, automation_id)
                        lines.append(
                            f"{index} | {snapshot['type']} | {snapshot['name'] or '(unnamed)'} | "
                            f"id={snapshot['automation_id'] or '-'} | rect={snapshot['rect']} | "
                            f"enabled={snapshot['enabled']} visible={snapshot['visible']} | "
                            f"patterns={','.join(snapshot['patterns']) or '-'}"
                        )
                    return f"UI Automation controls ({len(matches)} matches):\n" + ("\n".join(lines) or "(none)")
                if not matches:
                    return {"ok": False, "content": "No matching UI Automation control", "error_code": "not_found"}
                index = int(arguments.get("index", 0))
                if not 0 <= index < len(matches):
                    raise ValueError(f"index must be between 0 and {len(matches) - 1}")
                if len(matches) > 1 and "index" not in arguments:
                    preview = "\n".join(f"{i}. {kind} | {name} | {automation_id or '-'}" for i, (_control, name, kind, automation_id) in enumerate(matches[:20]))
                    return {"ok": False, "content": f"Control query is ambiguous ({len(matches)} matches); provide index:\n{preview}", "error_code": "ambiguous"}
                control, name, kind, automation_id = matches[index]
                if action in {"inspect_control", "read_control"}:
                    snapshot = self._control_snapshot(control, name, kind, automation_id)
                    return {"ok": True, "content": str(snapshot), "control": snapshot}
                if action == "scroll_into_view":
                    try:
                        control.iface_scroll_item.ScrollIntoView()
                    except Exception as error:
                        return {"ok": False, "content": f"Control does not support ScrollItem: {error}", "error_code": "unsupported_control_pattern"}
                    return f"Scrolled control into view: {kind} | {name or automation_id}"
                control.set_focus()
                if action == "focus_control":
                    return f"Focused control: {kind} | {name or automation_id}"
                if action == "invoke":
                    try:
                        control.invoke()
                    except Exception as error:
                        return {
                            "ok": False,
                            "content": f"Control does not expose the UI Automation Invoke pattern: {error}",
                            "error_code": "unsupported_control_pattern",
                        }
                    return f"Invoked control: {kind} | {name or automation_id}"
                if action == "toggle":
                    try:
                        before = int(control.iface_toggle.CurrentToggleState)
                        control.iface_toggle.Toggle()
                        after = int(control.iface_toggle.CurrentToggleState)
                    except Exception as error:
                        return {"ok": False, "content": f"Control does not support Toggle: {error}", "error_code": "unsupported_control_pattern"}
                    return f"Toggled control: {kind} | {name or automation_id} ({before} -> {after})"
                if action == "select":
                    requested_value = arguments.get("value", arguments.get("text"))
                    try:
                        if requested_value is not None and callable(getattr(control, "select", None)):
                            control.select(str(requested_value))
                            return f"Selected value: {kind} | {name or automation_id} = {requested_value}"
                        control.iface_selection_item.Select()
                        selected = bool(control.iface_selection_item.CurrentIsSelected)
                    except Exception as error:
                        return {"ok": False, "content": f"Control does not support selecting this item or value: {error}", "error_code": "unsupported_control_pattern"}
                    return f"Selected control: {kind} | {name or automation_id}; selected={selected}"
                if action in {"expand", "collapse"}:
                    try:
                        pattern = control.iface_expand_collapse
                        before = int(pattern.CurrentExpandCollapseState)
                        pattern.Expand() if action == "expand" else pattern.Collapse()
                        after = int(pattern.CurrentExpandCollapseState)
                        return f"{action.title()}ed control: {kind} | {name or automation_id} ({before} -> {after})"
                    except Exception as pattern_error:
                        method = getattr(control, action, None)
                        if not callable(method):
                            return {"ok": False, "content": f"Control does not support ExpandCollapse: {pattern_error}", "error_code": "unsupported_control_pattern"}
                        try:
                            method()
                        except Exception as wrapper_error:
                            return {"ok": False, "content": f"Control could not {action}: {wrapper_error}", "error_code": "unsupported_control_pattern"}
                        return f"{action.title()}ed control through its automation wrapper: {kind} | {name or automation_id}"
                value = str(arguments.get("value", ""))
                errors = []
                updated = False
                try:
                    control.set_edit_text(value)
                    updated = True
                except Exception as error:
                    errors.append(str(error))
                if not updated:
                    try:
                        value_pattern = control.iface_value
                        if value_pattern is None:
                            raise RuntimeError("Value pattern is unavailable")
                        value_pattern.SetValue(value)
                        updated = True
                    except Exception as error:
                        errors.append(str(error))
                if not updated:
                    return {
                        "ok": False,
                        "content": "Control does not support setting a value through UI Automation: " + "; ".join(errors),
                        "error_code": "unsupported_control_pattern",
                    }
                return f"Set control value: {kind} | {name or automation_id} ({len(value)} characters)"
            if action == "window_state":
                raw_handle = arguments.get("handle")
                if raw_handle is None:
                    raise ValueError("handle is required for window_state")
                import win32con
                import win32gui
                hwnd = int(raw_handle)
                if not win32gui.IsWindow(hwnd):
                    return {"ok": False, "content": f"Window handle no longer exists: {hwnd}", "error_code": "not_found"}
                state_name = str(arguments.get("value", "")).strip().lower()
                commands = {"minimize": win32con.SW_MINIMIZE, "maximize": win32con.SW_MAXIMIZE, "restore": win32con.SW_RESTORE}
                if state_name not in commands:
                    raise ValueError("value must be minimize, maximize, or restore")
                win32gui.ShowWindow(hwnd, commands[state_name])
                return f"Window state changed: {state_name} | {win32gui.GetWindowText(hwnd)}"
            if action == "activate_window":
                raw_handle = arguments.get("handle")
                query = str(arguments.get("text", "")).strip().casefold()
                if raw_handle is None and not query:
                    raise ValueError("handle or text is required for activate_window")
                matches = [item for item in self._windows() if item["handle"] == int(raw_handle)] if raw_handle is not None else [item for item in self._windows() if query in item["title"].casefold()]
                if not matches:
                    return {"ok": False, "content": f"No visible window title contains: {query}", "error_code": "not_found"}
                if len(matches) > 1:
                    titles = "\n".join(f"- {item['title']}" for item in matches[:20])
                    return {"ok": False, "content": f"Window query is ambiguous ({len(matches)} matches):\n{titles}", "error_code": "ambiguous"}
                import win32con
                import win32gui
                import win32process
                hwnd = matches[0]["handle"]
                win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
                try:
                    win32gui.SetForegroundWindow(hwnd)
                except Exception:
                    # Attach to the foreground thread instead of clicking the title bar,
                    # which can trigger a close/minimize control on narrow windows.
                    import win32api
                    foreground = win32gui.GetForegroundWindow()
                    current_thread = win32api.GetCurrentThreadId()
                    target_thread = win32process.GetWindowThreadProcessId(hwnd)[0]
                    foreground_thread = win32process.GetWindowThreadProcessId(foreground)[0] if foreground else 0
                    attached = []
                    try:
                        if foreground_thread and foreground_thread != current_thread:
                            win32process.AttachThreadInput(foreground_thread, current_thread, True)
                            attached.append((foreground_thread, current_thread))
                        if target_thread != current_thread:
                            win32process.AttachThreadInput(target_thread, current_thread, True)
                            attached.append((target_thread, current_thread))
                        win32gui.SetForegroundWindow(hwnd)
                    finally:
                        for source_thread, destination_thread in reversed(attached):
                            win32process.AttachThreadInput(source_thread, destination_thread, False)
                return f"Activated window: {matches[0]['title']}"

            gui = self._pyautogui()
            if action == "screen_size":
                left, top, right, bottom = self._virtual_screen_bounds()
                return f"Virtual desktop: origin ({left}, {top}), size {right - left}x{bottom - top} pixels"
            if action == "position":
                point = gui.position()
                return f"Pointer position: ({point.x}, {point.y})"
            if action == "move":
                x, y = self._point(arguments)
                duration = self._duration(arguments)
                if duration <= 0:
                    gui.moveTo(x, y)
                else:
                    start = gui.position()
                    deadline = time.monotonic() + duration
                    while True:
                        if self._cancelled(arguments):
                            return {"ok": False, "content": "The user pressed Esc and cancelled computer control.", "error_code": "user_cancelled"}
                        remaining = deadline - time.monotonic()
                        if remaining <= 0:
                            break
                        fraction = 1.0 - remaining / duration
                        gui.moveTo(round(start.x + (x - start.x) * fraction), round(start.y + (y - start.y) * fraction))
                        time.sleep(min(0.03, remaining))
                    gui.moveTo(x, y)
                return f"Pointer moved to ({x}, {y})"
            if action in {"click", "double_click", "right_click"}:
                x, y = self._point(arguments)
                button = "right" if action == "right_click" else str(arguments.get("button", "left"))
                clicks = 2 if action == "double_click" else 1
                gui.click(x=x, y=y, clicks=clicks, interval=0.12, button=button)
                return f"{action} at ({x}, {y})"
            if action == "drag":
                x, y = self._point(arguments)
                to_x, to_y = self._point(arguments, "to_x", "to_y")
                button = str(arguments.get("button", "left"))
                gui.moveTo(x, y)
                gui.mouseDown(button=button)
                try:
                    duration = self._duration(arguments, 0.5)
                    start = time.monotonic()
                    while True:
                        if self._cancelled(arguments):
                            return {"ok": False, "content": "The user pressed Esc and cancelled computer control.", "error_code": "user_cancelled"}
                        elapsed = time.monotonic() - start
                        fraction = 1.0 if duration <= 0 else min(1.0, elapsed / duration)
                        gui.moveTo(round(x + (to_x - x) * fraction), round(y + (to_y - y) * fraction))
                        if fraction >= 1.0:
                            break
                        time.sleep(0.03)
                finally:
                    gui.mouseUp(button=button)
                return f"Dragged from ({x}, {y}) to ({to_x}, {to_y})"
            if action == "scroll":
                amount = self._integer(arguments, "amount")
                x = arguments.get("x")
                y = arguments.get("y")
                if (x is None) != (y is None):
                    raise ValueError("x and y must be provided together for scroll")
                if x is not None:
                    scroll_x, scroll_y = self._point(arguments)
                    gui.moveTo(scroll_x, scroll_y)
                gui.scroll(amount)
                return f"Scrolled {amount} clicks"
            if action == "type":
                text = str(arguments.get("text", ""))
                if not text:
                    raise ValueError("text is required for type")
                interval = self._duration(arguments, 0.01, 1.0)
                # Chunk typing so physical Esc is observed between chunks.
                for start in range(0, len(text), 32):
                    if self._cancelled(arguments):
                        return {"ok": False, "content": "The user pressed Esc and cancelled computer control.", "error_code": "user_cancelled"}
                    chunk = text[start:start + 32]
                    if chunk.isascii():
                        gui.write(chunk, interval=interval)
                    else:
                        self._paste_text(gui, chunk)
                return f"Typed {len(text)} characters"
            if action in {"key", "key_down", "key_up"}:
                key = self._normalize_key(arguments.get("text", ""))
                if not key:
                    raise ValueError("text is required for key")
                if key in {"esc", "escape"}:
                    return {
                        "ok": False,
                        "content": "Escape is reserved for the user to cancel computer control. Press Esc physically; do not send it through computer.",
                        "error_code": "reserved_cancel_key",
                    }
                if action == "key_up":
                    self._send_keys([key], release=False, key_up_only=True)
                else:
                    self._send_keys([key], release=action == "key")
                return f"{action.replace('_', ' ').title()}: {key}"
            if action == "hotkey":
                keys = arguments.get("keys")
                if not isinstance(keys, list) or not keys:
                    raise ValueError("keys must be a non-empty array")
                normalized = [self._normalize_key(key) for key in keys]
                if "esc" in normalized or "escape" in normalized:
                    return {
                        "ok": False,
                        "content": "Escape is reserved for the user to cancel computer control. Press Esc physically; do not send it through computer.",
                        "error_code": "reserved_cancel_key",
                    }
                self._send_keys(normalized, release=True)
                return f"Pressed hotkey: {'+'.join(normalized)}"
            if action == "wait":
                seconds = self._duration(arguments, 1.0)
                deadline = time.monotonic() + seconds
                while time.monotonic() < deadline:
                    if self._cancelled(arguments):
                        return {
                            "ok": False,
                            "content": "The user pressed Esc and cancelled computer control.",
                            "error_code": "user_cancelled",
                        }
                    time.sleep(min(0.05, max(0.0, deadline - time.monotonic())))
                return f"Waited {seconds:g} seconds"
            raise ValueError(f"unsupported action: {action}")
        except (ValueError, TypeError) as error:
            return {"ok": False, "content": str(error), "error_code": "invalid_arguments"}
        except Exception as error:
            return {"ok": False, "content": f"Computer operation failed: {error}", "error_code": "tool_error"}
