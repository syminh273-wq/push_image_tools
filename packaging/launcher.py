"""Desktop entry point for the packaged build: start the web server and open the browser."""
from __future__ import annotations

import os
import threading
import webbrowser

from app import accounts
from app.web import app

PORT = int(os.environ.get("PORT", "5050"))


def main() -> None:
    url = f"http://127.0.0.1:{PORT}"
    print(f"Gemini Video Tool is running at {url}  (close this window to stop)")
    if not any(a["status"] != "unknown" for a in accounts.get_all()):
        accounts.scan_all()
    threading.Timer(1.5, webbrowser.open, args=(url,)).start()
    app.run(host="127.0.0.1", port=PORT, debug=False, threaded=True)


if __name__ == "__main__":
    main()
