"""Account registry: which profiles in accounts/ are actually signed in to Gemini.

A profile directory only proves Chrome was opened with it once, not that a Google account
is signed in. scan_all() opens each profile briefly, loads Gemini and records the result in
data/accounts.json, so the scheduler can pick accounts without the user choosing one.

Statuses:
  ready       signed in, Gemini prompt box visible
  signed_out  Gemini shows a "Sign in" link
  verify      Google shows a verification / unusual-traffic page; a person must resolve it
              in a visible window (python -m app.tools.login_accounts <name>)
  no_video    signed in, but the plan has no "Create video" tool (needs Google AI Pro/Ultra)
  error       the profile could not be opened (e.g. already open in another Chrome)
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import shutil
import threading
import time
from datetime import datetime
from typing import Iterable

from playwright.async_api import async_playwright

from . import credentials, store
from .browser import launch_profile
from .gemini import GeminiAutomation, GeminiChallengeError
from .models import ACCOUNTS_DIR, validate_account

log = logging.getLogger("gemini_video_tool.accounts")

ACCOUNTS_FILE = store.DATA_DIR / "accounts.json"
SCAN_TIMEOUT_S = 60
LOGIN_TIMEOUT_S = 15 * 60
SIGN_IN_URL = ("https://accounts.google.com/ServiceLogin?hl=en"
               "&continue=https%3A%2F%2Fgemini.google.com%2Fapp%3Fhl%3Den")

_lock = threading.RLock()
_registry: dict[str, dict] = {}
_scan_thread: threading.Thread | None = None
# name -> {"state": "waiting" | "done" | "failed" | "cancelled", "message", "cancel": Event}
_logins: dict[str, dict] = {}


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _load() -> None:
    global _registry
    try:
        raw = json.loads(ACCOUNTS_FILE.read_text(encoding="utf-8"))
        _registry = raw if isinstance(raw, dict) else {}
    except (OSError, json.JSONDecodeError):
        _registry = {}


def _persist_locked() -> None:
    tmp = ACCOUNTS_FILE.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(_registry, indent=2, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, ACCOUNTS_FILE)


def profile_names() -> list[str]:
    if not ACCOUNTS_DIR.exists():
        return []
    return [c.name for c in sorted(ACCOUNTS_DIR.iterdir())
            if c.is_dir() and not c.name.startswith(".")]


def get_all() -> list[dict]:
    """Every profile directory with its last known status ('unknown' if never scanned)."""
    with _lock:
        return [{"name": n, "status": "unknown", "email": None, "checked_at": None,
                 "message": None, **_registry.get(n, {})} for n in profile_names()]


def ready_names() -> list[str]:
    with _lock:
        return [n for n in profile_names() if _registry.get(n, {}).get("status") == "ready"]


def record(name: str, status: str, *, email: str | None = None, message: str | None = None) -> None:
    """Update one account after a scan or a real run (runs are the freshest evidence)."""
    with _lock:
        cur = _registry.get(name, {})
        cur.update(status=status, checked_at=_now(), message=message)
        if email:
            cur["email"] = email
        _registry[name] = cur
        _persist_locked()


def is_scanning() -> bool:
    return _scan_thread is not None and _scan_thread.is_alive()


async def _record_signed_in(gemini: GeminiAutomation, name: str) -> str:
    """Gemini is signed in: record ready / no_video with the email. Returns the status."""
    email = await gemini.account_email()
    if await gemini.has_video_tool():
        record(name, "ready", email=email)
        return "ready"
    record(name, "no_video", email=email, message="plan has no 'Create video' tool")
    return "no_video"


async def _scan_one(pw, name: str) -> None:
    ctx = None
    try:
        ctx = await launch_profile(pw, name, "chrome", headless=True)
        gemini = GeminiAutomation(ctx, name)
        await gemini.open()
        await gemini.check_challenge()
        if await gemini.is_authenticated():
            await _record_signed_in(gemini, name)
        else:
            record(name, "signed_out", message="Gemini shows a Sign in link")
    except GeminiChallengeError as e:
        record(name, "verify", message=str(e))
    except Exception as e:
        # Most common cause: the profile is already open in another Chrome window.
        record(name, "error", message=str(e).splitlines()[0][:200])
    finally:
        if ctx is not None:
            try:
                await ctx.close()
            except Exception:
                pass
    log.info("scanned %s: %s", name, _registry.get(name, {}).get("status"))


async def _scan(names: Iterable[str]) -> None:
    async with async_playwright() as pw:
        for name in names:  # one at a time: a burst of logins from one IP looks worse
            try:
                await asyncio.wait_for(_scan_one(pw, name), SCAN_TIMEOUT_S)
            except asyncio.TimeoutError:
                record(name, "error", message=f"no answer within {SCAN_TIMEOUT_S}s")
    # Signed out but a password is saved: sign back in (the scan's profile is closed by now).
    for name in names:
        if _registry.get(name, {}).get("status") == "signed_out" and credentials.has(name):
            try:
                start_login(name)
            except ValueError:
                pass  # a login window is already open


def scan_all(skip: Iterable[str] = (), only: Iterable[str] | None = None) -> bool:
    """Start a background scan of every profile (or just `only`) not in `skip` (busy
    accounts). Profiles with a login window open are skipped too.

    Returns False if a scan is already running.
    """
    global _scan_thread
    skip = set(skip) | {n for n in _logins if login_active(n)}
    names = [n for n in (list(only) if only is not None else profile_names()) if n not in skip]
    with _lock:
        if is_scanning():
            return False
        _scan_thread = threading.Thread(target=lambda: asyncio.run(_scan(names)),
                                        daemon=True, name="account-scan")
        _scan_thread.start()
    return True


def wait_for_scan(timeout: float | None = None) -> None:
    t = _scan_thread
    if t is not None:
        t.join(timeout)


# ---------- interactive login (Accounts tab) ----------
#
# Opens a visible Chrome window on the Google sign-in page for this profile and waits until
# Gemini is signed in. If a Gmail + password is saved for the profile (credentials.py,
# macOS Keychain) the sign-in form is filled automatically; 2-Step Verification (tap Yes on
# the phone, SMS code, ...) is always left to the user in that window.

# Google sign-in page, VERIFIED 2026-10-02:
#   /signin/identifier        input#identifierId (type=text) + button "Next"
#   /signin/challenge/pk      passkey prompt -> button "Try another way"
#   /signin/challenge/selection  options "Enter your password" / 2-Step Verification methods
#   /signin/challenge/pwd     input[name=Passwd] + button "Next"
GOOGLE_EMAIL_INPUT = "#identifierId"
GOOGLE_PASSWORD_INPUT = 'input[type="password"][name="Passwd"]'
GOOGLE_WRONG_PASSWORD = "text=/Wrong password|Sai mật khẩu/i"  # CANDIDATE
# 2-Step Verification with Google Authenticator: CANDIDATE (the probed account had no
# Authenticator set up, so this option was not on its list).
GOOGLE_TOTP_OPTION = re.compile(r"Google Authenticator", re.I)
GOOGLE_TOTP_INPUT = 'input[name="totpPin"], #totpPin'
# Phone prompt ("Tap Yes on your phone or tablet"), the default 2-Step method for most
# accounts. CANDIDATE: option label on /challenge/selection and the number-match screen.
GOOGLE_PHONE_OPTION = re.compile(r"Tap Yes on your phone or tablet|Get a notification on your phone|"
                                 r"Nhấn vào Có trên điện thoại", re.I)
GOOGLE_PHONE_PROMPT_TEXT = re.compile(r"Tap Yes|Check your phone|tap the number|Kiểm tra điện thoại", re.I)
_MATCH_NUMBER = re.compile(r"^\s*(\d{1,3})\s*$", re.M)


async def _phone_prompt_note(page) -> str | None:
    """UI note while Google waits for "Yes" on the phone; includes the number to tap when
    Google shows one (number matching)."""
    try:
        text = await page.locator("body").inner_text()
    except Exception:
        return None
    if not GOOGLE_PHONE_PROMPT_TEXT.search(text):
        return None
    m = _MATCH_NUMBER.search(text)
    if m:
        return f"Mở điện thoại / máy tính bảng, bấm Yes rồi chọn số {m.group(1)}"
    return "Mở điện thoại / máy tính bảng và bấm Yes để xác nhận đăng nhập"


async def _autofill_step(page, cred: dict, done: set[str]) -> str | None:
    """Advance Google's sign-in form by one step using the saved credentials.

    `done` remembers which steps already ran so a step is never repeated (a second
    password attempt would only lock the account). Returns a note for the UI, if any.
    """
    url = page.url
    if "accounts.google.com" not in url:
        return None
    nxt = page.get_by_role("button", name="Next", exact=True)

    # "Choose an account" list on a profile that was signed in before. CANDIDATE
    if "email" not in done and "accountchooser" in url:
        done.add("email")
        await page.get_by_text(cred["email"], exact=True).first.click()
        return "picked the saved Gmail"

    email_box = page.locator(GOOGLE_EMAIL_INPUT)
    if "email" not in done and await email_box.is_visible():
        done.add("email")
        await email_box.fill(cred["email"])
        await nxt.click()
        return "filled Gmail"

    pw_box = page.locator(GOOGLE_PASSWORD_INPUT)
    if "password" not in done and await pw_box.is_visible():
        done.add("password")
        await pw_box.fill(cred["password"])
        await nxt.click()
        return "filled password"

    if "password" in done and await page.locator(GOOGLE_WRONG_PASSWORD).count():
        return "saved password is wrong — type it in the window, then update it here"

    # Passkey prompt: switch to the password method (once).
    if "/challenge/pk" in url and "password" not in done and "pk" not in done:
        done.add("pk")
        await page.get_by_role("button", name="Try another way").click()
        return "skipping passkey"

    pick_pw = page.get_by_text("Enter your password", exact=True)
    if "/challenge/selection" in url and "password" not in done and await pick_pw.count():
        await pick_pw.first.click()
        return "choosing password"

    if cred.get("totp") and "password" in done:
        code_box = page.locator(GOOGLE_TOTP_INPUT)
        if "totp" not in done and await code_box.first.is_visible():
            done.add("totp")
            await code_box.first.fill(credentials.totp_code(cred["totp"]))
            await nxt.click()
            return "entered Authenticator code"
        pick_totp = page.get_by_text(GOOGLE_TOTP_OPTION)
        if "totp_pick" not in done and "/challenge/selection" in url and await pick_totp.count():
            done.add("totp_pick")
            await pick_totp.first.click()
            return "choosing Authenticator"
        # Google opened a different method (e.g. "tap Yes on your phone"): switch method.
        other = page.get_by_role("button", name="Try another way")
        if ("totp_pick" not in done and "/challenge/selection" not in url
                and "/challenge/pwd" not in url and await other.count()):
            await other.first.click()
            return "switching to Authenticator"

    if not cred.get("totp") and "password" in done:
        # Default 2-Step method: tap Yes on the phone. Pick it if Google lists the methods.
        pick_phone = page.get_by_text(GOOGLE_PHONE_OPTION)
        if "phone_pick" not in done and "/challenge/selection" in url and await pick_phone.count():
            done.add("phone_pick")
            await pick_phone.first.click()
            return "choosing 'Tap Yes on your phone'"

    if "password" in done and "/challenge/" in url:
        return (await _phone_prompt_note(page)
                or "Xác minh 2 bước — làm theo hướng dẫn trong cửa sổ Chrome")
    return None

def login_active(name: str) -> bool:
    info = _logins.get(name)
    return bool(info and info["state"] == "waiting")


def login_states() -> dict[str, dict]:
    return {n: {"state": i["state"], "message": i.get("message")} for n, i in _logins.items()}


async def _login(name: str, cancel: threading.Event) -> None:
    info = _logins[name]
    cred = await asyncio.to_thread(credentials.get, name)
    autofill_done: set[str] = set()
    async with async_playwright() as pw:
        ctx = await launch_profile(pw, name, "chrome", headless=False)
        try:
            gemini = GeminiAutomation(ctx, name)
            await gemini.open()
            if not await gemini.is_authenticated():
                await gemini.p.goto(SIGN_IN_URL, wait_until="domcontentloaded")
            deadline = time.monotonic() + LOGIN_TIMEOUT_S
            while time.monotonic() < deadline:
                if cancel.is_set():
                    info.update(state="cancelled", message="cancelled")
                    return
                if gemini.page is None or gemini.page.is_closed():
                    if not ctx.pages:
                        info.update(state="cancelled", message="window was closed")
                        return
                    gemini.page = ctx.pages[-1]
                try:
                    if gemini._on_gemini() and await gemini.is_authenticated():
                        status = await _record_signed_in(gemini, name)
                        info.update(state="done", message=status)
                        return
                    if cred:
                        note = await _autofill_step(gemini.page, cred, autofill_done)
                        if note:
                            info["message"] = note
                except Exception:
                    pass  # page navigating mid-check
                await asyncio.sleep(3)
            info.update(state="failed", message=f"not signed in within {LOGIN_TIMEOUT_S // 60} min")
        finally:
            try:
                await ctx.close()
            except Exception:
                pass


def start_login(name: str) -> None:
    """Open a visible Chrome window for profile `name` (created if new) on Google sign-in.

    Uses the Gmail + password saved for the profile, if any (see save_credentials)."""
    name = validate_account(name)
    with _lock:
        if login_active(name):
            raise ValueError(f"a login window for {name} is already open")
        cancel = threading.Event()
        msg = "signing in automatically…" if credentials.has(name) else "sign in in the Chrome window"
        _logins[name] = {"state": "waiting", "message": msg, "cancel": cancel}

    def run() -> None:
        try:
            asyncio.run(_login(name, cancel))
        except Exception as e:
            _logins[name].update(state="failed", message=str(e).splitlines()[0][:200])
        log.info("login %s: %s (%s)", name, _logins[name]["state"], _logins[name].get("message"))

    threading.Thread(target=run, daemon=True, name=f"login-{name}").start()


def save_credentials(name: str, email: str, password: str, totp: str | None = None) -> None:
    name = validate_account(name)
    email = email.strip()
    if "@" not in email or not password:
        raise ValueError("enter the Gmail address and its password")
    if totp:
        try:
            totp = credentials.normalize_totp(totp)
        except ValueError:
            raise ValueError("the Authenticator key is not valid (letters A-Z and digits 2-7)")
    credentials.save(name, email, password, totp)


def forget_credentials(name: str) -> bool:
    return credentials.delete(validate_account(name))


def cancel_login(name: str) -> bool:
    info = _logins.get(name)
    if not info or info["state"] != "waiting":
        return False
    info["cancel"].set()
    return True


def delete_account(name: str) -> None:
    """Delete the profile directory (signs the tool out; the Google account is untouched)."""
    name = validate_account(name)
    if login_active(name):
        raise ValueError("close the login window first")
    path = ACCOUNTS_DIR / name
    if path.resolve().parent != ACCOUNTS_DIR.resolve() or not path.is_dir():
        raise ValueError(f"no profile named {name}")
    shutil.rmtree(path)
    credentials.delete(name)
    with _lock:
        _registry.pop(name, None)
        _logins.pop(name, None)
        _persist_locked()


_load()
