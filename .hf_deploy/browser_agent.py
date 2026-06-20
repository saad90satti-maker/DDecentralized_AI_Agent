"""
Browser Automation Agent - Playwright-based web interaction for Ghost Engine

Provides methods for:
- Automated form filling
- MetaMask wallet interaction
- Social media automation
- Airdrop claiming
- Data scraping and submission

Usage:
    from browser_agent import BrowserAgent
    async with BrowserAgent() as agent:
        await agent.goto("https://example.com")
        await agent.fill_form({"email": "user@example.com", "password": "secret"})
        await agent.click("button:has-text('Submit')")
"""

import os
import asyncio
import logging
from typing import Dict, Any, Optional
from pathlib import Path

from browser_controller import BrowserController, ActionResult

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("BrowserAgent")


class BrowserAgent:
    """Legacy-compatible wrapper around BrowserController."""

    def __init__(self, headless: bool = True, user_data_dir: Optional[str] = None):
        self.headless = headless
        self.user_data_dir = user_data_dir or str(Path.home() / ".browser_agent")
        self._controller: Optional[BrowserController] = None

    async def __aenter__(self):
        self._controller = BrowserController(
            headless=self.headless,
            user_data_dir=self.user_data_dir,
        )
        await self._controller.start()
        return self

    async def __aexit__(self, *args):
        if self._controller:
            await self._controller.close()

    @property
    def page(self):
        return self._controller.page if self._controller else None

    async def goto(self, url: str, wait_until: str = "networkidle") -> Dict[str, Any]:
        result = await self._controller.navigate(url, wait_until=wait_until)
        return result.to_dict()

    async def fill_form(self, fields: Dict[str, str]) -> Dict[str, Any]:
        result = await self._controller.fill_form(fields)
        return {"status": "success" if result.success else "error", "results": result.data}

    async def click(self, selector: str) -> Dict[str, Any]:
        result = await self._controller.click(selector)
        return result.to_dict()

    async def get_text(self, selector: str) -> Dict[str, Any]:
        result = await self._controller.get_text(selector)
        return result.to_dict()

    async def screenshot(self, path: str = "screenshot.png") -> Dict[str, Any]:
        result = await self._controller.screenshot(path)
        return result.to_dict()

    async def wait_for_selector(self, selector: str, timeout: int = 5000) -> Dict[str, Any]:
        result = await self._controller._wait_for_selector(selector, timeout)
        return result.to_dict()

    async def execute_script(self, script: str, arg: Any = None) -> Dict[str, Any]:
        result = await self._controller.execute_script(script, arg)
        return result.to_dict()

    async def get_cookies(self) -> Dict[str, Any]:
        result = await self._controller.get_cookies()
        return result.to_dict()

    async def airdrop_claim_workflow(
        self, airdrop_url: str, form_data: Dict[str, str]
    ) -> Dict[str, Any]:
        result = await self._controller.execute_workflow([
            {"action": "goto", "url": airdrop_url},
            {"action": "fill_form", "fields": form_data},
            {"action": "click", "selector": "button[type='submit']"},
            {"action": "scroll"},
        ])
        text_result = await self._controller.get_inner_text("body")
        return {
            "status": "success" if result.success else "error",
            "message": "Airdrop claim workflow completed",
            "page_text": text_result.data.get("text", "")[:500] if text_result.success else None,
            "steps": result.data,
        }


async def example_usage():
    async with BrowserAgent(headless=False) as agent:
        await agent.goto("https://example.com")
        await agent.screenshot("example.png")
        print("Screenshot saved to example.png")


if __name__ == "__main__":
    asyncio.run(example_usage())
