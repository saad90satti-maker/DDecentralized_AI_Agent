"""
Ghost Media Engine: Launch Chrome via Playwright with CDP port exposed.
Playwright reliably starts Chrome with the correct profile and args.
"""
import asyncio
import subprocess
import sys
import time
from pathlib import Path

PROFILE = str(Path.home() / "AppData/Local/Google/Chrome/User Data/Default")


async def launch_cdp_chrome():
    from playwright.async_api import async_playwright

    print("Ghost Engine: Launching Chrome via Playwright + CDP port 9222...")
    print(f"  Profile: {PROFILE}")

    p = await async_playwright().start()
    context = await p.chromium.launch_persistent_context(
        user_data_dir=PROFILE,
        headless=False,
        channel="chrome",
        args=[
            "--remote-debugging-port=9222",
            "--disable-blink-features=AutomationControlled",
            "--no-sandbox",
        ],
        no_viewport=False,
    )

    page = context.pages[0] if context.pages else await context.new_page()
    await page.goto("https://github.com", wait_until="domcontentloaded")
    print(f"  GitHub title: {await page.title()}")

    # Keep alive - user can open more pages
    print("\nGhost Engine: Chrome running with CDP on port 9222.")
    print("  Open browser UI to navigate. CDP accessible at ws://127.0.0.1:9222")
    print("  Press Ctrl+C in terminal to close.\n")

    # Wait forever (or until interrupted)
    try:
        while True:
            await asyncio.sleep(10)
            pages = context.pages
            print(f"  [heartbeat] {len(pages)} tab(s) open", end="\r")
    except asyncio.CancelledError:
        pass
    finally:
        await context.close()
        await p.stop()
        print("\nGhost Engine: Chrome closed.")


if __name__ == "__main__":
    try:
        asyncio.run(launch_cdp_chrome())
    except KeyboardInterrupt:
        print("\nShutdown requested.")
