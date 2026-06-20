"""
Browser Control Demo - Ghost Media Engine
==========================================
Demonstrates: navigation, page analysis, form fill, screenshot, self-healing.
Uses your Chrome profile with all logged-in sessions.
"""

import asyncio
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from ghost_media_engine.config import EngineConfig
from ghost_media_engine.logging import init_logging, get_logger
from ghost_media_engine.browser.controller import BrowserController


async def main():
    init_logging(level="INFO")
    logger = get_logger("Demo")

    config = EngineConfig.from_env()

    async with BrowserController(config) as browser:
        logger.success("Browser ready - watch the automation!")

        # 1. Navigate to YouTube
        logger.info("[1/5] Opening YouTube...")
        result = await browser.navigate("https://www.youtube.com")
        logger.success("YouTube loaded: %s", result.data.get("title", "") if result.success else result.error)
        await asyncio.sleep(2)

        # 2. Analyze page
        logger.info("[2/5] Analyzing page...")
        analysis = await browser.analyze_page()
        if analysis.success:
            data = analysis.data
            logger.info("Title: %s", data.get("title", ""))
            buttons = data.get("buttons", [])
            for b in buttons[:5]:
                logger.info("  Button: '%s' (disabled=%s)", b.get("text", "")[:30], b.get("disabled"))

        # 3. Dismiss any dialogs
        logger.info("[3/5] Dismissing dialogs...")
        dismiss = await browser.dismiss_dialogs()
        logger.info("Dismissed: %s", dismiss.data.get("dismissed", []) if dismiss.success else "none")

        # 4. Navigate to GitHub
        logger.info("[4/5] Opening GitHub...")
        result = await browser.navigate("https://github.com")
        logger.success("GitHub loaded: %s", result.data.get("title", "") if result.success else result.error)
        await asyncio.sleep(1)

        # 5. Take screenshot
        logger.info("[5/5] Taking screenshot...")
        await browser.screenshot("ghost_engine_demo.png")
        logger.success("Screenshot saved: ghost_engine_demo.png")

        # Stats
        stats = browser.get_stats()
        logger.info("=== Session Complete ===")
        logger.info("Actions: %d total, %d succeeded, %d failed",
                     stats["total_actions"], stats["successes"], stats["failures"])
        logger.info("Browser stays open for 15 seconds...")

        try:
            for i in range(15, 0, -1):
                print(f"\r  {i}s remaining... ", end="", flush=True)
                await asyncio.sleep(1)
        except (KeyboardInterrupt, asyncio.CancelledError):
            pass

        logger.success("Done!")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nClosed.")
