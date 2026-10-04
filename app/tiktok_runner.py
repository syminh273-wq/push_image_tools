"""Runner for TikTok tabs.

Each TikTok tab the user has open in Chrome is "a session". When the user clicks Run on a
tab from the UI, this module starts a background thread that:

  1. Locates the tab in the CDP browser.
  2. If `video_url` is given, navigates the tab to that single video.
     Otherwise it opens the For You feed and scrolls down video by video.
  3. For each video: dwell, posts one comment from the templates (cycling),
     waits, scrolls to the next.
  4. Stops cleanly on Stop signal or when `max_comments` is reached.

State is kept in-memory and broadcast over SSE per-tab so the UI updates live.
"""
from __future__ import annotations

import asyncio
import logging
import queue
import threading
import time
import uuid
from datetime import datetime
from typing import Optional

from playwright.async_api import Browser

from . import tabs
from .browser import profile_dir
from .tiktok import DEFAULT_DWELL_S, TikTokAutomation, TikTokError

log = logging.getLogger("gemini_video_tool.tiktok_runner")

# tab_uid -> {"thread", "task", "loop", "state": {counters, started_at, ...}, "stop": Event}
_running: dict[str, dict] = {}
# tab_uid -> list of queue.Queue for SSE subscribers.
_subs: dict[str, list[queue.Queue]] = {}
# tab_uid -> log buffer (last 200 lines).
_log_buffers: dict[str, list[str]] = {}
_lock = threading.RLock()

# Shared asyncio loop (created lazily). Same loop used by web.py's HTTP handlers
# and the background runners here, so Playwright Browser objects stay attached to
# one loop instead of being created and torn down per request.
_async_loop: asyncio.AbstractEventLoop | None = None
_async_thread: threading.Thread | None = None


def _ensure_loop() -> asyncio.AbstractEventLoop:
    global _async_loop, _async_thread
    if _async_loop is not None and _async_thread is not None and _async_thread.is_alive():
        return _async_loop
    loop = asyncio.new_event_loop()

    def _runner() -> None:
        asyncio.set_event_loop(loop)
        try:
            loop.run_forever()
        finally:
            loop.close()

    t = threading.Thread(target=_runner, daemon=True, name="tiktok-asyncio-shared")
    t.start()
    _async_loop = loop
    _async_thread = t
    return loop


def submit(coro):
    """Schedule a coroutine on the shared loop. Returns concurrent.futures.Future."""
    return asyncio.run_coroutine_threadsafe(coro, _ensure_loop())


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _broadcast(uid: str, event: str, payload: dict) -> None:
    with _lock:
        subs = list(_subs.get(uid, []))
    import json
    data = json.dumps(payload)
    for q in subs:
        try:
            q.put_nowait((event, data))
        except queue.Full:
            pass


def _append_log(uid: str, line: str) -> None:
    with _lock:
        buf = _log_buffers.setdefault(uid, [])
        buf.append(line)
        if len(buf) > 200:
            del buf[:-200]
    _broadcast(uid, "log", {"line": line})


def _update_state(uid: str, **fields) -> None:
    with _lock:
        rec = _running.get(uid)
        if not rec:
            return
        rec["state"].update(fields)
        snapshot = dict(rec["state"])
    _broadcast(uid, "state", snapshot)


def _make_default_state(tab: dict) -> dict:
    return {
        "uid": tab["uid"],
        "url": tab.get("url", ""),
        "title": tab.get("title", ""),
        "username": tab.get("username", ""),
        "logged_in": bool(tab.get("logged_in")),
        "active": bool(tab.get("active")),
        "is_running": False,
        "comments_sent": 0,
        "comments_failed": 0,
        "last_error": None,
        "started_at": None,
        "stopped_at": None,
        "current_video": None,
        "last_comment": None,
    }


async def _run_loop(tab: dict, video_url: Optional[str], templates: list[str],
                    dwell_s: float, max_comments: int, scroll_after_each: bool,
                    cooldown_s: float, skip_first: int,
                    headless: bool,
                    stop_event: asyncio.Event) -> None:
    uid = tab["uid"]
    owned_browser: Optional[Browser] = None
    # If the tab came from an account profile (not a live Chrome tab), force
    # headless mode and use that profile so the saved cookies are honoured.
    profile_name = tab.get("profile_name")
    if profile_name:
        headless = True
    if headless:
        # Launch a dedicated, invisible Chrome instance with a private profile so
        # the user's normal browsing is not disturbed. The profile lives under
        # accounts/<name>/ and persists across runs — the user signs in once with
        # the corresponding login helper and then every subsequent run uses the
        # same logged-in session, fully invisible.
        from playwright.async_api import async_playwright
        _append_log(uid, "[runner] launching headless Chrome (invisible window)")
        pw = await async_playwright().start()
        ctx = await _launch_headless_context(pw, profile_name=profile_name)
        owned_browser = ctx.browser if hasattr(ctx, "browser") else None
        # The persistent context returns a context, not a browser — its pages live
        # directly on the context.
        headless_ctx = ctx
    else:
        browser = await tabs.connector.get_browser()
        if browser is None:
            _append_log(uid, "[runner] no Chrome with CDP found — start Chrome with "
                              "--remote-debugging-port=9222 and refresh.")
            _update_state(uid, is_running=False, last_error="no CDP browser")
            return

    if headless:
        # The persistent context starts with no pages; reuse the first one (it
        # opens about:blank) or create a new one for our URL.
        pages = headless_ctx.pages
        page = pages[0] if pages else await headless_ctx.new_page()
        if video_url:
            _append_log(uid, f"[runner] opening {video_url}")
            await page.goto(video_url, wait_until="domcontentloaded", timeout=20000)
        else:
            _append_log(uid, "[runner] opening For You feed")
            await page.goto("https://www.tiktok.com/foryou",
                            wait_until="domcontentloaded", timeout=20000)
    else:
        page = await tabs.find_page_by_url(browser, tab["url"])
        if page is None:
            _append_log(uid, f"[runner] tab {tab['url']!r} not found in Chrome — it may have been closed.")
            _update_state(uid, is_running=False, last_error="tab not found")
            return
        if page.url != tab["url"]:
            _append_log(uid, f"[runner] tab URL drifted: scanned={tab['url']!r} "
                              f"actual={page.url!r} — continuing with the live tab.")

    automation = TikTokAutomation(page, uid)
    if not templates:
        _append_log(uid, "[runner] no comment templates configured — nothing to send.")
        if headless:
            await _shutdown_headless(pw, headless_ctx)
        return

    cycle = 0
    sent = 0
    failed = 0
    videos_seen = 0
    last_template = ""
    import random
    try:
        # For headless we already navigated above. For non-headless, open_or_focus
        # navigates the user's tab (or just focuses it if URL matches).
        if not headless:
            if video_url:
                _append_log(uid, f"[runner] opening {video_url}")
                await automation.open_or_focus(video_url)
            else:
                _append_log(uid, "[runner] opening For You feed")
                await automation.open_or_focus("https://www.tiktok.com/foryou")
        _update_state(uid, is_running=True, started_at=_now(),
                      last_error=None, current_video=page.url)

        while not stop_event.is_set():
            if sent >= max_comments:
                _append_log(uid, f"[runner] reached max_comments={max_comments}, stopping")
                break

            template = templates[cycle % len(templates)]
            cycle += 1
            last_template = template
            videos_seen += 1

            # Dwell = base + random jitter (±40 %) so the cadence is irregular.
            jitter = dwell_s * 0.40
            this_dwell = max(0.0, dwell_s + random.uniform(-jitter, jitter))
            try:
                await automation.dwell(this_dwell)
            except Exception as e:
                _append_log(uid, f"[runner] dwell failed: {e!r}")

            if await automation.is_login_wall():
                _append_log(uid, "[runner] login wall shown — please sign in to this TikTok tab.")
                _update_state(uid, last_error="login wall")
                break

            # Skip the first `skip_first` videos — useful for letting the feed
            # "warm up" before commenting.
            if videos_seen <= skip_first:
                _append_log(uid, f"[runner] skipping video {videos_seen}/{skip_first} (no comment)")
                if scroll_after_each and sent < max_comments:
                    moved = await automation.scroll_feed()
                    if not moved:
                        _append_log(uid, "[runner] could not scroll to next video, stopping")
                        break
                continue

            try:
                ok = await automation.comment(template)
            except TikTokError as e:
                _append_log(uid, f"[runner] comment failed: {e}")
                failed += 1
                _update_state(uid, comments_sent=sent, comments_failed=failed,
                              last_comment=None, last_error=str(e))
                # Still scroll past the failed video so we don't get stuck on it.
                if scroll_after_each and sent < max_comments:
                    moved = await automation.scroll_feed()
                    if not moved:
                        _append_log(uid, "[runner] could not scroll to next video, stopping")
                        break
                continue
            except Exception as e:
                _append_log(uid, f"[runner] unexpected error: {e!r}")
                failed += 1
                _update_state(uid, comments_sent=sent, comments_failed=failed,
                              last_comment=None, last_error=str(e))
                if scroll_after_each and sent < max_comments:
                    moved = await automation.scroll_feed()
                    if not moved:
                        _append_log(uid, "[runner] could not scroll to next video, stopping")
                        break
                continue

            if ok:
                sent += 1
                _append_log(uid, f"[runner] comment #{sent} posted: {template[:60]!r}")
                _update_state(uid, comments_sent=sent, comments_failed=failed,
                              last_comment=_now(), current_video=page.url, last_error=None)
            else:
                failed += 1
                _append_log(uid, f"[runner] comment #{sent+failed} did not confirm — assuming failed")
                _update_state(uid, comments_sent=sent, comments_failed=failed,
                              last_comment=None, last_error="comment did not confirm")

            if not scroll_after_each and sent >= max_comments:
                break
            if scroll_after_each and sent < max_comments:
                # Cooldown between posts (with ±40 % jitter) so the account doesn't
                # look like a bot firing on the dot. The user is watching the tab —
                # we don't need to be fast, we need to look human.
                cj = cooldown_s * 0.40
                cooldown = max(0.0, cooldown_s + random.uniform(-cj, cj))
                if cooldown > 0:
                    _append_log(uid, f"[runner] cooling down {cooldown:.1f}s")
                    # Sleep in 1s chunks so stop signal is respected promptly.
                    end_at = asyncio.get_event_loop().time() + cooldown
                    while not stop_event.is_set() and asyncio.get_event_loop().time() < end_at:
                        await asyncio.sleep(1.0)
                moved = await automation.scroll_feed()
                if not moved:
                    _append_log(uid, "[runner] could not scroll to next video, stopping")
                    break
                _update_state(uid, current_video=page.url)

        _append_log(uid, "[runner] done.")
    except asyncio.CancelledError:
        _append_log(uid, "[runner] cancelled.")
        raise
    except Exception as e:
        _append_log(uid, f"[runner] fatal: {e!r}")
        _update_state(uid, last_error=str(e))
    finally:
        _update_state(uid, is_running=False, stopped_at=_now(), last_comment=last_template or None)
        if headless:
            try:
                await _shutdown_headless(pw, headless_ctx)
            except Exception as e:
                _append_log(uid, f"[runner] headless shutdown error: {e!r}")


def start_run(*, tab: dict, video_url: Optional[str], templates: list[str],
              dwell_s: float, max_comments: int, scroll_after_each: bool,
              cooldown_s: float = 12.0, skip_first: int = 0,
              headless: bool = False) -> dict:
    """Start a background run for `tab`. If one is already running, returns its state."""
    uid = tab["uid"]
    with _lock:
        existing = _running.get(uid)
        if existing and existing.get("thread") and existing["thread"].is_alive():
            return {**existing["state"], "already_running": True}

    state = _make_default_state(tab)
    stop = threading.Event()
    rec: dict = {"thread": None, "task": None, "loop": None,
                 "state": state, "stop": stop}

    def thread_main() -> None:
        # Run the async work on the shared loop so the Playwright Browser used by
        # tabs.connector stays attached to the same loop across requests.
        loop = _ensure_loop()
        rec["loop"] = loop

        # asyncio.Event — the real stop signal inside the loop. _run_loop checks
        # .is_set() every iteration; we flip it when the threading.Event goes off.
        stop_event = asyncio.Event()
        rec["stop_event"] = stop_event

        async def watcher() -> None:
            # Mirror the threading.Event into the asyncio.Event so _run_loop sees it.
            while not stop.is_set():
                await asyncio.sleep(0.2)
            _append_log(uid, "[runner] stop signal received by watcher")
            stop_event.set()
            _append_log(uid, "[runner] stop_event set, _run_loop will exit on next check")

        async def main() -> None:
            stop_coro = asyncio.ensure_future(watcher())
            run_task = asyncio.ensure_future(_run_loop(
                tab, video_url, templates, dwell_s, max_comments,
                scroll_after_each, cooldown_s, skip_first, headless, stop_event))
            try:
                # Whichever finishes first, wait for the other to settle and cancel
                # it if still running. Without this, a stuck Playwright operation can
                # hold the run past the stop signal for many seconds.
                done, pending = await asyncio.wait(
                    {stop_coro, run_task},
                    return_when=asyncio.FIRST_COMPLETED,
                )
                for t in pending:
                    t.cancel()
                for t in pending:
                    try:
                        await t
                    except (asyncio.CancelledError, Exception):
                        pass
                if run_task in done:
                    return run_task.result()
            finally:
                for t in (stop_coro, run_task):
                    if not t.done():
                        t.cancel()
                stop_event.set()

        future = submit(main())
        try:
            future.result()  # block this supervisor thread, not the loop
        finally:
            with _lock:
                _running.pop(uid, None)

    t = threading.Thread(target=thread_main, daemon=True, name=f"tiktok-{uid}")
    rec["thread"] = t
    with _lock:
        _running[uid] = rec
    t.start()
    return state


def stop_run(uid: str) -> bool:
    """Signal the runner to stop. Returns True if a run was actually running."""
    with _lock:
        rec = _running.get(uid)
    if not rec:
        return False
    rec["stop"].set()
    return True


def get_state(uid: str) -> Optional[dict]:
    with _lock:
        rec = _running.get(uid)
        if rec is None:
            return None
        return dict(rec["state"])


def subscribe(uid: str) -> queue.Queue:
    q: queue.Queue = queue.Queue(maxsize=200)
    with _lock:
        _subs.setdefault(uid, []).append(q)
    return q


def unsubscribe(uid: str, q: queue.Queue) -> None:
    with _lock:
        subs = _subs.get(uid, [])
        if q in subs:
            subs.remove(q)


def get_log(uid: str) -> list[str]:
    with _lock:
        return list(_log_buffers.get(uid, []))


# --- Headless mode: a private, invisible Chrome just for this bot run ---

_TIKTOK_HEADLESS_PROFILE = "tiktok_headless"


async def _launch_headless_context(pw, *, profile_name: str | None = None):
    """Launch an invisible Chromium with a dedicated persistent profile.

    The profile lives under accounts/<profile_name>/. The user signs in once
    (a visible helper window opens the first time, see login_tiktok_headless()),
    and every subsequent run reuses the saved session — fully invisible.

    `profile_name` selects which profile to use. Defaults to
    `tiktok_headless` — the one created by login_tiktok_headless(). When the
    tab was discovered via scan_account_profiles(), the corresponding
    account profile is used so its saved TikTok cookies apply.
    """
    from .browser import launch_profile
    name = profile_name or _TIKTOK_HEADLESS_PROFILE
    return await launch_profile(pw, name, channel="chromium", headless=True)


async def _shutdown_headless(pw, ctx) -> None:
    """Tear down the headless context and Playwright instance cleanly."""
    try:
        await ctx.close()
    except Exception:
        pass
    try:
        await pw.stop()
    except Exception:
        pass


async def login_tiktok_headless() -> dict:
    """Open a *visible* window using the headless profile so the user can sign
    in once. Subsequent runs use headless mode with the saved session."""
    from playwright.async_api import async_playwright
    from .browser import launch_profile
    pw = await async_playwright().start()
    ctx = await launch_profile(pw, _TIKTOK_HEADLESS_PROFILE,
                               channel="chromium", headless=False)
    page = ctx.pages[0] if ctx.pages else await ctx.new_page()
    await page.goto("https://www.tiktok.com/login", wait_until="domcontentloaded", timeout=20000)
    return {
        "ok": True,
        "message": "A visible Chrome window opened with the headless profile. "
                   "Sign in to TikTok, then close the window — your session "
                   "is saved and future runs will be invisible.",
        "profile": str(profile_dir(_TIKTOK_HEADLESS_PROFILE)),
        "page_url": page.url,
        "pw": pw,
        "ctx": ctx,
    }


async def login_tiktok_profile(profile_name: str) -> dict:
    """Open a visible Chrome using an arbitrary account profile so the user
    can sign in to TikTok. The session is saved to that profile's Cookies
    file; subsequent headless runs with that profile will be logged in."""
    from playwright.async_api import async_playwright
    from .browser import launch_profile
    pw = await async_playwright().start()
    ctx = await launch_profile(pw, profile_name, channel="chromium", headless=False)
    page = ctx.pages[0] if ctx.pages else await ctx.new_page()
    await page.goto("https://www.tiktok.com/login", wait_until="domcontentloaded", timeout=20000)
    return {
        "ok": True,
        "message": f"A visible Chrome window opened with profile '{profile_name}'. "
                   "Sign in to TikTok, then close the window — the session is "
                   "saved and future headless runs will reuse it.",
        "profile": str(profile_dir(profile_name)),
        "page_url": page.url,
        "pw": pw,
        "ctx": ctx,
    }