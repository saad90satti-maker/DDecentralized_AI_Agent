"""
Ecosystem Agent Base — Universal Agent Adapter

Every agent in the ecosystem extends this base class.
It provides:
  - Automatic registration with the Kernel
  - EIL message sending/receiving
  - Heartbeat (health reporting)
  - Task handling
  - Knowledge read/write to SharedMemory
"""

import asyncio
import json
import logging
import time
import uuid
from typing import Any, Dict, List, Optional

from ecosystem_language import EILMessage, format_eil
from ecosystem_shared_memory import EcosystemMemory

logger = logging.getLogger("ecosystem.agent")


class EcosystemAgent:
    """Base class for all ecosystem agents."""

    agent_type = "base"

    def __init__(self, kernel, memory: Optional[EcosystemMemory] = None,
                 agent_id: Optional[str] = None):
        from ecosystem_kernel import EcosystemKernel as EK
        self._kernel: EK = kernel
        self._memory: EcosystemMemory = memory or EcosystemMemory()
        self.agent_id = agent_id or f"{self.agent_type}-{uuid.uuid4().hex[:6]}"
        self._message_queue: asyncio.Queue = asyncio.Queue()
        self._running = False
        self._task_count = 0
        self._error_count = 0
        self._start_time = time.time()
        self._active_task: Optional[str] = None
        self._capabilities: Dict[str, Any] = self._declare_capabilities()

        self._kernel.register_agent(
            self.agent_id, self.agent_type,
            capabilities=self._capabilities,
            ref=self,
        )

        self._register_msg = EILMessage.register_agent(
            self.agent_id, self.agent_type, self._capabilities
        )
        self._kernel.event_bus.subscribe(f"msg:{self.agent_type}", self._route_to_self)

    def _declare_capabilities(self) -> Dict[str, Any]:
        return {
            "tasks": [],
            "description": f"{self.agent_type} agent",
            "version": "1.0",
        }

    async def _route_to_self(self, msg: EILMessage) -> None:
        if msg.dst == self.agent_id or msg.dst == self.agent_type:
            await self.handle_message(msg)

    # ─── Message Handling ─────────────────────────────────────────

    async def send(self, msg: EILMessage) -> None:
        """Send an EIL message via the kernel."""
        if msg.src == "unknown":
            msg.src = self.agent_id
        await self._kernel.send_message(msg)

    async def send_to(self, dst: str, task: str, result: Optional[Dict] = None,
                      priority: int = 5, msg_type: str = "request") -> str:
        """Convenience: send a message to a specific agent."""
        msg = EILMessage(
            src=self.agent_id, dst=dst, type=msg_type, task=task,
            priority=priority, result=result or {},
            sender_type=self.agent_type,
        )
        await self.send(msg)
        return msg.id

    async def broadcast(self, task: str, result: Optional[Dict] = None) -> None:
        """Broadcast a message to all agents."""
        msg = EILMessage.broadcast(self.agent_id, task, result, self.agent_type)
        await self.send(msg)

    async def handle_message(self, msg: EILMessage) -> None:
        """Override this in subclasses. Called when a message arrives."""
        if msg.type == "task":
            await self._handle_task(msg)
        elif msg.type == "request":
            await self._handle_request(msg)
        elif msg.type == "query":
            await self._handle_query(msg)
        elif msg.type == "health":
            await self._handle_health_check(msg)
        elif msg.type == "learn":
            await self._handle_learn(msg)
        elif msg.type == "broadcast":
            await self._handle_broadcast(msg)

    async def _handle_task(self, msg: EILMessage) -> None:
        """Default task handler — override for specific behavior."""
        task_ref = msg.ref or msg.id
        self._active_task = task_ref
        try:
            result = await self.execute_task(msg.task, msg.result)
            self._task_count += 1
            reply = EILMessage.response(
                self.agent_id, msg.src, task_ref,
                result, status="done", task=msg.task,
            )
            await self.send(reply)
        except Exception as e:
            self._error_count += 1
            reply = EILMessage.error(self.agent_id, msg.src, msg.task, str(e), task_ref)
            await self.send(reply)
        finally:
            self._active_task = None

    async def execute_task(self, task: str, params: Dict[str, Any]) -> Dict[str, Any]:
        """Override this! The actual work of the agent."""
        return {"status": "not_implemented", "task": task}

    async def _handle_request(self, msg: EILMessage) -> None:
        reply = EILMessage.response(self.agent_id, msg.src, msg.id, {
            "agent_id": self.agent_id,
            "type": self.agent_type,
            "status": "active" if self._active_task else "idle",
            "tasks_completed": self._task_count,
            "uptime_s": round(time.time() - self._start_time, 1),
        })
        await self.send(reply)

    async def _handle_query(self, msg: EILMessage) -> None:
        data = self._memory.search_knowledge(msg.task)
        reply = EILMessage.response(self.agent_id, msg.src, msg.id, {
            "results": data,
            "query": msg.task,
        })
        await self.send(reply)

    async def _handle_health_check(self, msg: EILMessage) -> None:
        reply = EILMessage.health(self.agent_id, {
            "status": "active" if self._active_task else "idle",
            "tasks_completed": self._task_count,
            "errors": self._error_count,
            "uptime_s": round(time.time() - self._start_time, 1),
        })
        await self.send(reply)

    async def _handle_learn(self, msg: EILMessage) -> None:
        self._memory.add_learning(
            msg.src, msg.result,
            confidence=msg.result.get("confidence", 0.5),
        )

    async def _handle_broadcast(self, msg: EILMessage) -> None:
        pass

    # ─── Knowledge Access ─────────────────────────────────────────

    def remember(self, key: str) -> Optional[Any]:
        return self._memory.get_knowledge(key)

    def learn(self, key: str, value: Any, confidence: float = 1.0,
              tags: Optional[List[str]] = None) -> None:
        self._memory.store_knowledge(key, value, source=self.agent_id,
                                     agent_type=self.agent_type,
                                     confidence=confidence, tags=tags)

    def search_knowledge(self, query: str) -> List[Dict[str, Any]]:
        return self._memory.search_knowledge(query)

    # ─── Lifecycle ────────────────────────────────────────────────

    async def start(self) -> None:
        self._running = True
        self._start_time = time.time()
        self._msg_processor = asyncio.create_task(self._process_message_loop())
        logger.info("Agent %s (%s) started", self.agent_id, self.agent_type)

    async def _process_message_loop(self) -> None:
        """Background task that processes incoming messages."""
        while self._running:
            try:
                msg = await asyncio.wait_for(self._message_queue.get(), timeout=1.0)
                await self.handle_message(msg)
            except asyncio.TimeoutError:
                continue
            except Exception as e:
                logger.warning("Agent %s msg loop error: %s", self.agent_id, e)

    async def stop(self) -> None:
        self._running = False
        if hasattr(self, '_msg_processor') and self._msg_processor:
            self._msg_processor.cancel()
        logger.info("Agent %s stopped (%d tasks, %d errors)",
                    self.agent_id, self._task_count, self._error_count)

    def get_status(self) -> Dict[str, Any]:
        return {
            "agent_id": self.agent_id,
            "type": self.agent_type,
            "status": "active" if self._active_task else "idle",
            "tasks_completed": self._task_count,
            "errors": self._error_count,
            "uptime_s": round(time.time() - self._start_time, 1),
            "active_task": self._active_task,
        }


# ═══════════════════════════════════════════════════════════════
# SPECIALIZED AGENTS
# ═══════════════════════════════════════════════════════════════

class PlannerAgent(EcosystemAgent):
    """Creates plans, decomposes goals, assigns tasks to other agents."""

    agent_type = "planner"

    def _declare_capabilities(self) -> Dict[str, Any]:
        return {
            "tasks": ["create_plan", "decompose_goal", "assign_tasks", "prioritize"],
            "description": "Strategic planner and goal decomposition engine",
        }

    async def execute_task(self, task: str, params: Dict[str, Any]) -> Dict[str, Any]:
        if "create_plan" in task or "plan" in task:
            return await self._create_plan(params.get("goal", "Unspecified goal"))
        elif "decompose" in task:
            return self._decompose(params.get("goal", ""))
        elif "evaluate" in task:
            return self._evaluate_feasibility(params.get("plan", {}))
        return {"status": "unknown_task", "task": task}

    async def _create_plan(self, goal: str) -> Dict[str, Any]:
        plan_id = f"plan-{uuid.uuid4().hex[:8]}"
        steps = [
            {"step": 1, "action": "research", "description": f"Research {goal}"},
            {"step": 2, "action": "plan", "description": f"Design solution for {goal}"},
            {"step": 3, "action": "build", "description": f"Implement {goal}"},
            {"step": 4, "action": "audit", "description": f"Verify {goal}"},
            {"step": 5, "action": "evolve", "description": f"Optimize {goal}"},
        ]
        plan = {
            "plan_id": plan_id,
            "goal": goal,
            "steps": steps,
            "total_steps": len(steps),
            "status": "created",
        }
        self.learn(f"plan:{plan_id}", plan, confidence=0.8, tags=["plan", "strategy"])
        for step in steps:
            agent_type = step["action"]
            agents = self._kernel.get_agents_by_type(agent_type)
            if agents:
                await self.send_to(
                    agents[0].agent_id,
                    f"execute_step_{step['step']}: {step['description']}",
                    {"plan_id": plan_id, "step": step},
                    priority=7,
                )
        return plan

    def _decompose(self, goal: str) -> Dict[str, Any]:
        tasks = []
        domains = ["research", "planning", "execution", "verification", "optimization"]
        for i, domain in enumerate(domains):
            tasks.append({
                "id": f"task-{uuid.uuid4().hex[:6]}",
                "domain": domain,
                "description": f"{domain.capitalize()} for: {goal[:50]}",
                "priority": 5 + i,
                "dependencies": tasks[-1]["id"] if tasks else None,
            })
        return {"goal": goal, "tasks": tasks, "total": len(tasks)}

    def _evaluate_feasibility(self, plan: Dict) -> Dict[str, Any]:
        agents = self._kernel.get_agents()
        available_types = set(a.agent_type for a in agents.values())
        required = set(s["action"] for s in plan.get("steps", []))
        missing = required - available_types
        return {
            "feasible": len(missing) == 0,
            "available_agents": list(available_types),
            "missing_agent_types": list(missing),
            "suggestions": [f"Create {m} agent" for m in missing],
        }


class ExecutorAgent(EcosystemAgent):
    """Executes tasks, runs commands, performs actions."""

    agent_type = "executor"

    def _declare_capabilities(self) -> Dict[str, Any]:
        return {
            "tasks": ["execute", "run_script", "shell_command", "process_task"],
            "description": "Task execution engine for the ecosystem",
        }

    async def execute_task(self, task: str, params: Dict[str, Any]) -> Dict[str, Any]:
        import subprocess
        command = params.get("command", task)
        timeout = params.get("timeout", 30)
        try:
            result = subprocess.run(
                command, shell=True, capture_output=True, text=True,
                timeout=timeout, cwd=str(BASE_DIR),
            )
            return {
                "stdout": result.stdout[-500:],
                "stderr": result.stderr[-500:],
                "returncode": result.returncode,
                "success": result.returncode == 0,
            }
        except subprocess.TimeoutExpired:
            return {"success": False, "error": "timeout"}
        except Exception as e:
            return {"success": False, "error": str(e)}


class ResearcherAgent(EcosystemAgent):
    """Collects information, searches knowledge, investigates topics."""

    agent_type = "research"

    def _declare_capabilities(self) -> Dict[str, Any]:
        return {
            "tasks": ["research", "search", "investigate", "find_information"],
            "description": "Information gathering and research agent",
        }

    async def execute_task(self, task: str, params: Dict[str, Any]) -> Dict[str, Any]:
        topic = params.get("topic", task)
        results = self._memory.search_knowledge(topic, min_confidence=0.3)
        if results:
            return {
                "topic": topic,
                "source": "ecosystem_memory",
                "results": results[:10],
                "total_found": len(results),
            }
        return {
            "topic": topic,
            "source": "no_data",
            "results": [],
            "suggestion": "Consider adding knowledge about this topic",
        }


class MonitorAgent(EcosystemAgent):
    """Tracks health, system resources, agent status, and alerts on failures."""

    agent_type = "monitor"

    def _declare_capabilities(self) -> Dict[str, Any]:
        return {
            "tasks": ["monitor", "health_check", "status_report", "alert"],
            "description": "System health and performance monitoring",
        }

    async def execute_task(self, task: str, params: Dict[str, Any]) -> Dict[str, Any]:
        if "agents" in task.lower():
            agents = self._kernel.get_agents()
            return {
                "total": len(agents),
                "alive": sum(1 for a in agents.values()
                             if (time.time() - a.last_heartbeat) < 60),
                "dead": sum(1 for a in agents.values()
                            if (time.time() - a.last_heartbeat) >= 60),
                "agents": {aid: r.to_dict() for aid, r in agents.items()},
            }
        elif "health" in task or "status" in task:
            return self._kernel.get_status()
            agents = self._kernel.get_agents()
            return {
                "total": len(agents),
                "alive": sum(1 for a in agents.values()
                             if (time.time() - a.last_heartbeat) < 60),
                "dead": sum(1 for a in agents.values()
                            if (time.time() - a.last_heartbeat) >= 60),
                "agents": {aid: r.to_dict() for aid, r in agents.items()},
            }
        return self._kernel.get_status()


class MemoryAgent(EcosystemAgent):
    """Manages knowledge, stores patterns, bridges memory systems."""

    agent_type = "memory"

    def _declare_capabilities(self) -> Dict[str, Any]:
        return {
            "tasks": ["store", "recall", "search", "bridge", "consolidate"],
            "description": "Knowledge management and memory consolidation",
        }

    async def execute_task(self, task: str, params: Dict[str, Any]) -> Dict[str, Any]:
        if "store" in task or "save" in task:
            key = params.get("key", task)
            value = params.get("value", params)
            conf = params.get("confidence", 1.0)
            tags = params.get("tags", [])
            self.learn(key, value, confidence=conf, tags=tags)
            return {"stored": True, "key": key}
        elif "recall" in task or "get" in task:
            val = self.remember(params.get("key", task))
            return {"found": val is not None, "value": val}
        elif "search" in task or "find" in task:
            results = self._memory.search_knowledge(params.get("query", task))
            return {"results": results, "count": len(results)}
        elif "stats" in task or "snapshot" in task:
            return self._memory.snapshot()
        return {"status": "unknown_task"}


class EvolutionAgent(EcosystemAgent):
    """Analyzes the ecosystem and suggests improvements."""

    agent_type = "evolution"

    def _declare_capabilities(self) -> Dict[str, Any]:
        return {
            "tasks": ["analyze", "suggest", "optimize", "evolve", "report"],
            "description": "Self-evolution and optimization engine",
        }

    async def execute_task(self, task: str, params: Dict[str, Any]) -> Dict[str, Any]:
        if "analyze" in task:
            return self._analyze_ecosystem()
        elif "suggest" in task:
            return self._generate_suggestions()
        elif "report" in task:
            return self._evolution_report()
        return {"status": "analyzing", "task": task}

    def _analyze_ecosystem(self) -> Dict[str, Any]:
        agents = self._kernel.get_agents()
        status = self._kernel.get_status()
        suggestions = []
        if len(agents) == 0:
            suggestions.append("No agents registered — ecosystem is empty")
        dead_agents = [aid for aid, a in agents.items()
                       if (time.time() - a.last_heartbeat) >= 60]
        if dead_agents:
            suggestions.append(f"{len(dead_agents)} agents are not responding")
        tasks_pending = status.get("tasks", {}).get("pending", 0)
        if tasks_pending > 10:
            suggestions.append(f"Task backlog: {tasks_pending} pending tasks")
        return {
            "agent_count": len(agents),
            "alive_agents": status.get("agents", {}).get("alive", 0),
            "dead_agents": dead_agents,
            "suggestions": suggestions,
            "health_score": self._calculate_health_score(status),
        }

    def _generate_suggestions(self) -> Dict[str, Any]:
        return {
            "suggestions": [
                {"priority": 9, "area": "agents",
                 "suggestion": "Ensure all core agents are registered and alive"},
                {"priority": 7, "area": "knowledge",
                 "suggestion": "Populate knowledge base with seed data for better task routing"},
                {"priority": 5, "area": "monitoring",
                 "suggestion": "Enable periodic health broadcasts from all agents"},
                {"priority": 3, "area": "evolution",
                 "suggestion": "Run evolution analysis every 100 ticks to detect bottlenecks"},
            ]
        }

    def _evolution_report(self) -> Dict[str, Any]:
        return {
            "ecosystem_age_ticks": self._kernel.tick,
            "total_messages": self._kernel._ecosystem_stats.get("total_messages", 0),
            "total_tasks": self._kernel._ecosystem_stats.get("total_tasks", 0),
            "total_errors": self._kernel._ecosystem_stats.get("total_errors", 0),
            "total_learns": self._kernel._ecosystem_stats.get("total_learns", 0),
            "analysis": self._analyze_ecosystem(),
            "suggestions": self._generate_suggestions(),
        }

    def _calculate_health_score(self, status: Dict[str, Any]) -> float:
        agents = status.get("agents", {})
        total = agents.get("total", 0)
        alive = agents.get("alive", 0)
        if total == 0:
            return 0.0
        return round((alive / total) * 100, 1)


class CoordinatorAgent(EcosystemAgent):
    """Maintains order, routes tasks, ensures agents are working correctly."""

    agent_type = "coordinator"

    def _declare_capabilities(self) -> Dict[str, Any]:
        return {
            "tasks": ["coordinate", "route", "balance", "orchestrate", "assign"],
            "description": "Ecosystem coordinator and task orchestrator",
        }

    async def execute_task(self, task: str, params: Dict[str, Any]) -> Dict[str, Any]:
        if "balance" in task or "route" in task:
            return self._balance_load()
        elif "orchestrate" in task:
            return await self._orchestrate_workflow(params.get("goal", "unknown"))
        elif "ping" in task or "discover" in task:
            return self._discover_agents()
        return {"status": "coordinating", "task": task}

    def _balance_load(self) -> Dict[str, Any]:
        agents = self._kernel.get_agents()
        task_counts = {aid: a.tasks_completed for aid, a in agents.items()}
        if not task_counts:
            return {"status": "no_agents"}
        avg = sum(task_counts.values()) / len(task_counts)
        imbalanced = [aid for aid, tc in task_counts.items() if tc < avg - 2]
        return {
            "average_tasks": round(avg, 1),
            "balanced": len(imbalanced) == 0,
            "imbalanced_agents": imbalanced,
            "total_agents": len(agents),
        }

    async def _orchestrate_workflow(self, goal: str) -> Dict[str, Any]:
        plan_msg = await self.send_to(
            self._kernel.find_agent_for_task("planner") or "planner",
            f"plan: {goal}",
            {"goal": goal},
            priority=8,
        )
        return {
            "goal": goal,
            "status": "workflow_initiated",
            "message": f"Plan request sent for: {goal[:80]}",
        }

    def _discover_agents(self) -> Dict[str, Any]:
        agents = self._kernel.get_agents()
        by_type = defaultdict(list)
        for aid, a in agents.items():
            by_type[a.agent_type].append(aid)
        return {
            "total": len(agents),
            "by_type": dict(by_type),
            "agent_list": list(agents.keys()),
        }


from pathlib import Path
from collections import defaultdict

BASE_DIR = Path(__file__).resolve().parent
