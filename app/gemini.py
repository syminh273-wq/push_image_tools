"""Gemini Web automation. ALL Gemini-specific selectors live in this file.

Selector status (checked against gemini.google.com on 2026-10-01):
  VERIFIED   = seen on the live page during development.
  CANDIDATE  = signed-in-only UI; based on Gemini's accessible labels but not yet
               confirmed in this environment. On failure the debug dump in
               screenshots/<account>/ lists every control on the page so these
               can be corrected quickly.
"""
from __future__ import annotations

import asyncio
import base64
import logging
import re
import sys
import time
from datetime import datetime
from pathlib import Path

from playwright.async_api import BrowserContext, Locator, Page
from playwright.async_api import TimeoutError as PWTimeout

from .models import SCREENSHOTS_DIR

log = logging.getLogger(__name__)

GEMINI_URL = "https://gemini.google.com/app"
GEMINI_HOST = "gemini.google.com"
# hl=en forces the English UI in the tool's tab, so the English labels below match even when
# the account's language is Vietnamese (other tabs keep their own language).
GEMINI_START_URL = GEMINI_URL + "?hl=en"
# How long a non-interactive run waits for a manual login in the browser window.
LOGIN_POLL_TIMEOUT_S = 600

# ---------------------------------------------------------------------------
# Selectors
# ---------------------------------------------------------------------------

# VERIFIED: signed-out pages show a "Sign in" link to accounts.google.com/ServiceLogin.
SIGN_IN_LINK = 'a[href^="https://accounts.google.com/ServiceLogin"]'

# VERIFIED (vi): the avatar link is labelled "Tài khoản Google: <name> (<email>)";
# English UI: "Google Account: <name> (<email>)".
ACCOUNT_BUTTON = ('a[aria-label*="Google Account"], a[aria-label*="Tài khoản Google"], '
                  'a[href*="accounts.google.com/SignOutOptions"]')
EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+(\.[\w-]+)+")

# VERIFIED: the prompt box is a Quill editor exposed as role=textbox with this label
# (vi: "Nhập câu lệnh cho Gemini").
PROMPT_BOX_NAME = re.compile(r"Enter a prompt|Nhập câu lệnh", re.I)

# VERIFIED (signed-in, 2026-10-01): the "+" button left of the prompt is "Upload & tools"
# (vi: "Nội dung tải lên và công cụ"); its menu holds both "Upload files" and the
# "Create video" tool. Signed-out / older UI: "Add files", "Open upload file menu".
ADD_FILES_BUTTON_NAME = re.compile(
    r"^(Upload & tools|Nội dung tải lên và công cụ|Add files|Open upload file menu)$", re.I)

# Older UI only: a separate "Tools" button. VERIFIED: the video tool is the menuitemcheckbox
# "Create video" in the "Upload & tools" menu.
TOOLS_BUTTON_NAME = re.compile(r"^Tools$", re.I)
VIDEO_TOOL_NAME = re.compile(r"video", re.I)
# VERIFIED: extra tools (sometimes including "Create video") sit behind "More tools".
MORE_TOOLS_NAME = re.compile(r"^(More tools|Công cụ khác|Thêm công cụ)$", re.I)
# VERIFIED: once selected, the tool shows as a chip with a "Deselect Videos" button.
VIDEO_TOOL_ACTIVE_NAME = re.compile(r"Deselect.*video", re.I)
# VERIFIED: first use of the video tool opens a "Create videos" intro dialog with "Try it".
INTRO_DISMISS_NAME = re.compile(r"^(Try it|Got it|Dùng thử|Đã hiểu)$", re.I)

# VERIFIED: a reference video longer than 10s opens a trim dialog with this hint.
TRIM_DIALOG_TEXT = re.compile(r"reference videos up to", re.I)

# VERIFIED: a pasted image shows as a blob: <img> next to a "close attachment" button.
# One "close attachment" button is shown per attached file (image or video).
ATTACHMENT_CHIP = "button[aria-label='close attachment']"
MIME_TYPES = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp",
              ".mp4": "video/mp4", ".mov": "video/quicktime", ".webm": "video/webm"}

# VERIFIED: the send button is "Send message" (enabled once text or an image is present).
SEND_BUTTON_NAME = re.compile(r"^Send message$", re.I)
STOP_BUTTON_NAME = re.compile(r"^Stop", re.I)

# CANDIDATE: model responses are <model-response> custom elements; videos are <video>.
MODEL_RESPONSE = "model-response"
VIDEO = "video"
# VERIFIED: the finished video is a <video src="https://contribution.usercontent.google.com/download?...">
# inside <video-player>, with a "Download video" button next to it.
DOWNLOAD_BUTTON_NAME = re.compile(r"^Download video$|Download", re.I)

# Response text that means Gemini refused or failed instead of producing a video.
FAILURE_TEXT = re.compile(
    r"(can't|cannot|couldn't|unable to) (create|generate|make)|"
    r"reached your (daily )?limit|try again later|something went wrong",
    re.I,
)
# Subset of failures that mean this account is out of video quota (switch to another account).
QUOTA_TEXT = re.compile(
    r"reached your (daily |video )?(generation )?limit|limit (for|on) (video|generat)|"
    r"quota|try again tomorrow|come back tomorrow|out of (video )?generations",
    re.I,
)


# Google verification / anti-abuse pages. Seeing one means: stop using this account and let a
# person clear it in a visible window.
CHALLENGE_URL = re.compile(r"google\.com/sorry/|accounts\.google\.com/.*(challenge|signin/rejected|speedbump)",
                           re.I)
CHALLENGE_TEXT = re.compile(
    r"unusual traffic|verify it'?s you|confirm it'?s you|couldn'?t sign you in|"
    r"this browser or app may not be secure|not a robot|automated queries|"
    r"lưu lượng truy cập bất thường|xác minh đó là bạn",
    re.I,
)
CAPTCHA_FRAME = "iframe[src*='recaptcha'], iframe[title*='reCAPTCHA']"


# Pastes a file into the prompt box (no OS file dialog involved).
PASTE_FILE_JS = """async ([b64, name, mime]) => {
  const bin = atob(b64); const bytes = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);
  const data = new DataTransfer();
  data.items.add(new File([bytes], name, {type: mime}));
  const box = document.querySelector('[role=textbox][contenteditable=true]') || document.querySelector('[role=textbox]');
  if (!box) return false;
  box.focus();
  box.dispatchEvent(new ClipboardEvent('paste', {clipboardData: data, bubbles: true, cancelable: true}));
  return true;
}"""

VIDEO_SRC_JS = "v => v.currentSrc || v.src || (v.querySelector('source') || {}).src || ''"

# Fetches a URL (blob: or https:) inside the page, so the page's cookies apply.
FETCH_AS_BASE64_JS = """async (u) => {
  try {
    const r = await fetch(u, {credentials: 'include'});
    if (!r.ok) return '';
    const b = await r.blob();
    return await new Promise(res => { const fr = new FileReader();
      fr.onload = () => res(fr.result.split(',')[1]); fr.readAsDataURL(b); });
  } catch (e) { return ''; }
}"""


class GeminiError(RuntimeError):
    def __init__(self, operation: str, message: str):
        super().__init__(f"{operation}: {message}")
        self.operation = operation


class GeminiQuotaError(GeminiError):
    """The account hit its video generation limit."""


class GeminiAuthError(GeminiError):
    """The account profile is not signed in (or signed in as the wrong Gmail)."""


class GeminiNoVideoToolError(GeminiError):
    """This account's Gemini has no "Create video" tool (plan without Veo). Retrying on the
    same account is pointless; the pair should move to another account."""


class GeminiChallengeError(GeminiError):
    """Google showed a verification / unusual-traffic page. A person has to resolve it in a
    visible window; retrying automatically only makes the account look worse."""


async def _first_visible(candidates: list[Locator], timeout_ms: int) -> Locator | None:
    """Return the first candidate that becomes visible within timeout_ms."""
    deadline = time.monotonic() + timeout_ms / 1000
    while time.monotonic() < deadline:
        for loc in candidates:
            try:
                if await loc.first.is_visible():
                    return loc.first
            except Exception:
                pass
        await asyncio.sleep(0.5)
    return None


class GeminiAutomation:
    def __init__(self, context: BrowserContext, account: str, attached: bool = False):
        """attached=True: the context belongs to the user's own running Chrome, so the tool
        works only in a tab it opens itself and never closes the user's browser or tabs."""
        self.context = context
        self.account = account
        self.attached = attached
        self.page: Page | None = None
        self._videos_before = 0
        self._responses_before = 0

    # -- lifecycle ---------------------------------------------------------

    async def open(self) -> None:
        if self.attached or not self.context.pages:
            self.page = await self.context.new_page()
        else:
            self.page = self.context.pages[0]
        if self.attached:
            await self.page.bring_to_front()  # let the user watch the tool's tab
        await self.page.goto(GEMINI_START_URL, wait_until="domcontentloaded")
        # Gemini renders client-side; wait until either the prompt box or a Sign in link exists.
        await _first_visible([self._prompt_box(), self.page.locator(SIGN_IN_LINK)], 30_000)
        await self.check_challenge()

    async def check_challenge(self) -> None:
        """Raise GeminiChallengeError if Google is asking for verification instead of Gemini."""
        p = self.p
        if CHALLENGE_URL.search(p.url) or await p.locator(CAPTCHA_FRAME).count():
            raise GeminiChallengeError("check_challenge", f"Google verification page: {p.url}")
        if self._on_gemini() and await self._prompt_box().first.is_visible():
            return  # normal Gemini page; skip the (slow) full-text check
        try:
            text = await p.locator("body").inner_text(timeout=5_000)
        except Exception:
            return
        m = CHALLENGE_TEXT.search(text)
        if m:
            raise GeminiChallengeError("check_challenge", f"Google asks for verification ({m.group(0)!r})")

    async def new_chat(self) -> None:
        await self.p.goto(GEMINI_START_URL, wait_until="domcontentloaded")
        if not await _first_visible([self._prompt_box()], 30_000):
            raise GeminiError("new_chat", "prompt box did not appear")

    async def close(self) -> None:
        if self.attached:
            if self.page and not self.page.is_closed():
                await self.page.close()
            return
        await self.context.close()

    @property
    def p(self) -> Page:
        if self.page is None:
            raise GeminiError("page", "open() has not been called")
        return self.page

    def _on_gemini(self) -> bool:
        # Any Gemini page counts: /app, /app/<chat id>, /u/1/app (multi-login), ?hl=...
        return self.p.url.split("/")[2:3] == [GEMINI_HOST]

    def _prompt_box(self) -> Locator:
        return self.p.get_by_role("textbox", name=PROMPT_BOX_NAME)

    # -- authentication ----------------------------------------------------

    async def is_authenticated(self) -> bool:
        if not self._on_gemini():
            return False
        if await self.p.locator(SIGN_IN_LINK).count() > 0:
            return False
        return await self._prompt_box().first.is_visible()

    async def account_email(self) -> str | None:
        """Email of the Google account Gemini is signed in with, read from the avatar link."""
        for loc in (self.p.locator(ACCOUNT_BUTTON), self.p.locator("[aria-label*='@']")):
            for i in range(await loc.count()):
                m = EMAIL_RE.search(await loc.nth(i).get_attribute("aria-label") or "")
                if m:
                    return m.group(0).lower()
        return None

    async def ensure_authenticated(self, interactive: bool = True) -> None:
        if await self.is_authenticated():
            log.info("Session is authenticated.")
            return
        if not interactive:
            raise GeminiAuthError("ensure_authenticated", "not logged in; run the login command first")
        if not sys.stdin.isatty():
            # No terminal to press Enter in: poll until the user finishes logging in.
            print(f"\nPlease log in to your Gemini account in the browser window "
                  f"(waiting up to {LOGIN_POLL_TIMEOUT_S // 60} min).")
            deadline = time.monotonic() + LOGIN_POLL_TIMEOUT_S
            while time.monotonic() < deadline:
                await asyncio.sleep(3)
                # Login may close or replace the tab; follow whichever page is still open.
                if self.page is None or self.page.is_closed():
                    # In the user's own Chrome, never take over one of their other tabs.
                    if self.attached or not self.context.pages:
                        raise GeminiError("ensure_authenticated", "browser window was closed before login finished")
                    self.page = self.context.pages[-1]
                try:
                    if await self.is_authenticated():
                        log.info("Login confirmed.")
                        return
                except Exception as e:  # page navigating mid-check
                    log.debug("auth check skipped: %s", e)
            raise GeminiError("ensure_authenticated", "login was not completed in time")
        for _ in range(3):
            print(
                "\nPlease log in to your Gemini account in the browser window.\n"
                "Complete any required verification manually.\n"
                "After Gemini is ready, press Enter in this terminal."
            )
            await asyncio.to_thread(input)
            if not self._on_gemini():
                await self.p.goto(GEMINI_START_URL, wait_until="domcontentloaded")
            await _first_visible([self._prompt_box()], 15_000)
            if await self.is_authenticated():
                log.info("Login confirmed.")
                return
            print("Gemini still does not look signed in (a 'Sign in' link is visible).")
        raise GeminiError("ensure_authenticated", "login was not completed")

    # -- generation steps --------------------------------------------------

    async def select_video_tool(self) -> None:
        p = self.p
        if not await p.get_by_role("button", name=VIDEO_TOOL_ACTIVE_NAME).count():
            tools = await _first_visible([p.get_by_role("button", name=TOOLS_BUTTON_NAME)], 2_000)
            if tools:
                await tools.click()
            else:
                # Current UI: the tools live in the "Upload & tools" (+) menu.
                await p.get_by_role("button", name=ADD_FILES_BUTTON_NAME).first.click()
            candidates = [
                p.get_by_role("menuitemcheckbox", name=VIDEO_TOOL_NAME),
                p.get_by_role("menuitem", name=VIDEO_TOOL_NAME),
                p.locator(".cdk-overlay-container").get_by_role("button", name=VIDEO_TOOL_NAME),
            ]
            item = await _first_visible(candidates, 4_000)
            if not item:
                # VERIFIED (2026-10-02): some accounts list only a few tools and hide the rest,
                # including "Create video", behind a "More tools" entry in the same menu.
                more = await _first_visible([p.get_by_role("button", name=MORE_TOOLS_NAME),
                                             p.get_by_role("menuitem", name=MORE_TOOLS_NAME)], 2_000)
                if more:
                    await more.click()
                    item = await _first_visible(candidates, 8_000)
            if not item:
                raise GeminiNoVideoToolError("select_video_tool", "no 'Create video' in the tools menu: "
                                             "this account's plan has no video generation")
            await item.click()
        await self._dismiss_intro()
        if not await _first_visible([p.get_by_role("button", name=VIDEO_TOOL_ACTIVE_NAME)], 10_000):
            raise GeminiError("select_video_tool", "video tool did not become active")

    async def has_video_tool(self) -> bool:
        """Open the tools menu (and "More tools") and report whether "Create video" exists."""
        p = self.p
        if await p.get_by_role("button", name=VIDEO_TOOL_ACTIVE_NAME).count():
            return True
        await p.get_by_role("button", name=ADD_FILES_BUTTON_NAME).first.click()
        items = [p.get_by_role("menuitemcheckbox", name=VIDEO_TOOL_NAME),
                 p.get_by_role("menuitem", name=VIDEO_TOOL_NAME)]
        found = await _first_visible(items, 3_000)
        if not found:
            more = await _first_visible([p.get_by_role("button", name=MORE_TOOLS_NAME)], 2_000)
            if more:
                await more.click()
                found = await _first_visible(items, 3_000)
        await p.keyboard.press("Escape")
        return found is not None

    async def _dismiss_intro(self) -> None:
        """The first time the video tool is used Gemini shows a "Create videos" intro dialog."""
        button = await _first_visible([self.p.get_by_role("button", name=INTRO_DISMISS_NAME)], 3_000)
        if button:
            log.debug("Dismissing the video tool intro dialog.")
            await button.click()
            await asyncio.sleep(1)

    async def attach_file(self, path: Path) -> None:
        """Paste a file (image or video) into the prompt box, like Cmd+V; no OS file dialog."""
        p = self.p
        chips = p.locator(ATTACHMENT_CHIP)
        before = await chips.count()
        mime = MIME_TYPES.get(path.suffix.lower(), "application/octet-stream")
        await self._prompt_box().first.click()
        pasted = await p.evaluate(PASTE_FILE_JS, [base64.b64encode(path.read_bytes()).decode(), path.name, mime])
        if not pasted:
            raise GeminiError("attach_file", "prompt box not found for pasting")
        # Videos take longer to upload than images.
        if not await self._wait_count_above(chips, before, 120_000 if mime.startswith("video/") else 30_000):
            raise GeminiError("attach_file", f"{path.name} did not appear as an attachment after pasting")
        if mime.startswith("video/") and await _first_visible([p.get_by_text(TRIM_DIALOG_TEXT)], 2_000):
            raise GeminiError("attach_file", f"Gemini asks to trim {path.name}: reference videos must be "
                                             f"10s or shorter")
        log.info("Attached %s.", path.name)

    async def enter_prompt(self, prompt: str) -> None:
        box = self._prompt_box().first
        await box.click()
        await box.fill(prompt)
        text = (await box.inner_text()).strip()
        if prompt.strip()[:30] not in text:
            raise GeminiError("enter_prompt", "prompt text did not land in the input box")

    async def start_generation(self) -> None:
        p = self.p
        self._videos_before = await p.locator(VIDEO).count()
        self._responses_before = await p.locator(MODEL_RESPONSE).count()
        send = p.get_by_role("button", name=SEND_BUTTON_NAME).first
        try:
            # The send button stays disabled while the image is still uploading.
            await send.wait_for(state="visible", timeout=30_000)
            deadline = time.monotonic() + 60
            while not await send.is_enabled():
                if time.monotonic() > deadline:
                    raise GeminiError("start_generation", "send button stayed disabled")
                await asyncio.sleep(0.5)
            await send.click()
        except PWTimeout as e:
            raise GeminiError("start_generation", "send button not found") from e
        if not await self._wait_count_above(p.locator(MODEL_RESPONSE), self._responses_before, 60_000):
            raise GeminiError("start_generation", "Gemini did not start a response after sending")
        log.info("Generation started.")

    async def wait_for_video(self, timeout_s: int = 600) -> Locator:
        """Wait until the newest response holds a finished video; screenshot progress each minute.

        Gemini shows a grey placeholder while generating, so a video only counts once it has
        an http(s) source and the stop button is gone.
        """
        p = self.p
        deadline = time.monotonic() + timeout_s
        last_report = last_shot = 0.0
        # VERIFIED (2026-10-03): after "Something went wrong" the Stop button can stay on screen
        # forever, so an error text that stays unchanged this long counts even while "busy".
        stuck_after = 30.0
        failure_seen: tuple[str, float] | None = None
        while time.monotonic() < deadline:
            responses = p.locator(MODEL_RESPONSE)
            latest = responses.last
            busy = await p.get_by_role("button", name=STOP_BUTTON_NAME).count()
            if await responses.count() > self._responses_before:
                videos = latest.locator(VIDEO)
                for k in range(await videos.count()):
                    src = await videos.nth(k).evaluate(VIDEO_SRC_JS)
                    if src.startswith("http") and not busy:
                        log.info("Video ready.")
                        return videos.nth(k)
            text = (await latest.inner_text()).strip() if await latest.count() else ""
            now = time.monotonic()
            failed = bool(text) and bool(QUOTA_TEXT.search(text) or FAILURE_TEXT.search(text))
            if failed and (failure_seen is None or failure_seen[0] != text):
                failure_seen = (text, now)
            elif not failed:
                failure_seen = None
            if failure_seen and (not busy or now - failure_seen[1] >= stuck_after):
                if QUOTA_TEXT.search(text):
                    raise GeminiQuotaError("wait_for_video", f"account out of quota: {text[:300]}")
                raise GeminiError("wait_for_video", f"Gemini reported a failure: {text[:300]}")
            if now - last_report > 30:
                elapsed = int(timeout_s - (deadline - now))
                log.info("  still generating (%ss)... %s", elapsed, text[:80].replace("\n", " "))
                last_report = now
            if now - last_shot > 60:
                await self._progress_shot()
                last_shot = now
            await asyncio.sleep(5)
        raise GeminiError("wait_for_video", f"no video after {timeout_s}s")

    async def download_video(self, output_path: Path, video: Locator | None = None) -> Path:
        p = self.p
        output_path.parent.mkdir(parents=True, exist_ok=True)
        if video is None:
            video = p.locator(MODEL_RESPONSE).last.locator(VIDEO).last

        # Preferred: fetch the video's own source inside the page, with the page's session.
        # Works the same in the user's Chrome and in a tool profile.
        src = await video.evaluate(VIDEO_SRC_JS)
        if src.startswith("http"):
            b64 = await p.evaluate(FETCH_AS_BASE64_JS, src)
            if b64:
                output_path.write_bytes(base64.b64decode(b64))
                log.info("Saved video source.")
                return self._check_mp4(output_path)
            log.warning("Fetching the video source failed; trying the Download button.")

        # Fallback: Gemini's "Download video" button -> browser download event.
        response = p.locator(MODEL_RESPONSE).last
        button = await _first_visible(
            [response.get_by_role("button", name=DOWNLOAD_BUTTON_NAME),
             p.get_by_role("button", name=DOWNLOAD_BUTTON_NAME)],
            5_000,
        )
        if not button:
            raise GeminiError("download_video", "no video source and no Download button")
        try:
            async with p.expect_download(timeout=120_000) as dl_info:
                await button.click()
            download = await dl_info.value
            await download.save_as(str(output_path))
        except PWTimeout as e:
            raise GeminiError("download_video", "Download button gave no download (check your "
                                                "Chrome Downloads folder)") from e
        log.info("Saved via Download button.")
        return self._check_mp4(output_path)

    async def _wait_count_above(self, loc: Locator, before: int, timeout_ms: int) -> bool:
        deadline = time.monotonic() + timeout_ms / 1000
        while time.monotonic() < deadline:
            if await loc.count() > before:
                return True
            await asyncio.sleep(0.5)
        return False

    async def _progress_shot(self) -> None:
        out_dir = SCREENSHOTS_DIR / self.account
        out_dir.mkdir(parents=True, exist_ok=True)
        try:
            await self.p.screenshot(path=str(out_dir / "progress.png"))
        except Exception as e:
            log.debug("progress screenshot failed: %s", e)

    @staticmethod
    def _check_mp4(path: Path) -> Path:
        data = path.read_bytes()[:12] if path.exists() else b""
        if len(data) < 12 or data[4:8] != b"ftyp":
            log.warning("Downloaded file does not look like an MP4 (no 'ftyp' header): %s", path)
        if not path.exists() or path.stat().st_size == 0:
            raise GeminiError("download_video", "downloaded file is empty")
        return path

    # -- debugging ---------------------------------------------------------

    async def dump_debug(self, operation: str) -> Path | None:
        """Save screenshot, HTML and a list of visible controls for selector repair."""
        if self.page is None or self.page.is_closed():
            return None
        out_dir = SCREENSHOTS_DIR / self.account
        out_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        shot = out_dir / f"error-{stamp}.png"
        try:
            await self.page.screenshot(path=str(shot), full_page=True)
            (out_dir / f"error-{stamp}.html").write_text(await self.page.content(), encoding="utf-8")
            controls = await self.page.evaluate(
                """() => [...document.querySelectorAll(
                     'button,a,[role=button],[role=menuitem],[role=menuitemcheckbox],[role=textbox],input,video')]
                   .filter(e => e.getClientRects().length)
                   .map(e => [e.tagName, e.getAttribute('role') || '', e.getAttribute('aria-label') || '',
                              (e.innerText || '').trim().replace(/\\s+/g, ' ').slice(0, 60)].join(' | '))"""
            )
            (out_dir / f"error-{stamp}.controls.txt").write_text(
                f"operation: {operation}\nurl: {self.page.url}\n\n" + "\n".join(controls), encoding="utf-8"
            )
        except Exception as e:  # never let debugging hide the real error
            log.warning("Could not save debug info: %s", e)
        print(f"Failed operation: {operation}")
        print(f"Current URL: {self.page.url}")
        print(f"Debug files: {out_dir}/error-{stamp}.*")
        return shot
