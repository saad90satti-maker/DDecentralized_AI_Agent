"""
Ecosystem Kernel v1.0 — The Central Brain

This is the operating core of the Decentralized AI Ecosystem.
It provides:

  1. Agent Registry — every agent registers here
  2. Event Bus — pub/sub message routing between all agents
  3. Task Scheduler — priority-based task queue with routing
  4. Health Monitor — tracks agent liveness and system resources
  5. Tick Engine — drives the ecosystem forward in discrete cycles
  6. Shared Memory Gateway — unified read/write to all memory layers

All agents communicate THROUGH the kernel, not directly.
The kernel is a singleton asyncio application.
"""

import asyncio
import json
import os
import time
import uuid
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Set

from loguru import logger as loguru_logger
import structlog
from cachetools import TTLCache
import diskcache as dc

from ecosystem_language import EILMessage, MSG_TYPES, PRIORITIES

# Structured logging setup
structlog.configure(
    processors=[
        structlog.stdlib.filter_by_level,
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.JSONRenderer(),
    ],
    wrapper_class=structlog.stdlib.BoundLogger,
    context_class=dict,
    logger_factory=structlog.PrintLoggerFactory(),
    cache_logger_on_first_use=True,
)
logger = structlog.get_logger("ecosystem.kernel")

BASE_DIR = Path(__file__).resolve().parent
LOG_DIR = BASE_DIR / "agent_logs"
DATA_DIR = BASE_DIR / "agent_data"
LOG_DIR.mkdir(exist_ok=True)
DATA_DIR.mkdir(exist_ok=True)

ROUTES_FILE = DATA_DIR / "ecosystem_routes.json"
AGENTS_FILE = DATA_DIR / "ecosystem_agents.json"
TASKS_FILE = DATA_DIR / "ecosystem_tasks.json"

# Cache layer
_agent_cache = TTLCache(maxsize=256, ttl=30)
_task_cache = TTLCache(maxsize=512, ttl=60)
_knowledge_cache = TTLCache(maxsize=1024, ttl=120)
_disk_cache = dc.Cache(str(DATA_DIR / "diskcache"))


class AgentRecord:
    def __init__(self, agent_id: str, agent_type: str, capabilities: Dict[str, Any],
                 ref: Any = None):
        self.agent_id = agent_id
        self.agent_type = agent_type
        self.capabilities = capabilities
        self.ref = ref
        self.status = "idle"
        self.last_heartbeat = time.time()
        self.tasks_completed = 0
        self.tasks_failed = 0
        self.messages_sent = 0
        self.messages_received = 0
        self.registered_at = time.time()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "agent_id": self.agent_id,
            "agent_type": self.agent_type,
            "capabilities": self.capabilities,
            "status": self.status,
            "last_heartbeat": self.last_heartbeat,
            "tasks_completed": self.tasks_completed,
            "tasks_failed": self.tasks_failed,
            "messages_sent": self.messages_sent,
            "messages_received": self.messages_received,
            "registered_at": self.registered_at,
            "alive": (time.time() - self.last_heartbeat) < 30,
        }


class TaskRecord:
    def __init__(self, msg: EILMessage):
        self.id = msg.id or f"task-{uuid.uuid4().hex[:12]}"
        self.msg = msg
        self.created_at = time.time()
        self.assigned_to: Optional[str] = None
        self.started_at: Optional[float] = None
        self.completed_at: Optional[float] = None
        self.retries = 0
        self.max_retries = 3
        self.status = "pending"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "task": self.msg.task,
            "src": self.msg.src,
            "dst": self.msg.dst,
            "priority": self.msg.priority,
            "assigned_to": self.assigned_to,
            "status": self.status,
            "retries": self.retries,
            "created_at": self.created_at,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
        }


class EventBus:
    """Lightweight pub/sub event bus for in-process agent communication."""

    def __init__(self):
        self._subscribers: Dict[str, List[Callable]] = defaultdict(list)
        self._history: List[Dict[str, Any]] = []
        self._max_history = 500

    def subscribe(self, event_type: str, callback: Callable) -> None:
        self._subscribers[event_type].append(callback)

    def unsubscribe(self, event_type: str, callback: Callable) -> None:
        if callback in self._subscribers.get(event_type, []):
            self._subscribers[event_type].remove(callback)

    async def publish(self, event_type: str, data: Any) -> None:
        entry = {"type": event_type, "data": data, "timestamp": time.time()}
        self._history.append(entry)
        if len(self._history) > self._max_history:
            self._history = self._history[-self._max_history:]
        for cb in self._subscribers.get(event_type, []):
            try:
                await cb(data)
            except Exception as e:
                loguru_logger.error("EventBus subscriber error: {}", e)

    def get_history(self, last_n: int = 50) -> List[Dict[str, Any]]:
        return self._history[-last_n:]


class EcosystemKernel:
    """The central brain. Singleton. Coordinates everything."""

    def __init__(self):
        self.node_id = f"kernel-{uuid.uuid4().hex[:8]}"
        self.tick = 0
        self.start_time = time.time()
        self.running = False

        self.event_bus = EventBus()
        self._agents: Dict[str, AgentRecord] = {}
        self._tasks: Dict[str, TaskRecord] = {}
        self._routing_table: Dict[str, str] = {}
        self._handlers: Dict[str, Callable] = {}
        self._message_queue: asyncio.Queue = asyncio.Queue()
        self._task_queue: asyncio.PriorityQueue = asyncio.PriorityQueue()

        self._tick_task: Optional[asyncio.Task] = None
        self._worker_task: Optional[asyncio.Task] = None

        self._health_history: List[Dict[str, Any]] = []
        self._ecosystem_stats: Dict[str, Any] = {
            "total_messages": 0,
            "total_tasks": 0,
            "total_errors": 0,
            "total_learns": 0,
        }

        self._load_state()

    # ─── Agent Registry ──────────────────────────────────────────────

    def register_agent(self, agent_id: str, agent_type: str,
                       capabilities: Optional[Dict[str, Any]] = None,
                       ref: Any = None) -> bool:
        if agent_id in self._agents:
            self._agents[agent_id].last_heartbeat = time.time()
            self._agents[agent_id].status = "idle"
            return True
        self._agents[agent_id] = AgentRecord(
            agent_id, agent_type, capabilities or {}, ref
        )
        self._routing_table[agent_type] = agent_id
        loguru_logger.info("Agent registered: {} (type={})", agent_id, agent_type)
        self._save_agents()
        return True

    def unregister_agent(self, agent_id: str) -> None:
        self._agents.pop(agent_id, None)
        self._routing_table = {
            k: v for k, v in self._routing_table.items() if v != agent_id
        }
        loguru_logger.info("Agent unregistered: {}", agent_id)
        self._save_agents()

    def get_agent(self, agent_id: str) -> Optional[AgentRecord]:
        return self._agents.get(agent_id)

    def get_agents_by_type(self, agent_type: str) -> List[AgentRecord]:
        return [a for a in self._agents.values() if a.agent_type == agent_type]

    def get_agents(self) -> Dict[str, AgentRecord]:
        return dict(self._agents)

    def find_agent_for_task(self, task: str) -> Optional[str]:
        """Route a task to the best agent based on capability matching."""
        best = None
        best_score = -1
        for aid, rec in self._agents.items():
            if rec.status == "idle" and rec.alive:
                caps = rec.capabilities.get("tasks", [])
                score = 0
                for c in caps:
                    if c.lower() in task.lower():
                        score += 10
                if rec.agent_type.lower() in task.lower():
                    score += 5
                if score > best_score:
                    best_score = score
                    best = aid
        if best is None:
            for aid, rec in self._agents.items():
                if rec.alive and rec.status != "retired":
                    return aid
        return best

    # ─── Message Routing ─────────────────────────────────────────────

    async def send_message(self, msg: EILMessage) -> None:
        """Send an EIL message to its destination via the event bus."""
        self._ecosystem_stats["total_messages"] += 1
        await self._message_queue.put(msg)

    async def _route_message(self, msg: EILMessage) -> None:
        """Route a single message to its target agent(s)."""
        if msg.type == "register":
            await self._handle_register(msg)
            return
        if msg.type == "learn":
            self._ecosystem_stats["total_learns"] += 1

        await self.event_bus.publish(f"msg:{msg.type}", msg)

        if msg.dst == "*":
            await self.event_bus.publish("broadcast", msg)
            for aid in self._agents:
                agent = self._agents[aid]
                if agent.ref and hasattr(agent.ref, "handle_message"):
                    await agent.ref.handle_message(msg)
                    agent.messages_received += 1
            return

        if msg.type in ("response", "error") and msg.ref:
            task = self._tasks.get(msg.ref)
            if task:
                is_done = msg.type == "response" and msg.status == "done"
                task.status = "done" if is_done else "failed"
                task.completed_at = time.time()
                if task.assigned_to and task.assigned_to in self._agents:
                    agent = self._agents[task.assigned_to]
                    if is_done:
                        agent.tasks_completed += 1
                    else:
                        agent.tasks_failed += 1
                    agent.status = "idle"
                if not is_done:
                    self._ecosystem_stats["total_errors"] += 1

        if msg.dst == "kernel":
            await self._handle_kernel_message(msg)
            return

        if msg.dst in self._agents:
            agent = self._agents[msg.dst]
            if agent.ref and hasattr(agent.ref, "handle_message"):
                await agent.ref.handle_message(msg)
                agent.messages_received += 1
            return

        agent_type_match = self._routing_table.get(msg.dst)
        if agent_type_match:
            await self.send_message(EILMessage(
                src=msg.src, dst=agent_type_match, type=msg.type,
                task=msg.task, priority=msg.priority, status=msg.status,
                result=msg.result, ref=msg.ref, sender_type=msg.sender_type,
            ))
            return

        loguru_logger.warning("No route for message dst={} (task={})", msg.dst, msg.task)

    async def _handle_register(self, msg: EILMessage) -> None:
        self.register_agent(
            msg.src,
            msg.sender_type,
            capabilities=msg.result,
            ref=msg.result.get("_ref"),
        )

    async def _handle_kernel_message(self, msg: EILMessage) -> None:
        handler = self._handlers.get(msg.task)
        if handler:
            await handler(msg)
        elif msg.task == "get_status":
            reply = EILMessage.response("kernel", msg.src, msg.id, self.get_status())
            await self.send_message(reply)
        elif msg.task == "list_agents":
            agents_data = {aid: r.to_dict() for aid, r in self._agents.items()}
            reply = EILMessage.response("kernel", msg.src, msg.id, {"agents": agents_data})
            await self.send_message(reply)
        elif msg.task == "shutdown":
            loguru_logger.warning("Shutdown requested by {}", msg.src)
            self.running = False

    # ─── Task Scheduling ─────────────────────────────────────────────

    async def submit_task(self, msg: EILMessage) -> str:
        """Submit a task to the ecosystem. Returns task ID."""
        task = TaskRecord(msg)
        self._tasks[task.id] = task
        self._ecosystem_stats["total_tasks"] += 1
        priority = max(0, min(10, msg.priority))
        await self._task_queue.put((priority, time.time(), task))
        self._save_tasks()
        return task.id

    async def _process_tasks(self) -> None:
        """Worker loop: consume tasks from queue and route to agents."""
        while self.running:
            try:
                priority, timestamp, task = await asyncio.wait_for(
                    self._task_queue.get(), timeout=1.0
                )
            except asyncio.TimeoutError:
                continue

            target = task.msg.dst if task.msg.dst != "*" else None
            if not target or target == "kernel":
                target = self.find_agent_for_task(task.msg.task)
            if target and target not in self._agents:
                target = self._routing_table.get(target)
            if target and target not in self._agents:
                for aid, rec in self._agents.items():
                    if rec.agent_type == task.msg.dst and rec.alive:
                        target = aid
                        break

            if target and target in self._agents:
                task.assigned_to = target
                task.status = "active"
                task.started_at = time.time()
                agent = self._agents[target]
                agent.status = "active"
                assign_msg = EILMessage(
                    src="kernel", dst=target, type="task",
                    task=task.msg.task, priority=task.msg.priority,
                    status="active", result=task.msg.result,
                    ref=task.id, sender_type="kernel",
                )
                if agent.ref and hasattr(agent.ref, "handle_message"):
                    await agent.ref.handle_message(assign_msg)
                self._save_tasks()
                loguru_logger.info("Task {} assigned to {}: {}", task.id[:12], target, task.msg.task[:80])
            else:
                task.status = "failed"
                task.retries += 1
                if task.retries < task.max_retries:
                    task.status = "pending"
                    await asyncio.sleep(0.5)
                    await self._task_queue.put((priority, time.time(), task))
                    loguru_logger.warning("Task {} queued for retry ({}/{})",
                                          task.id[:12], task.retries, task.max_retries)
                else:
                    loguru_logger.error("Task {} failed after {} retries: no available agent",
                                       task.id[:12], task.max_retries)

    # ─── Health Monitoring ────────────────────────────────────────────

    def _check_health(self) -> Dict[str, Any]:
        """Check health of all agents and system resources."""
        import psutil
        now = time.time()
        agents_alive = 0
        agents_dead = 0
        for agent in self._agents.values():
            if (now - agent.last_heartbeat) < 60:
                agents_alive += 1
            else:
                agents_dead += 1

        status = {
            "tick": self.tick,
            "uptime_s": round(time.time() - self.start_time, 1),
            "agents": {
                "total": len(self._agents),
                "alive": agents_alive,
                "dead": agents_dead,
            },
            "tasks": {
                "total": len(self._tasks),
                "pending": sum(1 for t in self._tasks.values() if t.status == "pending"),
                "active": sum(1 for t in self._tasks.values() if t.status == "active"),
                "done": sum(1 for t in self._tasks.values() if t.status == "done"),
                "failed": sum(1 for t in self._tasks.values() if t.status == "failed"),
            },
            "stats": dict(self._ecosystem_stats),
        }

        try:
            status["cpu_percent"] = psutil.cpu_percent(interval=0.1)
            status["memory_percent"] = psutil.virtual_memory().percent
            status["memory_available_gb"] = round(psutil.virtual_memory().available / (1024**3), 2)
        except Exception:
            pass

        self._health_history.append(status)
        if len(self._health_history) > 1000:
            self._health_history = self._health_history[-1000:]
        loguru_logger.info("health_check", tick=self.tick, alive=agents_alive, total=len(self._agents))
        return status

    # ─── Tick Engine ──────────────────────────────────────────────────

    async def _tick_loop(self) -> None:
        """Drives the ecosystem forward in discrete cycles."""
        while self.running:
            self.tick += 1

            while not self._message_queue.empty():
                msg = await self._message_queue.get()
                await self._route_message(msg)

            if self.tick % 5 == 0:
                health = self._check_health()
                if self.tick % 20 == 0:
                    loguru_logger.info("Health tick {}: {} agents, {} pending tasks",
                                      self.tick, health["agents"]["alive"],
                                      health["tasks"]["pending"])

            if self.tick % 60 == 0:
                self._save_state()

            await asyncio.sleep(1.0)

    # ─── Lifecycle ────────────────────────────────────────────────────

    async def start(self) -> None:
        """Start the ecosystem kernel."""
        if self.running:
            return
        self.running = True
        self.start_time = time.time()
        loguru_logger.info("Ecosystem Kernel starting (node={})", self.node_id)
        self._tick_task = asyncio.create_task(self._tick_loop())
        self._worker_task = asyncio.create_task(self._process_tasks())
        loguru_logger.info("Ecosystem Kernel operational")

    async def stop(self) -> None:
        """Gracefully shut down the ecosystem kernel."""
        loguru_logger.info("Ecosystem Kernel shutting down...")
        self.running = False
        if self._tick_task:
            self._tick_task.cancel()
        if self._worker_task:
            self._worker_task.cancel()
        self._save_state()
        loguru_logger.info("Ecosystem Kernel stopped after {} ticks", self.tick)

    def get_status(self) -> Dict[str, Any]:
        """Get full ecosystem status."""
        health = self._check_health()
        return {
            "ecosystem": {
                "node_id": self.node_id,
                "tick": self.tick,
                "uptime_s": health["uptime_s"],
                "running": self.running,
            },
            "agents": health["agents"],
            "tasks": health["tasks"],
            "stats": health["stats"],
            "cpu_percent": health.get("cpu_percent"),
            "memory_percent": health.get("memory_percent"),
            "memory_available_gb": health.get("memory_available_gb"),
        }

    # ─── Persistence ──────────────────────────────────────────────────

    def _save_agents(self) -> None:
        try:
            data = {aid: r.to_dict() for aid, r in self._agents.items()}
            AGENTS_FILE.write_text(json.dumps(data, indent=2, default=str))
        except Exception as e:
            loguru_logger.warning("Failed to save agents: {}", e)

    def _save_tasks(self) -> None:
        try:
            data = [t.to_dict() for t in self._tasks.values()]
            TASKS_FILE.write_text(json.dumps(data, indent=2, default=str))
        except Exception as e:
            loguru_logger.warning("Failed to save tasks: {}", e)

    def _save_state(self) -> None:
        self._save_agents()
        self._save_tasks()

    def _load_state(self) -> None:
        try:
            if AGENTS_FILE.exists():
                data = json.loads(AGENTS_FILE.read_text())
                loaded = 0
                for aid, info in data.items():
                    last_hb = info.get("last_heartbeat", 0)
                    if time.time() - last_hb > 300:
                        continue
                    rec = AgentRecord(
                        aid, info.get("agent_type", "unknown"),
                        info.get("capabilities", {}),
                    )
                    rec.status = "idle"
                    rec.tasks_completed = info.get("tasks_completed", 0)
                    rec.tasks_failed = info.get("tasks_failed", 0)
                    rec.last_heartbeat = time.time()
                    self._agents[aid] = rec
                    loaded += 1
                if loaded > 0:
                    loguru_logger.info("Loaded {} agents from state", loaded)
        except Exception as e:
            loguru_logger.debug("No saved agent state: {}", e)

        try:
            if TASKS_FILE.exists():
                data = json.loads(TASKS_FILE.read_text())
                for t in data:
                    self._ecosystem_stats["total_tasks"] += 1
                loguru_logger.info("Loaded {} task records", len(data))
        except Exception as e:
            loguru_logger.debug("No saved task state: {}", e)
