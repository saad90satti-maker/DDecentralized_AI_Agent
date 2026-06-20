"""
Browser Control Script - Ghost Media Engine
============================================
Takes control of your Chrome browser with your logged-in sessions.
Headless=False so you can watch the automation in real-time.
"""

import asyncio
import sys
import os

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from ghost_media_engine.config import EngineConfig
from ghost_media_engine.logging import init_logging, get_logger
from ghost_media_engine.browser.controller import BrowserController


async def main():
    """Take control of browser and perform automation."""
    init_logging(level="INFO")
    logger = get_logger("BrowserControl")

    # Load config from .env
    config = EngineConfig.from_env()
    logger.info("Browser profile: %s", config.browser.user_data_dir)

    # Start browser with your Chrome profile (visible mode)
    async with BrowserController(config) as browser:
        logger.success("Browser started - you can see it now!")

        # Step 1: Go to Google
        logger.info("Step 1: Navigating to Google...")
        result = await browser.navigate("https://www.google.com")
        if result.success:
            logger.success("Google loaded: %s", result.data.get("title", ""))
        else:
            logger.error("Failed to load Google: %s", result.error)

        # Step 2: Analyze the page
        logger.info("Step 2: Analyzing page state...")
        analysis = await browser.analyze_page()
        if analysis.success:
            data = analysis.data
            logger.info("Page title: %s", data.get("title", ""))
            logger.info("URL: %s", data.get("url", ""))
            logger.info("Buttons found: %d", len(data.get("buttons", [])))
            logger.info("Forms found: %d", len(data.get("forms", [])))

        # Step 3: Search for something
        logger.info("Step 3: Performing search...")
        search_result = await browser.execute_workflow([
            {"action": "click", "selector": "textarea[name='q'], input[name='q']"},
            {"action": "fill", "selector": "textarea[name='q'], input[name='q']", "value": "Ghost Media Engine AI"},
            {"action": "click", "selector": "input[name='btnK'], button[type='submit']"},
        ])

        if search_result.success:
            logger.success("Search completed!")
        else:
            logger.warning("Search may have failed: %s", search_result.error)

        # Step 4: Wait and take screenshot
        await asyncio.sleep(2)
        screenshot_result = await browser.screenshot("ghost_engine_screenshot.png")
        if screenshot_result.success:
            logger.success("Screenshot saved: ghost_engine_screenshot.png")

        # Step 5: Print stats
        stats = browser.get_stats()
        logger.info("=== Session Stats ===")
        logger.info("Total actions: %d", stats["total_actions"])
        logger.info("Successes: %d", stats["successes"])
        logger.info("Failures: %d", stats["failures"])
        logger.info("Circuit breaker: %s", stats["circuit_breaker"])

        # Keep browser open for you to see
        logger.success("Automation complete! Browser stays open for 30 seconds...")
        logger.info("You can interact with the browser manually.")
        logger.info("Press Ctrl+C to close earlier.")

        try:
            for i in range(30, 0, -1):
                print(f"\r  Closing in {i}s... ", end="", flush=True)
                await asyncio.sleep(1)
        except (KeyboardInterrupt, asyncio.CancelledError):
            pass

        logger.success("Closing browser...")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nBrowser closed by user.")
