# -*- coding: utf-8 -*-
"""Non-blocking Windows control indicator and Esc cancellation state."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import threading
import time
import uuid
from pathlib import Path

_STATE_PATH = Path(tempfile.gettempdir()) / "chengsi_computer_overlay.json"
_PROCESS: subprocess.Popen | None = None
_LOCK = threading.Lock()


def _write_state(active: bool, label: str = "Controlling computer", session_id: str = "", cancelled: bool = False, ready: bool = False, error: str = "") -> None:
    payload = {
        "active": active,
        "label": label,
        "session_id": session_id,
        "cancelled": cancelled,
        "ready": ready,
        "error": error,
        "updated_at": time.time(),
    }
    temporary = _STATE_PATH.with_name(f"{_STATE_PATH.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp")
    try:
        temporary.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        os.replace(temporary, _STATE_PATH)
    finally:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass


def _read_state() -> dict:
    try:
        value = json.loads(_STATE_PATH.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError, json.JSONDecodeError):
        return {}


def show(label: str = "Controlling computer", session_id: str = "") -> bool:
    """Show or update the indicator; return False when Esc cancelled this session."""
    global _PROCESS
    if os.name != "nt":
        return True
    with _LOCK:
        state = _read_state()
        if state.get("cancelled") and state.get("session_id") == session_id:
            return False
        _write_state(True, label, session_id, ready=False, error="")
        if _PROCESS is None or _PROCESS.poll() is not None:
            _PROCESS = subprocess.Popen(
                [sys.executable, str(Path(__file__).resolve()), "--worker"],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                close_fds=True,
            )
        deadline = time.monotonic() + 2.0
        while time.monotonic() < deadline:
            current = _read_state()
            if current.get("cancelled") and current.get("session_id") == session_id:
                return False
            if current.get("ready") and current.get("active") and current.get("session_id") == session_id:
                return True
            if current.get("error"):
                raise RuntimeError(str(current["error"]))
            if _PROCESS.poll() is not None:
                raise RuntimeError(f"Computer overlay worker exited with code {_PROCESS.returncode}.")
            time.sleep(0.02)
        raise RuntimeError("Computer overlay did not finish rendering within 2 seconds.")


def hide() -> None:
    global _PROCESS
    if os.name != "nt":
        return
    with _LOCK:
        state = _read_state()
        _write_state(False, "", str(state.get("session_id", "")), bool(state.get("cancelled", False)), ready=False)
        process = _PROCESS
        _PROCESS = None
        if process is not None and process.poll() is None:
            try:
                process.terminate()
                process.wait(timeout=1)
            except (OSError, subprocess.TimeoutExpired):
                try:
                    process.kill()
                except OSError:
                    pass


def is_cancelled(session_id: str = "") -> bool:
    state = _read_state()
    return bool(state.get("cancelled") and state.get("session_id") == session_id)


def clear_cancelled(session_id: str = "") -> None:
    with _LOCK:
        state = _read_state()
        if not session_id or state.get("session_id") == session_id:
            _write_state(False, "", session_id, False, ready=False)


def _enable_per_monitor_dpi() -> None:
    """Keep overlay coordinates aligned with PyAutoGUI's physical pixels."""
    if os.name != "nt":
        return
    import ctypes
    try:
        # Per-monitor-v2 prevents Tk from virtualizing geometry on scaled displays.
        if ctypes.windll.user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4)):
            return
    except (AttributeError, OSError):
        pass
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except (AttributeError, OSError):
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except (AttributeError, OSError):
            pass


def _virtual_screen() -> tuple[int, int, int, int]:
    import win32api
    import win32con

    logical_left = win32api.GetSystemMetrics(win32con.SM_XVIRTUALSCREEN)
    logical_top = win32api.GetSystemMetrics(win32con.SM_YVIRTUALSCREEN)
    logical_width = win32api.GetSystemMetrics(win32con.SM_CXVIRTUALSCREEN)
    logical_height = win32api.GetSystemMetrics(win32con.SM_CYVIRTUALSCREEN)
    try:
        import pyautogui
        physical_width, physical_height = pyautogui.size()
        scale_x = physical_width / max(1, logical_width)
        scale_y = physical_height / max(1, logical_height)
    except Exception:
        scale_x = scale_y = 1.0
    return (
        round(logical_left * scale_x),
        round(logical_top * scale_y),
        round(logical_width * scale_x),
        round(logical_height * scale_y),
    )


def _worker() -> None:
    """Render only narrow edge windows; no full-screen surface is ever created."""
    _enable_per_monitor_dpi()
    import tkinter as tk
    import ctypes
    import win32api
    import win32con
    import win32gui

    left, top, width, height = _virtual_screen()
    blue = "#1687ff"
    border = 6
    windows: list[tk.Toplevel] = []
    root = tk.Tk()
    root.withdraw()

    def make_panel(x: int, y: int, w: int, h: int, title: str) -> tk.Toplevel:
        panel = tk.Toplevel(root)
        panel.title(title)
        panel.overrideredirect(True)
        panel.configure(bg=blue)
        panel.geometry(f"{max(1, w)}x{max(1, h)}{x:+d}{y:+d}")
        panel.attributes("-topmost", True)
        panel.update_idletasks()
        hwnd = panel.winfo_id()
        style = win32gui.GetWindowLong(hwnd, win32con.GWL_EXSTYLE)
        style |= win32con.WS_EX_TRANSPARENT | win32con.WS_EX_TOOLWINDOW | getattr(win32con, "WS_EX_NOACTIVATE", 0x08000000)
        win32gui.SetWindowLong(hwnd, win32con.GWL_EXSTYLE, style)
        win32gui.SetWindowPos(hwnd, win32con.HWND_TOPMOST, x, y, w, h, win32con.SWP_NOACTIVATE | win32con.SWP_SHOWWINDOW)
        windows.append(panel)
        return panel

    make_panel(left, top, width, border, "ChengsiComputerOverlayTop")
    make_panel(left, top + height - border, width, border, "ChengsiComputerOverlayBottom")
    make_panel(left, top + border, border, height - border * 2, "ChengsiComputerOverlayLeft")
    make_panel(left + width - border, top + border, border, height - border * 2, "ChengsiComputerOverlayRight")

    # Size the blue status window from the rendered text instead of using a
    # fixed rectangle that can overflow on scaled or narrow displays.
    status = make_panel(left + 40, top + 36, 1, 1, "ChengsiComputerOverlayStatus")
    label = tk.Label(
        status,
        text="Chengsi is controlling · Esc to cancel",
        bg="#0879ed",
        fg="white",
        font=("Segoe UI", 20, "bold"),
        padx=32,
        pady=14,
        anchor="w",
        justify="left",
        wraplength=0,
    )
    label.pack(fill="both", expand=True)

    def resize_status(text: str) -> None:
        label.configure(text=text)
        root.update_idletasks()
        # Tk reports logical pixels while the desktop tool uses physical pixels.
        scale_x = width / max(1, win32api.GetSystemMetrics(win32con.SM_CXVIRTUALSCREEN))
        scale_y = height / max(1, win32api.GetSystemMetrics(win32con.SM_CYVIRTUALSCREEN))
        requested_width = max(1, label.winfo_reqwidth())
        requested_height = max(1, label.winfo_reqheight())
        physical_width = min(round(requested_width * scale_x), max(240, round(width * 0.8)))
        physical_height = round(requested_height * scale_y)
        status.geometry(
            f"{max(1, round(physical_width / max(scale_x, 0.01)))}x"
            f"{max(1, round(physical_height / max(scale_y, 0.01)))}"
            f"{left + round(20 * scale_x):+d}{top + round(18 * scale_y):+d}"
        )
        status.update_idletasks()

    resize_status("Chengsi is controlling · Esc to cancel")
    _write_state(True, str(_read_state().get("label") or "computer control"), str(_read_state().get("session_id") or ""), ready=True)

    last_label = ""
    escape_was_down = bool(win32api.GetAsyncKeyState(win32con.VK_ESCAPE) & 0x8000)
    hotkey_id = 0xC351
    status_hwnd = status.winfo_id()
    old_wndproc = None

    def close() -> None:
        try:
            ctypes.windll.user32.UnregisterHotKey(status_hwnd, hotkey_id)
        except Exception:
            pass
        for panel in windows:
            try:
                panel.destroy()
            except tk.TclError:
                pass
        root.destroy()

    def cancel_control() -> None:
        state = _read_state()
        _write_state(False, "", str(state.get("session_id", "")), True)
        close()

    def window_proc(hwnd, message, wparam, lparam):
        if message == win32con.WM_HOTKEY and wparam == hotkey_id:
            root.after(0, cancel_control)
            return 0
        return win32gui.CallWindowProc(old_wndproc, hwnd, message, wparam, lparam)

    old_wndproc = win32gui.SetWindowLong(status_hwnd, win32con.GWL_WNDPROC, window_proc)
    if not ctypes.windll.user32.RegisterHotKey(status_hwnd, hotkey_id, 0, win32con.VK_ESCAPE):
        raise RuntimeError("Could not register Esc as the computer-control cancel key")

    def refresh() -> None:
        nonlocal last_label, escape_was_down
        state = _read_state()
        escape_down = bool(win32api.GetAsyncKeyState(win32con.VK_ESCAPE) & 0x8000)
        if escape_down and not escape_was_down:
            cancel_control()
            return
        escape_was_down = escape_down
        if not state.get("active"):
            close()
            return
        current = str(state.get("label") or "computer control").replace("_", " ")
        if current != last_label:
            resize_status(f"Chengsi · {current} · Esc to cancel")
            last_label = current
        root.after(10, refresh)

    refresh()
    root.mainloop()


if __name__ == "__main__" and "--worker" in sys.argv:
    try:
        _worker()
    except Exception as error:
        try:
            state = _read_state()
            _write_state(
                False,
                "",
                str(state.get("session_id", "")),
                bool(state.get("cancelled", False)),
                ready=False,
                error=f"Overlay worker failed: {error}",
            )
        except Exception:
            pass
        raise
