"""Log in once for each account profile. Run this once after creating accounts.

Usage:
    python -m app.tools.login_accounts acc_hosyminh acc_syminh
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

from playwright.async_api import async_playwright

from app.browser import launch_profile
from app.models import validate_account


async def login_one(pw, account: str) -> None:
    print(f"\n=== Logging in: {account} ===")
    ctx = await launch_profile(pw, account, channel="chrome", headless=False)
    page = await ctx.new_page()
    await page.goto("https://gemini.google.com/")
    print(f"  -> Chrome opened. Log into Gmail for '{account}', then come back here.")
    print(f"  -> Once you see Gemini's chat page, press Enter here to save & continue...")
    await asyncio.to_thread(input)
    # Save cookies by closing (persistent context writes to disk on close)
    await ctx.close()
    print(f"  -> Saved profile for '{account}'")


async def main() -> None:
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    accounts = [validate_account(a) for a in sys.argv[1:]]
    async with async_playwright() as pw:
        for acc in accounts:
            await login_one(pw, acc)
    print("\nAll accounts logged in. You can now run UI and use Run All.")


if __name__ == "__main__":
    asyncio.run(main())