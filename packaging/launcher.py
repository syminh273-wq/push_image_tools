"""Desktop entry point for the packaged build: a local server shown in a native app window.

The window is pywebview (Edge WebView2 on Windows); without it the UI opens in the default
browser. The Windows build has no console, so output goes to GeminiVideoTool.log next to the
executable and a crash is shown in a message box.

NO_WINDOW=1 runs the server alone (CI smoke test).
"""
from __future__ import annotations

import os
import socket
import sys
import threading
import time
import traceback
import webbrowser
from pathlib import Path

PORT = int(os.environ.get("PORT", "5050"))
TITLE = "TikTok Manager"
APP_DIR = Path(sys.executable if getattr(sys, "frozen", False) else __file__).resolve().parent


def _redirect_output() -> None:
    """The Windows exe has no console; send stdout/stderr to a log file instead."""
    if sys.stdout is None or sys.stderr is None or (getattr(sys, "frozen", False) and sys.platform == "win32"):
        log = open(APP_DIR / "GeminiVideoTool.log", "a", encoding="utf-8", buffering=1)
        sys.stdout = sys.stderr = log


def _port_in_use(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex(("127.0.0.1", port)) == 0


def _start_server() -> None:
    from app import accounts
    from app.web import app

    if not any(a["status"] != "unknown" for a in accounts.get_all()):
        accounts.scan_all()
    threading.Thread(target=app.run, daemon=True, name="flask",
                     kwargs={"host": "127.0.0.1", "port": PORT, "debug": False, "threaded": True}).start()
    for _ in range(100):
        if _port_in_use(PORT):
            return
        time.sleep(0.1)
    raise RuntimeError(f"server did not start on port {PORT}")


def _show_window(url: str) -> None:
    try:
        import webview
    except ImportError:
        webbrowser.open(url)
        print(f"{TITLE} is running at {url}  (Ctrl+C to stop)")
        threading.Event().wait()
        return
    webview.create_window(TITLE, url, width=1280, height=860, min_size=(900, 600))
    webview.start()  # returns when the window is closed; daemon threads end with the process


def main() -> None:
    url = f"http://127.0.0.1:{PORT}"
    if not _port_in_use(PORT):  # in use: most likely another copy is already running
        _start_server()
    print(f"{TITLE} server at {url}")
    if os.environ.get("NO_WINDOW") == "1":
        try:
            import webview  # noqa: F401
            print("pywebview available")
        except ImportError:
            print("pywebview missing - would fall back to the browser")
        threading.Event().wait()
    _show_window(url)


def _report_crash(err: str) -> None:
    print(err, file=sys.stderr)
    log = APP_DIR / "GeminiVideoTool-error.log"
    try:
        log.write_text(err, encoding="utf-8")
    except OSError:
        pass
    if sys.platform == "win32":
        import ctypes
        ctypes.windll.user32.MessageBoxW(None, f"{err[-1500:]}\n\nSaved to {log}", f"{TITLE} - error", 0x10)


if __name__ == "__main__":
    _redirect_output()
    try:
        main()
    except Exception:
        _report_crash(traceback.format_exc())
        sys.exit(1)
