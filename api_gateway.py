"""
Unified API Gateway v2 — cloud-native model router with latency-based
dynamic provider switching. No local LLM dependencies.

When primary provider latency spikes above threshold, the gateway
automatically switches to the fastest available provider without restart.
"""

import os
import json
import time
import logging
import asyncio
from typing import Optional, AsyncIterator
from dataclasses import dataclass, field

import httpx

logger = logging.getLogger("api_gateway")

# ---------------------------------------------------------------------------
# Provider configuration
# ---------------------------------------------------------------------------

PROVIDER_CONFIGS = {
    "groq": {
        "base_url": "https://api.groq.com/openai/v1",
        "env_key": "GROQ_API_KEY",
        "models": {
            "llama-3.3-70b-versatile": {"max_tokens": 32768, "supports_fc": True},
            "llama-3.1-8b-instant": {"max_tokens": 8192, "supports_fc": True},
            "mixtral-8x7b-32768": {"max_tokens": 32768, "supports_fc": True},
            "deepseek-r1-distill-llama-70b": {"max_tokens": 65536, "supports_fc": False},
        },
    },
    "deepseek": {
        "base_url": "https://api.deepseek.com/v1",
        "env_key": "DEEPSEEK_API_KEY",
        "models": {
            "deepseek-chat": {"max_tokens": 65536, "supports_fc": True},
            "deepseek-coder": {"max_tokens": 65536, "supports_fc": True},
        },
    },
    "gemini": {
        "base_url": "https://generativelanguage.googleapis.com/v1beta",
        "env_key": "GEMINI_API_KEY",
        "models": {
            "gemini-2.5-flash": {"max_tokens": 65536, "supports_fc": True},
            "gemini-2.5-pro": {"max_tokens": 65536, "supports_fc": True},
        },
    },
    "openai": {
        "base_url": os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1"),
        "env_key": "OPENAI_API_KEY",
        "models": {
            "gpt-5": {"max_tokens": 65536, "supports_fc": True},
            "gpt-5-nano": {"max_tokens": 16384, "supports_fc": True},
        },
    },
}


@dataclass
class GatewayConfig:
    preferred_provider: str = os.getenv("PREFERRED_PROVIDER", "groq")
    preferred_model: str = os.getenv("PREFERRED_MODEL", "llama-3.3-70b-versatile")
    fallback_provider: str = os.getenv("FALLBACK_PROVIDER", "deepseek")
    fallback_model: str = os.getenv("FALLBACK_MODEL", "deepseek-chat")
    timeout: int = int(os.getenv("GATEWAY_TIMEOUT", "60"))
    max_retries: int = int(os.getenv("GATEWAY_MAX_RETRIES", "3"))

    # Latency-based switching
    latency_window: int = int(os.getenv("GATEWAY_LATENCY_WINDOW", "10"))  # samples to keep
    latency_threshold_ms: float = float(os.getenv("GATEWAY_LATENCY_THRESHOLD", "5000"))  # 5s


@dataclass
class GatewayResponse:
    text: str
    provider: str
    model: str
    latency_ms: float
    tool_calls: list = field(default_factory=list)
    finish_reason: str = "stop"


# ---------------------------------------------------------------------------
# Unified API Gateway v2 — Dynamic Provider Switching
# ---------------------------------------------------------------------------

class UnifiedAPIGateway:
    """Zero local LLM dependency. Dynamically selects fastest provider
    based on rolling latency history."""

    def __init__(self, config: Optional[GatewayConfig] = None):
        self.config = config or GatewayConfig()
        self._client = httpx.AsyncClient(timeout=self.config.timeout)
        self._providers: dict = {}
        self._latency_history: dict[str, list[float]] = {}  # provider -> [latency_ms]
        self._current_provider: Optional[str] = None

    async def initialize(self):
        """Probe all configured providers."""
        for name, cfg in PROVIDER_CONFIGS.items():
            api_key = os.getenv(cfg["env_key"])
            if not api_key:
                continue
            try:
                resp = await self._client.get(
                    f"{cfg['base_url'].rstrip('/')}/models",
                    headers={"Authorization": f"Bearer {api_key}"},
                    timeout=5,
                )
                if resp.status_code == 200:
                    self._providers[name] = {**cfg, "api_key": api_key}
                    self._latency_history[name] = []
                    logger.info("Provider %s ONLINE (%d models)", name, len(cfg["models"]))
            except Exception as e:
                logger.warning("Provider %s unreachable: %s", name, e)

        # Seed current provider
        if self.config.preferred_provider in self._providers:
            self._current_provider = self.config.preferred_provider
        elif self._providers:
            self._current_provider = next(iter(self._providers))

        if not self._providers:
            logger.critical("No remote providers available")
        return self._providers

    # ------------------------------------------------------------------
    # Latency tracking
    # ------------------------------------------------------------------

    def _record_latency(self, provider: str, latency_ms: float):
        window = self.config.latency_window
        if provider in self._latency_history:
            self._latency_history[provider].append(latency_ms)
            if len(self._latency_history[provider]) > window:
                self._latency_history[provider] = self._latency_history[provider][-window:]

    def _get_median_latency(self, provider: str) -> Optional[float]:
        samples = self._latency_history.get(provider, [])
        if not samples:
            return None
        sorted_s = sorted(samples)
        return sorted_s[len(sorted_s) // 2]

    def _select_best_provider(self, preferred: str) -> str:
        """Select the provider with lowest median latency, preferring the
        current provider if its latency is below threshold."""
        if len(self._providers) <= 1:
            return preferred

        current_latency = self._get_median_latency(preferred)
        if current_latency is None or current_latency < self.config.latency_threshold_ms:
            return preferred  # current is fine (or no data yet — stay put)

        # Find the fastest provider among those with actual data
        best_name = preferred
        best_latency = current_latency or float("inf")

        for name in self._providers:
            if name == preferred:
                continue
            med = self._get_median_latency(name)
            if med is None:
                continue  # Skip providers with no success data (avoids 401 looping)
            if med < best_latency:
                best_latency = med
                best_name = name

        if best_name != preferred:
            logger.info("Latency switch: %s (%.0fms) -> %s (%.0fms)",
                        preferred, current_latency or 0, best_name, best_latency)
        return best_name

    # ------------------------------------------------------------------
    # Core inference
    # ------------------------------------------------------------------

    async def chat(
        self,
        messages: list,
        model: Optional[str] = None,
        provider: Optional[str] = None,
        temperature: float = 0.3,
        max_tokens: Optional[int] = None,
        tools: Optional[list] = None,
        stream: bool = False,
    ) -> GatewayResponse:
        provider = provider or self._current_provider or self.config.preferred_provider
        model = model or self.config.preferred_model

        if provider not in self._providers:
            return await self._fallback(messages, model, temperature, max_tokens, tools, stream)

        # Dynamic provider selection based on latency
        selected = self._select_best_provider(provider)
        if selected != provider:
            provider = selected
            self._current_provider = selected

        cfg = self._providers[provider]
        api_key = cfg["api_key"]
        url = f"{cfg['base_url'].rstrip('/')}/chat/completions"

        payload = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens or cfg["models"].get(model, {}).get("max_tokens", 16384),
        }
        if tools and cfg["models"].get(model, {}).get("supports_fc", False):
            payload["tools"] = tools
            payload["tool_choice"] = "auto"

        for attempt in range(self.config.max_retries):
            t0 = time.monotonic()
            try:
                resp = await self._client.post(
                    url,
                    headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                    json=payload,
                )

                if resp.status_code == 200:
                    latency = (time.monotonic() - t0) * 1000
                    self._record_latency(provider, latency)
                    data = resp.json()
                    choice = data["choices"][0]
                    msg = choice.get("message", {})
                    return GatewayResponse(
                        text=msg.get("content", "") or "",
                        provider=provider, model=model, latency_ms=latency,
                        tool_calls=msg.get("tool_calls", []),
                        finish_reason=choice.get("finish_reason", "stop"),
                    )
                elif resp.status_code == 429:
                    wait = 2 ** attempt
                    logger.warning("Rate limited on %s/%s, retry in %ds", provider, model, wait)
                    await asyncio.sleep(wait)
                    continue
                else:
                    logger.error("%s/%s returned %d", provider, model, resp.status_code)
                    if attempt < self.config.max_retries - 1:
                        await asyncio.sleep(1)
                        continue
                    return await self._fallback(messages, model, temperature, max_tokens, tools, stream)
            except httpx.TimeoutException:
                logger.warning("Timeout %s/%s (attempt %d)", provider, model, attempt + 1)
                self._record_latency(provider, 99999)  # Penalize
                if attempt < self.config.max_retries - 1:
                    await asyncio.sleep(1)
                    continue
                return await self._fallback(messages, model, temperature, max_tokens, tools, stream)
            except Exception as e:
                logger.error("Error %s/%s: %s", provider, model, e)
                return await self._fallback(messages, model, temperature, max_tokens, tools, stream)

        return await self._fallback(messages, model, temperature, max_tokens, tools, stream)

    # ------------------------------------------------------------------
    # Streaming
    # ------------------------------------------------------------------

    async def chat_stream(
        self,
        messages: list,
        model: Optional[str] = None,
        provider: Optional[str] = None,
        temperature: float = 0.3,
    ) -> AsyncIterator[str]:
        provider = provider or self._current_provider or self.config.preferred_provider
        model = model or self.config.preferred_model

        if provider not in self._providers:
            provider = next(iter(self._providers), None)
            if not provider:
                yield "ERROR: No providers available"
                return

        cfg = self._providers[provider]
        api_key = cfg["api_key"]
        url = f"{cfg['base_url'].rstrip('/')}/chat/completions"

        payload = {
            "model": model, "messages": messages, "temperature": temperature,
            "max_tokens": cfg["models"].get(model, {}).get("max_tokens", 16384),
            "stream": True,
        }
        try:
            t0 = time.monotonic()
            async with self._client.stream(
                "POST", url,
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                json=payload,
            ) as resp:
                async for line in resp.aiter_lines():
                    if line.startswith("data: "):
                        chunk = line[6:]
                        if chunk.strip() == "[DONE]":
                            break
                        try:
                            data = json.loads(chunk)
                            content = data["choices"][0].get("delta", {}).get("content", "")
                            if content:
                                yield content
                        except (json.JSONDecodeError, KeyError, IndexError):
                            continue
            latency = (time.monotonic() - t0) * 1000
            self._record_latency(provider, latency)
        except Exception as e:
            logger.error("Stream error %s/%s: %s", provider, model, e)
            yield f"\n[STREAM ERROR: {e}]"

    # ------------------------------------------------------------------
    # Fallback chain (dynamic — picks fastest surviving provider)
    # ------------------------------------------------------------------

    async def _fallback(self, messages: list, model: str, temperature: float,
                        max_tokens: Optional[int], tools: Optional[list], stream: bool) -> GatewayResponse:
        # Rank available providers by median latency
        ranked = sorted(
            [p for p in self._providers if p != self._current_provider],
            key=lambda p: self._get_median_latency(p) or 99999,
        )

        for name in ranked:
            fb_model = next(iter(self._providers[name]["models"]), None)
            if fb_model:
                logger.info("Fallback to %s/%s", name, fb_model)
                resp = await self.chat(
                    messages, model=fb_model, provider=name,
                    temperature=temperature, max_tokens=max_tokens, tools=tools,
                )
                if resp.provider != "none":
                    return resp

        # Last resort — try any provider
        for name, cfg in self._providers.items():
            fb_model = next(iter(cfg["models"]), None)
            if fb_model:
                logger.info("Emergency fallback to %s/%s", name, fb_model)
                return await self.chat(
                    messages, model=fb_model, provider=name,
                    temperature=temperature, max_tokens=max_tokens, tools=tools,
                )

        return GatewayResponse(
            text="ERROR: All providers unavailable. Set API keys.",
            provider="none", model="none", latency_ms=0,
        )

    # ------------------------------------------------------------------
    # Status
    # ------------------------------------------------------------------

    def get_status(self) -> dict:
        return {
            "current_provider": self._current_provider,
            "providers": list(self._providers.keys()),
            "latency_history": {
                p: {"samples": len(h), "median_ms": self._get_median_latency(p)}
                for p, h in self._latency_history.items()
            },
            "available_models": {
                name: list(cfg["models"].keys()) for name, cfg in self._providers.items()
            },
        }

    async def close(self):
        await self._client.aclose()
