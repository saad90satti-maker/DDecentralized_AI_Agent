"""Kernel Node — central coordinator managing agent lifecycle, state, and simulation ticks."""

import asyncio
import time
import logging
from typing import Dict, Any, Optional, Callable
from daios.kernel.config import DAIOSConfig
from daios.kernel.state_manager import StateManager
from daios.kernel.resource_tracker import ResourceTracker

logger = logging.getLogger("daios.kernel")


class KernelNode:
    def __init__(self, config: Optional[DAIOSConfig] = None):
        self.config = config or DAIOSConfig()
        self.state_mgr = StateManager(self.config.data_dir)
        self.resource_tracker = ResourceTracker()
        self._agent_registry: Dict[str, Any] = {}
        self._message_handlers: Dict[str, Callable] = {}
        self._running = False
        self._tick_task: Optional[asyncio.Task] = None
        self._message_queue: asyncio.Queue = asyncio.Queue()

    async def start(self) -> None:
        logger.info("DAIOS Kernel starting (tick=%.1fs, max_agents=%d)",
                     self.config.simulation_tick_interval, self.config.max_agents)
        self._running = True
        self.state_mgr.state.kernel_status = "running"
        self.state_mgr.state.phase = "operational"
        self._tick_task = asyncio.create_task(self._tick_loop())
        logger.info("Kernel operational — T+0")

    async def stop(self) -> None:
        logger.info("Kernel shutting down...")
        self._running = False
        if self._tick_task:
            self._tick_task.cancel()
            try:
                await self._tick_task
            except asyncio.CancelledError:
                pass
        if self.config.memory_persistence:
            self.state_mgr.save_checkpoint()
            logger.info("Checkpoint saved at tick %d", self.state_mgr.state.tick)
        self.state_mgr.state.kernel_status = "stopped"
        logger.info("Kernel stopped")

    async def register_agent(self, agent_id: str, agent_instance: Any) -> bool:
        if len(self._agent_registry) >= self.config.max_agents:
            logger.warning("Max agents reached (%d)", self.config.max_agents)
            return False
        if agent_id in self._agent_registry:
            logger.warning("Agent %s already registered", agent_id)
            return False
        self._agent_registry[agent_id] = agent_instance
        agent_type = getattr(agent_instance, "agent_type", "unknown")
        self.state_mgr.register_agent(agent_id, agent_type)
        logger.info("Agent registered: %s (%s)", agent_id, agent_type)
        return True

    async def unregister_agent(self, agent_id: str) -> None:
        agent = self._agent_registry.pop(agent_id, None)
        if agent:
            self.state_mgr.unregister_agent(agent_id)
            logger.info("Agent unregistered: %s", agent_id)

    def get_agent(self, agent_id: str) -> Optional[Any]:
        return self._agent_registry.get(agent_id)

    def get_all_agents(self) -> Dict[str, Any]:
        return dict(self._agent_registry)

    async def send_message(self, msg: Dict[str, Any]) -> None:
        self.resource_tracker.record_message()
        self.state_mgr.state.total_messages_sent += 1
        await self._message_queue.put(msg)

    async def process_messages(self) -> None:
        while not self._message_queue.empty():
            msg = await self._message_queue.get()
            target = msg.get("to", "kernel")
            if target == "kernel":
                await self._handle_kernel_message(msg)
            elif target in self._agent_registry:
                agent = self._agent_registry[target]
                try:
                    await agent.handle_message(msg)
                except Exception as e:
                    logger.error("Agent %s message handling error: %s", target, e)
            else:
                logger.warning("Unknown message target: %s", target)

    async def _handle_kernel_message(self, msg: Dict[str, Any]) -> None:
        cmd = msg.get("command", "")
        handler = self._message_handlers.get(cmd)
        if handler:
            await handler(msg)
        elif cmd == "status":
            await self._reply(msg, self.get_status())
        elif cmd == "shutdown":
            await self.stop()
        else:
            logger.debug("Unknown kernel command: %s", cmd)

    async def _reply(self, original: Dict[str, Any], data: Any) -> None:
        reply = {
            "type": "response",
            "from": "kernel",
            "to": original.get("from", "unknown"),
            "in_response_to": original.get("id", ""),
            "data": data,
            "tick": self.state_mgr.state.tick,
        }
        target = reply["to"]
        if target in self._agent_registry:
            await self._agent_registry[target].handle_message(reply)

    def register_handler(self, command: str, handler: Callable) -> None:
        self._message_handlers[command] = handler

    def get_status(self) -> Dict[str, Any]:
        return {
            "kernel": self.state_mgr.state.kernel_status,
            "phase": self.state_mgr.state.phase,
            "tick": self.state_mgr.state.tick,
            "agents": {
                "active": self.state_mgr.agent_count,
                "total_created": self.state_mgr.state.total_agents_created,
                "list": list(self._agent_registry.keys()),
            },
            "resources": self.state_mgr.all_resources(),
            "performance": self.resource_tracker.summary(),
            "uptime_s": round(time.time() - self.state_mgr.state.start_time, 1),
            "total_tasks": self.state_mgr.state.total_tasks_completed,
            "total_discoveries": self.state_mgr.state.total_discoveries,
        }

    async def _tick_loop(self) -> None:
        while self._running:
            self.resource_tracker.tick_start()
            await self._on_tick()
            metrics = self.resource_tracker.tick_end()
            if self.state_mgr.state.tick % 10 == 0:
                logger.debug("Tick %d | agents=%d msgs=%d tick=%.0fms cpu=%.1f%% mem=%.1fMB",
                             self.state_mgr.state.tick,
                             self.state_mgr.agent_count,
                             metrics.messages_per_tick,
                             metrics.tick_duration_ms,
                             metrics.cpu_percent,
                             metrics.memory_mb)
            await asyncio.sleep(self.config.simulation_tick_interval)

    async def _on_tick(self) -> None:
        self.state_mgr.tick()
        await self.process_messages()
        for agent in list(self._agent_registry.values()):
            try:
                await agent.on_tick()
            except Exception as e:
                logger.error("Agent %s tick error: %s", getattr(agent, "agent_id", "?"), e)

        if self.config.enable_growth and self.state_mgr.state.tick % 5 == 0:
            idle_agents = self.state_mgr.idle_agents(self.config.agent_retirement_idle_ticks)
            for aid in idle_agents:
                if self.state_mgr.get_agent(aid):
                    logger.info("Retiring idle agent: %s", aid)
                    await self.unregister_agent(aid)
