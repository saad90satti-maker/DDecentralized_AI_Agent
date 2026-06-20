"""
Stealth Browser Automation - Anti-detection Playwright wrapper for Ghost Engine

Provides human-like browser interactions with:
- Anti-detection measures (webdriver hiding, random user agents)
- Human-like typing delays and mouse movement
- Cookie persistence
- Resource blocking for performance

Usage:
    from stealth_browser import BrowserStealth
    async with BrowserStealth(headless=False) as browser:
        await browser.goto("https://example.com")
        await browser.type_text("#search", "hello world")
"""

import asyncio
import json
import logging
import os
import random
from pathlib import Path
from typing import Any, Dict, List, Optional

from browser_controller import BrowserController, ActionResult

logger = logging.getLogger("StealthBrowser")


class BrowserStealth:
    """Legacy-compatible wrapper around BrowserController with stealth defaults."""

    def __init__(
        self,
        headless: bool = False,
        user_data_dir: Optional[str] = None,
        viewport: Optional[Dict[str, int]] = None,
        user_agent: Optional[str] = None,
        locale: str = "en-US",
        timezone_id: str = "America/Los_Angeles",
    ):
        self._controller = BrowserController(
            headless=headless,
            user_data_dir=user_data_dir,
            viewport=viewport,
            user_agent=user_agent,
            locale=locale,
            timezone_id=timezone_id,
            block_resources=True,
        )

    async def __aenter__(self):
        await self._controller.start()
        return self

    async def __aexit__(self, exc_type, exc, tb):
        await self._controller.close()

    @property
    def page(self):
        return self._controller.page

    @property
    def context(self):
        return self._controller._context

    async def human_delay(self, minimum_ms: int = 120, maximum_ms: int = 420) -> None:
        await asyncio.sleep(random.uniform(minimum_ms / 1000, maximum_ms / 1000))

    async def goto(self, url: str, wait_until: str = "networkidle") -> Dict[str, Any]:
        result = await self._controller.navigate(url, wait_until=wait_until)
        return result.to_dict()

    async def type_text(self, selector: str, text: str) -> None:
        result = await self._controller.type_text(selector, text)
        if not result.success:
            raise RuntimeError(result.error or "type_text failed")

    async def click(self, selector: str, timeout: int = 15000) -> Dict[str, Any]:
        result = await self._controller.click(selector, timeout=timeout)
        return result.to_dict()

    async def wait_for_selector(self, selector: str, timeout: int = 15000) -> Dict[str, Any]:
        result = await self._controller._wait_for_selector(selector, timeout)
        return result.to_dict()

    async def get_text(self, selector: str) -> Dict[str, Any]:
        result = await self._controller.get_text(selector)
        return result.to_dict()

    async def ensure_login(
        self,
        login_url: str,
        email_selector: str,
        password_selector: str,
        submit_selector: str,
        credentials: Dict[str, str],
        success_selector: Optional[str] = None,
    ) -> Dict[str, Any]:
        steps = [
            {"action": "goto", "url": login_url},
            {"action": "fill", "selector": email_selector, "value": credentials["email"]},
            {"action": "fill", "selector": password_selector, "value": credentials["password"]},
            {"action": "click", "selector": submit_selector},
        ]
        if success_selector:
            steps.append({"action": "wait_for", "selector": success_selector, "timeout": 20000})

        result = await self._controller.execute_workflow(steps)
        if result.success:
            await self._controller._save_cookies()
        return {
            "status": "success" if result.success else "error",
            "message": "Login complete" if result.success else "Login failed",
            "url": self._controller.url,
            "details": result.data,
        }

    async def execute_workflow(self, config: Dict[str, Any]) -> Dict[str, Any]:
        steps = config.get("steps", [])
        result = await self._controller.execute_workflow(steps)
        return result.to_dict()

    async def _save_cookies(self) -> None:
        await self._controller._save_cookies()


if __name__ == "__main__":
    import asyncio

    async def run_example():
        async with BrowserStealth(headless=False) as browser:
            await browser.goto("https://example.com")
            print("Page loaded", browser.page.url)

    asyncio.run(run_example())
