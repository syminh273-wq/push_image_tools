"""Chrome CDP tab scanner.

Connects to a running Chrome instance via CDP (the user already opened TikTok in their
Chrome — no Google sign-in required) and lists its open tabs. Used by the TikTok manager
to show every tab whose URL points at tiktok.com, mark which ones are logged in, and
locate the Playwright Page object for the runner.

Two connection modes are supported, tried in order:
  1. Read DevToolsActivePort from ~/Library/Application Support/Google/Chrome and connect.
  2. Try a few common CDP ports (9222, 9229) over ws://127.0.0.1.

Connection is async (Playwright async API). A single Playwright instance and CDP browser
are reused across scans so we don't pay the connection cost on every poll. The browser
object is shared with the runner — when a tab is run, we hand the runner the existing
Page so we don't reload anything.
"""
from __future__ import annotations

import asyncio
import logging
import threading
import time
from pathlib import Path
from typing import Optional

from playwright.async_api import Browser, Page, Playwright, async_playwright

from .browser import CHROME_USER_DATA, start_chrome_with_debugging

log = logging.getLogger("gemini_video_tool.tabs")

TIKTOK_HOSTS = ("tiktok.com", "tiktokv.com", "musical.ly")

# CDP ports tried when DevToolsActivePort is not present. Mirrors the ports Chrome itself
# uses for its --remote-debugging-port flag.
DEFAULT_CDP_PORTS = (9222, 9229)


_chrome_proc_singleton: Optional[object] = None


def _is_tiktok(url: str) -> bool:
    if not url:
        return False
    url = url.lower()
    return any(host in url for host in TIKTOK_HOSTS)


async def _connect_once(pw: Playwright) -> Optional[Browser]:
    """Try DevToolsActivePort first, then a couple of common CDP ports."""
    port_file = CHROME_USER_DATA / "DevToolsActivePort"
    if port_file.is_file():
        try:
            port, ws_path = port_file.read_text().split()[:2]
            return await pw.chromium.connect_over_cdp(f"ws://127.0.0.1:{port}{ws_path}")
        except Exception as e:
            log.warning("CDP via port file failed: %s", e)
    for port in DEFAULT_CDP_PORTS:
        try:
            return await pw.chromium.connect_over_cdp(f"http://127.0.0.1:{port}")
        except Exception:
            continue
    return None


class ChromeConnector:
    """Lazy singleton: one Playwright + one CDP browser for the whole Flask app."""

    def __init__(self) -> None:
        self._pw: Optional[Playwright] = None
        self._browser: Optional[Browser] = None
        self._lock = threading.Lock()
        self._last_attempt = 0.0
        self._fail_count = 0

    async def get_browser(self) -> Optional[Browser]:
        """Return a live CDP browser or None. Tries to (re)connect if needed.

        Caller must not store the browser across awaits longer than a single request —
        the connection can drop when the user closes Chrome. Always go through this method.
        """
        now = time.time()
        if self._browser is not None:
            try:
                # Cheap liveness check — fails fast if Chrome was closed.
                contexts = self._browser.contexts
                _ = len(contexts)
                # Reset fail counter on success
                self._fail_count = 0
                return self._browser
            except Exception:
                self._browser = None
        # After repeated failures, drop the cached Playwright too — the underlying
        # connection might be wedged. Throttle reconnect so we don't spam.
        if now - self._last_attempt < 1.0 and self._browser is None:
            return None
        with self._lock:
            self._last_attempt = now
            if self._browser is not None:
                return self._browser
            if self._fail_count >= 2:
                # Nuke the Playwright instance so the next attempt gets a fresh one.
                log.info("CDP has failed %d times; resetting Playwright", self._fail_count)
                if self._pw is not None:
                    try:
                        await self._pw.stop()
                    except Exception:
                        pass
                    self._pw = None
                self._fail_count = 0
            if self._pw is None:
                self._pw = await async_playwright().start()
            self._browser = await _connect_once(self._pw)
            if self._browser is None:
                self._fail_count += 1
                log.info("No Chrome with CDP found (attempt %d); user must enable "
                         "remote debugging or run with --remote-debugging-port=9222",
                         self._fail_count)
            return self._browser

    async def close(self) -> None:
        if self._browser is not None:
            try:
                await self._browser.close()
            except Exception:
                pass
            self._browser = None
        if self._pw is not None:
            try:
                await self._pw.stop()
            except Exception:
                pass
            self._pw = None


connector = ChromeConnector()


async def _page_info(page: Page, *, active: bool) -> dict:
    """Extract the bits of a tab the UI cares about."""
    url = page.url or ""
    title = ""
    try:
        title = await page.title() or ""
    except Exception:
        pass
    # Chrome's target id is what CDP / Playwright uses to identify a tab across reloads;
    # Playwright surfaces it as Page._guid for connected browsers, but the public path is the
    # underlying TargetInfo — we read it through CDP.
    return {
        "title": title,
        "url": url,
        "active": active,
    }


async def _list_tabs_via_cdp(browser: Browser) -> list[dict]:
    """Use the raw CDP `Target.getTargets` so we get every tab — including pages in other
    contexts Playwright doesn't expose (Chrome runs every tab inside one BrowserContext, but
    some extensions or incognito setups create multiple contexts)."""
    out: list[dict] = []
    contexts = browser.contexts
    for ctx in contexts:
        pages = list(ctx.pages)
        for page in pages:
            try:
                info = await _page_info(page, active=False)
            except Exception:
                continue
            if not _is_tiktok(info["url"]):
                continue
            # CDSes's BrowserContext exposes a helper but Page doesn't carry a stable id here;
            # we use the url + title as a soft key. The runner re-resolves the Page by URL.
            out.append({**info, "context_id": "default"})
    return out


async def _active_tabs(browser: Browser) -> set[str]:
    """The currently visible tab in each context. CDP exposes 'page' target type with
    `targetInfo` including `isAttached`/`type`. Playwright gives us pages[0] of each context
    which is the most-recently active tab for normal Chrome windows."""
    active_urls: set[str] = set()
    for ctx in browser.contexts:
        pages = list(ctx.pages)
        if pages:
            try:
                active_urls.add(pages[0].url or "")
            except Exception:
                pass
    return active_urls


async def scan_tiktok_tabs() -> list[dict]:
    """List Chrome tabs whose URL points at TikTok, with `active` and `logged_in`.

    `logged_in` is heuristic: true if cookies for tiktok.com include a session token. The
    runner rechecks this at run-time — the UI value is "is this tab probably usable right now".
    """
    browser = await connector.get_browser()
    if browser is None:
        return []
    try:
        tabs = await _list_tabs_via_cdp(browser)
        active = await _active_tabs(browser)
    except Exception as e:
        log.warning("scan failed: %s", e)
        return []
    for t in tabs:
        t["active"] = t["url"] in active
        t["logged_in"] = await _is_logged_in(browser, t["url"])
    # Stable id = a hash of the URL; collisions on two tabs of the same video are vanishingly
    # rare in practice and the UI will just merge them.
    for t in tabs:
        t["uid"] = _tab_uid(t["url"])
    return tabs


async def _is_logged_in(browser: Browser, url: str) -> bool:
    """Best-effort login check via CDP. Returns False on any error — the UI treats unknown
    as not-logged-in, so the user sees the safe state."""
    try:
        from urllib.parse import urlparse
        host = (urlparse(url).hostname or "").lower()
        if not host:
            return False
        # Cookies in CDP are scoped by domain — use the parent domain.
        parts = host.split(".")
        if len(parts) >= 2:
            domain = ".".join(parts[-2:])
        else:
            domain = host
        contexts = browser.contexts
        for ctx in contexts:
            cookies = await ctx.cookies()
            for c in cookies:
                if not c.get("name"):
                    continue
                if domain not in (c.get("domain") or "").lower():
                    continue
                n = c["name"].lower()
                if n.startswith("sessionid") or n == "ttwid" or n == "ms_token" or "uid_tt" in n:
                    return True
        return False
    except Exception:
        return False


_TIKTOK_COOKIE_NAMES = (
    "sessionid", "sessionid_ss", "ttwid", "ms_token",
    "uid_tt", "sid_tt", "sid_guard",
)


def _profile_has_tiktok_cookie(profile_dir_path: Path) -> bool:
    """Check if a Chrome profile directory has TikTok login cookies.

    Chrome stores cookies in <profile>/Default/Cookies (SQLite). We open it
    read-only and look for any cookie on tiktok.com / tiktokv.com / musical.ly.
    Returns False on any error — the UI treats unknown as not-logged-in.
    """
    try:
        import sqlite3
        candidates = [
            profile_dir_path / "Default" / "Cookies",
            profile_dir_path / "Cookies",  # older Chromium layout
        ]
        cookies_db = None
        for c in candidates:
            if c.is_file():
                cookies_db = c
                break
        if cookies_db is None:
            return False
        # Chrome locks Cookies while running; try to copy + open read-only.
        import shutil, tempfile, os
        with tempfile.NamedTemporaryFile(delete=False, suffix=".db") as tmp:
            try:
                shutil.copy2(cookies_db, tmp.name)
                tmp_path = tmp.name
            except Exception:
                os.unlink(tmp.name)
                return False
        try:
            conn = sqlite3.connect(f"file:{tmp_path}?mode=ro", uri=True)
            try:
                rows = conn.execute(
                    "SELECT name FROM cookies WHERE host_key LIKE '%tiktok%'"
                ).fetchall()
            finally:
                conn.close()
            names = {r[0].lower() for r in rows if r and r[0]}
            return any(any(cookie in n for cookie in _TIKTOK_COOKIE_NAMES)
                       for n in names)
        finally:
            try:
                os.unlink(tmp_path)
            except Exception:
                pass
    except Exception:
        return False


async def scan_account_profiles() -> list[dict]:
    """Scan every account profile under accounts/ and return synthetic TikTok
    tabs for the ones that have valid TikTok cookies. These are NOT real browser
    tabs — clicking Run on one launches a headless browser with that profile.

    This is what lets the user see *every* signed-in TikTok account, not just
    the ones with a tab open in their main Chrome window.
    """
    from .models import ACCOUNTS_DIR
    out: list[dict] = []
    if not ACCOUNTS_DIR.exists():
        return out
    for entry in sorted(ACCOUNTS_DIR.iterdir()):
        if not entry.is_dir() or entry.name.startswith("."):
            continue
        # Skip the synthetic headless profile — its session is used implicitly
        # when `headless=true` is passed to run, not as a separate tab.
        if entry.name == "tiktok_headless":
            continue
        if not _profile_has_tiktok_cookie(entry):
            continue
        uid = "ttprof_" + entry.name
        out.append({
            "uid": uid,
            "title": f"Profile: {entry.name}",
            "url": "https://www.tiktok.com/foryou",
            "active": False,
            "context_id": f"profile:{entry.name}",
            "logged_in": True,
            "source": "profile",
            "profile_name": entry.name,
        })
    return out


async def scan_tiktok_tabs() -> list[dict]:
    """List Chrome tabs whose URL points at TikTok, with `active` and `logged_in`.

    Combines three sources so the user sees every TikTok session available:
      1. Chrome local tabs (via CDP)
      2. Account profiles under accounts/ that hold TikTok cookies
      3. The dedicated headless profile

    `logged_in` is heuristic: true if cookies for tiktok.com include a session token. The
    runner rechecks this at run-time — the UI value is "is this tab probably usable right now".
    """
    seen: dict[str, dict] = {}

    # 1. Live Chrome tabs.
    local = await _scan_chrome_tabs()
    for t in local:
        seen[t["uid"]] = t

    # 2. Account profiles with stored TikTok cookies.
    try:
        profile_tabs = await scan_account_profiles()
    except Exception as e:
        log.warning("scan_account_profiles failed: %s", e)
        profile_tabs = []
    for t in profile_tabs:
        # Don't duplicate a live tab that already points at foryou on the same uid.
        if t["uid"] not in seen:
            seen[t["uid"]] = t

    return list(seen.values())


async def _scan_chrome_tabs() -> list[dict]:
    """Internal: scan only the live Chrome browser via CDP."""
    browser = await connector.get_browser()
    if browser is None:
        return []
    try:
        tabs = await _list_tabs_via_cdp(browser)
        active = await _active_tabs(browser)
    except Exception as e:
        log.warning("scan failed: %s", e)
        return []
    for t in tabs:
        t["active"] = t["url"] in active
        t["logged_in"] = await _is_logged_in(browser, t["url"])
        t["source"] = "chrome"
    for t in tabs:
        t["uid"] = _tab_uid(t["url"])
    return tabs


def _tab_uid(url: str) -> str:
    """Stable id for a tab = a short hash of its URL. Chrome itself does not expose a stable
    tab id via the standard Playwright Page object for connected browsers, so we use URL.
    Collisions only happen if the user has the same video open in two tabs — UI then merges
    them which is acceptable for v1."""
    import hashlib
    return "tt_" + hashlib.sha1(url.encode("utf-8")).hexdigest()[:10]


def _extract_tiktok_id(url: str) -> str:
    """The numeric id inside `/photo/<id>` or `/video/<id>`. Same post in photo+video
    carousel shares this id."""
    import re
    m = re.search(r"/(?:photo|video)/(\d+)", url or "")
    return m.group(1) if m else ""


async def find_page_by_url(browser: Browser, url: str) -> Optional[Page]:
    """Locate the Playwright Page that currently shows `url`. Returns None if the user
    navigated away or closed the tab.

    Matching is fuzzy on purpose — TikTok sometimes adds tracking query strings,
    redirects /photo/<id> to /video/<id> for the same post, or normalises trailing
    slashes. We try (in order):
      1. exact URL match
      2. same path (ignore query/fragment)
      3. same TikTok numeric content id
    """
    from urllib.parse import urlparse
    target_path = (urlparse(url or "").path or "").rstrip("/")
    target_id = _extract_tiktok_id(url)
    try:
        for ctx in browser.contexts:
            for page in ctx.pages:
                p_url = page.url or ""
                if not p_url:
                    continue
                if p_url == url:
                    return page
                p_path = (urlparse(p_url).path or "").rstrip("/")
                if target_path and p_path == target_path:
                    return page
                if target_id and _extract_tiktok_id(p_url) == target_id:
                    return page
    except Exception:
        return None
    return None


async def ensure_chrome_running(debug_port: int = 9222) -> bool:
    """Best-effort: if no CDP endpoint responds, launch a Chrome with debugging enabled
    on debug_port so the user can manually open TikTok tabs. Returns True if Chrome is up."""
    browser = await connector.get_browser()
    if browser is not None:
        return True
    try:
        proc = start_chrome_with_debugging(port=debug_port)
        global _chrome_proc_singleton
        _chrome_proc_singleton = proc
    except Exception as e:
        log.warning("failed to launch Chrome: %s", e)
        return False
    # Wait for DevToolsActivePort to appear so connect_over_cdp will succeed.
    for _ in range(40):
        await asyncio.sleep(0.25)
        if (CHROME_USER_DATA / "DevToolsActivePort").is_file():
            break
    return await connector.get_browser() is not None