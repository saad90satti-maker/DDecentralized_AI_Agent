"""
Ecosystem Telegram Agent — messaging integration.

Sends messages, manages channels, and bridges research
findings to Telegram groups.

Requires TELEGRAM_BOT_TOKEN in .env.
"""

import asyncio
import json
import logging
import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from dotenv import load_dotenv

from ecosystem_agent import EcosystemAgent
from ecosystem_kernel import EcosystemKernel
from ecosystem_shared_memory import EcosystemMemory
from ecosystem_language import EILMessage

load_dotenv()
logger = logging.getLogger("ecosystem.agent.telegram")


class TelegramAgent(EcosystemAgent):
    """Messaging agent for Telegram integration."""

    agent_type = "telegram"

    def __init__(self, kernel: EcosystemKernel,
                 memory: Optional[EcosystemMemory] = None,
                 agent_id: Optional[str] = None):
        self._bot_token = os.getenv("TELEGRAM_BOT_TOKEN", "")
        self._chat_id = os.getenv("TELEGRAM_CHAT_ID", "")
        self._available = bool(self._bot_token)
        super().__init__(kernel, memory, agent_id)
        self._bot = None

    def _declare_capabilities(self) -> Dict[str, Any]:
        return {
            "tasks": [
                "send_message", "send_article", "broadcast_update",
                "send_markdown", "list_chats",
            ],
            "description": "Telegram messaging integration agent",
            "credentials_configured": self._available,
            "version": "1.0.0",
        }

    async def _get_bot(self):
        if self._bot is None and self._available:
            try:
                from telegram import Bot
                self._bot = Bot(token=self._bot_token)
            except ImportError:
                logger.warning("python-telegram-bot not installed")
                return None
        return self._bot

    async def execute_task(self, task: str,
                           params: Dict[str, Any]) -> Dict[str, Any]:
        if not self._available:
            return {"status": "failed",
                    "error": "Telegram not configured. Set TELEGRAM_BOT_TOKEN in .env"}

        task_lower = task.lower()

        if "send_message" in task_lower or "message" in task_lower:
            return await self._send_message(params)
        if "send_article" in task_lower or "article" in task_lower:
            return await self._send_article(params)
        if "broadcast" in task_lower:
            return await self._broadcast(params)
        if "send_markdown" in task_lower or "markdown" in task_lower:
            return await self._send_markdown(params)

        return {"status": "unknown_task", "task": task,
                "hint": "Supported: send_message, send_article, broadcast_update, send_markdown"}

    async def _send_message(self, params: Dict[str, Any]) -> Dict[str, Any]:
        text = params.get("text", "")
        chat_id = params.get("chat_id") or self._chat_id
        if not text or not chat_id:
            return {"status": "failed",
                    "error": "Provide 'text' and 'chat_id' (or set TELEGRAM_CHAT_ID)"}
        try:
            bot = await self._get_bot()
            if not bot:
                return {"status": "failed",
                        "error": "python-telegram-bot not available"}
            await bot.send_message(chat_id=chat_id, text=text[:4096])
            self.learn(f"telegram:msg:{chat_id}", {
                "text_preview": text[:100],
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }, confidence=1.0, tags=["telegram", "message"])
            return {"status": "done", "chat_id": str(chat_id)}
        except Exception as e:
            return {"status": "failed", "error": str(e)}

    async def _send_article(self, params: Dict[str, Any]) -> Dict[str, Any]:
        title = params.get("title", "Research Update")
        summary = params.get("summary", "")
        url = params.get("url", "")
        chat_id = params.get("chat_id") or self._chat_id
        if not chat_id:
            return {"status": "failed",
                    "error": "Provide 'chat_id' or set TELEGRAM_CHAT_ID"}

        text = f"*{title}*\n\n{summary[:500]}"
        if url:
            text += f"\n\n🔗 [Read more]({url})"
        return await self._send_message({"text": text, "chat_id": chat_id})

    async def _broadcast(self, params: Dict[str, Any]) -> Dict[str, Any]:
        text = params.get("text", "")
        chats = params.get("chat_ids", [])
        if self._chat_id:
            chats.append(self._chat_id)
        if not text or not chats:
            return {"status": "failed",
                    "error": "Provide 'text' and 'chat_ids' list"}
        results = []
        for cid in set(chats):
            try:
                bot = await self._get_bot()
                if bot:
                    await bot.send_message(chat_id=cid, text=text[:4096])
                    results.append({"chat_id": str(cid), "status": "done"})
            except Exception as e:
                results.append({"chat_id": str(cid), "status": "failed", "error": str(e)})
        return {"status": "done", "results": results,
                "sent": sum(1 for r in results if r["status"] == "done"),
                "failed": sum(1 for r in results if r["status"] == "failed")}

    async def _send_markdown(self, params: Dict[str, Any]) -> Dict[str, Any]:
        text = params.get("text", "")
        chat_id = params.get("chat_id") or self._chat_id
        if not text or not chat_id:
            return {"status": "failed",
                    "error": "Provide 'text' and 'chat_id'"}
        try:
            bot = await self._get_bot()
            if not bot:
                return {"status": "failed",
                        "error": "python-telegram-bot not available"}
            await bot.send_message(
                chat_id=chat_id, text=text[:4096],
                parse_mode="MarkdownV2",
                disable_web_page_preview=True,
            )
            return {"status": "done", "chat_id": str(chat_id)}
        except Exception as e:
            return {"status": "failed", "error": str(e)}

    async def start(self):
        await super().start()
        status = "configured" if self._available else "missing TELEGRAM_BOT_TOKEN"
        logger.info("TelegramAgent %s ready (%s)", self.agent_id, status)

    async def stop(self):
        await super().stop()
        logger.info("TelegramAgent %s stopped", self.agent_id)
