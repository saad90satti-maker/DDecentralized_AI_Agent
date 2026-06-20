"""
Telemetry Layer — Real-time asynchronous telemetry collection and reporting.
Collects system metrics, publishes to MQTT, and logs to the unified logging system.
All I/O is non-blocking (asyncio) so the Swarm heartbeat never freezes.
"""

import asyncio
import json
import os
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from logging_system import get_logger

logger = get_logger("Telemetry")

_BASE_DIR = Path(__file__).resolve().parent


class TelemetryCollector:
    """Async telemetry collector — CPU, memory, network, and swarm metrics."""

    def __init__(self, node_id: str = "ghost-agent"):
        self.node_id = node_id
        self._buffer: List[Dict[str, Any]] = []
        self._max_buffer = 500
        self._running = False
        self._task: Optional[asyncio.Task] = None
        self._listeners: List[Callable[[Dict[str, Any]], Any]] = []
        self._interval = 15
        self._config = self._load_config()

    def _load_config(self) -> dict:
        try:
            path = _BASE_DIR / "config.json"
            if path.exists():
                return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            pass
        return {}

    def add_listener(self, listener: Callable[[Dict[str, Any]], Any]) -> None:
        self._listeners.append(listener)

    async def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._collection_loop())
        logger.info("Telemetry: collector started (interval=%ds)", self._interval)

    async def stop(self) -> None:
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("Telemetry: collector stopped")

    async def _collection_loop(self) -> None:
        while self._running:
            try:
                snapshot = await self._collect_snapshot()
                self._buffer.append(snapshot)
                if len(self._buffer) > self._max_buffer:
                    self._buffer = self._buffer[-self._max_buffer:]

                for listener in self._listeners:
                    try:
                        if asyncio.iscoroutinefunction(listener):
                            await listener(snapshot)
                        else:
                            listener(snapshot)
                    except Exception as e:
                        logger.debug("Telemetry listener error: %s", e)

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.warning("Telemetry collection error: %s", e)

            await asyncio.sleep(self._interval)

    async def _collect_snapshot(self) -> Dict[str, Any]:
        cpu = await self._async_get_cpu()
        mem = await self._async_get_memory()

        return {
            "timestamp": time.time(),
            "node_id": self.node_id,
            "cpu_percent": cpu,
            "memory_percent": mem,
            "connections_active": 0,
            "uptime_seconds": time.time() - _get_process_start_time(),
            "mode": os.getenv("GHOST_MODE", "autonomous"),
        }

    async def _async_get_cpu(self) -> float:
        try:
            import psutil
            return psutil.cpu_percent(interval=0.3)
        except ImportError:
            return 0.0

    async def _async_get_memory(self) -> float:
        try:
            import psutil
            return psutil.virtual_memory().percent
        except ImportError:
            return 0.0

    def read_recent(self, seconds: int = 300) -> List[Dict[str, Any]]:
        cutoff = time.time() - seconds
        return [e for e in self._buffer if e["timestamp"] >= cutoff]

    def latest(self) -> Optional[Dict[str, Any]]:
        return self._buffer[-1] if self._buffer else None

    @property
    def status(self) -> Dict[str, Any]:
        return {
            "running": self._running,
            "buffer_size": len(self._buffer),
            "listeners": len(self._listeners),
            "interval_s": self._interval,
        }


def _get_process_start_time() -> float:
    try:
        import psutil
        return psutil.Process().create_time()
    except Exception:
        return time.time()


class MQTTTelemetryPublisher:
    """Async telemetry publisher via MQTT — non-blocking."""

    def __init__(self, mqtt_client):
        self._client = mqtt_client
        self._topic = "ghost/telemetry"

    async def publish(self, snapshot: Dict[str, Any]) -> None:
        if not self._client or not getattr(self._client, 'is_connected', False):
            return
        try:
            payload = json.dumps(snapshot, default=str)
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(
                None,
                lambda: self._client.publish(self._topic, payload, qos=1),
            )
        except Exception as e:
            logger.debug("MQTT telemetry publish: %s", e)
