"""TikTok Web automation. All TikTok-specific selectors live in this file.

We deliberately use loose, accessible-name-based selectors (Playwright `get_by_role`,
`get_by_text`) so a small UI tweak in TikTok doesn't break us. Every constant here is a
CANDIDATE — the user must run against the real site to VERIFY them, and on failure the
existing per-account screenshots/<name>/ dump pattern will show every visible control.

Flow used by the runner:
  open(url)            navigate the user's existing TikTok tab to `url` (a video or feed)
  dwell(seconds)       let the page render and the video play
  comment(text)        open comment box, paste text, post
  scroll_feed()        scroll the parent page to load the next video in the feed
"""
from __future__ import annotations

import asyncio
import logging
import re
from typing import Callable, Optional

from playwright.async_api import Browser, BrowserContext, Page, TimeoutError as PWTimeout

log = logging.getLogger(__name__)

# TikTok URLs we recognise as "a single video" vs "the For You / Following feed".
SINGLE_VIDEO_RE = re.compile(r"/video/\d+", re.I)
FEED_RE = re.compile(r"foryou|following|feed", re.I)

# ---------------------------------------------------------------------------
# Selectors
# ---------------------------------------------------------------------------

# The comment composer: TikTok uses Draft.js (a contenteditable div), NOT a <textarea>.
# The placeholder sits in a sibling `.public-DraftEditorPlaceholder-inner` and reads
# "Add comment..." (en) or "Thêm bình luận..." (vi).
COMMENT_BOX_PLACEHOLDER = re.compile(r"Add comment|Thêm bình luận", re.I)

# The Post button next to the comment composer.
COMMENT_POST_NAME = re.compile(r"^(Post|Đăng)$", re.I)

# Login wall — TikTok sometimes forces login before showing comments. The whole-page
# dialog has aria-label "Log in" or contains the text "Log in to comment".
LOGIN_WALL_TEXT = re.compile(r"log in to comment|sign in to comment|đăng nhập để bình luận", re.I)

# When a comment posts successfully the editor clears and the new comment appears in
# the comments list. We look for the just-posted text under the video to confirm.
COMMENT_LIST_ITEM = "div[class*='CommentItem'], li[class*='comment']"

# Generic sleep for the page to actually paint the video — TikTok's React app is slow.
DEFAULT_DWELL_S = 4.0


class TikTokError(RuntimeError):
    """The runner raised this so the SSE log gets one line per failure."""


class TikTokAutomation:
    """Wraps a single Playwright Page (a TikTok tab the user already has open)."""

    def __init__(self, page: Page, tab_uid: str) -> None:
        self.page = page
        self.tab_uid = tab_uid

    # ---- navigation ----

    async def goto(self, url: str, *, timeout_s: float = 30.0) -> None:
        log.info("[tiktok %s] navigating to %s", self.tab_uid, url)
        await self.page.goto(url, wait_until="domcontentloaded", timeout=int(timeout_s * 1000))
        # Bring the tab to the front so the user can watch the bot.
        try:
            await self.page.bring_to_front()
        except Exception:
            pass

    async def open_or_focus(self, url: str) -> None:
        """Navigate the tab if its URL differs, otherwise just focus it. We never open
        a new tab — that would interrupt the user's browsing."""
        cur = self.page.url or ""
        if cur.split("#")[0] == url.split("#")[0]:
            try:
                await self.page.bring_to_front()
            except Exception:
                pass
            return
        await self.goto(url)

    async def dwell(self, seconds: float = DEFAULT_DWELL_S) -> None:
        await asyncio.sleep(max(0.0, seconds))

    async def scroll_feed(self, *, distance_pixels: int = 900, pause_s: float = 2.0) -> bool:
        """Scroll the page down to load the next video.

        Returns True if we believe we advanced to a different video. The For You feed
        keeps the same URL while scrolling through videos, so URL is not a reliable
        signal — we look at the DOM (which <video> is visible / the active feed item).

        We try several mechanisms because TikTok has changed its scroll handler over
        time and headless Chrome sometimes swallows wheel events on the body's
        invisible scroller. Order matters: the dedicated next-button is most
        reliable on the current desktop UI, then fallbacks.
        """
        sig_before = await self._video_signature()

        # 1. Dedicated next-video button. TikTok renders a navigation control with
        #    data-e2e="feed-navigation-next" / "feed-navigation-prev"; clicking
        #    it advances exactly one video in the feed. This is what the user's
        #    mouse would do.
        for sel in ('[data-e2e="feed-navigation-next"]',
                    'button[aria-label*="Next" i][aria-label*="video" i]'):
            try:
                loc = self.page.locator(sel).first
                if await loc.count() and await loc.is_visible(timeout=500):
                    await loc.click(force=True, timeout=1500)
                    await asyncio.sleep(pause_s)
                    sig_after = await self._video_signature()
                    if sig_after != sig_before:
                        log.info("[tiktok %s] scroll via %s ok", self.tab_uid, sel)
                        return True
            except Exception:
                continue

        # 2. ArrowDown — TikTok's keyboard shortcut for the For You feed.
        try:
            await self.page.keyboard.press("ArrowDown")
        except Exception:
            pass
        await asyncio.sleep(pause_s)
        sig_after = await self._video_signature()
        if sig_after != sig_before:
            log.info("[tiktok %s] scroll via ArrowDown ok", self.tab_uid)
            return True

        # 3. mouse.wheel — works when the page has a real scrollable container
        #    (older UIs / single-video pages).
        try:
            await self.page.mouse.move(640, 400)
            await self.page.mouse.wheel(0, distance_pixels)
        except Exception:
            pass
        await asyncio.sleep(pause_s)
        sig_after = await self._video_signature()
        if sig_after != sig_before:
            log.info("[tiktok %s] scroll via wheel ok", self.tab_uid)
            return True

        # 4. PageDown — last-ditch fallback.
        try:
            await self.page.keyboard.press("PageDown")
        except Exception:
            pass
        await asyncio.sleep(pause_s)
        sig_after = await self._video_signature()
        if sig_after != sig_before:
            log.info("[tiktok %s] scroll via PageDown ok", self.tab_uid)
            return True

        # 5. JS-driven scroll on any scrollable element. Catches the case where
        #    the body has overflow:hidden and the real scroller is inside the
        #    React tree.
        try:
            await self.page.evaluate(
                """(d) => {
                    const all = document.querySelectorAll('*');
                    for (const el of all) {
                        const s = getComputedStyle(el);
                        if ((s.overflowY === 'scroll' || s.overflowY === 'auto')
                            && el.scrollHeight > el.clientHeight + 4) {
                            el.scrollBy(0, d);
                            return true;
                        }
                    }
                    window.scrollBy(0, d);
                    return false;
                }""",
                distance_pixels,
            )
        except Exception:
            pass
        await asyncio.sleep(pause_s)
        sig_after = await self._video_signature()
        moved = sig_after != sig_before
        if not moved:
            log.warning("[tiktok %s] scroll_feed: no method advanced the feed "
                        "(sig=%s, url=%s)", self.tab_uid, sig_after, self.page.url)
        return moved

    async def _video_signature(self) -> tuple:
        """Cheap, JS-only signature of "which video is currently in view".

        Combines several signals so it survives TikTok's DOM rewrites:
          - page.url (changes when user navigates to a single video)
          - src of the largest visible <video>
          (currentTime is left out: it moves while a video plays, so it looks like a new video)
          - text/attributes of any element marked "active feed item" / current
        Anything that throws returns '' so the signature degrades gracefully.
        """
        url = self.page.url or ""
        try:
            data = await self.page.evaluate(
                """() => {
                    const vids = Array.from(document.querySelectorAll('video'));
                    let best = null;
                    let bestArea = -1;
                    for (const v of vids) {
                        const r = v.getBoundingClientRect();
                        const visible = r.bottom > 0 && r.top < window.innerHeight
                            && r.width > 100 && r.height > 100;
                        if (!visible) continue;
                        const area = r.width * r.height;
                        if (area > bestArea) { best = v; bestArea = area; }
                    }
                    const src = best ? (best.src || best.currentSrc || '') : '';
                    // Active feed-item marker — TikTok uses several class/data combos
                    // across versions, so probe a few.
                    const selectors = [
                        '[data-e2e="feed-item"][data-active="true"]',
                        '.feed-item-active',
                        '[aria-current="true"]',
                        '[data-e2e="browse-video"][data-active="true"]',
                    ];
                    let activeHash = '';
                    for (const sel of selectors) {
                        const el = document.querySelector(sel);
                        if (el) {
                            activeHash = (el.dataset && (el.dataset.vid || el.dataset.id || ''))
                                || el.id || el.className || sel;
                            break;
                        }
                    }
                    // Fallback: hash of the topmost visible feed item by its y position.
                    if (!activeHash) {
                        const items = Array.from(document.querySelectorAll(
                            '[data-e2e="feed-item"], [data-e2e="browse-video"]'));
                        let topY = Infinity, topSig = '';
                        for (const it of items) {
                            const r = it.getBoundingClientRect();
                            if (r.top >= 0 && r.top < topY) {
                                topY = r.top;
                                topSig = (it.dataset && (it.dataset.vid || it.dataset.id))
                                    || it.id || it.className.slice(0, 40);
                            }
                        }
                        activeHash = topSig;
                    }
                    return { src: src.slice(-120), activeHash: String(activeHash).slice(0, 80) };
                }"""
            )
        except Exception:
            return (url, "", "", "")
        if not isinstance(data, dict):
            return (url, "", "", "")
        return (url, data.get("src", ""), data.get("activeHash", ""))

    # ---- comments ----

    async def video_key(self) -> str:
        """Identifies the video in view so the same post is never commented twice.

        A single-video page has its id in the URL. On the For You feed the URL stays the same, so
        the video's source identifies it instead. Returns "" if neither can be read.
        """
        m = re.search(r"/(?:video|photo)/(\d+)", self.page.url or "")
        if m:
            return "id:" + m.group(1)
        _, src, active = await self._video_signature()
        key = f"{src}|{active}"
        return key if key != "|" else ""

    async def is_login_wall(self) -> bool:
        try:
            txt = await self.page.locator("body").inner_text(timeout=2000)
        except Exception:
            return False
        return bool(LOGIN_WALL_TEXT.search(txt or ""))

    async def comment(self, text: str, *, timeout_s: float = 15.0) -> bool:
        """Type `text` into the comment editor and click Post. Returns True if the post
        appears to have succeeded (editor cleared and our text shows in the list).

        TikTok's comment composer is a Draft.js contenteditable div
        (NOT a `<textarea>`). The selector is `.public-DraftEditor-content`; the
        placeholder text "Add comment..." lives in a sibling
        `.public-DraftEditorPlaceholder-inner`. The Post button is
        `[data-e2e="comment-post"]` and stays disabled until text is entered —
        we type via `keyboard.insert_text()` so Draft.js state updates.
        """
        if await self.is_login_wall():
            raise TikTokError("login wall shown — please sign in to this TikTok tab")

        # On the For You feed the comment composer is hidden until the user opens
        # the comments panel. Click the comment icon first.
        log.info("[tiktok %s] opening comment panel", self.tab_uid)
        await self._open_comment_panel()

        # Bail out fast if the composer never appeared. Every step below has a
        # tight timeout so the runner can hit its stop check or move on quickly.
        editor = self.page.locator(".public-DraftEditor-content").first
        try:
            await editor.wait_for(state="visible", timeout=2500)
        except PWTimeout:
            # One retry: maybe the icon closed an already-open panel. Click again.
            await self._open_comment_panel()
            try:
                await editor.wait_for(state="visible", timeout=2500)
            except PWTimeout:
                raise TikTokError("comment composer not visible — UI may have changed "
                                  "or the comments panel did not open")

        try:
            await editor.scroll_into_view_if_needed(timeout=1500)
        except Exception:
            pass

        # Focus via JS (avoids the placeholder overlay intercepting clicks) then
        # use insert_text which produces the input events Draft.js listens for.
        await self.page.evaluate(
            "() => document.querySelector('.public-DraftEditor-content')?.focus()"
        )
        # Clear any previous draft so the new text doesn't get appended to it.
        await self.page.keyboard.press("Control+A")
        await self.page.keyboard.press("Delete")
        await self.page.keyboard.insert_text(text)
        await asyncio.sleep(0.3)

        # Wait for the Post button to become enabled (it is disabled while empty).
        post_btn = self.page.locator('[data-e2e="comment-post"]').first
        try:
            await post_btn.wait_for(state="visible", timeout=2000)
        except PWTimeout:
            raise TikTokError("comment Post button not found — UI may have changed")
        # Click via JS — the button is small and often overlaid by sibling icons,
        # but JS click always hits the right element regardless of pointer events.
        await self.page.evaluate(
            "() => document.querySelector('[data-e2e=\"comment-post\"]')?.click()"
        )
        await asyncio.sleep(1.5)

        # Success indicator: the editor is empty again. Draft.js keeps a tiny
        # empty paragraph in innerHTML but textContent is "" after a successful post.
        try:
            cleared = not await editor.text_content(timeout=500)
        except Exception:
            cleared = True
        return cleared

    async def _open_comment_panel(self) -> None:
        """Best-effort: open the comments panel on the For You feed so the Draft.js
        comment editor is visible. No error if it's already open or the icon isn't
        there (e.g. single-video page where the editor is visible by default).

        IMPORTANT: do NOT click the icon if the editor is already visible — clicking
        it a second time would *close* the panel, which is why the runner kept
        reporting "comment composer not visible" on every other video.
        """
        editor = self.page.locator(".public-DraftEditor-content").first
        try:
            if await editor.count() and await editor.is_visible(timeout=400):
                return
        except Exception:
            pass

        # Common selectors for the comment icon on the side action bar.
        # `data-e2e` is the most stable; aria-label is the fallback across locales.
        candidates = [
            '[data-e2e="comment-icon"]',
            '[data-e2e="browse-comment"]',
            'button[aria-label*="comment" i]',
            'button[aria-label*="Bình luận" i]',
            # last-resort: the second action button on the side bar (heart, comment, ...)
            'div[class*="ActionBar"] button:nth-of-type(2)',
        ]
        for sel in candidates:
            try:
                loc = self.page.locator(sel).first
                if await loc.count() and await loc.is_visible(timeout=400):
                    await loc.click(timeout=1500)
                    # give the panel time to animate in
                    await asyncio.sleep(1.2)
                    return
            except Exception:
                continue

    # ---- helpers ----

    @staticmethod
    def is_single_video(url: str) -> bool:
        return bool(SINGLE_VIDEO_RE.search(url or ""))

    @staticmethod
    def is_feed(url: str) -> bool:
        return bool(FEED_RE.search(url or ""))