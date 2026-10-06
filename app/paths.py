"""Where the app reads and writes files, from source or from a PyInstaller build.

From source both roots are the project folder. In a frozen build (the .exe), PROJECT_ROOT is
the folder holding the executable, so data/, accounts/, output/ ... sit next to it and
survive updates; BUNDLE_ROOT is PyInstaller's unpacked bundle (read-only: web/dist and the
seed prompts).
"""
from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

FROZEN = getattr(sys, "frozen", False)
PROJECT_ROOT = Path(sys.executable).resolve().parent if FROZEN else Path(__file__).resolve().parent.parent
BUNDLE_ROOT = Path(getattr(sys, "_MEIPASS", PROJECT_ROOT))

if sys.platform == "win32":
    CHROME_USER_DATA = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData/Local")) / "Google/Chrome/User Data"
elif sys.platform == "darwin":
    CHROME_USER_DATA = Path.home() / "Library/Application Support/Google/Chrome"
else:
    CHROME_USER_DATA = Path.home() / ".config/google-chrome"

# Chrome 136+ ignores --remote-debugging-port when it uses the default user-data dir, so each
# CDP-controlled Chrome gets its own profile. The first one uses CDP_PROFILE_DIR; the next ones use
# chrome-cdp-profile-<id>. Every launched instance is listed in CDP_INSTANCES_FILE with its port.
CDP_PROFILE_DIR = PROJECT_ROOT / "data" / "chrome-cdp-profile"
CDP_INSTANCES_FILE = PROJECT_ROOT / "data" / "chrome-cdp-instances.json"
# Written by the build before the instance registry; read once to adopt that Chrome.
CDP_PORT_FILE = CDP_PROFILE_DIR / "cdp_port.txt"

# Seed files copied next to the executable on first run; the user's own data is never bundled.
_SEED_FILES = ("prompts/default.txt", "prompts/tiktok_content.txt",
               "data/prompts.json", "data/system_rules.json")


def seed_from_bundle() -> None:
    if not FROZEN:
        return
    for rel in _SEED_FILES:
        src, dst = BUNDLE_ROOT / rel, PROJECT_ROOT / rel
        if src.is_file() and not dst.exists():
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)


seed_from_bundle()
