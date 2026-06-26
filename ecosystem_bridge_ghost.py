"""
Ecosystem Bridge — Ghost Production Components
================================================
Wraps the existing ghost_*.py production agents as ecosystem agents.
Each bridge agent extends EcosystemAgent and delegates to the underlying
ghost implementation, preserving all original functionality while adding
EIL communication, heartbeat, and ecosystem awareness.

Bridged Agents:
  - BridgedExecutorAgent  → ghost_executor.GhostExecutionAuthority
  - BridgedSwarmAgent     → ghost_swarm.GhostSwarmNode
  - BridgedCoreAgent      → ghost_core.GhostCore
  - BridgedSchedulerAgent → ghost_scheduler.GhostScheduler
"""

import asyncio
import json
import logging
import time
import uuid
from typing import Any, Dict, List, Optional

logger = logging.getLogger("ecosystem.bridge.ghost")

from ecosystem_agent import EcosystemAgent
from ecosystem_kernel import EcosystemKernel
from ecosystem_shared_memory import EcosystemMemory


class BridgedExecutorAgent(EcosystemAgent):
    """Bridges ghost_executor.GhostExecutionAuthority into the ecosystem."""

    agent_type = "ghost_executor"

    def __init__(self, kernel, memory=None, agent_id=None):
        super().__init__(kernel, memory, agent_id)
        self._ghost = None
        self._ghost_running = False

    def _declare_capabilities(self):
        return {
            "tasks": [
                "execute", "research", "scrape", "llm", "hf_inference",
                "run_cycle", "diagnose", "self_patch", "propagate",
            ],
            "description": "Ghost Execution Authority — autonomous evolve loop with LLM, Tor, CDP, scaper",
            "version": "1.0.0",
        }

    async def execute_task(self, task: str, params: Dict[str, Any]) -> Dict[str, Any]:
        ghost = self._get_ghost()
        if ghost is None:
            return {"status": "error", "message": "GhostExecutionAuthority not available"}

        task_lower = task.lower()
        if "cycle" in task_lower or "evolve" in task_lower:
            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(
                None, lambda: ghost.run_cycle(
                    research_query=params.get("research_query"),
                    llm_prompt=params.get("llm_prompt"),
                    scrape_url=params.get("scrape_url"),
                )
            )
            return result

        if "research" in task_lower:
            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(
                None, lambda: ghost.execute_research(params.get("query", task))
            )
            return result

        if "scrape" in task_lower:
            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(
                None, lambda: ghost.execute_scrape(
                    params.get("url", task),
                    params.get("extract"),
                )
            )
            return result

        if "llm" in task_lower:
            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(
                None, lambda: ghost.execute_llm_task(params.get("prompt", task))
            )
            return result

        if "hf" in task_lower or "inference" in task_lower:
            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(
                None, lambda: ghost.execute_hf_task(params.get("prompt", task))
            )
            return result

        if "diagnose" in task_lower:
            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(None, ghost.run_diagnostic)
            return {"diagnostic": result}

        if "patch" in task_lower or "self_patch" in task_lower:
            network = ghost.network.check()
            loop = asyncio.get_event_loop()
            patches = await loop.run_in_executor(None, lambda: ghost.self_patch(network))
            return {"patches": patches, "count": len(patches)}

        if "propagate" in task_lower:
            loop = asyncio.get_event_loop()
            peers = await loop.run_in_executor(
                None, lambda: ghost.trigger_propagation(params.get("timeout", 10.0))
            )
            return {"peers_found": peers, "count": len(peers)}

        return {"status": "unknown_task", "task": task}

    def _get_ghost(self):
        if self._ghost is None:
            try:
                from ghost_executor import GhostExecutionAuthority
                self._ghost = GhostExecutionAuthority()
                logger.info("BridgedExecutorAgent: GhostExecutionAuthority loaded")
            except Exception as e:
                logger.warning("BridgedExecutorAgent: failed to load GhostExecutionAuthority: %s", e)
        return self._ghost

    async def start(self):
        await super().start()
        await self.send_to("kernel", "bridge_ready", {
            "bridged_component": "ghost_executor",
            "agent_id": self.agent_id,
        })

    async def stop(self):
        if self._ghost:
            try:
                self._ghost.stop()
            except Exception:
                pass
        await super().stop()


class BridgedSwarmAgent(EcosystemAgent):
    """Bridges ghost_swarm.GhostSwarmNode into the ecosystem."""

    agent_type = "ghost_swarm"

    def __init__(self, kernel, memory=None, agent_id=None):
        super().__init__(kernel, memory, agent_id)
        self._swarm = None

    def _declare_capabilities(self):
        return {
            "tasks": [
                "swarm_peers", "swarm_send", "swarm_broadcast",
                "swarm_discover", "swarm_status", "swarm_bootstrap",
            ],
            "description": "Ghost Swarm Node — P2P mesh networking with DHT, UDP discovery, TCP mesh",
            "version": "1.0.0",
        }

    async def execute_task(self, task: str, params: Dict[str, Any]) -> Dict[str, Any]:
        swarm = self._get_swarm()
        if swarm is None:
            return {"status": "error", "message": "GhostSwarmNode not available"}

        task_lower = task.lower()
        if "peers" in task_lower:
            return {
                "peers": {pid: {"host": p.host, "port": p.port, "last_seen": p.last_seen}
                          for pid, p in swarm.peers.items()},
                "count": len(swarm.peers),
            }

        if "status" in task_lower:
            return {
                "node_id": swarm.node_id,
                "port": swarm.port,
                "running": swarm._running,
                "peers": len(swarm.peers),
                "dht": swarm.dht is not None,
            }

        if "send" in task_lower:
            target = params.get("target", "")
            payload = params.get("payload", {})
            try:
                from ghost_swarm import SwarmMessage
                msg = SwarmMessage(src=swarm.node_id, dst=target,
                                   type=params.get("type", "ecosystem"),
                                   payload=payload)
                await swarm.send_message(msg)
                return {"sent": True, "target": target}
            except Exception as e:
                return {"sent": False, "error": str(e)}

        if "broadcast" in task_lower:
            try:
                from ghost_swarm import SwarmMessage
                msg = SwarmMessage(src=swarm.node_id, dst="*",
                                   type=params.get("type", "ecosystem"),
                                   payload=params.get("payload", {}))
                await swarm.broadcast(msg)
                return {"broadcast": True}
            except Exception as e:
                return {"broadcast": False, "error": str(e)}

        if "bootstrap" in task_lower:
            try:
                await swarm.bootstrap_sequence()
                return {"bootstrapped": True, "peers": len(swarm.peers)}
            except Exception as e:
                return {"bootstrapped": False, "error": str(e)}

        return {"status": "unknown_task", "task": task}

    def _get_swarm(self):
        if self._swarm is None:
            try:
                from ghost_swarm import GhostSwarmNode
                self._swarm = GhostSwarmNode(
                    node_id=f"eco-{uuid.uuid4().hex[:6]}",
                    port=9876,
                )
                logger.info("BridgedSwarmAgent: GhostSwarmNode loaded")
            except Exception as e:
                logger.warning("BridgedSwarmAgent: failed to load GhostSwarmNode: %s", e)
        return self._swarm

    async def start(self):
        await super().start()
        swarm = self._get_swarm()
        if swarm:
            try:
                await swarm.start()
                logger.info("BridgedSwarmAgent: swarm started on port %d", swarm.port)
            except Exception as e:
                logger.warning("BridgedSwarmAgent: swarm start failed: %s", e)

    async def stop(self):
        if self._swarm:
            try:
                await self._swarm.stop()
            except Exception:
                pass
        await super().stop()


class BridgedCoreAgent(EcosystemAgent):
    """Bridges ghost_core.GhostCore into the ecosystem."""

    agent_type = "ghost_core"

    def __init__(self, kernel, memory=None, agent_id=None):
        super().__init__(kernel, memory, agent_id)
        self._core = None

    def _declare_capabilities(self):
        return {
            "tasks": [
                "dsp_cycle", "introspect", "analyze", "reflect",
            ],
            "description": "Ghost Core — DSP intelligence engine with adaptive FFT, meta-cognition, swarm interface",
            "version": "1.0.0",
        }

    async def execute_task(self, task: str, params: Dict[str, Any]) -> Dict[str, Any]:
        core = self._get_core()
        if core is None:
            return {"status": "error", "message": "GhostCore not available"}

        task_lower = task.lower()
        if "dsp" in task_lower or "cycle" in task_lower:
            result = await core.run_dsp_cycle()
            return result

        if "introspect" in task_lower:
            loop = asyncio.get_event_loop()
            lib_map = await loop.run_in_executor(None, core.introspect)
            return {
                "modules_scanned": len(lib_map),
                "capability_summary": core.capability_summary,
            }

        if "analyze" in task_lower:
            loop = asyncio.get_event_loop()
            lib_map = await loop.run_in_executor(None, core.introspect)
            return {
                "library_count": len(lib_map),
                "capabilities": core.capability_summary,
                "cycle_count": core.cycle_count,
            }

        return {"status": "unknown_task", "task": task}

    def _get_core(self):
        if self._core is None:
            try:
                from ghost_core import GhostCore
                interval = float(getattr(self, '_interval', 3.0))
                self._core = GhostCore(interval=interval)
                logger.info("BridgedCoreAgent: GhostCore loaded")
            except Exception as e:
                logger.warning("BridgedCoreAgent: failed to load GhostCore: %s", e)
        return self._core

    async def stop(self):
        if self._core:
            try:
                await self._core.close()
            except Exception:
                pass
        await super().stop()


class BridgedSchedulerAgent(EcosystemAgent):
    """Bridges ghost_scheduler.GhostScheduler into the ecosystem."""

    agent_type = "ghost_scheduler"

    def __init__(self, kernel, memory=None, agent_id=None):
        super().__init__(kernel, memory, agent_id)
        self._scheduler = None

    def _declare_capabilities(self):
        return {
            "tasks": [
                "schedule", "unschedule", "list_jobs", "run_job",
            ],
            "description": "Ghost Scheduler — cron-like periodic task execution",
            "version": "1.0.0",
        }

    async def execute_task(self, task: str, params: Dict[str, Any]) -> Dict[str, Any]:
        sched = self._get_scheduler()
        if sched is None:
            return {"status": "error", "message": "GhostScheduler not available"}

        task_lower = task.lower()
        if "schedule" in task_lower:
            job_id = sched.schedule(
                name=params.get("name", "ecosystem_job"),
                interval_s=params.get("interval_s", 60),
                payload=params.get("payload", {}),
                max_runs=params.get("max_runs", 0),
            )
            handler = params.get("handler")
            if handler:
                sched.register(params.get("name", "ecosystem_job"), handler)
            return {"job_id": job_id, "scheduled": True}

        if "unschedule" in task_lower or "remove" in task_lower:
            removed = sched.remove_job(params.get("job_id", task))
            return {"removed": removed}

        if "list" in task_lower or "jobs" in task_lower:
            return {"jobs": sched.list_jobs()}

        return {"status": "unknown_task", "task": task}

    def _get_scheduler(self):
        if self._scheduler is None:
            try:
                from ghost_scheduler import GhostScheduler
                self._scheduler = GhostScheduler()
                logger.info("BridgedSchedulerAgent: GhostScheduler loaded")
            except Exception as e:
                logger.warning("BridgedSchedulerAgent: failed to load GhostScheduler: %s", e)
        return self._scheduler

    async def start(self):
        await super().start()
        sched = self._get_scheduler()
        if sched:
            try:
                asyncio.create_task(sched.start())
                logger.info("BridgedSchedulerAgent: scheduler loop started")
            except Exception as e:
                logger.warning("BridgedSchedulerAgent: scheduler start failed: %s", e)

    async def stop(self):
        if self._scheduler:
            try:
                await self._scheduler.stop()
            except Exception:
                pass
        await super().stop()


# Factory for easy registration in launcher
BRIDGED_AGENTS = {
    "ghost_executor": BridgedExecutorAgent,
    "ghost_swarm": BridgedSwarmAgent,
    "ghost_core": BridgedCoreAgent,
    "ghost_scheduler": BridgedSchedulerAgent,
}
