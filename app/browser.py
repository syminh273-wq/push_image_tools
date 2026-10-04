from __future__ import annotations

import logging
import subprocess
import time
from pathlib import Path

from playwright.async_api import Browser, BrowserContext, Playwright

from .models import ACCOUNTS_DIR

log = logging.getLogger(__name__)


def profile_dir(account: str) -> Path:
    """Dedicated user_data_dir for one Gemini account. Never the user's normal Chrome profile."""
    path = ACCOUNTS_DIR / account
    path.mkdir(parents=True, exist_ok=True)
    return path


CHROME_USER_DATA = Path.home() / "Library/Application Support/Google/Chrome"


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


def start_chrome_with_debugging(port: int = 9222,
                                user_data_dir: Path | None = None) -> subprocess.Popen:
    """Start a dedicated Chrome instance with CDP enabled and NO origin prompt.

    Flags:
      --remote-debugging-port=<port>           enable CDP
      --remote-allow-origins=*                 accept connection from any origin
                                               (no "Allow debugging" dialog)
      --no-first-run / --no-default-browser-check  silent startup
      --disable-blink-features=AutomationControlled  hide "controlled by automated software"

    Returns the Popen handle so the caller can keep it alive or kill it later.
    """
    args = [
        _chrome_binary(),
        f"--remote-debugging-port={port}",
        "--remote-allow-origins=*",
        "--no-first-run",
        "--no-default-browser-check",
        "--disable-blink-features=AutomationControlled",
        "--no-sandbox",
        "--disable-dev-shm-usage",
    ]
    if user_data_dir is not None:
        user_data_dir.mkdir(parents=True, exist_ok=True)
        args.append(f"--user-data-dir={user_data_dir}")
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


async def connect_running_chrome(pw: Playwright, auto_start: bool = True,
                                 debug_port: int = 9222) -> Browser:
    """Connect to Chrome over CDP without an "Allow" prompt.

    If Chrome isn't already running with the right flags, starts a dedicated instance
    on debug_port using start_chrome_with_debugging() — the user does not need to
    manually enable chrome://inspect/#remote-debugging or click any dialog.
    """
    port_file = CHROME_USER_DATA / "DevToolsActivePort"
    chrome_proc: subprocess.Popen | None = None

    if not port_file.is_file() and auto_start:
        log.info("No Chrome with remote debugging — starting a fresh instance on port %d", debug_port)
        chrome_proc = start_chrome_with_debugging(port=debug_port)
        # Wait until DevToolsActivePort appears (Chrome writes it when ready).
        for _ in range(40):
            if port_file.is_file():
                break
            time.sleep(0.25)
        if not port_file.is_file():
            chrome_proc.terminate()
            raise FileNotFoundError(
                f"Chrome did not expose DevToolsActivePort at {port_file} within 10s"
            )

    if not port_file.is_file():
        raise FileNotFoundError(
            "Chrome remote debugging is off. Open chrome://inspect/#remote-debugging in Chrome "
            "and enable 'Allow remote debugging for this browser instance'."
        )

    port, ws_path = port_file.read_text().split()[:2]
    endpoint = f"ws://127.0.0.1:{port}{ws_path}"
    log.debug("Connecting to running Chrome at %s", endpoint)
    return await pw.chromium.connect_over_cdp(endpoint)
