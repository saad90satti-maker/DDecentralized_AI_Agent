"""
Unified Browser Controller - Ghost Engine
=========================================
Production-ready async Playwright automation with:
- Async context manager for clean lifecycle
- Self-healing error recovery (page refresh, context reset, browser restart)
- Auto-retry with exponential backoff
- Human-like interaction patterns
- Session persistence (cookies, localStorage)
- DOM state analysis for autonomous decisions
- Resource blocking for performance
"""

import asyncio
import json
import random
import time
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, AsyncGenerator, Callable, Dict, List, Optional, Tuple

from playwright.async_api import (
    BrowserContext,
    Page,
    Playwright,
    async_playwright,
    Error as PlaywrightError,
)

from ghost_media_engine.config import BrowserConfig, EngineConfig
from ghost_media_engine.logging import get_logger
from ghost_media_engine.utils.retry import (
    CircuitBreaker,
    RetryPolicy,
    retry_async,
)

logger = get_logger("BrowserController")


# ---------------------------------------------------------------------------
# State & dataclasses
# ---------------------------------------------------------------------------

class BrowserState(str, Enum):
    IDLE = "idle"
    NAVIGATING = "navigating"
    INTERACTING = "interacting"
    ERROR = "error"
    RECOVERING = "recovering"
    CLOSED = "closed"


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


@dataclass
class PageAnalysis:
    """Typed result from DOM state analysis."""
    title: str = ""
    url: str = ""
    body_preview: str = ""
    forms: List[Dict] = field(default_factory=list)
    buttons: List[Dict] = field(default_factory=list)
    links: List[Dict] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)
    dialogs: List[str] = field(default_factory=list)
    loading: bool = False


# Stealth init script
STEALTH_INIT = """
Object.defineProperty(navigator, 'webdriver', { get: () => false });
window.navigator.chrome = { runtime: {} };
Object.defineProperty(navigator, 'languages', { get: () => ['en-US', 'en'] });
Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3, 4, 5] });
"""

DEFAULT_USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_5) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
]


# ---------------------------------------------------------------------------
# BrowserController
# ---------------------------------------------------------------------------

class BrowserController:
    """
    Async-first Playwright controller with self-healing and auto-retry.

    Usage as context manager:
        async with BrowserController(config) as browser:
            result = await browser.navigate("https://example.com")
            result = await browser.click("button#submit")

    Usage standalone:
        browser = BrowserController(config)
        await browser.start()
        # ... operations ...
        await browser.close()
    """

    def __init__(self, config: Optional[EngineConfig] = None):
        self._config = config or EngineConfig()
        self._browser_cfg = self._config.browser
        self._playwright: Optional[Playwright] = None
        self._context: Optional[BrowserContext] = None
        self._page: Optional[Page] = None
        self._state = BrowserState.IDLE
        self._error_count = 0
        self._last_error: Optional[str] = None
        self._start_time = 0.0
        self._action_log: List[Dict[str, Any]] = []
        self._circuit_breaker = CircuitBreaker(
            failure_threshold=5,
            recovery_timeout=60.0,
        )

    # -- Async context manager --

    @asynccontextmanager
    async def session(self) -> AsyncGenerator["BrowserController", None]:
        """Async context manager that ensures clean startup/shutdown."""
        await self.start()
        try:
            yield self
        finally:
            await self.close()

    async def __aenter__(self):
        await self.start()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close()

    # -- Lifecycle --

    async def start(self) -> None:
        """Launch browser with stealth configuration."""
        self._start_time = time.time()
        self._playwright = await async_playwright().start()
        await self._launch_context()
        logger.success("Browser started (headless=%s)", self._browser_cfg.headless)

    async def close(self) -> None:
        """Gracefully close browser and save session state."""
        self._state = BrowserState.CLOSED
        await self._save_cookies()
        if self._page and not self._page.is_closed():
            await self._page.close()
        if self._context:
            await self._context.close()
        if self._playwright:
            await self._playwright.stop()
        logger.info(
            "Browser closed. Session: %.1fs, Actions: %d, Errors: %d",
            time.time() - self._start_time,
            len(self._action_log),
            self._error_count,
        )

    async def _launch_context(self) -> None:
        """Launch a new browser context with stealth args."""
        user_agent = random.choice(DEFAULT_USER_AGENTS)
        profile_dir = Path(self._browser_cfg.user_data_dir)
        profile_dir.mkdir(parents=True, exist_ok=True)

        self._context = await self._playwright.chromium.launch_persistent_context(
            str(profile_dir),
            headless=self._browser_cfg.headless,
            viewport=self._browser_cfg.viewport,
            user_agent=user_agent,
            locale=self._browser_cfg.locale,
            timezone_id=self._browser_cfg.timezone_id,
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
        if self._browser_cfg.block_resources:
            await self._page.route("**/*", self._route_handler)

    async def _apply_stealth(self, page: Page) -> None:
        """Inject anti-detection scripts."""
        await page.add_init_script(STEALTH_INIT)
        await page.set_extra_http_headers({
            "accept-language": "en-US,en;q=0.9",
            "dnt": "1",
            "upgrade-insecure-requests": "1",
        })

    async def _route_handler(self, route, request) -> None:
        """Block heavy resources for performance."""
        blocked = ("image", "font", "media")
        if request.resource_type in blocked:
            await route.abort()
        else:
            await route.continue_()

    # -- Cookie persistence --

    async def _load_cookies(self) -> None:
        cookies_file = Path(self._browser_cfg.user_data_dir) / "cookies.json"
        if cookies_file.exists():
            try:
                cookies = json.loads(cookies_file.read_text(encoding="utf-8"))
                await self._context.add_cookies(cookies)
                logger.debug("Loaded %d cookies", len(cookies))
            except Exception as exc:
                logger.warning("Cookie load failed: %s", exc)

    async def _save_cookies(self) -> None:
        if not self._context:
            return
        try:
            cookies = await self._context.cookies()
            cookies_file = Path(self._browser_cfg.user_data_dir) / "cookies.json"
            cookies_file.write_text(json.dumps(cookies, indent=2), encoding="utf-8")
            logger.debug("Saved %d cookies", len(cookies))
        except Exception as exc:
            logger.warning("Cookie save failed: %s", exc)

    # -- Self-healing error recovery --

    def _is_retryable(self, error: Exception) -> bool:
        error_str = str(error).lower()
        retryable = [
            "timeout", "navigation failed", "net::err_",
            "target closed", "session closed", "connection closed",
            "browser has been closed", "page has been closed",
        ]
        return any(pattern in error_str for pattern in retryable)

    async def _recover_from_error(self, error: Exception) -> bool:
        """Attempt to recover from browser errors. Returns True if recovery succeeded."""
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
        """Recover from a closed page by creating a new one."""
        try:
            if self._context:
                pages = self._context.pages
                if pages:
                    self._page = pages[-1]
                else:
                    self._page = await self._context.new_page()
                await self._apply_stealth(self._page)
                self._state = BrowserState.IDLE
                logger.info("Page recovered successfully")
                return True
        except Exception as exc:
            logger.error("Page recovery failed: %s", exc)
        return await self._full_restart()

    async def _recover_navigation(self) -> bool:
        """Recover from navigation failure by going back."""
        try:
            if self._page and not self._page.is_closed():
                await self._page.go_back(timeout=10000)
                self._state = BrowserState.IDLE
                logger.info("Navigation recovery via go_back")
                return True
        except Exception:
            pass
        return await self._recover_closed_page()

    async def _full_restart(self) -> bool:
        """Full browser restart - last resort recovery."""
        try:
            if self._page and not self._page.is_closed():
                await self._page.close()
            if self._context:
                await self._context.close()
            await self._launch_context()
            self._state = BrowserState.IDLE
            self._error_count = 0
            self._circuit_breaker.reset()
            logger.success("Full browser restart successful")
            return True
        except Exception as exc:
            logger.error("Full restart failed: %s", exc)
            self._state = BrowserState.ERROR
            return False

    # -- Core action executor with retry --

    async def _execute(
        self,
        action_name: str,
        func: Callable,
        *args,
        **kwargs,
    ) -> ActionResult:
        """Execute an action with retry, self-healing, and circuit breaker."""
        start = time.time()
        policy = RetryPolicy(
            max_attempts=3,
            base_delay=1.0,
            max_delay=15.0,
        )

        for attempt in range(1, policy.max_attempts + 1):
            # Check circuit breaker
            if not self._circuit_breaker.allow_request():
                elapsed = (time.time() - start) * 1000
                return ActionResult(
                    success=False,
                    error=f"Circuit breaker OPEN (failures={self._circuit_breaker.failure_count})",
                    attempts=attempt,
                    duration_ms=elapsed,
                    page_url=self._page.url if self._page else "",
                )

            try:
                self._state = BrowserState.INTERACTING
                result = await func(*args, **kwargs)
                elapsed = (time.time() - start) * 1000
                self._error_count = 0
                self._circuit_breaker.record_success()
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
                self._circuit_breaker.record_failure()
                self._log_action(action_name, False, attempt, 0, str(exc))

                if attempt < policy.max_attempts and self._is_retryable(exc):
                    delay = min(
                        policy.max_delay,
                        policy.base_delay * (policy.exponential_base ** (attempt - 1)),
                    )
                    logger.info(
                        "Retry %d/%d for %s in %.1fs: %s",
                        attempt, policy.max_attempts, action_name, delay, exc,
                    )
                    await asyncio.sleep(delay)
                    recovered = await self._recover_from_error(exc)
                    if not recovered:
                        break
                else:
                    break

        elapsed = (time.time() - start) * 1000
        self._state = BrowserState.ERROR
        error_msg = self._last_error or "Unknown error"
        return ActionResult(
            success=False,
            error=error_msg,
            attempts=policy.max_attempts,
            duration_ms=elapsed,
            page_url=self._page.url if self._page else "",
        )

    def _log_action(
        self, action: str, success: bool, attempt: int,
        duration_ms: float, error: Optional[str] = None,
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

    # -- Public API: Navigation --

    @property
    def state(self) -> BrowserState:
        return self._state

    @property
    def page(self) -> Optional[Page]:
        return self._page

    @property
    def url(self) -> str:
        return self._page.url if self._page else ""

    def get_stats(self) -> Dict[str, Any]:
        return {
            "state": self._state.value,
            "total_actions": len(self._action_log),
            "successes": sum(1 for a in self._action_log if a["success"]),
            "failures": sum(1 for a in self._action_log if not a["success"]),
            "error_count": self._error_count,
            "circuit_breaker": self._circuit_breaker.state.value,
            "uptime_seconds": round(time.time() - self._start_time, 1),
            "current_url": self.url,
        }

    async def navigate(
        self, url: str, wait_until: str = "domcontentloaded",
        timeout: Optional[int] = None,
    ) -> ActionResult:
        """Navigate to URL with retry and self-healing."""
        timeout = timeout or self._browser_cfg.navigation_timeout_ms

        async def _do():
            self._state = BrowserState.NAVIGATING
            resp = await self._page.goto(url, wait_until=wait_until, timeout=timeout)
            await asyncio.sleep(random.uniform(0.3, 0.8))
            return {
                "url": self._page.url,
                "status": resp.status if resp else None,
                "title": await self._page.title(),
            }
        return await self._execute("navigate", _do)

    async def reload(self, wait_until: str = "domcontentloaded") -> ActionResult:
        async def _do():
            await self._page.reload(wait_until=wait_until, timeout=15000)
            await asyncio.sleep(random.uniform(0.3, 0.8))
            return {"url": self._page.url, "title": await self._page.title()}
        return await self._execute("reload", _do)

    async def go_back(self) -> ActionResult:
        async def _do():
            await self._page.go_back(timeout=15000)
            await asyncio.sleep(random.uniform(0.3, 0.8))
            return {"url": self._page.url}
        return await self._execute("go_back", _do)

    # -- Public API: Interaction --

    async def click(
        self, selector: str, timeout: Optional[int] = None,
    ) -> ActionResult:
        timeout = timeout or self._browser_cfg.action_timeout_ms

        async def _do():
            await self._page.click(selector, timeout=timeout)
            delay = random.randint(80, 300)
            await asyncio.sleep(delay / 1000)
            return {"selector": selector, "clicked": True}
        return await self._execute("click", _do)

    async def type_text(
        self, selector: str, text: str,
        clear_first: bool = True, human_like: bool = True,
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
                        char, delay=random.randint(40, 120),
                    )
            else:
                await self._page.fill(selector, text)
            return {"selector": selector, "typed": len(text)}
        return await self._execute("type_text", _do)

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
                await asyncio.sleep(random.uniform(0.1, 0.25))
            return results
        return await self._execute("fill_form", _do)

    async def scroll_to_bottom(self) -> ActionResult:
        async def _do():
            prev_height = 0
            for _ in range(10):
                height = await self._page.evaluate("document.body.scrollHeight")
                if height == prev_height:
                    break
                await self._page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                prev_height = height
                await asyncio.sleep(random.uniform(0.3, 0.6))
            return {"scrolled": True, "final_height": prev_height}
        return await self._execute("scroll_to_bottom", _do)

    # -- Public API: Extraction --

    async def get_text(self, selector: str) -> ActionResult:
        async def _do():
            text = await self._page.text_content(selector, timeout=5000)
            return {"selector": selector, "text": text}
        return await self._execute("get_text", _do)

    async def get_inner_text(self, selector: str = "body") -> ActionResult:
        async def _do():
            text = await self._page.inner_text(selector, timeout=5000)
            return {"selector": selector, "text": text}
        return await self._execute("get_inner_text", _do)

    async def get_attribute(self, selector: str, attribute: str) -> ActionResult:
        async def _do():
            value = await self._page.get_attribute(selector, attribute, timeout=5000)
            return {"selector": selector, "attribute": attribute, "value": value}
        return await self._execute("get_attribute", _do)

    async def execute_script(self, script: str, arg: Any = None) -> ActionResult:
        async def _do():
            result = await self._page.evaluate(script, arg)
            return {"result": result}
        return await self._execute("execute_script", _do)

    async def screenshot(
        self, path: str = "screenshot.png", full_page: bool = False,
    ) -> ActionResult:
        async def _do():
            await self._page.screenshot(path=path, full_page=full_page)
            return {"path": path, "full_page": full_page}
        return await self._execute("screenshot", _do)

    # -- Public API: DOM Analysis --

    async def analyze_page(self) -> ActionResult:
        """Analyze current DOM state for autonomous decision-making."""
        async def _do():
            analysis = await self._page.evaluate("""() => {
                const title = document.title;
                const url = window.location.href;
                const body = document.body ? document.body.innerText.substring(0, 2000) : '';
                const forms = Array.from(document.querySelectorAll('form')).map(f => ({
                    action: f.action, method: f.method,
                    inputs: Array.from(f.querySelectorAll('input,textarea,select')).map(i => ({
                        type: i.type, name: i.name, id: i.id,
                        placeholder: i.placeholder, value: i.value ? '***' : ''
                    }))
                }));
                const buttons = Array.from(document.querySelectorAll('button,[role=button]'))
                    .slice(0, 20).map(b => ({
                        text: b.innerText.trim().substring(0, 50),
                        tag: b.tagName, disabled: b.disabled || false
                    }));
                const links = Array.from(document.querySelectorAll('a[href]'))
                    .slice(0, 20).map(a => ({
                        text: a.innerText.trim().substring(0, 50), href: a.href
                    }));
                const errors = Array.from(document.querySelectorAll(
                    '.error,.alert-danger,[role=alert]'
                )).map(e => e.innerText.trim().substring(0, 100));
                const loading = document.querySelector(
                    '.loading,.spinner,[role=progressbar]'
                ) !== null;
                const dialogs = Array.from(document.querySelectorAll(
                    '[role=dialog],.modal,.popup'
                )).map(d => d.innerText.trim().substring(0, 200));
                return { title, url, body_preview: body, forms, buttons, links, errors, loading, dialogs };
            }""")
            return PageAnalysis(**analysis).to_dict() if hasattr(PageAnalysis, 'to_dict') else analysis
        return await self._execute("analyze_page", _do)

    async def dismiss_dialogs(self) -> ActionResult:
        """Auto-detect and dismiss common dialogs."""
        async def _do():
            dismissed = []
            consent_selectors = [
                "button:has-text('Accept all')",
                "button:has-text('Accept')",
                "button:has-text('I agree')",
                "button:has-text('OK')",
                "button:has-text('Got it')",
            ]
            for sel in consent_selectors:
                try:
                    el = await self._page.query_selector(sel)
                    if el:
                        await self._page.click(sel, timeout=3000)
                        dismissed.append(sel)
                        await asyncio.sleep(random.uniform(0.3, 0.6))
                        break
                except Exception:
                    continue
            return {"dismissed": dismissed}
        return await self._execute("dismiss_dialogs", _do)

    async def wait_for(
        self, selector: str, timeout: Optional[int] = None,
    ) -> ActionResult:
        timeout = timeout or self._browser_cfg.action_timeout_ms

        async def _do():
            await self._page.wait_for_selector(selector, timeout=timeout)
            return {"selector": selector, "appeared": True}
        return await self._execute("wait_for", _do)

    # -- Workflow execution --

    async def execute_workflow(self, steps: List[Dict[str, Any]]) -> ActionResult:
        """Execute a sequence of browser actions from a config list."""
        async def _do():
            results = []
            for i, step in enumerate(steps):
                action = step.get("action")
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
                        r = await self.wait_for(step["selector"], step.get("timeout"))
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
                await asyncio.sleep(random.uniform(0.2, 0.6))
            return {"step_results": results, "completed": True}
        return await self._execute("execute_workflow", _do)
