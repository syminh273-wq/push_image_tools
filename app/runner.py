from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import AsyncIterator, Callable

from playwright.async_api import Playwright, TimeoutError as PWTimeout, async_playwright

from . import accounts, models_store, store
from .browser import launch_attach_profile, launch_profile
from .gemini import (GeminiAuthError, GeminiAutomation, GeminiChallengeError, GeminiError,
                     GeminiNoVideoToolError, GeminiQuotaError)
from .media import prepare_reference_video
from .models import Job, ValidationError, resolve_prompt, validate_image, validate_video

OUTPUT_DIR = store.PROJECT_ROOT / "output"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

log = logging.getLogger("gemini_video_tool.runner")

# run_pair exit codes. QUOTA/AUTH/CHALLENGE are account problems, not pair problems: the
# scheduler requeues the pair on another account instead of counting it as a failed attempt.
# STOPPED = cancelled by the user from the Processes tab.
RC_OK, RC_FAILED, RC_INVALID, RC_QUOTA, RC_AUTH, RC_CHALLENGE, RC_STOPPED, RC_NO_VIDEO = range(8)


@asynccontextmanager
async def _session(pw: Playwright, pair: dict, headless: bool
                   ) -> AsyncIterator[GeminiAutomation]:
    """One isolated Gemini context for this pair. Failures bubble out cleanly.

    For mode='attach': launch a fresh persistent Chrome with profile accounts/__attach__
    (no CDP attach → no 'Allow remote debugging' dialog).
    For mode='account': launch persistent Chrome with profile accounts/<account>.
    Either way each pair gets its own browser process — pairs can run in parallel.
    """
    if pair["mode"] == "attach":
        log.info("[1/7] Opening attach browser (headless=%s)...", headless)
        ctx = await launch_attach_profile(pw, headless=headless)
        gemini = GeminiAutomation(ctx, "__attach__", attached=False)
        try:
            yield gemini
        finally:
            await gemini.close()
    else:
        account = pair.get("account") or "default"
        channel = "chrome"
        log.info("[1/7] Opening browser (account=%s, headless=%s)...", account, headless)
        ctx = await launch_profile(pw, account, channel, headless=headless)
        gemini = GeminiAutomation(ctx, account)
        try:
            yield gemini
        finally:
            await gemini.close()


async def _prepare(gemini: GeminiAutomation, pair: dict) -> None:
    await gemini.open()
    log.info("[2/7] Checking authentication...")
    # Each profile must already be logged in (run `python -m app.cli login --account <name>`
    # once with a non-headless window). Background mode never prompts interactively.
    await gemini.ensure_authenticated(interactive=False)
    email = await gemini.account_email()
    log.info("Signed in as %s", email or "(email not detected)")
    accounts.record(gemini.account, "ready", email=email)
    expected = (pair.get("email") or "").strip().lower()
    if expected and email and email != expected:
        raise GeminiAuthError(
            "ensure_authenticated",
            f"Gemini is signed in as {email}, not {expected}; switch account in that "
            f"Chrome window or update the pair email.",
        )


async def _run_job(gemini: GeminiAutomation, job: Job, timeout: int) -> Path:
    step = "select_video_tool"
    try:
        files = job.files + ([prepare_reference_video(job.video, job.video_start)] if job.video else [])
        log.info("[3/7] Attaching %s...", " + ".join(f.name for f in files))
        await gemini.select_video_tool()
        step = "attach_file"
        for f in files:
            await gemini.attach_file(f)
        log.info("[4/7] Entering prompt (%d chars)...", len(job.prompt))
        step = "enter_prompt"
        await gemini.enter_prompt(job.prompt)
        log.info("[5/7] Starting generation...")
        step = "start_generation"
        await gemini.start_generation()
        log.info("[6/7] Waiting for video... (timeout %ss)", timeout)
        step = "wait_for_video"
        video = await gemini.wait_for_video(timeout)
        log.info("[7/7] Downloading video...")
        step = "download_video"
        return await gemini.download_video(job.output, video)
    except PWTimeout as e:
        raise GeminiError(step, str(e).splitlines()[0]) from e


def _job_from_pair(pair: dict) -> Job:
    images = [validate_image(Path(pair[k]).expanduser())
              for k in ("model_image", "product_image") if pair.get(k)]
    if not images and pair.get("image"):
        images = [validate_image(Path(pair["image"]).expanduser())]
    if not images:
        raise ValidationError("pair has no image")
    video = validate_video(Path(pair["video"]).expanduser()) if pair.get("video") else None
    # The prompt is the snapshot taken when the pair was queued; very old pairs may have none.
    prompt = (pair.get("prompt") or "").strip() or resolve_prompt(None, None)
    output = OUTPUT_DIR / f"{images[-1].stem}-{datetime.now():%Y%m%d-%H%M%S}.mp4"
    return Job(image=images[0], extra_images=images[1:], prompt=prompt, output=output, video=video,
               video_start=float(pair.get("video_start", 0)))


async def run_pair(pair: dict, *, headless: bool,
                   log_cb: Callable[[str], None]) -> int:
    """Run one pair. Streams log lines through log_cb. Returns exit code (0 = success)."""
    pair_id = pair["id"]
    headless_eff = headless and pair.get("mode") != "attach"

    async def emit(line: str) -> None:
        log_cb(line)

    try:
        job = _job_from_pair(pair)
    except (ValidationError, FileNotFoundError) as e:
        await emit(f"[error] invalid pair: {e}")
        store.set_status(pair_id, "failed", exit_code=RC_INVALID)
        return RC_INVALID

    await emit(f"Pair {pair_id} starting (headless={headless_eff})")
    await emit(f"  prompt: {pair.get('prompt_name') or '-'}"
               + (f" · product: {pair['product_name']}" if pair.get("product_name") else ""))
    for f in job.files:
        await emit(f"  image: {f}")
    if job.video:
        await emit(f"  video: {job.video} (start={job.video_start}s)")
    await emit(f"  output: {job.output}")
    await emit(f"  prompt ({len(job.prompt)} chars): {job.prompt[:120]}{'...' if len(job.prompt) > 120 else ''}")

    store.set_status(pair_id, "running")

    class _Stream:
        def write(self, buf: str) -> int:
            for line in buf.splitlines():
                if line:
                    log_cb(line)
            return len(buf)

        def flush(self) -> None:
            pass

    import sys as _sys
    saved_out, saved_err = _sys.stdout, _sys.stderr
    _sys.stdout = _Stream()
    _sys.stderr = _Stream()
    rc = RC_FAILED
    try:
        async with async_playwright() as pw:
            async with _session(pw, pair, headless_eff) as gemini:
                await _prepare(gemini, pair)
                try:
                    out_path = await _run_job(gemini, job, int(pair.get("timeout") or 600))
                    await emit(f"Video generated: {out_path}")
                    store.set_status(pair_id, "done", exit_code=0, output=str(out_path))
                    models_store.increment_use(pair.get("model_image"))
                    rc = RC_OK
                except (GeminiQuotaError, GeminiNoVideoToolError):
                    raise
                except GeminiError as e:
                    await emit(f"Pipeline error in {e.operation}: {e}")
                    try:
                        await gemini.dump_debug(e.operation)
                    except Exception as debug_err:  # pragma: no cover
                        await emit(f"(could not dump debug: {debug_err})")
                    store.set_status(pair_id, "failed", exit_code=1)
                    rc = RC_FAILED
    except GeminiError as e:
        await emit(f"Pipeline error in {e.operation}: {e}")
        store.set_status(pair_id, "failed", exit_code=1)
        rc = (RC_QUOTA if isinstance(e, GeminiQuotaError)
              else RC_AUTH if isinstance(e, GeminiAuthError)
              else RC_CHALLENGE if isinstance(e, GeminiChallengeError)
              else RC_NO_VIDEO if isinstance(e, GeminiNoVideoToolError) else RC_FAILED)
        account = "__attach__" if pair.get("mode") == "attach" else (pair.get("account") or "default")
        if rc == RC_AUTH:
            accounts.record(account, "signed_out", message=str(e))
        elif rc == RC_CHALLENGE:
            accounts.record(account, "verify", message=str(e))
        elif rc == RC_NO_VIDEO:
            accounts.record(account, "no_video", message="plan has no 'Create video' tool")
    except asyncio.CancelledError:
        # Stop button: the browser was already closed by the context managers above.
        await emit("[stopped by user]")
        store.set_status(pair_id, "failed", exit_code=RC_STOPPED)
        rc = RC_STOPPED
    except Exception as e:  # pragma: no cover
        await emit(f"Unexpected error: {e}")
        store.set_status(pair_id, "failed", exit_code=1)
        rc = RC_FAILED
    finally:
        _sys.stdout, _sys.stderr = saved_out, saved_err
        await emit(f"[exit {rc}]")
    return rc