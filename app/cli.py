from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import AsyncIterator

from playwright.async_api import Playwright, async_playwright
from playwright.async_api import TimeoutError as PWTimeout

from .browser import connect_running_chrome, launch_profile, profile_dir
from .gemini import GeminiAutomation, GeminiError
from .media import prepare_reference_video
from .models import (PROJECT_ROOT, Job, ValidationError, load_jobs, resolve_prompt, validate_account,
                     validate_image, validate_video)

log = logging.getLogger("gemini_video_tool")


async def _keep_open(enabled: bool) -> None:
    if enabled:
        print("Browser left open for debugging. Press Enter to close it.")
        await asyncio.to_thread(input)


@asynccontextmanager
async def session(pw: Playwright, args: argparse.Namespace) -> AsyncIterator[GeminiAutomation]:
    """A Gemini tab in either the user's running Chrome (--attach) or a tool profile (--account)."""
    if args.attach:
        log.info("[1/7] Connecting to your running Chrome...")
        try:
            browser = await connect_running_chrome(pw)
        except FileNotFoundError as e:
            raise ValidationError(str(e)) from e
        except Exception as e:
            raise GeminiError("connect", f"could not connect to Chrome (approve the connection "
                                         f"prompt in Chrome?): {str(e).splitlines()[0]}") from e
        if not browser.contexts:
            await browser.close()
            raise GeminiError("connect", "Chrome has no open window; open one and try again")
        gemini = GeminiAutomation(browser.contexts[0], "attached", attached=True)
        try:
            yield gemini
        finally:
            await gemini.close()  # closes only the tab the tool opened
            await browser.close()  # for a connected browser this only disconnects
    else:
        log.info("[1/7] Opening browser (profile: %s)...", profile_dir(args.account))
        gemini = GeminiAutomation(await launch_profile(pw, args.account, args.channel), args.account)
        try:
            yield gemini
        finally:
            await gemini.close()


async def prepare(gemini: GeminiAutomation, args: argparse.Namespace) -> None:
    await gemini.open()
    log.info("[2/7] Checking authentication...")
    await gemini.ensure_authenticated(interactive=True)
    email = await gemini.account_email()
    log.info("Signed in as %s", email or "(email not detected)")
    if args.email and email and email != args.email.strip().lower():
        raise GeminiError("ensure_authenticated",
                          f"Gemini is signed in as {email}, not {args.email}; switch account in that "
                          f"Chrome window or drop --email")


async def run_job(gemini: GeminiAutomation, job: Job, timeout: int) -> Path:
    step = "select_video_tool"
    try:
        # Gemini references at most 10s of video; longer clips are trimmed locally first.
        files = [job.image] + ([prepare_reference_video(job.video, job.video_start)] if job.video else [])
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
        # A selector that never matched: report it as a step failure so debug files get saved.
        raise GeminiError(step, str(e).splitlines()[0]) from e


async def cmd_login(args: argparse.Namespace) -> int:
    async with async_playwright() as pw:
        async with session(pw, args) as gemini:
            try:
                await prepare(gemini, args)
            except GeminiError as e:
                log.error("%s", e)
                await gemini.dump_debug(e.operation)
                await _keep_open(args.keep_open_on_error)
                return 1
    print(f"Account '{args.account}' is logged in. Profile saved at {profile_dir(args.account)}")
    return 0


async def cmd_jobs(args: argparse.Namespace, jobs: list[Job]) -> int:
    failures = 0
    async with async_playwright() as pw:
        async with session(pw, args) as gemini:
            try:
                await prepare(gemini, args)
            except GeminiError as e:
                log.error("%s", e)
                await gemini.dump_debug(e.operation)
                await _keep_open(args.keep_open_on_error)
                return 1
            for i, job in enumerate(jobs, start=1):
                if len(jobs) > 1:
                    log.info("=== Job %d/%d: %s ===", i, len(jobs), job.image.name)
                try:
                    if i > 1:
                        await gemini.new_chat()
                    out = await run_job(gemini, job, args.timeout)
                    print(f"\nVideo generated successfully:\n{out}\n")
                except GeminiError as e:
                    failures += 1
                    log.error("Job %d failed: %s", i, e)
                    await gemini.dump_debug(e.operation)
                    await _keep_open(args.keep_open_on_error)
    if len(jobs) > 1:
        log.info("Batch finished: %d succeeded, %d failed.", len(jobs) - failures, failures)
    return 1 if failures else 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m app.cli",
        description="Generate videos on Gemini Web from an image + prompt, in your running Chrome "
                    "(--attach) or a dedicated browser profile (--account).",
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="debug logging")
    sub = parser.add_subparsers(dest="command", required=True)

    common = argparse.ArgumentParser(add_help=False)
    who = common.add_mutually_exclusive_group(required=True)
    who.add_argument("--attach", action="store_true",
                     help="use your running Chrome (enable chrome://inspect/#remote-debugging first)")
    who.add_argument("--account", help="use a dedicated tool profile, e.g. account_01 (accounts/<name>/)")
    common.add_argument("--email", help="stop unless Gemini is signed in as this email")
    common.add_argument("--channel", default="chrome", choices=["chrome", "chromium", "msedge"],
                        help="browser for --account (default: installed Google Chrome)")
    common.add_argument("--keep-open-on-error", action="store_true",
                        help="pause after a failure until Enter is pressed")

    sub.add_parser("login", parents=[common], help="open Gemini and log in manually; the session is persisted")

    gen = sub.add_parser("generate", parents=[common], help="generate one video")
    gen.add_argument("--image", required=True, help="png/jpg/jpeg/webp reference image (the person)")
    gen.add_argument("--video", help="optional mp4/mov/webm reference video (e.g. the dance to follow)")
    gen.add_argument("--video-start", type=float, default=0.0,
                     help="second to start the 10s reference clip from (videos > 10s are trimmed)")
    gen.add_argument("--prompt", help="video prompt; default: prompts/default.txt")
    gen.add_argument("--prompt-file", help="read the prompt from this text file")
    gen.add_argument("--output", help="where to save the .mp4; default: output/<image>-<time>.mp4")
    gen.add_argument("--timeout", type=int, default=600, help="generation timeout in seconds (default 600)")

    batch = sub.add_parser("batch", parents=[common], help="generate videos sequentially from a jobs.json file")
    batch.add_argument("--jobs", required=True, help='JSON array of {"image", optional "video", "prompt"/"prompt_file", "output"}')
    batch.add_argument("--output-dir", default="./output", help="directory for outputs without an explicit path")
    batch.add_argument("--timeout", type=int, default=600, help="per-video timeout in seconds (default 600)")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO, format="%(message)s")
    logging.getLogger("asyncio").setLevel(logging.WARNING)
    try:
        if args.account:
            validate_account(args.account)
        if args.command == "login":
            if args.attach:
                raise ValidationError("login is only for --account profiles; --attach uses your Chrome's session.")
            return asyncio.run(cmd_login(args))
        if args.command == "generate":
            image = validate_image(args.image)
            output = (Path(args.output) if args.output else
                      PROJECT_ROOT / "output" / f"{image.stem}-{datetime.now():%Y%m%d-%H%M%S}.mp4")
            jobs = [Job(image=image,
                        prompt=resolve_prompt(args.prompt, args.prompt_file),
                        output=output.expanduser().resolve(),
                        video=validate_video(args.video) if args.video else None,
                        video_start=args.video_start)]
        else:
            jobs = load_jobs(args.jobs, Path(args.output_dir).expanduser().resolve())
        return asyncio.run(cmd_jobs(args, jobs))
    except ValidationError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 2
    except GeminiError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\nInterrupted.", file=sys.stderr)
        return 130


if __name__ == "__main__":
    sys.exit(main())
