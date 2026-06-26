"""
Ecosystem X (Twitter) Agent — social media integration.

Posts research findings, articles, and ecosystem updates to X.
Supports posting threads, searching, and monitoring mentions.

Requires X API v2 credentials in .env:
  X_API_KEY, X_API_KEY_SECRET, X_ACCESS_TOKEN, X_ACCESS_TOKEN_SECRET
"""

import asyncio
import json
import logging
import os
import re
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from dotenv import load_dotenv

from ecosystem_agent import EcosystemAgent
from ecosystem_kernel import EcosystemKernel
from ecosystem_shared_memory import EcosystemMemory
from ecosystem_language import EILMessage

load_dotenv()
logger = logging.getLogger("ecosystem.agent.x")


class XAgent(EcosystemAgent):
    """Social media agent for X (Twitter) integration."""

    agent_type = "x_social"

    def __init__(self, kernel: EcosystemKernel,
                 memory: Optional[EcosystemMemory] = None,
                 agent_id: Optional[str] = None):
        self._available = self._check_credentials()
        super().__init__(kernel, memory, agent_id)
        self._client = None

    def _check_credentials(self) -> bool:
        required = ["X_API_KEY", "X_API_KEY_SECRET",
                    "X_ACCESS_TOKEN", "X_ACCESS_TOKEN_SECRET"]
        present = all(os.getenv(k) for k in required)
        if not present:
            logger.warning("X credentials not fully configured")
        return present

    def _declare_capabilities(self) -> Dict[str, Any]:
        return {
            "tasks": [
                "post_tweet", "post_thread", "search_x",
                "get_timeline", "monitor_mentions",
            ],
            "description": "X (Twitter) social media integration agent",
            "credentials_configured": self._available,
            "version": "1.0.0",
        }

    async def _get_client(self):
        if self._client is None and self._available:
            import tweepy
            self._client = tweepy.Client(
                consumer_key=os.getenv("X_API_KEY"),
                consumer_secret=os.getenv("X_API_KEY_SECRET"),
                access_token=os.getenv("X_ACCESS_TOKEN"),
                access_token_secret=os.getenv("X_ACCESS_TOKEN_SECRET"),
                wait_on_rate_limit=True,
            )
        return self._client

    async def execute_task(self, task: str,
                           params: Dict[str, Any]) -> Dict[str, Any]:
        if not self._available:
            return {"status": "failed",
                    "error": "X credentials not configured. Set X_API_KEY, X_API_KEY_SECRET, X_ACCESS_TOKEN, X_ACCESS_TOKEN_SECRET in .env"}

        task_lower = task.lower()

        if "post_tweet" in task_lower or "tweet" in task_lower:
            return await self._post_tweet(params)
        if "post_thread" in task_lower or "thread" in task_lower:
            return await self._post_thread(params)
        if "search" in task_lower:
            return await self._search(params)
        if "timeline" in task_lower:
            return await self._timeline(params)
        if "monitor" in task_lower or "mentions" in task_lower:
            return await self._monitor_mentions(params)

        return {"status": "unknown_task", "task": task,
                "hint": "Supported: post_tweet, post_thread, search_x, get_timeline, monitor_mentions"}

    async def _post_tweet(self, params: Dict[str, Any]) -> Dict[str, Any]:
        text = params.get("text", "")
        if not text:
            return {"status": "failed", "error": "Provide 'text' parameter"}

        if len(text) > 280:
            text = text[:277] + "..."

        client = await self._get_client()
        try:
            response = await asyncio.to_thread(client.create_tweet, text=text)
            tweet_id = response.data.get("id", "")
            self.learn(f"x:tweet:{tweet_id}", {
                "text": text,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }, confidence=1.0, tags=["x", "tweet"])
            return {
                "status": "done",
                "tweet_id": tweet_id,
                "text": text,
                "url": f"https://x.com/user/status/{tweet_id}",
            }
        except Exception as e:
            return {"status": "failed", "error": str(e)}

    async def _post_thread(self, params: Dict[str, Any]) -> Dict[str, Any]:
        tweets = params.get("tweets", [])
        if not tweets:
            return {"status": "failed",
                    "error": "Provide 'tweets' list of strings"}

        client = await self._get_client()
        posted = []
        reply_to = None
        try:
            for text in tweets:
                if len(text) > 280:
                    text = text[:277] + "..."
                kwargs = {"text": text}
                if reply_to:
                    kwargs["in_reply_to_tweet_id"] = reply_to
                response = await asyncio.to_thread(
                    lambda: client.create_tweet(**kwargs)
                )
                tweet_id = response.data.get("id", "")
                posted.append({"tweet_id": tweet_id, "text": text})
                reply_to = tweet_id
                await asyncio.sleep(0.5)
            return {
                "status": "done",
                "tweets_posted": len(posted),
                "thread": posted,
            }
        except Exception as e:
            return {"status": "partial" if posted else "failed",
                    "error": str(e),
                    "posted": posted}

    async def _search(self, params: Dict[str, Any]) -> Dict[str, Any]:
        query = params.get("query", "")
        max_results = min(params.get("max_results", 10), 100)
        if not query:
            return {"status": "failed", "error": "Provide 'query' parameter"}

        client = await self._get_client()
        try:
            response = await asyncio.to_thread(
                lambda: client.search_recent_tweets(
                    query=query,
                    max_results=max_results,
                    tweet_fields=["created_at", "public_metrics", "author_id"],
                )
            )
            tweets = []
            if response.data:
                for tweet in response.data:
                    tweets.append({
                        "id": tweet.id,
                        "text": tweet.text[:200],
                        "created_at": str(tweet.created_at) if hasattr(tweet, "created_at") else "",
                        "author_id": tweet.author_id if hasattr(tweet, "author_id") else "",
                    })
            return {"status": "done", "query": query,
                    "results": tweets, "count": len(tweets)}
        except Exception as e:
            return {"status": "failed", "error": str(e)}

    async def _timeline(self, params: Dict[str, Any]) -> Dict[str, Any]:
        client = await self._get_client()
        try:
            response = await asyncio.to_thread(
                lambda: client.get_home_timeline(
                    max_results=min(params.get("max_results", 20), 100),
                    tweet_fields=["created_at", "public_metrics"],
                )
            )
            tweets = []
            if response.data:
                for tweet in response.data:
                    tweets.append({
                        "id": tweet.id,
                        "text": tweet.text[:200],
                        "created_at": str(tweet.created_at) if hasattr(tweet, "created_at") else "",
                    })
            return {"status": "done", "tweets": tweets, "count": len(tweets)}
        except Exception as e:
            return {"status": "failed", "error": str(e)}

    async def _monitor_mentions(self, params: Dict[str, Any]) -> Dict[str, Any]:
        client = await self._get_client()
        try:
            me = await asyncio.to_thread(client.get_me)
            user_id = me.data.id
            response = await asyncio.to_thread(
                lambda: client.get_users_mentions(
                    id=user_id,
                    max_results=min(params.get("max_results", 20), 100),
                    tweet_fields=["created_at", "author_id"],
                )
            )
            mentions = []
            if response.data:
                for tweet in response.data:
                    mentions.append({
                        "id": tweet.id,
                        "text": tweet.text[:200],
                        "author_id": tweet.author_id,
                        "created_at": str(tweet.created_at),
                    })
            return {"status": "done", "mentions": mentions, "count": len(mentions)}
        except Exception as e:
            return {"status": "failed", "error": str(e)}

    async def start(self):
        await super().start()
        status = "configured" if self._available else "missing credentials"
        logger.info("XAgent %s ready (%s)", self.agent_id, status)

    async def stop(self):
        await super().stop()
        logger.info("XAgent %s stopped", self.agent_id)
