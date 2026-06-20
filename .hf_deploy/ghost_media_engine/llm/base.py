"""
Abstract LLM interface with rate limiting and timeout support.
All LLM backends implement this interface.
"""

import asyncio
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, Optional

from ghost_media_engine.logging import get_logger

logger = get_logger("LLM")


@dataclass
class LLMResponse:
    """Unified response from any LLM backend."""
    success: bool
    output: str = ""
    model: str = ""
    source: str = ""
    latency_ms: float = 0.0
    error: Optional[str] = None
    raw: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "success": self.success,
            "output": self.output[:500],
            "model": self.model,
            "source": self.source,
            "latency_ms": round(self.latency_ms, 2),
            "error": self.error,
        }


class BaseLLM(ABC):
    """
    Abstract base class for LLM backends.

    All implementations must provide:
    - generate(prompt, **kwargs) -> LLMResponse
    - health_check() -> bool
    """

    def __init__(self, name: str, timeout: int = 30, max_retries: int = 3):
        self.name = name
        self.timeout = timeout
        self.max_retries = max_retries
        self._call_count = 0
        self._error_count = 0
        self._total_latency = 0.0

    @abstractmethod
    async def generate(self, prompt: str, **kwargs) -> LLMResponse:
        """Generate a response from the LLM."""
        ...

    @abstractmethod
    async def health_check(self) -> bool:
        """Check if the LLM backend is available and responding."""
        ...

    def get_stats(self) -> Dict[str, Any]:
        """Get usage statistics."""
        avg_latency = (self._total_latency / self._call_count * 1000) if self._call_count > 0 else 0
        return {
            "name": self.name,
            "total_calls": self._call_count,
            "total_errors": self._error_count,
            "avg_latency_ms": round(avg_latency, 2),
            "success_rate": round(
                (self._call_count - self._error_count) / self._call_count * 100, 1
            ) if self._call_count > 0 else 0,
        }

    def _record_call(self, latency: float, success: bool) -> None:
        self._call_count += 1
        self._total_latency += latency
        if not success:
            self._error_count += 1


class RateLimiter:
    """Async rate limiter using token bucket algorithm."""

    def __init__(self, rpm: int = 15):
        self.rpm = rpm
        self._tokens = rpm
        self._last_refill = time.time()
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        """Wait until a token is available."""
        async with self._lock:
            now = time.time()
            elapsed = now - self._last_refill
            # Refill tokens based on elapsed time
            new_tokens = elapsed * (self.rpm / 60.0)
            self._tokens = min(self.rpm, self._tokens + new_tokens)
            self._last_refill = now

            if self._tokens < 1:
                # Calculate wait time for next token
                wait_time = (1 - self._tokens) * (60.0 / self.rpm)
                logger.debug("Rate limiter: waiting %.1fs for token", wait_time)
                await asyncio.sleep(wait_time)
                self._tokens = 1
                self._last_refill = time.time()

            self._tokens -= 1
