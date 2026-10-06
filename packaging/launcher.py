"""Desktop entry point for the packaged build: start the web server and open the browser.

A crash is written to GeminiVideoTool-error.log next to the executable and the console stays
open, so a double-clicked .exe never just vanishes.
"""
from __future__ import annotations

import os
import socket
import sys
import threading
import traceback
import webbrowser
from pathlib import Path

PORT = int(os.environ.get("PORT", "5050"))


def _port_in_use(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex(("127.0.0.1", port)) == 0


def main() -> None:
    url = f"http://127.0.0.1:{PORT}"
    if _port_in_use(PORT):
        # Most likely the app is already running in another window.
        print(f"Port {PORT} is already in use - opening {url}")
        webbrowser.open(url)
        return

    from app import accounts
    from app.web import app

    print(f"Gemini Video Tool is running at {url}  (close this window to stop)")
    if not any(a["status"] != "unknown" for a in accounts.get_all()):
        accounts.scan_all()
    if os.environ.get("NO_BROWSER") != "1":
        threading.Timer(1.5, webbrowser.open, args=(url,)).start()
    app.run(host="127.0.0.1", port=PORT, debug=False, threaded=True)


if __name__ == "__main__":
    try:
        main()
    except Exception:
        err = traceback.format_exc()
        print(err, file=sys.stderr)
        log = Path(sys.executable if getattr(sys, "frozen", False) else __file__).resolve().parent / "GeminiVideoTool-error.log"
        try:
            log.write_text(err, encoding="utf-8")
            print(f"Error saved to {log}", file=sys.stderr)
        except OSError:
            pass
        if sys.stdin and sys.stdin.isatty():
            input("Press Enter to close...")
        sys.exit(1)
