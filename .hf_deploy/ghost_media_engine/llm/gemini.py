"""
Gemini LLM backend using free-tier API.
Async httpx calls with rate limiting and retry.
"""

import asyncio
import json
import re
import time
from typing import Any, Dict, Optional

import httpx

from ghost_media_engine.config import LLMConfig
from ghost_media_engine.llm.base import BaseLLM, LLMResponse, RateLimiter
from ghost_media_engine.logging import get_logger

logger = get_logger("GeminiLLM")


class GeminiLLM(BaseLLM):
    """
    Gemini API connector with async httpx, rate limiting, and retry.

    Usage:
        llm = GeminiLLM(config.llm)
        response = await llm.generate("Summarize this text...")
    """

    def __init__(self, config: LLMConfig):
        super().__init__(
            name="gemini",
            timeout=config.gemini_timeout,
            max_retries=config.max_retries,
        )
        self.api_key = config.gemini_api_key
        self.model = config.gemini_model
        self.base_url = "https://generativelanguage.googleapis.com/v1beta"
        self.rate_limiter = RateLimiter(rpm=config.rate_limit_rpm)
        self._client: Optional[httpx.AsyncClient] = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(timeout=self.timeout)
        return self._client

    async def generate(self, prompt: str, **kwargs) -> LLMResponse:
        """Generate a response from Gemini API."""
        if not self.api_key:
            self._record_call(0, False)
            return LLMResponse(
                success=False,
                error="GEMINI_API_KEY not configured",
                model=self.model,
                source="gemini",
            )

        # Rate limit
        await self.rate_limiter.acquire()

        payload = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {
                "temperature": kwargs.get("temperature", 0.4),
                "maxOutputTokens": kwargs.get("max_tokens", 600),
            },
        }

        last_error = None
        for attempt in range(1, self.max_retries + 1):
            start = time.time()
            try:
                client = await self._get_client()
                url = f"{self.base_url}/{self.model}:generateContent"
                response = await client.post(
                    url,
                    json=payload,
                    params={"key": self.api_key},
                )

                latency = time.time() - start

                if response.status_code == 200:
                    data = response.json()
                    output = data["candidates"][0]["content"]["parts"][0]["text"]
                    self._record_call(latency, True)
                    logger.success("Gemini response in %.1fs (%d chars)", latency, len(output))
                    return LLMResponse(
                        success=True,
                        output=output.strip(),
                        model=self.model,
                        source="gemini",
                        latency_ms=latency * 1000,
                        raw=data,
                    )

                if response.status_code == 429:
                    retry_after = 15
                    logger.warning("Gemini rate limited, waiting %ds", retry_after)
                    await asyncio.sleep(retry_after)
                    continue

                last_error = f"HTTP {response.status_code}: {response.text[:200]}"
                logger.warning("Gemini error (attempt %d/%d): %s", attempt, self.max_retries, last_error)

            except httpx.TimeoutException:
                latency = time.time() - start
                last_error = f"Timeout after {latency:.1f}s"
                logger.warning("Gemini timeout (attempt %d/%d)", attempt, self.max_retries)
            except Exception as exc:
                latency = time.time() - start
                last_error = str(exc)
                logger.warning("Gemini error (attempt %d/%d): %s", attempt, self.max_retries, exc)

            if attempt < self.max_retries:
                await asyncio.sleep(2 ** attempt)

        self._record_call(0, False)
        return LLMResponse(
            success=False,
            error=last_error,
            model=self.model,
            source="gemini",
        )

    async def health_check(self) -> bool:
        """Verify Gemini API is reachable."""
        if not self.api_key:
            return False
        try:
            client = await self._get_client()
            response = await client.get(
                f"{self.base_url}/models",
                params={"key": self.api_key},
            )
            return response.status_code == 200
        except Exception:
            return False

    async def close(self) -> None:
        if self._client and not self._client.is_closed:
            await self._client.aclose()
