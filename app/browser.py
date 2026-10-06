from __future__ import annotations

import json
import logging
import socket
import subprocess
import time
from pathlib import Path

from playwright.async_api import Browser, BrowserContext, Playwright

from .models import ACCOUNTS_DIR
from .paths import CDP_INSTANCES_FILE, CDP_PORT_FILE, CDP_PROFILE_DIR

log = logging.getLogger(__name__)


def profile_dir(account: str) -> Path:
    """Dedicated user_data_dir for one Gemini account. Never the user's normal Chrome profile."""
    path = ACCOUNTS_DIR / account
    path.mkdir(parents=True, exist_ok=True)
    return path


def _chrome_binary() -> str:
    """Locate Google Chrome binary on macOS/Linux/Windows."""
    candidates = [
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
        "/usr/bin/google-chrome",
        "/usr/bin/chromium",
        "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe",
        "C:\\Program Files (x86)\\Google\\Chrome\\Application\\chrome.exe",
    ]
    for c in candidates:
        if Path(c).exists():
            return c
    # Fall back to PATH lookup
    return "google-chrome"


def port_in_use(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex(("127.0.0.1", port)) == 0


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def load_debug_instances() -> list[dict]:
    """Debug Chrome instances this app launched: [{"id", "port", "profile_dir"}, ...].

    Instances stay listed after their window is closed, so a relaunch can be told apart from a
    fresh one. An install that predates the registry adopts the single Chrome it recorded in
    cdp_port.txt, so a Chrome that is still running keeps being found.
    """
    try:
        items = json.loads(CDP_INSTANCES_FILE.read_text(encoding="utf-8")).get("instances", [])
        return [i for i in items if isinstance(i, dict) and "port" in i and "id" in i]
    except FileNotFoundError:
        pass
    except (OSError, ValueError):
        log.warning("cannot read %s; ignoring it", CDP_INSTANCES_FILE)
        return []
    try:
        legacy_port = int(CDP_PORT_FILE.read_text().strip())
    except (OSError, ValueError):
        return []
    items = [{"id": 1, "port": legacy_port, "profile_dir": str(CDP_PROFILE_DIR)}]
    _save_debug_instances(items)
    return items


def _save_debug_instances(items: list[dict]) -> None:
    CDP_INSTANCES_FILE.parent.mkdir(parents=True, exist_ok=True)
    CDP_INSTANCES_FILE.write_text(json.dumps({"instances": items}, indent=2), encoding="utf-8")


def add_debug_instance() -> dict:
    """Reserve a new debug Chrome: its own port and its own profile dir.

    Chrome given an existing --user-data-dir hands the launch to the running process and exits,
    so every instance needs a profile of its own. Instance 1 keeps the original profile, so the
    TikTok logins from before this change still apply.
    """
    items = load_debug_instances()
    new_id = max((i["id"] for i in items), default=0) + 1
    used_ports = {i["port"] for i in items}
    if 9222 not in used_ports and not port_in_use(9222):
        port = 9222
    else:
        port = _free_port()
        while port in used_ports:
            port = _free_port()
    profile_dir = CDP_PROFILE_DIR if new_id == 1 else CDP_PROFILE_DIR.with_name(f"chrome-cdp-profile-{new_id}")
    inst = {"id": new_id, "port": port, "profile_dir": str(profile_dir)}
    items.append(inst)
    _save_debug_instances(items)
    return inst


def start_chrome_with_debugging(port: int,
                                user_data_dir: Path) -> subprocess.Popen:
    """Start a dedicated Chrome instance with CDP enabled and NO origin prompt.

    Flags:
      --remote-debugging-port=<port>           enable CDP
      --user-data-dir=<dir>                    required: Chrome 136+ ignores the debug port on
                                               the default profile, and an already-running
                                               Chrome would hand off the launch and exit
      --remote-allow-origins=*                 accept connection from any origin
                                               (no "Allow debugging" dialog)
      --no-first-run / --no-default-browser-check  silent startup
      --disable-blink-features=AutomationControlled  hide "controlled by automated software"

    The caller picks a free port and profile (see add_debug_instance). Returns the Popen handle
    so the caller can keep it alive or kill it later.
    """
    user_data_dir.mkdir(parents=True, exist_ok=True)
    args = [
        _chrome_binary(),
        f"--remote-debugging-port={port}",
        f"--user-data-dir={user_data_dir}",
        "--remote-allow-origins=*",
        "--no-first-run",
        "--no-default-browser-check",
        "--disable-blink-features=AutomationControlled",
        "--no-sandbox",
        "--disable-dev-shm-usage",
    ]
    log.info("Starting Chrome: %s", " ".join(args))
    return subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


async def launch_profile(pw: Playwright, account: str, channel: str = "chrome",
                        headless: bool = False) -> BrowserContext:
    """Launch a persistent context for the account.

    channel="chrome" uses the installed Google Chrome (Google sign-in tends to accept it
    more readily than bundled Chromium). channel="chromium" uses Playwright's Chromium.

    headless=True runs without a visible window — useful for background/bulk runs. Google
    sign-in may be stricter in headless mode, so each account profile should be logged in
    once with headless=False first.
    """
    user_data_dir = profile_dir(account)
    log.debug("Using profile %s (channel=%s, headless=%s)", user_data_dir, channel, headless)
    extra_args = [
        "--no-first-run",
        "--no-default-browser-check",
        # Hide "controlled by automated software" banner that triggers Google's bot check.
        "--disable-blink-features=AutomationControlled",
    ]
    if headless:
        # Headless Chromium needs a few extra flags to run inside Docker / sandbox-less envs.
        extra_args += [
            "--no-sandbox",
            "--disable-dev-shm-usage",
        ]
    return await pw.chromium.launch_persistent_context(
        user_data_dir=str(user_data_dir),
        channel=None if channel == "chromium" else channel,
        headless=headless,
        accept_downloads=True,
        viewport={"width": 1280, "height": 900},
        # Playwright adds --enable-automation by default, which shows an infobar and
        # makes Google more likely to refuse the sign-in page.
        ignore_default_args=["--enable-automation"],
        args=extra_args,
    )


async def launch_attach_profile(pw: Playwright, headless: bool = False) -> BrowserContext:
    """Launch a dedicated persistent Chrome for 'attach' mode pairs.

    This replaces the previous 'connect to running Chrome over CDP' approach which
    triggered Chrome's 'Allow remote debugging?' permission prompt. Now we just
    launch our own persistent browser — same approach as account mode, but with
    a dedicated profile (accounts/__attach__) so the user can sign in once and
    reuse the session.

    Each pair still gets its own browser process, so pairs can run in parallel.
    """
    return await launch_profile(pw, "__attach__", channel="chrome", headless=headless)


async def connect_running_chrome(pw: Playwright, auto_start: bool = True) -> Browser:
    """Connect to Chrome over CDP without an "Allow" prompt.

    Connects to the first debug Chrome from the instance registry that is listening. If none is,
    starts a new instance with start_chrome_with_debugging() — the user does not need to
    manually enable chrome://inspect/#remote-debugging or click any dialog.
    """
    port = next((i["port"] for i in load_debug_instances() if port_in_use(i["port"])), None)

    if port is None and auto_start:
        log.info("No Chrome with remote debugging — starting a fresh instance")
        inst = add_debug_instance()
        chrome_proc = start_chrome_with_debugging(port=inst["port"], user_data_dir=Path(inst["profile_dir"]))
        # Wait until the launched Chrome is listening on the port it was given.
        for _ in range(40):
            time.sleep(0.25)
            if port_in_use(inst["port"]):
                port = inst["port"]
                break
        else:
            chrome_proc.terminate()
            raise ConnectionError(f"Chrome did not expose CDP on port {inst['port']} within 10s")

    if port is None:
        raise ConnectionError(
            "Chrome remote debugging is off. Open a debug Chrome from the TikTok manager, or start "
            "Chrome with --remote-debugging-port."
        )

    endpoint = f"http://127.0.0.1:{port}"
    log.debug("Connecting to running Chrome at %s", endpoint)
    return await pw.chromium.connect_over_cdp(endpoint)
