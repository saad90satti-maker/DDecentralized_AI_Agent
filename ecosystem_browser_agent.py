"""
Ecosystem Browser Agent — browser-use powered web automation.

Integrates browser-use (Playwright CDP) into the ecosystem as a first-class
EcosystemAgent. Supports LLM-guided browsing, searching, data extraction,
screenshot capture, and page monitoring with shared memory persistence.

Tasks:
  - browse:       Navigate to URL, optionally extract content
  - search:       Web search via Google/DuckDuckGo
  - extract:      Extract structured data from current page
  - screenshot:   Capture page screenshot (returns base64 or file path)
  - fill_form:    Fill and submit a form
  - monitor:      Periodically check a page for changes
  - click:        Click an element on the page
  - scrape:       Scrape data with CSS selectors
"""

import asyncio
import base64
import json
import logging
import os
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from dotenv import load_dotenv

from ecosystem_agent import EcosystemAgent
from ecosystem_kernel import EcosystemKernel
from ecosystem_shared_memory import EcosystemMemory
from ecosystem_language import EILMessage

load_dotenv()

logger = logging.getLogger("ecosystem.agent.browser")

BASE_DIR = Path(__file__).resolve().parent
SCREENSHOT_DIR = BASE_DIR / "screenshots"
SCREENSHOT_DIR.mkdir(exist_ok=True)


def _make_llm():
    """Create an LLM instance from available credentials.

    Priority: Groq (fast, free) > Google Gemini (free) > Ollama (local).
    """
    groq_key = os.getenv("GROQ_API_KEY")
    if groq_key:
        from browser_use.llm.groq.chat import ChatGroq
        return ChatGroq(
            model="meta-llama/llama-4-maverick-17b-128e-instruct",
            api_key=groq_key,
            temperature=0.1,
        )

    gemini_key = os.getenv("GEMINI_API_KEY")
    if gemini_key:
        from browser_use.llm.google.chat import ChatGoogle
        return ChatGoogle(
            model="gemini-2.5-flash",
            api_key=gemini_key,
            temperature=0.1,
        )

    try:
        from browser_use.llm.ollama.chat import ChatOllama
        return ChatOllama(model="llama3.2:1b", temperature=0.1)
    except Exception:
        pass

    raise RuntimeError(
        "No LLM credentials found. Set GROQ_API_KEY, GEMINI_API_KEY, "
        "or run a local Ollama server."
    )


def _make_browser_profile():
    """Create a BrowserProfile from .env settings."""
    from browser_use import BrowserProfile

    headless = os.getenv("HEADLESS_BROWSER", "false").strip().lower()
    return BrowserProfile(
        headless=headless in ("true", "1", "yes"),
        allowed_domains=["*"],
        highlight_elements=True,
        keep_alive=False,
    )


class BrowserAgent(EcosystemAgent):
    """Web automation agent powered by browser-use."""

    agent_type = "browser"

    def __init__(self, kernel: EcosystemKernel,
                 memory: Optional[EcosystemMemory] = None,
                 agent_id: Optional[str] = None):
        super().__init__(kernel, memory, agent_id)
        self._llm = None
        self._browser = None
        self._browser_refs = 0
        self._concurrent_tasks: Dict[str, asyncio.Task] = {}

    def _declare_capabilities(self) -> Dict[str, Any]:
        return {
            "tasks": [
                "browse", "search", "extract", "screenshot",
                "fill_form", "monitor", "click", "scrape",
            ],
            "description": "Web automation agent powered by browser-use",
            "llm_providers": ["groq", "gemini", "ollama"],
            "version": "1.0.0",
        }

    async def _get_browser(self):
        """Lazy-init shared browser instance."""
        if self._browser is None:
            from browser_use import Browser
            self._browser = Browser(browser_profile=_make_browser_profile())
        self._browser_refs += 1
        return self._browser

    async def _release_browser(self):
        self._browser_refs -= 1

    async def execute_task(self, task: str,
                           params: Dict[str, Any]) -> Dict[str, Any]:
        task_lower = task.lower()

        if "browse" in task_lower:
            return await self._browse(params)
        if "search" in task_lower or "web_search" in task_lower:
            return await self._search_web(params)
        if "extract" in task_lower:
            return await self._extract(params)
        if "screenshot" in task_lower:
            return await self._screenshot(params)
        if "fill_form" in task_lower or "form" in task_lower:
            return await self._fill_form(params)
        if "monitor" in task_lower:
            return await self._monitor(params)
        if "click" in task_lower:
            return await self._click_element(params)
        if "scrape" in task_lower:
            return await self._scrape(params)

        return {"status": "unknown_task", "task": task,
                "hint": "Supported: browse, search, extract, screenshot, fill_form, monitor, click, scrape"}

    async def _run_agent(self, task_prompt: str,
                         max_steps: int = 30) -> Dict[str, Any]:
        """Run a browser-use Agent for a single task."""
        from browser_use import Agent, Tools, ActionResult

        if self._llm is None:
            self._llm = _make_llm()

        browser = await self._get_browser()

        tools = Tools()

        @tools.action(description="Store data in ecosystem shared memory")
        async def save_to_memory(key: str, value: str):
            self.learn(f"browser:{key}", value,
                       confidence=0.9, tags=["browser", "web"])
            return ActionResult(extracted_content=f"Saved '{key}' to memory")

        @tools.action(description="Store a screenshot with description")
        async def save_screenshot(description: str, browser_session):
            import datetime as dt
            ts = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"browser_{ts}_{uuid.uuid4().hex[:6]}.png"
            filepath = str(SCREENSHOT_DIR / filename)
            data = await browser_session.take_screenshot()
            if isinstance(data, str):
                raw = base64.b64decode(data)
            else:
                raw = data
            with open(filepath, "wb") as f:
                f.write(raw)
            self.learn(f"screenshot:{filename}", {
                "path": filepath, "description": description,
                "timestamp": dt.datetime.now().isoformat(),
            }, confidence=0.9, tags=["browser", "screenshot"])
            return ActionResult(
                extracted_content=f"Screenshot saved: {filepath}",
                include_extracted_content_only_once=True,
            )

        agent = Agent(
            task=task_prompt,
            llm=self._llm,
            browser=browser,
            tools=tools,
            use_vision=True,
            max_actions_per_step=5,
        )

        try:
            history = await agent.run(max_steps=max_steps)
            result_text = history.final_result() or ""
            step_count = len(history.history)
            usage = None
            if hasattr(history, "usage") and history.usage:
                usage = history.usage

            return {
                "status": "done",
                "result": result_text,
                "steps": step_count,
                "usage": str(usage) if usage else None,
                "success": True,
            }
        except Exception as e:
            logger.error("browser-use agent failed: %s", e)
            return {"status": "failed", "error": str(e), "success": False}
        finally:
            await self._release_browser()

    async def _browse(self, params: Dict[str, Any]) -> Dict[str, Any]:
        url = params.get("url", "")
        goal = params.get("goal", "")
        if not url and not goal:
            return {"status": "failed",
                    "error": "Provide 'url' or 'goal' parameter"}

        prompt = f"Navigate to {url}." if url else ""
        if goal:
            prompt += f" Goal: {goal}"
        prompt += (
            " After completing the task, use the done action "
            "and include the important content in your final answer."
        )

        result = await self._run_agent(prompt,
                                       max_steps=params.get("max_steps", 30))
        if result.get("success"):
            self.learn(f"browse:{url or goal}", {
                "result": result["result"],
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }, confidence=0.8, tags=["browser", "browse"])
        return result

    async def _search_web(self, params: Dict[str, Any]) -> Dict[str, Any]:
        query = params.get("query", "")
        if not query:
            return {"status": "failed",
                    "error": "Provide 'query' parameter for search"}

        prompt = (
            f"Search the web for: {query}. "
            "Visit the most relevant result and summarize the key information. "
            "Use the done action when finished and include your findings."
        )
        result = await self._run_agent(prompt,
                                       max_steps=params.get("max_steps", 20))
        if result.get("success"):
            self.learn(f"search:{query}", {
                "result": result["result"],
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }, confidence=0.8, tags=["browser", "search"])
            self.broadcast(f"search_result:{query}", {
                "summary": result["result"][:300],
            })
        return result

    async def _extract(self, params: Dict[str, Any]) -> Dict[str, Any]:
        url = params.get("url", "")
        schema_desc = params.get("schema", params.get("fields", ""))
        if not url:
            return {"status": "failed",
                    "error": "Provide 'url' parameter"}

        prompt = f"Go to {url} and extract: {schema_desc}"
        if schema_desc:
            prompt += (
                f". Extract the following fields: {schema_desc}. "
                "Present the data in a clear structured format."
            )
        prompt += (
            " Use the done action when finished and include "
            "all extracted data."
        )
        return await self._run_agent(prompt,
                                     max_steps=params.get("max_steps", 25))

    async def _screenshot(self, params: Dict[str, Any]) -> Dict[str, Any]:
        url = params.get("url", "")
        description = params.get("description", "page screenshot")
        if url:
            prompt = (
                f"Go to {url}, wait for the page to fully load, "
                f"then use save_screenshot with description='{description}' "
                "and call done."
            )
        else:
            prompt = (
                f"Take a screenshot of the current page with "
                f"description='{description}' and call done."
            )
        result = await self._run_agent(prompt,
                                       max_steps=params.get("max_steps", 15))
        if result.get("success"):
            result["screenshot_dir"] = str(SCREENSHOT_DIR)
        return result

    async def _fill_form(self, params: Dict[str, Any]) -> Dict[str, Any]:
        url = params.get("url", "")
        fields = params.get("fields", {})
        if not url or not fields:
            return {"status": "failed",
                    "error": "Provide both 'url' and 'fields' parameters"}

        field_desc = "; ".join(f"{k}: {v}" for k, v in fields.items())
        prompt = (
            f"Go to {url}. Fill in the form with these values: {field_desc}. "
            "Submit the form after filling. Use the done action when finished "
            "and report whether submission succeeded."
        )
        return await self._run_agent(prompt,
                                     max_steps=params.get("max_steps", 30))

    async def _monitor(self, params: Dict[str, Any]) -> Dict[str, Any]:
        url = params.get("url", "")
        selector = params.get("selector", "body")
        previous = params.get("previous_content", "")

        if not url:
            return {"status": "failed",
                    "error": "Provide 'url' parameter"}

        from browser_use import Agent, Browser, BrowserProfile

        if self._llm is None:
            self._llm = _make_llm()

        profile = BrowserProfile(
            headless=True,
            allowed_domains=["*"],
        )
        browser = Browser(browser_profile=profile)

        try:
            agent = Agent(
                task=(
                    f"Go to {url}. Wait for the page to load completely. "
                    f"Find the content at selector '{selector}' "
                    "and return all the text content inside it. "
                    "Use the done action and include the text."
                ),
                llm=self._llm,
                browser=browser,
                use_vision=False,
            )
            history = await agent.run(max_steps=10)
            current_content = history.final_result() or ""
            changed = (
                previous and current_content.strip() != previous.strip()
            )
            return {
                "status": "done",
                "url": url,
                "selector": selector,
                "content": current_content[:2000],
                "changed": changed,
                "previous_content": previous or current_content,
            }
        finally:
            await browser.close()

    async def _click_element(self, params: Dict[str, Any]) -> Dict[str, Any]:
        url = params.get("url", "")
        selector = params.get("selector", params.get("target", ""))
        if not url or not selector:
            return {"status": "failed",
                    "error": "Provide both 'url' and 'selector' parameters"}

        prompt = (
            f"Go to {url}. Find and click the element described as: "
            f"'{selector}'. Wait for any navigation or changes to complete. "
            "Use the done action when finished and describe what happened."
        )
        return await self._run_agent(prompt,
                                     max_steps=params.get("max_steps", 20))

    async def _scrape(self, params: Dict[str, Any]) -> Dict[str, Any]:
        url = params.get("url", "")
        css_selectors = params.get("selectors", params.get("css", ""))
        if not url or not css_selectors:
            return {"status": "failed",
                    "error": "Provide both 'url' and 'selectors' parameters"}

        if isinstance(css_selectors, str):
            selectors_list = [s.strip() for s in css_selectors.split(",")]
        else:
            selectors_list = list(css_selectors)

        prompt = (
            f"Go to {url}. For each of these CSS selectors, extract "
            f"the text content: {', '.join(selectors_list)}. "
            "Present results clearly labeled by selector. "
            "Use the done action when finished."
        )
        result = await self._run_agent(prompt,
                                       max_steps=params.get("max_steps", 25))
        if result.get("success"):
            self.learn(f"scrape:{url}", {
                "selectors": selectors_list,
                "result": result["result"],
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }, confidence=0.8, tags=["browser", "scrape"])
        return result

    async def handle_message(self, msg: EILMessage) -> None:
        if msg.type == "task" and "monitor" in msg.task.lower():
            task_ref = msg.ref or msg.id
            self._active_task = task_ref
            try:
                result = await self.execute_task(msg.task, msg.result)
                self._task_count += 1
                reply = EILMessage.response(
                    self.agent_id, msg.src, task_ref,
                    result, status="done", task=msg.task,
                )
                await self.send(reply)
                if result.get("changed"):
                    alert = EILMessage.broadcast(
                        self.agent_id,
                        f"alert:page_changed:{msg.result.get('url', 'unknown')}",
                        {"change": result, "task": msg.task},
                        self.agent_type,
                    )
                    await self.send(alert)
            except Exception as e:
                self._error_count += 1
                reply = EILMessage.error(
                    self.agent_id, msg.src, msg.task, str(e), task_ref
                )
                await self.send(reply)
            finally:
                self._active_task = None
        else:
            await super().handle_message(msg)

    async def start(self):
        await super().start()
        logger.info("BrowserAgent %s ready (LLM: %s, headless: %s)",
                     self.agent_id,
                     "groq" if os.getenv("GROQ_API_KEY") else "gemini",
                     os.getenv("HEADLESS_BROWSER", "false"))

    async def stop(self):
        if self._browser is not None:
            try:
                await self._browser.close()
            except Exception:
                pass
            self._browser = None
        await super().stop()
        logger.info("BrowserAgent %s stopped", self.agent_id)
