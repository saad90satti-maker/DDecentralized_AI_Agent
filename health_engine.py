"""
Autonomous Self-Healing Engine v2 — transitions from passive monitoring
to active self-healing via the Tool Registry. When DHT/swarm degradation
is detected, the engine calls registered tools to re-init the node or
fall back to a relay, rather than just logging the failure.
"""

import os
import sys
import json
import time
import logging
import asyncio
import subprocess
from pathlib import Path
from typing import Optional, Callable
from dataclasses import dataclass, field

logger = logging.getLogger("health_engine")

HEALTH_LOG_PATH = Path("agent_logs/health_engine.json")


@dataclass
class HealthStatus:
    component: str
    healthy: bool
    detail: str = ""
    timestamp: float = 0.0


@dataclass
class RepairAction:
    name: str
    description: str
    repair_fn: Callable[[], bool]
    max_attempts: int = 3
    cooldown: float = 60.0
    tool_name: str = ""  # Optional tool registry tool to call instead


class HealthEngine:
    """
    v2: Autonomous health monitor that uses the Tool Registry for repairs.
    When DHT/swarm fails, it calls registry tools (dht_initialize, swarm_relay)
    instead of running inline pip installs.
    """

    def __init__(self, tool_registry=None, check_interval: float = 30.0):
        self.check_interval = check_interval
        self._history: list[dict] = []
        self._running = False
        self._last_repair: dict[str, float] = {}
        self._repair_counts: dict[str, int] = {}
        self._tool_registry = None
        self._repairs: dict[str, RepairAction] = {}
        if tool_registry is not None:
            self.set_tool_registry(tool_registry)

    def set_tool_registry(self, registry):
        self._tool_registry = registry
        self._build_repairs_from_registry()

    def _build_repairs_from_registry(self):
        """Map health components to tool registry tools dynamically."""
        if not self._tool_registry:
            return
        tool_map = {
            "dht": {
                "tool_name": "dht_initialize",
                "description": "Re-initialize Kademlia DHT node",
                "max_attempts": 3,
                "cooldown": 120.0,
            },
            "swarm_mesh": {
                "tool_name": "swarm_relay",
                "description": "Fall back to relay-based swarm peering",
                "max_attempts": 2,
                "cooldown": 300.0,
            },
            "browser_agent": {
                "tool_name": "install_package",
                "description": "Install Playwright and browser binaries",
                "max_attempts": 2,
                "cooldown": 600.0,
            },
            "api_gateway": {
                "tool_name": "install_package",
                "description": "Ensure API gateway dependencies",
                "max_attempts": 1,
                "cooldown": 60.0,
            },
            "tunnel": {
                "tool_name": "tunnel_activate",
                "description": "Activate Cloudflare Tunnel for external peering",
                "max_attempts": 2,
                "cooldown": 300.0,
            },
        }

        for component, cfg in tool_map.items():
            tool = self._tool_registry.get(cfg["tool_name"])
            if tool:
                self._repairs[component] = RepairAction(
                    name=cfg["tool_name"],
                    description=cfg["description"],
                    repair_fn=lambda: False,  # placeholder — actual call goes through tool registry
                    max_attempts=cfg["max_attempts"],
                    cooldown=cfg["cooldown"],
                    tool_name=cfg["tool_name"],
                )
                logger.debug("Health: mapped %s → tool '%s'", component, cfg["tool_name"])
            else:
                # Fall back to default repairs
                default = self._get_default_repair(component)
                if default:
                    self._repairs[component] = default

    def _get_default_repair(self, component: str) -> Optional[RepairAction]:
        defaults = {
            "dht": RepairAction(
                name="kademlia", description="Install kademlia DHT library (fallback)",
                repair_fn=self._pip_install_async("kademlia"),
                max_attempts=3, cooldown=300.0,
            ),
            "browser_agent": RepairAction(
                name="playwright", description="Install playwright (fallback)",
                repair_fn=self._pip_install_async("playwright"),
                max_attempts=2, cooldown=600.0,
            ),
        }
        return defaults.get(component)

    @staticmethod
    async def _pip_install_async(package: str):
        logger.info("pip install %s...", package)
        try:
            proc = await asyncio.create_subprocess_exec(
                sys.executable, "-m", "pip", "install", package,
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
            )
            await asyncio.wait_for(proc.wait(), timeout=60)
            return proc.returncode == 0
        except Exception as e:
            logger.error("pip install %s failed: %s", package, e)
            return False

    # ------------------------------------------------------------------
    # Check methods
    # ------------------------------------------------------------------

    async def check_dht(self) -> HealthStatus:
        try:
            from kademlia.network import Server
            return HealthStatus(component="dht", healthy=True, detail="kademlia library available")
        except ImportError:
            return HealthStatus(component="dht", healthy=False, detail="kademlia library not installed")

    async def check_swarm_mesh(self) -> HealthStatus:
        from cloud_native import CloudNativeConfig
        config = CloudNativeConfig()
        import httpx
        try:
            async with httpx.AsyncClient(timeout=5) as client:
                resp = await client.get(f"{config.manager_url}/api/status")
                if resp.status_code == 200:
                    data = resp.json()
                    dht_ready = data.get("dht", False) if isinstance(data, dict) else False
                    return HealthStatus(component="swarm_mesh", healthy=dht_ready,
                                        detail=f"DHT ready: {dht_ready}")
                return HealthStatus(component="swarm_mesh", healthy=False,
                                    detail=f"API returned {resp.status_code}")
        except Exception as e:
            return HealthStatus(component="swarm_mesh", healthy=False,
                                detail=f"API unreachable: {e}")

    async def check_api_gateway(self) -> HealthStatus:
        from api_gateway import UnifiedAPIGateway
        gateway = UnifiedAPIGateway()
        providers = await gateway.initialize()
        await gateway.close()
        if providers:
            return HealthStatus(component="api_gateway", healthy=True,
                                detail=f"Providers online: {', '.join(providers)}")
        return HealthStatus(component="api_gateway", healthy=False,
                            detail="No remote providers configured")

    async def check_tunnel(self) -> HealthStatus:
        import httpx
        from cloud_native import CloudNativeConfig
        config = CloudNativeConfig()
        if not config.tunnel_enabled:
            return HealthStatus(component="tunnel", healthy=True, detail="tunnel disabled")
        try:
            async with httpx.AsyncClient(timeout=5) as client:
                resp = await client.get(f"{config.manager_url}/api/status")
                if resp.status_code == 200:
                    return HealthStatus(component="tunnel", healthy=True,
                                        detail=f"API reachable via {config.manager_url}")
                return HealthStatus(component="tunnel", healthy=False,
                                    detail=f"API returned {resp.status_code}")
        except Exception as e:
            return HealthStatus(component="tunnel", healthy=False,
                                detail=f"API unreachable: {e}")

    async def check_browser_agent(self) -> HealthStatus:
        try:
            from playwright.async_api import async_playwright
            return HealthStatus(component="browser_agent", healthy=True,
                                detail="playwright library available")
        except ImportError:
            return HealthStatus(component="browser_agent", healthy=False,
                                detail="playwright not installed")

    # ------------------------------------------------------------------
    # Full check cycle
    # ------------------------------------------------------------------

    async def run_checks(self) -> list[HealthStatus]:
        results = await asyncio.gather(
            self.check_dht(),
            self.check_swarm_mesh(),
            self.check_api_gateway(),
            self.check_tunnel(),
            self.check_browser_agent(),
        )
        for r in results:
            r.timestamp = time.time()
            self._history.append({
                "component": r.component, "healthy": r.healthy,
                "detail": r.detail, "timestamp": r.timestamp,
            })
        self._trim_history()
        return results

    def _trim_history(self, max_entries: int = 1000):
        if len(self._history) > max_entries:
            self._history = self._history[-max_entries:]

    # ------------------------------------------------------------------
    # Autonomous repair — calls Tool Registry instead of inline scripts
    # ------------------------------------------------------------------

    async def auto_repair(self, status: HealthStatus) -> bool:
        if status.healthy:
            return True

        repair = self._repairs.get(status.component)
        if not repair:
            logger.info("No repair defined for %s", status.component)
            return False

        # Cooldown check
        last = self._last_repair.get(status.component, 0.0)
        if time.time() - last < repair.cooldown:
            remaining = repair.cooldown - (time.time() - last)
            logger.debug("Repair %s in cooldown (%.0fs)", status.component, remaining)
            return False

        attempts = self._repair_counts.get(status.component, 0)
        if attempts >= repair.max_attempts:
            logger.warning("Repair %s exhausted after %d attempts", status.component, attempts)
            return False

        logger.info("Auto-repair %s (attempt %d/%d): %s",
                    status.component, attempts + 1, repair.max_attempts, repair.description)

        # Execute via tool registry if available
        success = False
        if self._tool_registry and repair.tool_name:
            logger.info("Calling tool '%s' for component '%s'", repair.tool_name, status.component)
            result = await self._tool_registry.execute(
                repair.tool_name,
                {"component": status.component, "detail": status.detail},
                timeout=120,
            )
            success = result.get("status") == "ok"
            if not success:
                logger.warning("Tool '%s' returned: %s", repair.tool_name, result)
        else:
            # Fallback to inline repair function
            try:
                if asyncio.iscoroutinefunction(repair.repair_fn):
                    success = await repair.repair_fn()
                else:
                    success = await asyncio.get_event_loop().run_in_executor(None, repair.repair_fn)
            except Exception as e:
                logger.error("Repair %s exception: %s", status.component, e)

        self._last_repair[status.component] = time.time()
        self._repair_counts[status.component] = attempts + 1

        if success:
            logger.info("Repair %s SUCCEEDED via %s", status.component,
                        repair.tool_name or "inline")
        else:
            logger.error("Repair %s FAILED", status.component)

        self._history.append({
            "event": "repair", "component": status.component,
            "success": success, "attempt": attempts + 1,
            "tool": repair.tool_name, "timestamp": time.time(),
        })
        return success

    # ------------------------------------------------------------------
    # Persistent loop
    # ------------------------------------------------------------------

    async def run_forever(self):
        self._running = True
        logger.info("Health Engine v2 started (interval=%ds, tool_registry=%s)",
                    self.check_interval, self._tool_registry is not None)

        while self._running:
            try:
                results = await self.run_checks()
                for r in results:
                    logger.info("Health: %-20s %s  %s",
                                r.component, "[OK]" if r.healthy else "[DEGRADED]", r.detail)
                    if not r.healthy:
                        await self.auto_repair(r)
            except Exception as e:
                logger.error("Health check cycle error: %s", e)

            self._persist_state()
            await asyncio.sleep(self.check_interval)

    def stop(self):
        self._running = False

    def _persist_state(self):
        try:
            HEALTH_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
            state = {
                "last_checks": self._history[-50:] if self._history else [],
                "repair_counts": dict(self._repair_counts),
                "status": "degraded" if any(
                    not h["healthy"] for h in self._history[-5:]
                ) else "healthy",
            }
            HEALTH_LOG_PATH.write_text(json.dumps(state, indent=2), encoding="utf-8")
        except Exception as e:
            logger.debug("Failed to persist: %s", e)

    def get_report(self) -> dict:
        return {
            "running": self._running,
            "repair_counts": dict(self._repair_counts),
            "recent_checks": self._history[-20:] if self._history else [],
        }
