"""
Self-Heal Module — Process monitor and auto-restart for critical subsystems.
Watches registered modules and restarts them if they stop or become unhealthy.
"""

import asyncio
import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from logging_system import get_logger

logger = get_logger("SelfHeal")

_BASE_DIR = Path(__file__).resolve().parent


@dataclass
class ManagedModule:
    name: str
    health_check: Callable[[], bool]
    restart_handler: Optional[Callable[[], Any]] = None
    last_healthy: float = 0.0
    restart_count: int = 0
    last_restart: float = 0.0
    enabled: bool = True


class SelfHealer:
    """Monitors managed modules and restarts them on failure."""

    _instance: Optional["SelfHealer"] = None

    def __new__(cls) -> "SelfHealer":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self._initialized = True
        self._modules: Dict[str, ManagedModule] = {}
        self._running = False
        self._task: Optional[asyncio.Task] = None
        self._config = self._load_config()
        self._check_interval = self._config.get("check_interval", 30)
        self._cooldown = self._config.get("cooldown_seconds", 60)
        self._max_restarts = 5

    def _load_config(self) -> dict:
        try:
            path = _BASE_DIR / "config.json"
            if path.exists():
                return json.loads(path.read_text(encoding="utf-8")).get("self_heal", {})
        except Exception:
            pass
        return {}

    def register(self, name: str,
                 health_check: Callable[[], bool],
                 restart_handler: Optional[Callable[[], Any]] = None) -> None:
        if name in self._modules:
            logger.warning("SelfHeal: module '%s' already registered, overwriting", name)
        self._modules[name] = ManagedModule(
            name=name,
            health_check=health_check,
            restart_handler=restart_handler,
        )
        logger.info("SelfHeal: registered module '%s'", name)

    def unregister(self, name: str) -> None:
        self._modules.pop(name, None)
        logger.info("SelfHeal: unregistered module '%s'", name)

    async def start(self) -> None:
        if not self._config.get("enabled", True):
            logger.info("SelfHeal: disabled by configuration")
            return
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._monitor_loop())
        logger.info("SelfHeal: monitoring started (interval=%ds)", self._check_interval)

    async def stop(self) -> None:
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("SelfHeal: monitoring stopped")

    async def _monitor_loop(self) -> None:
        while self._running:
            try:
                await self._check_all()
            except Exception as e:
                logger.error("SelfHeal: monitor error: %s", e)
            await asyncio.sleep(self._check_interval)

    async def _check_all(self) -> None:
        now = time.time()
        for name, mod in list(self._modules.items()):
            if not mod.enabled:
                continue

            try:
                healthy = mod.health_check()
            except Exception as e:
                logger.warning("SelfHeal: health check for '%s' raised: %s", name, e)
                healthy = False

            if healthy:
                mod.last_healthy = now
                continue

            if (now - mod.last_restart) < self._cooldown:
                logger.debug("SelfHeal: '%s' unhealthy but in cooldown (%.0fs left)",
                             name, self._cooldown - (now - mod.last_restart))
                continue

            if mod.restart_count >= self._max_restarts:
                logger.error("SelfHeal: '%s' exceeds max restarts (%d) — manual intervention required",
                             name, self._max_restarts)
                mod.enabled = False
                continue

            logger.warning("SelfHeal: module '%s' is unhealthy — attempting restart (%d/%d)",
                           name, mod.restart_count + 1, self._max_restarts)

            try:
                if mod.restart_handler:
                    if asyncio.iscoroutinefunction(mod.restart_handler):
                        result = await mod.restart_handler()
                    else:
                        result = mod.restart_handler()
                    if result:
                        mod.restart_count += 1
                        mod.last_restart = now
                        logger.info("SelfHeal: module '%s' restarted successfully", name)
                    else:
                        logger.error("SelfHeal: module '%s' restart handler returned failure", name)
                else:
                    logger.warning("SelfHeal: module '%s' has no restart handler defined", name)
            except Exception as e:
                logger.error("SelfHeal: module '%s' restart failed: %s", name, e)

    def status(self) -> Dict[str, Any]:
        return {
            "running": self._running,
            "check_interval": self._check_interval,
            "modules": {
                name: {
                    "healthy": mod.health_check() if mod.enabled else False,
                    "restart_count": mod.restart_count,
                    "last_restart": mod.last_restart,
                    "enabled": mod.enabled,
                }
                for name, mod in self._modules.items()
            },
        }

    @property
    def healthy_module_count(self) -> int:
        count = 0
        for mod in self._modules.values():
            if mod.enabled:
                try:
                    if mod.health_check():
                        count += 1
                except Exception:
                    pass
        return count

    @property
    def total_modules(self) -> int:
        return sum(1 for m in self._modules.values() if m.enabled)
