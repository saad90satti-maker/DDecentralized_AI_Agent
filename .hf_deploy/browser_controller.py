"""
Unified Browser Controller - Ghost Engine
=========================================
Production-ready async Playwright browser automation with:
- Auto-retry with exponential backoff
- Self-healing error recovery (page refresh, context reset, browser restart)
- Human-like interaction patterns (typing delays, random viewport, mouse movement)
- Session persistence (cookies, localStorage)
- DOM state analysis and autonomous action decisions
- Non-blocking async operations for 24/7 stability

Usage:
    from browser_controller import BrowserController

    async with BrowserController(headless=False) as browser:
        result = await browser.navigate("https://example.com")
        result = await browser.click("button#submit")
        result = await browser.fill_form({"email": "test@example.com"})
"""

import asyncio
import json
import logging
import os
import random
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

try:
    from playwright.async_api import (
        BrowserContext,
        Page,
        Playwright,
        async_playwright,
        Error as PlaywrightError,
    )
except ImportError:
    raise ImportError(
        "Playwright required. Install: pip install playwright && playwright install"
    )

logger = logging.getLogger("BrowserController")


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

class BrowserState(str, Enum):
    IDLE = "idle"
    NAVIGATING = "navigating"
    INTERACTING = "interacting"
    ERROR = "error"
    RECOVERING = "recovering"
    CLOSED = "closed"


@dataclass
class RetryConfig:
    max_attempts: int = 3
    base_delay: float = 1.0
    max_delay: float = 30.0
    exponential_base: float = 2.0
    retryable_errors: Tuple[str, ...] = (
        "TimeoutError",
        "Navigation failed",
        "net::ERR_",
        "Target closed",
        "Session closed",
        "Connection closed",
    )


@dataclass
class HumanDelayConfig:
    min_type_delay_ms: int = 40
    max_type_delay_ms: int = 120
    min_click_delay_ms: int = 80
    max_click_delay_ms: int = 300
    min_between_actions_ms: int = 200
    max_between_actions_ms: int = 600
    min_page_load_delay_ms: int = 300
    max_page_load_delay_ms: int = 800


DEFAULT_USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_5) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36 Edg/124.0.0.0",
]

STEALTH_INIT_SCRIPT = """
Object.defineProperty(navigator, 'webdriver', { get: () => false });
window.navigator.chrome = { runtime: {} };
Object.defineProperty(navigator, 'languages', { get: () => ['en-US', 'en'] });
Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3, 4, 5] });
const origQuery = window.navigator.permissions.query;
window.navigator.permissions.query = (params) =>
    params.name === 'notifications'
        ? Promise.resolve({ state: Notification.permission })
        : origQuery(params);
if (window.chrome) { window.chrome.runtime = {}; }
"""


# ---------------------------------------------------------------------------
# Action result
# ---------------------------------------------------------------------------

@dataclass
class ActionResult:
    success: bool
    data: Any = None
    error: Optional[str] = None
    attempts: int = 1
    duration_ms: float = 0.0
    page_url: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "status": "success" if self.success else "error",
            "data": self.data,
            "error": self.error,
            "attempts": self.attempts,
            "duration_ms": round(self.duration_ms, 2),
            "page_url": self.page_url,
        }


# ---------------------------------------------------------------------------
# Browser Controller
# ---------------------------------------------------------------------------

class BrowserController:
    """
    Unified async browser controller with self-healing, auto-retry,
    and autonomous state analysis.
    """

    def __init__(
        self,
        headless: bool = False,
        user_data_dir: Optional[str] = None,
        viewport: Optional[Dict[str, int]] = None,
        user_agent: Optional[str] = None,
        locale: str = "en-US",
        timezone_id: str = "America/Los_Angeles",
        retry_config: Optional[RetryConfig] = None,
        delay_config: Optional[HumanDelayConfig] = None,
        cookies_file: Optional[str] = None,
        block_resources: bool = True,
        max_pages: int = 5,
    ):
        self.headless = headless
        self.user_data_dir = user_data_dir or str(
            Path.home() / ".ghost_browser_profile"
        )
        self.viewport = viewport or self._random_viewport()
        self.user_agent = user_agent or random.choice(DEFAULT_USER_AGENTS)
        self.locale = locale
        self.timezone_id = timezone_id
        self.retry = retry_config or RetryConfig()
        self.delay = delay_config or HumanDelayConfig()
        self.block_resources = block_resources
        self.max_pages = max_pages

        self._cookies_file = Path(
            cookies_file or str(Path(self.user_data_dir) / "cookies.json")
        )
        Path(self.user_data_dir).mkdir(parents=True, exist_ok=True)

        self._playwright: Optional[Playwright] = None
        self._context: Optional[BrowserContext] = None
        self._page: Optional[Page] = None
        self._state: BrowserState = BrowserState.IDLE
        self._action_log: List[Dict[str, Any]] = []
        self._error_count: int = 0
        self._last_error: Optional[str] = None
        self._start_time: float = 0.0

    # -- Lifecycle --

    async def __aenter__(self):
        await self.start()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close()

    async def start(self) -> None:
        self._start_time = time.time()
        self._playwright = await async_playwright().start()
        await self._launch_context()
        logger.info("BrowserController started (headless=%s)", self.headless)

    async def close(self) -> None:
        self._state = BrowserState.CLOSED
        await self._save_cookies()
        if self._page and not self._page.is_closed():
            await self._page.close()
        if self._context:
            await self._context.close()
        if self._playwright:
            await self._playwright.stop()
        logger.info(
            "BrowserController closed. Session: %.1fs, Actions: %d, Errors: %d",
            time.time() - self._start_time,
            len(self._action_log),
            self._error_count,
        )

    async def _launch_context(self) -> None:
        self._context = await self._playwright.chromium.launch_persistent_context(
            self.user_data_dir,
            headless=self.headless,
            viewport=self.viewport,
            user_agent=self.user_agent,
            locale=self.locale,
            timezone_id=self.timezone_id,
            accept_downloads=True,
            bypass_csp=True,
            java_script_enabled=True,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--disable-dev-shm-usage",
                "--no-sandbox",
                "--disable-setuid-sandbox",
                "--disable-infobars",
                "--disable-background-timer-throttling",
                "--disable-backgrounding-occluded-windows",
                "--disable-renderer-backgrounding",
            ],
        )
        self._page = await self._context.new_page()
        await self._apply_stealth(self._page)
        await self._load_cookies()
        if self.block_resources:
            await self._page.route("**/*", self._route_handler)

    async def _apply_stealth(self, page: Page) -> None:
        await page.add_init_script(STEALTH_INIT_SCRIPT)
        await page.set_extra_http_headers({
            "accept-language": "en-US,en;q=0.9",
            "dnt": "1",
            "upgrade-insecure-requests": "1",
        })

    async def _route_handler(self, route, request):
        blocked = ("image", "font", "media")
        if request.resource_type in blocked:
            await route.abort()
        else:
            await route.continue_()

    # -- Cookie persistence --

    async def _load_cookies(self) -> None:
        if self._cookies_file.exists():
            try:
                cookies = json.loads(self._cookies_file.read_text(encoding="utf-8"))
                await self._context.add_cookies(cookies)
            except Exception as exc:
                logger.warning("Cookie load failed: %s", exc)

    async def _save_cookies(self) -> None:
        if not self._context:
            return
        try:
            cookies = await self._context.cookies()
            self._cookies_file.write_text(
                json.dumps(cookies, indent=2), encoding="utf-8"
            )
        except Exception as exc:
            logger.warning("Cookie save failed: %s", exc)

    # -- Human-like delays --

    async def _human_delay(
        self, min_ms: Optional[int] = None, max_ms: Optional[int] = None
    ) -> None:
        lo = min_ms or self.delay.min_between_actions_ms
        hi = max_ms or self.delay.max_between_actions_ms
        await asyncio.sleep(random.uniform(lo / 1000, hi / 1000))

    async def _page_load_delay(self) -> None:
        await self._human_delay(
            self.delay.min_page_load_delay_ms, self.delay.max_page_load_delay_ms
        )

    # -- Error recovery --

    def _is_retryable(self, error: Exception) -> bool:
        error_str = str(error)
        return any(
            pattern.lower() in error_str.lower()
            for pattern in self.retry.retryable_errors
        )

    async def _recover_from_error(self, error: Exception) -> bool:
        self._error_count += 1
        self._last_error = str(error)
        self._state = BrowserState.RECOVERING
        logger.warning("Recovery attempt %d: %s", self._error_count, error)

        if self._error_count >= 5:
            logger.error("Too many errors, attempting full browser restart")
            return await self._full_restart()

        error_str = str(error).lower()
        if "target closed" in error_str or "session closed" in error_str:
            return await self._recover_closed_page()
        if "navigation" in error_str or "timeout" in error_str:
            return await self._recover_navigation()
        return False

    async def _recover_closed_page(self) -> bool:
        try:
            if self._context:
                pages = self._context.pages
                if pages:
                    self._page = pages[-1]
                else:
                    self._page = await self._context.new_page()
                await self._apply_stealth(self._page)
                self._state = BrowserState.IDLE
                return True
        except Exception as exc:
            logger.error("Page recovery failed: %s", exc)
        return await self._full_restart()

    async def _recover_navigation(self) -> bool:
        try:
            if self._page and not self._page.is_closed():
                await self._page.go_back(timeout=10000)
                self._state = BrowserState.IDLE
                return True
        except Exception:
            pass
        return await self._recover_closed_page()

    async def _full_restart(self) -> bool:
        try:
            if self._page and not self._page.is_closed():
                await self._page.close()
            if self._context:
                await self._context.close()
            await self._launch_context()
            self._state = BrowserState.IDLE
            self._error_count = 0
            logger.info("Full browser restart successful")
            return True
        except Exception as exc:
            logger.error("Full restart failed: %s", exc)
            self._state = BrowserState.ERROR
            return False

    # -- Core actions with retry --

    async def _execute_with_retry(
        self,
        action_name: str,
        func: Callable,
        *args,
        **kwargs,
    ) -> ActionResult:
        start = time.time()
        last_error = None

        for attempt in range(1, self.retry.max_attempts + 1):
            try:
                self._state = BrowserState.INTERACTING
                result = await func(*args, **kwargs)
                elapsed = (time.time() - start) * 1000
                self._error_count = 0
                self._state = BrowserState.IDLE
                self._log_action(action_name, True, attempt, elapsed)
                return ActionResult(
                    success=True,
                    data=result,
                    attempts=attempt,
                    duration_ms=elapsed,
                    page_url=self._page.url if self._page else "",
                )
            except Exception as exc:
                last_error = exc
                self._log_action(action_name, False, attempt, 0, str(exc))
                if attempt < self.retry.max_attempts and self._is_retryable(exc):
                    delay = min(
                        self.retry.max_delay,
                        self.retry.base_delay
                        * (self.retry.exponential_base ** (attempt - 1)),
                    )
                    logger.info(
                        "Retry %d/%d for %s in %.1fs: %s",
                        attempt,
                        self.retry.max_attempts,
                        action_name,
                        delay,
                        exc,
                    )
                    await asyncio.sleep(delay)
                    recovered = await self._recover_from_error(exc)
                    if not recovered:
                        break
                else:
                    break

        elapsed = (time.time() - start) * 1000
        self._state = BrowserState.ERROR
        error_msg = str(last_error) if last_error else "Unknown error"
        return ActionResult(
            success=False,
            error=error_msg,
            attempts=self.retry.max_attempts,
            duration_ms=elapsed,
            page_url=self._page.url if self._page else "",
        )

    def _log_action(
        self,
        action: str,
        success: bool,
        attempt: int,
        duration_ms: float,
        error: Optional[str] = None,
    ) -> None:
        entry = {
            "action": action,
            "success": success,
            "attempt": attempt,
            "duration_ms": round(duration_ms, 2),
            "timestamp": time.time(),
        }
        if error:
            entry["error"] = error[:200]
        self._action_log.append(entry)
        if len(self._action_log) > 500:
            self._action_log = self._action_log[-300:]

    # -- Public API --

    @property
    def state(self) -> BrowserState:
        return self._state

    @property
    def page(self) -> Optional[Page]:
        return self._page

    @property
    def url(self) -> str:
        return self._page.url if self._page else ""

    def get_action_log(self, limit: int = 50) -> List[Dict[str, Any]]:
        return self._action_log[-limit:]

    def get_stats(self) -> Dict[str, Any]:
        return {
            "state": self._state.value,
            "total_actions": len(self._action_log),
            "successes": sum(1 for a in self._action_log if a["success"]),
            "failures": sum(1 for a in self._action_log if not a["success"]),
            "error_count": self._error_count,
            "last_error": self._last_error,
            "uptime_seconds": round(time.time() - self._start_time, 1),
            "current_url": self.url,
        }

    # -- Navigation --

    async def navigate(
        self, url: str, wait_until: str = "domcontentloaded", timeout: int = 30000
    ) -> ActionResult:
        async def _do():
            self._state = BrowserState.NAVIGATING
            resp = await self._page.goto(url, wait_until=wait_until, timeout=timeout)
            await self._page_load_delay()
            return {
                "url": self._page.url,
                "status": resp.status if resp else None,
                "title": await self._page.title(),
            }
        return await self._execute_with_retry("navigate", _do)

    async def reload(self, wait_until: str = "domcontentloaded") -> ActionResult:
        async def _do():
            await self._page.reload(wait_until=wait_until, timeout=15000)
            await self._page_load_delay()
            return {"url": self._page.url, "title": await self._page.title()}
        return await self._execute_with_retry("reload", _do)

    async def go_back(self) -> ActionResult:
        async def _do():
            await self._page.go_back(timeout=15000)
            await self._page_load_delay()
            return {"url": self._page.url}
        return await self._execute_with_retry("go_back", _do)

    # -- Interaction --

    async def click(
        self,
        selector: str,
        timeout: int = 10000,
        wait_after_ms: Optional[int] = None,
    ) -> ActionResult:
        async def _do():
            await self._page.click(selector, timeout=timeout)
            delay = wait_after_ms or random.randint(
                self.delay.min_click_delay_ms, self.delay.max_click_delay_ms
            )
            await asyncio.sleep(delay / 1000)
            return {"selector": selector, "clicked": True}
        return await self._execute_with_retry("click", _do)

    async def type_text(
        self,
        selector: str,
        text: str,
        clear_first: bool = True,
        human_like: bool = True,
    ) -> ActionResult:
        async def _do():
            await self._page.click(selector, timeout=10000)
            await asyncio.sleep(random.uniform(0.05, 0.15))
            if clear_first:
                await self._page.fill(selector, "")
                await asyncio.sleep(random.uniform(0.05, 0.1))
            if human_like:
                for char in text:
                    await self._page.keyboard.type(
                        char,
                        delay=random.randint(
                            self.delay.min_type_delay_ms,
                            self.delay.max_type_delay_ms,
                        ),
                    )
            else:
                await self._page.fill(selector, text)
            return {"selector": selector, "typed": len(text)}
        return await self._execute_with_retry("type_text", _do)

    async def fill_form(self, fields: Dict[str, str]) -> ActionResult:
        async def _do():
            results = {}
            for selector, value in fields.items():
                candidates = [
                    f"[name='{selector}']",
                    f"#{selector}",
                    f"[aria-label='{selector}']",
                    f"input[placeholder*='{selector}']",
                    selector,
                ]
                filled = False
                for sel in candidates:
                    try:
                        el = await self._page.query_selector(sel)
                        if el:
                            await el.fill(value)
                            results[selector] = "filled"
                            filled = True
                            break
                    except Exception:
                        continue
                if not filled:
                    results[selector] = "not_found"
                await self._human_delay(100, 250)
            return results
        return await self._execute_with_retry("fill_form", _do)

    async def select_option(self, selector: str, value: str) -> ActionResult:
        async def _do():
            await self._page.select_option(selector, value, timeout=10000)
            return {"selector": selector, "value": value}
        return await self._execute_with_retry("select_option", _do)

    async def hover(self, selector: str) -> ActionResult:
        async def _do():
            await self._page.hover(selector, timeout=10000)
            await self._human_delay(200, 500)
            return {"selector": selector}
        return await self._execute_with_retry("hover", _do)

    async def scroll_to_bottom(self) -> ActionResult:
        async def _do():
            prev_height = 0
            for _ in range(10):
                height = await self._page.evaluate("document.body.scrollHeight")
                if height == prev_height:
                    break
                await self._page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                prev_height = height
                await self._human_delay(300, 600)
            return {"scrolled": True, "final_height": prev_height}
        return await self._execute_with_retry("scroll_to_bottom", _do)

    # -- Extraction --

    async def get_text(self, selector: str) -> ActionResult:
        async def _do():
            text = await self._page.text_content(selector, timeout=5000)
            return {"selector": selector, "text": text}
        return await self._execute_with_retry("get_text", _do)

    async def get_inner_text(self, selector: str = "body") -> ActionResult:
        async def _do():
            text = await self._page.inner_text(selector, timeout=5000)
            return {"selector": selector, "text": text}
        return await self._execute_with_retry("get_inner_text", _do)

    async def get_attribute(self, selector: str, attribute: str) -> ActionResult:
        async def _do():
            value = await self._page.get_attribute(selector, attribute, timeout=5000)
            return {"selector": selector, "attribute": attribute, "value": value}
        return await self._execute_with_retry("get_attribute", _do)

    async def query_selector(self, selector: str) -> ActionResult:
        async def _do():
            el = await self._page.query_selector(selector)
            return {"selector": selector, "found": el is not None}
        return await self._execute_with_retry("query_selector", _do)

    async def query_selector_all(self, selector: str) -> ActionResult:
        async def _do():
            elements = await self._page.query_selector_all(selector)
            return {"selector": selector, "count": len(elements)}
        return await self._execute_with_retry("query_selector_all", _do)

    # -- JavaScript --

    async def execute_script(self, script: str, arg: Any = None) -> ActionResult:
        async def _do():
            result = await self._page.evaluate(script, arg)
            return {"result": result}
        return await self._execute_with_retry("execute_script", _do)

    # -- Screenshots --

    async def screenshot(
        self, path: str = "screenshot.png", full_page: bool = False
    ) -> ActionResult:
        async def _do():
            await self._page.screenshot(path=path, full_page=full_page)
            return {"path": path, "full_page": full_page}
        return await self._execute_with_retry("screenshot", _do)

    # -- Cookies & Storage --

    async def get_cookies(self) -> ActionResult:
        async def _do():
            cookies = await self._context.cookies()
            return {"cookies": cookies, "count": len(cookies)}
        return await self._execute_with_retry("get_cookies", _do)

    async def set_cookies(self, cookies: List[Dict]) -> ActionResult:
        async def _do():
            await self._context.add_cookies(cookies)
            return {"set": len(cookies)}
        return await self._execute_with_retry("set_cookies", _do)

    async def clear_cookies(self) -> ActionResult:
        async def _do():
            await self._context.clear_cookies()
            return {"cleared": True}
        return await self._execute_with_retry("clear_cookies", _do)

    async def get_local_storage(self) -> ActionResult:
        async def _do():
            storage = await self._page.evaluate(
                "() => { let s = {}; for(let i=0; i<localStorage.length; i++) "
                "{ let k = localStorage.key(i); s[k] = localStorage.getItem(k); } "
                "return s; }"
            )
            return {"storage": storage}
        return await self._execute_with_retry("get_local_storage", _do)

    # -- DOM Analysis for autonomous decisions --

    async def analyze_page_state(self) -> ActionResult:
        """Analyze current DOM state for autonomous decision-making."""
        async def _do():
            analysis = await self._page.evaluate("""() => {
                const title = document.title;
                const url = window.location.href;
                const body = document.body ? document.body.innerText.substring(0, 2000) : '';
                const forms = Array.from(document.querySelectorAll('form')).map(f => ({
                    action: f.action,
                    method: f.method,
                    inputs: Array.from(f.querySelectorAll('input,textarea,select')).map(i => ({
                        type: i.type, name: i.name, id: i.id,
                        placeholder: i.placeholder, value: i.value ? '***' : ''
                    }))
                }));
                const buttons = Array.from(document.querySelectorAll('button,a[role=button],[role=button]'))
                    .slice(0, 20).map(b => ({
                        text: b.innerText.trim().substring(0, 50),
                        tag: b.tagName,
                        href: b.href || null,
                        disabled: b.disabled || false
                    }));
                const links = Array.from(document.querySelectorAll('a[href]'))
                    .slice(0, 20).map(a => ({
                        text: a.innerText.trim().substring(0, 50),
                        href: a.href
                    }));
                const errors = Array.from(document.querySelectorAll(
                    '.error,.alert-danger,.alert-error,[role=alert]'
                )).map(e => e.innerText.trim().substring(0, 100));
                const loading = document.querySelector(
                    '.loading,.spinner,[role=progressbar],.loader'
                ) !== null;
                const dialogs = Array.from(document.querySelectorAll(
                    '[role=dialog],.modal,.popup,.overlay'
                )).map(d => d.innerText.trim().substring(0, 200));
                return {
                    title, url, body_preview: body,
                    forms, buttons, links, errors, loading, dialogs
                };
            }""")
            return analysis
        return await self._execute_with_retry("analyze_page_state", _do)

    async def detect_consent_dialog(self) -> Optional[str]:
        """Try to detect and return selector for cookie/consent dialog."""
        consent_selectors = [
            "button:has-text('Accept all')",
            "button:has-text('Accept')",
            "button:has-text('I agree')",
            "button:has-text('OK')",
            "button:has-text('Got it')",
            "button:has-text('Allow all')",
            "[data-testid='cookie-accept']",
            "[aria-label*='Accept']",
            "[aria-label*='consent'] button",
        ]
        for sel in consent_selectors:
            try:
                el = await self._page.query_selector(sel)
                if el:
                    return sel
            except Exception:
                continue
        return None

    async def dismiss_dialogs(self) -> ActionResult:
        """Auto-detect and dismiss common dialogs (cookie consent, popups)."""
        async def _do():
            dismissed = []
            consent = await self.detect_consent_dialog()
            if consent:
                await self._page.click(consent, timeout=3000)
                dismissed.append("consent")
                await self._human_delay(300, 600)
            for sel in [
                "[aria-label='Close']",
                "button:has-text('Close')",
                ".modal-close",
                "[data-dismiss='modal']",
            ]:
                try:
                    el = await self._page.query_selector(sel)
                    if el and await el.is_visible():
                        await el.click(timeout=2000)
                        dismissed.append(sel)
                        await self._human_delay(200, 400)
                except Exception:
                    continue
            return {"dismissed": dismissed}
        return await self._execute_with_retry("dismiss_dialogs", _do)

    # -- Workflow execution --

    async def execute_workflow(self, steps: List[Dict[str, Any]]) -> ActionResult:
        """Execute a sequence of browser actions from a config list."""
        async def _do():
            results = []
            for i, step in enumerate(steps):
                action = step.get("action")
                params = {k: v for k, v in step.items() if k != "action"}
                try:
                    if action == "goto":
                        r = await self.navigate(step["url"])
                    elif action == "click":
                        r = await self.click(step["selector"])
                    elif action == "fill":
                        r = await self.type_text(step["selector"], step["value"])
                    elif action == "fill_form":
                        r = await self.fill_form(step["fields"])
                    elif action == "wait_for":
                        r = await self._wait_for_selector(
                            step["selector"], step.get("timeout", 10000)
                        )
                    elif action == "scroll":
                        r = await self.scroll_to_bottom()
                    elif action == "screenshot":
                        r = await self.screenshot(step.get("path", f"step_{i}.png"))
                    elif action == "script":
                        r = await self.execute_script(step["script"])
                    elif action == "get_text":
                        r = await self.get_text(step["selector"])
                    elif action == "dismiss":
                        r = await self.dismiss_dialogs()
                    else:
                        r = ActionResult(success=False, error=f"Unknown action: {action}")
                    results.append({"step": i, "action": action, **r.to_dict()})
                    if not r.success and step.get("required", True):
                        return {"step_results": results, "failed_at": i}
                except Exception as exc:
                    results.append({
                        "step": i, "action": action,
                        "status": "error", "error": str(exc),
                    })
                    if step.get("required", True):
                        return {"step_results": results, "failed_at": i}
                await self._human_delay()
            return {"step_results": results, "completed": True}
        return await self._execute_with_retry("execute_workflow", _do)

    async def _wait_for_selector(
        self, selector: str, timeout: int = 10000
    ) -> ActionResult:
        async def _do():
            await self._page.wait_for_selector(selector, timeout=timeout)
            return {"selector": selector, "appeared": True}
        return await self._execute_with_retry("wait_for_selector", _do)


# ---------------------------------------------------------------------------
# Standalone usage
# ---------------------------------------------------------------------------

async def main():
    logging.basicConfig(level=logging.INFO)
    async with BrowserController(headless=False) as browser:
        result = await browser.navigate("https://example.com")
        print("Navigate:", result.to_dict())

        result = await browser.analyze_page_state()
        print("Page analysis:", json.dumps(result.data, indent=2)[:500])

        result = await browser.screenshot("example_screenshot.png")
        print("Screenshot:", result.to_dict())

        print("Stats:", json.dumps(browser.get_stats(), indent=2))


if __name__ == "__main__":
    asyncio.run(main())
