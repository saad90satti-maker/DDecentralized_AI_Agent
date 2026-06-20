"""
Hermes/Ollama LLM backend with async HTTP and CLI fallback.
"""

import asyncio
import time
from typing import Any, Dict, Optional

import httpx

from ghost_media_engine.config import LLMConfig
from ghost_media_engine.llm.base import BaseLLM, LLMResponse
from ghost_media_engine.logging import get_logger

logger = get_logger("HermesLLM")


class HermesLLM(BaseLLM):
    """
    Hermes/Ollama LLM backend with HTTP-first, CLI-fallback strategy.

    Usage:
        llm = HermesLLM(config.llm)
        response = await llm.generate("Summarize this text...")
    """

    HEALTH_ENDPOINTS = ["/v1/models", "/v1/health", "/health", "/"]

    def __init__(self, config: LLMConfig):
        super().__init__(
            name="hermes",
            timeout=config.hermes_timeout,
            max_retries=config.max_retries,
        )
        self.url = config.hermes_url.rstrip("/")
        self.model = config.hermes_model
        self._client: Optional[httpx.AsyncClient] = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(timeout=self.timeout)
        return self._client

    async def generate(self, prompt: str, **kwargs) -> LLMResponse:
        """Generate a response from Hermes/Ollama."""
        # Try HTTP first
        result = await self._generate_http(prompt, **kwargs)
        if result.success:
            return result

        # Fallback to CLI
        return await self._generate_cli(prompt)

    async def _generate_http(self, prompt: str, **kwargs) -> LLMResponse:
        """Try generating via HTTP API."""
        start = time.time()
        endpoints = ["/v1/generate", "/generate", "/api/generate"]

        for endpoint in endpoints:
            try:
                client = await self._get_client()
                payload = {
                    "model": self.model,
                    "prompt": prompt,
                    "stream": False,
                }
                if kwargs.get("temperature"):
                    payload["temperature"] = kwargs["temperature"]
                if kwargs.get("max_tokens"):
                    payload["max_tokens"] = kwargs["max_tokens"]

                response = await client.post(
                    f"{self.url}{endpoint}",
                    json=payload,
                )

                latency = time.time() - start

                if response.status_code == 200:
                    data = response.json()
                    output = (
                        data.get("response")
                        or data.get("text")
                        or data.get("output", "")
                    )
                    self._record_call(latency, True)
                    logger.success("Hermes HTTP response in %.1fs via %s", latency, endpoint)
                    return LLMResponse(
                        success=True,
                        output=output.strip() if isinstance(output, str) else str(output),
                        model=self.model,
                        source="hermes_http",
                        latency_ms=latency * 1000,
                        raw=data,
                    )
            except Exception as exc:
                logger.debug("Hermes HTTP attempt failed (%s): %s", endpoint, exc)
                continue

        latency = time.time() - start
        self._record_call(latency, False)
        return LLMResponse(
            success=False,
            error="All HTTP endpoints failed",
            model=self.model,
            source="hermes_http",
        )

    async def _generate_cli(self, prompt: str) -> LLMResponse:
        """Fallback: generate via `ollama run` CLI."""
        start = time.time()
        try:
            process = await asyncio.create_subprocess_exec(
                "ollama", "run", self.model,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )

            stdout, stderr = await asyncio.wait_for(
                process.communicate(input=prompt.encode("utf-8")),
                timeout=self.timeout,
            )

            latency = time.time() - start
            output = stdout.decode("utf-8", errors="replace").strip()

            if process.returncode == 0 and output:
                self._record_call(latency, True)
                logger.success("Hermes CLI response in %.1fs", latency)
                return LLMResponse(
                    success=True,
                    output=output,
                    model=self.model,
                    source="hermes_cli",
                    latency_ms=latency * 1000,
                )
            else:
                error_msg = stderr.decode("utf-8", errors="replace").strip()
                self._record_call(latency, False)
                return LLMResponse(
                    success=False,
                    error=error_msg or "CLI returned empty output",
                    model=self.model,
                    source="hermes_cli",
                )

        except asyncio.TimeoutError:
            latency = time.time() - start
            self._record_call(latency, False)
            return LLMResponse(
                success=False,
                error=f"CLI timeout after {latency:.1f}s",
                model=self.model,
                source="hermes_cli",
            )
        except FileNotFoundError:
            self._record_call(0, False)
            return LLMResponse(
                success=False,
                error="ollama CLI not found",
                model=self.model,
                source="hermes_cli",
            )
        except Exception as exc:
            latency = time.time() - start
            self._record_call(latency, False)
            return LLMResponse(
                success=False,
                error=str(exc),
                model=self.model,
                source="hermes_cli",
            )

    async def health_check(self) -> bool:
        """Check if Hermes/Ollama is reachable."""
        for endpoint in self.HEALTH_ENDPOINTS:
            try:
                client = await self._get_client()
                response = await client.get(f"{self.url}{endpoint}")
                if response.status_code == 200:
                    return True
            except Exception:
                continue
        return False

    async def close(self) -> None:
        if self._client and not self._client.is_closed:
            await self._client.aclose()
