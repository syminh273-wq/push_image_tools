"""Chrome CDP tab scanner.

Connects to a running Chrome instance via CDP (the user already opened TikTok in their
Chrome — no Google sign-in required) and lists its open tabs. Used by the TikTok manager
to show every tab whose URL points at tiktok.com, mark which ones are logged in, and
locate the Playwright Page object for the runner.

Each debug Chrome is its own endpoint, so the scan lists the tabs of every one of them and tags
each tab with the port it came from. The runner uses that port to reach the right Chrome:
  1. Every debug Chrome this app launched (data/chrome-cdp-instances.json).
  2. A Chrome the user started by hand on one of DEFAULT_CDP_PORTS.

Connection is async (Playwright async API). A single Playwright instance is shared, and one CDP
connection is cached per port, so we don't pay the connection cost on every poll. The browser
object is shared with the runner — when a tab is run, we hand the runner the existing
Page so we don't reload anything.
"""
from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Optional

from playwright.async_api import Browser, Page, Playwright, async_playwright

from .browser import add_debug_instance, load_debug_instances, port_in_use, start_chrome_with_debugging

log = logging.getLogger("gemini_video_tool.tabs")

TIKTOK_HOSTS = ("tiktok.com", "tiktokv.com", "musical.ly")

# Ports of a Chrome the user started with --remote-debugging-port, checked alongside the ones
# this app launched. Mirrors the ports Chrome itself uses for its --remote-debugging-port flag.
DEFAULT_CDP_PORTS = (9222, 9229)

# Debug Chrome processes this app started. Kept referenced so the Popen objects are not dropped.
_chrome_procs: list = []


def _is_tiktok(url: str) -> bool:
    if not url:
        return False
    url = url.lower()
    return any(host in url for host in TIKTOK_HOSTS)


async def _connect_port(pw: Playwright, port: int) -> Optional[Browser]:
    """Connect to the Chrome listening on `port`. Tries IPv4 loopback, then IPv6, since some
    Chrome instances listen only on ::1. Returns None if neither answers."""
    for host in ("127.0.0.1", "[::1]"):
        endpoint = f"http://{host}:{port}"
        try:
            return await pw.chromium.connect_over_cdp(endpoint)
        except Exception as e:
            log.debug("CDP at %s not usable: %s", endpoint, e)
    return None


def debug_endpoints() -> list[dict]:
    """Every debug Chrome to scan: the ones this app launched first (label "#<id>"), then the usual
    external ports that are not already covered (label "ngoài")."""
    out: list[dict] = []
    for inst in load_debug_instances():
        out.append({"port": inst["port"], "label": f"#{inst['id']}", "managed": True})
    managed_ports = {e["port"] for e in out}
    for port in DEFAULT_CDP_PORTS:
        if port not in managed_ports:
            out.append({"port": port, "label": "ngoài", "managed": False})
    return out


class ChromeConnector:
    """Lazy singleton: one Playwright for the whole Flask app, one CDP browser per debug port."""

    def __init__(self) -> None:
        self._pw: Optional[Playwright] = None
        self._browsers: dict[int, Browser] = {}

    def connected_ports(self) -> set[int]:
        return {port for port, b in self._browsers.items() if b.is_connected()}

    async def get_browser(self, port: int) -> Optional[Browser]:
        """Return a live CDP browser for `port`, or None. Connects if needed.

        Caller must not store the browser across awaits longer than a single request —
        the connection can drop when the user closes Chrome. Always go through this method.
        """
        cached = self._browsers.get(port)
        if cached is not None:
            if cached.is_connected():
                return cached
            self._browsers.pop(port, None)
        # No lock here: a threading.Lock held across this await could block the loop itself.
        # Two concurrent connects to one port just leave one extra connection, which is harmless.
        if self._pw is None:
            self._pw = await async_playwright().start()
        browser = await _connect_port(self._pw, port)
        if browser is None:
            log.debug("no Chrome answering CDP on port %d", port)
        else:
            self._browsers[port] = browser
        return browser

    async def close(self) -> None:
        for browser in self._browsers.values():
            try:
                await browser.close()
            except Exception:
                pass
        self._browsers.clear()
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

    # 1. Live tabs of every debug Chrome.
    for endpoint in debug_endpoints():
        for t in await _scan_chrome_tabs(endpoint):
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


async def _scan_chrome_tabs(endpoint: dict) -> list[dict]:
    """Internal: scan the TikTok tabs of one debug Chrome (an entry from debug_endpoints())."""
    port = endpoint["port"]
    browser = await connector.get_browser(port)
    if browser is None:
        return []
    try:
        tabs = await _list_tabs_via_cdp(browser)
        active = await _active_tabs(browser)
    except Exception as e:
        log.warning("scan of Chrome on port %d failed: %s", port, e)
        return []
    for t in tabs:
        t["active"] = t["url"] in active
        t["logged_in"] = await _is_logged_in(browser, t["url"])
        t["source"] = "chrome"
        t["debug_port"] = port
        t["chrome_label"] = endpoint["label"]
        t["uid"] = _tab_uid(port, t["url"])
    return tabs


def debug_chromes(tabs_list: list[dict]) -> list[dict]:
    """Status of each debug Chrome for the UI header, from the last scan. Chromes this app
    launched are always listed (so a closed one shows as off); external ones only when reachable."""
    connected = connector.connected_ports()
    out = []
    for endpoint in debug_endpoints():
        port = endpoint["port"]
        alive = port in connected
        if not endpoint["managed"] and not alive:
            continue
        out.append({
            "port": port,
            "label": endpoint["label"],
            "managed": endpoint["managed"],
            "alive": alive,
            "tabs": sum(1 for t in tabs_list if t.get("debug_port") == port),
        })
    return out


def _tab_uid(port: int, url: str) -> str:
    """Stable id for a tab = a short hash of its Chrome's port and its URL. The port is part of
    the key so the same video open in two debug Chromes stays two separate tabs. Chrome itself
    does not expose a stable tab id via Playwright for connected browsers, so we use the URL."""
    import hashlib
    return "tt_" + hashlib.sha1(f"{port}|{url}".encode("utf-8")).hexdigest()[:10]


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


async def launch_debug_chrome() -> dict:
    """Open a new debug Chrome with its own port and profile, and connect to it.

    Every call opens another window, so several debug Chromes can run side by side, each with its
    own TikTok login. Returns the new instance as {"id", "port", "profile_dir", "label"}.
    Raises ConnectionError if the window does not come up with CDP in time.
    """
    inst = add_debug_instance()
    proc = start_chrome_with_debugging(port=inst["port"], user_data_dir=Path(inst["profile_dir"]))
    _chrome_procs.append(proc)
    # Wait until the new Chrome is listening so connect_over_cdp will succeed.
    for _ in range(40):
        await asyncio.sleep(0.25)
        if proc.poll() is not None:
            raise ConnectionError(f"Chrome #{inst['id']} đã thoát ngay sau khi mở")
        if port_in_use(inst["port"]):
            break
    else:
        raise ConnectionError(f"Chrome #{inst['id']} chưa mở cổng CDP {inst['port']} sau 10 giây")
    browser = await connector.get_browser(inst["port"])
    if browser is None:
        raise ConnectionError(f"Chrome #{inst['id']} đã mở nhưng chưa kết nối được CDP")
    # Bring the new window to the front, so it shows up on top instead of behind other windows.
    try:
        ctx = browser.contexts[0]
        page = ctx.pages[0] if ctx.pages else await ctx.new_page()
        await page.bring_to_front()
    except Exception as e:
        log.warning("could not bring Chrome #%d to front: %r", inst["id"], e)
    return {**inst, "label": f"#{inst['id']}"}