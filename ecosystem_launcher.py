"""
Ecosystem Launcher v1.0 — Project Omega Awakening

Boot sequence for the Decentralized AI Ecosystem.
Starts the Kernel, registers all agents, bridges existing memory,
and begins autonomous operation.

Activation Sequence:
  1. Initialize Kernel
  2. Start Event Bus
  3. Register Core Agents (Planner, Executor, Researcher, Monitor, Memory, Evolution, Coordinator)
  4. Bridge Existing Memory Systems (DAIOS, Ghost, Knowledge DB)
  5. Begin Tick Loop
  6. Run Health Verification
  7. Enable Self-Organization
  8. Report Ecosystem Score
"""

import asyncio
import json
import os
import signal
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from loguru import logger

BASE_DIR = Path(__file__).resolve().parent
LOG_DIR = BASE_DIR / "agent_logs"
LOG_DIR.mkdir(exist_ok=True)

logger.remove()
logger.add(
    LOG_DIR / "ecosystem_{time:YYYYMMDD_HHmmss}.log",
    rotation="10 MB",
    retention="7 days",
    level="INFO",
    format="{time:YYYY-MM-DD HH:mm:ss} | {level:<7} | {name} | {message}",
)
logger.add(
    sys.stderr,
    level="INFO",
    format="{time:YYYY-MM-DD HH:mm:ss} | {level:<7} | {name} | {message}",
)

from ecosystem_kernel import EcosystemKernel
from ecosystem_shared_memory import EcosystemMemory
from ecosystem_language import EILMessage, format_eil
from ecosystem_agent import (
    PlannerAgent, ExecutorAgent, ResearcherAgent,
    MonitorAgent, MemoryAgent, EvolutionAgent, CoordinatorAgent,
)

try:
    from ecosystem_browser_agent import BrowserAgent
    _BROWSER_AGENT_AVAILABLE = True
except ImportError as e:
    _BROWSER_AGENT_AVAILABLE = False
    _BROWSER_AGENT_IMPORT_ERR = str(e)

try:
    from research_engine.agent import ResearchEngineAgent
    _RESEARCH_ENGINE_AVAILABLE = True
except ImportError:
    _RESEARCH_ENGINE_AVAILABLE = False

try:
    from ecosystem_x_agent import XAgent
    _X_AGENT_AVAILABLE = True
except ImportError:
    _X_AGENT_AVAILABLE = False

try:
    from ecosystem_telegram_agent import TelegramAgent
    _TELEGRAM_AGENT_AVAILABLE = True
except ImportError:
    _TELEGRAM_AGENT_AVAILABLE = False

try:
    from ecosystem_bridge_ghost import BRIDGED_AGENTS
    _GHOST_BRIDGE_AVAILABLE = True
except ImportError:
    _GHOST_BRIDGE_AVAILABLE = False
    BRIDGED_AGENTS = {}

try:
    from ecosystem_hardening import EcosystemHardening
    _HARDENING_AVAILABLE = True
except ImportError:
    _HARDENING_AVAILABLE = False


class EcosystemLauncher:
    """Boot sequence for the entire ecosystem."""

    def __init__(self):
        self.kernel: Optional[EcosystemKernel] = None
        self.memory: Optional[EcosystemMemory] = None
        self.agents: Dict[str, object] = {}
        self.start_time: float = 0.0
        self.boot_log: List[str] = []
        self.hardening: Optional[EcosystemHardening] = None

    def log(self, msg: str) -> None:
        self.boot_log.append(msg)
        logger.info(msg)

    async def boot(self, ghost_bridge: bool = False) -> bool:
        """Execute the full boot sequence. Returns True if successful."""
        self.start_time = time.time()
        self.log("=" * 60)
        self.log("  PROJECT OMEGA — ECOSYSTEM AWAKENING")
        self.log("=" * 60)

        # ─── Step 1: Start Kernel ────────────────────────────────
        self.log("[1/8] Initializing Ecosystem Kernel...")
        self.kernel = EcosystemKernel()
        await self.kernel.start()
        self.log(f"  Kernel online: node={self.kernel.node_id}")

        # ─── Step 2: Start Memory ────────────────────────────────
        self.log("[2/8] Initializing Shared Memory Layer...")
        self.memory = EcosystemMemory()
        stats = self.memory.snapshot()
        self.log(f"  Memory online: {stats['knowledge']['total_entries']} knowledge entries, "
                 f"{stats['learning']['total_patterns']} patterns")

        # ─── Step 3: Bridge Existing Memory ──────────────────────
        self.log("[3/8] Bridging existing memory systems...")
        daios_bridged = self._bridge_daios_memory()
        ghost_bridged = self._bridge_ghost_knowledge()
        db_bridged = self._bridge_knowledge_db()
        self.log(f"  Bridged: DAIOS={daios_bridged}, Ghost={ghost_bridged}, DB={db_bridged}")

        # ─── Step 4: Register Core Agents ────────────────────────
        self.log("[4/8] Registering core ecosystem agents...")
        agent_classes = [
            ("planner", PlannerAgent),
            ("executor", ExecutorAgent),
            ("research", ResearcherAgent),
            ("monitor", MonitorAgent),
            ("memory", MemoryAgent),
            ("evolution", EvolutionAgent),
            ("coordinator", CoordinatorAgent),
        ]
        if _BROWSER_AGENT_AVAILABLE:
            agent_classes.append(("browser", BrowserAgent))
        if _RESEARCH_ENGINE_AVAILABLE:
            agent_classes.append(("research_engine", ResearchEngineAgent))
        if _X_AGENT_AVAILABLE:
            agent_classes.append(("x_social", XAgent))
        if _TELEGRAM_AGENT_AVAILABLE:
            agent_classes.append(("telegram", TelegramAgent))
        for agent_type, cls in agent_classes:
            try:
                agent = cls(kernel=self.kernel, memory=self.memory)
                await agent.start()
                self.agents[agent_type] = agent
                self.log(f"  Agent: {agent.agent_id} ({agent_type})")
            except Exception as e:
                self.log(f"  FAILED: {agent_type} — {e}")

        self.log(f"  Total agents registered: {len(self.kernel.get_agents())}")

        # ─── Step 4b (optional): Bridge Ghost Production Components ─
        if ghost_bridge:
            self.log("[4b/8] Bridging Ghost production components...")
            if _GHOST_BRIDGE_AVAILABLE:
                for agent_type, cls in BRIDGED_AGENTS.items():
                    try:
                        agent = cls(kernel=self.kernel, memory=self.memory)
                        await agent.start()
                        self.agents[agent_type] = agent
                        self.log(f"  Ghost bridge: {agent.agent_id} ({agent_type})")
                    except Exception as e:
                        self.log(f"  Ghost bridge FAILED: {agent_type} — {e}")
                self.log(f"  Total agents with ghost bridges: {len(self.kernel.get_agents())}")
            else:
                self.log("  Ghost bridge module not available (ecosystem_bridge_ghost.py)")
        else:
            self.log("[4b/8] Ghost bridging skipped (use --production for full mode)")

        # ─── Step 5: Verify Communication ────────────────────────
        self.log("[5/8] Verifying inter-agent communication...")
        comm_results = await self._verify_communication()
        for result in comm_results:
            self.log(f"  {result}")

        # ─── Step 6: Self-Organization Test ──────────────────────
        self.log("[6/8] Testing self-organization...")
        org_results = await self._test_self_organization()
        for result in org_results:
            self.log(f"  {result}")

        # ─── Step 7: Ecosystem Score ─────────────────────────────
        self.log("[7/8] Calculating ecosystem scores...")
        scores = await self._calculate_scores()
        for name, score in scores.items():
            self.log(f"  {name}: {score:.1f}%")

        # ─── Step 7b: Initialize Hardening Layer ─────────────────
        self.log("[7b/8] Initializing system hardening layer...")
        if _HARDENING_AVAILABLE:
            try:
                self.hardening = EcosystemHardening(kernel=self.kernel, memory=self.memory)
                await self.hardening.start()
                dep_check = self.hardening.check_dependencies()
                if dep_check.get("all_ok"):
                    self.log("  Dependencies: ALL OK")
                else:
                    missing = [k for k, v in dep_check.items() if isinstance(v, dict) and v.get("status") == "missing"]
                    self.log(f"  Dependencies: {len(missing)} missing — {missing}")
                backup = self.hardening.backup_configs()
                self.log(f"  Config backup: {len(backup['files'])} files saved")
                self.log("  Hardening layer active (5-min health reports, hourly backups)")
            except Exception as e:
                self.log(f"  Hardening init FAILED: {e}")
        else:
            self.log("  Hardening module not available")

        # ─── Step 8: Final Report ────────────────────────────────
        self.log("[8/8] Generating ecosystem report...")
        report = self._generate_report(scores)
        self.log("")
        self.log("=" * 60)
        self.log("  ECOSYSTEM AWAKENING COMPLETE")
        self.log(f"  Uptime: {time.time() - self.start_time:.1f}s")
        self.log(f"  Agents: {len(self.kernel.get_agents())}")
        self.log(f"  Tasks: {self.kernel._ecosystem_stats['total_tasks']}")
        self.log("=" * 60)

        report_path = LOG_DIR / "ecosystem_report.json"
        report_path.write_text(json.dumps(report, indent=2, default=str))
        self.log(f"  Report saved: {report_path}")

        return True

    def _bridge_daios_memory(self) -> int:
        count = 0
        try:
            sys.path.insert(0, str(BASE_DIR))
            from daios.memory.shared_memory import SharedMemory
            daios_mem = SharedMemory(str(BASE_DIR / "daios" / "data"))
            count = self.memory.bridge_from_daios(daios_mem)
        except Exception as e:
            self.log(f"  (DAIOS memory bridge skipped: {e})")
        return count

    def _bridge_ghost_knowledge(self) -> int:
        count = 0
        try:
            from shared_knowledge import SharedKnowledge as GhostKnowledge
            ghost_know = GhostKnowledge()
            count = self.memory.bridge_from_ghost(ghost_know)
        except Exception as e:
            self.log(f"  (Ghost knowledge bridge skipped: {e})")
        return count

    def _bridge_knowledge_db(self) -> int:
        count = 0
        try:
            import sqlite3
            db_path = BASE_DIR / "session_data" / "knowledge.db"
            if db_path.exists():
                conn = sqlite3.connect(str(db_path))
                c = conn.cursor()
                try:
                    c.execute("SELECT key, value FROM knowledge")
                    for key, value in c.fetchall():
                        try:
                            val = json.loads(value)
                        except Exception:
                            val = value
                        self.memory.store_knowledge(f"legacy:{key}", val,
                                                     source="legacy_db", confidence=1.0)
                        count += 1
                except Exception:
                    pass
                conn.close()
        except Exception as e:
            self.log(f"  (Knowledge DB bridge skipped: {e})")
        return count

    async def _verify_communication(self) -> List[str]:
        results = []
        agent_ids = list(self.kernel.get_agents().keys())
        if not agent_ids:
            return ["No agents to verify"]

        test_msg = EILMessage(
            src="launcher", dst=agent_ids[0], type="request",
            task="ping", priority=1,
        )
        try:
            await self.kernel.send_message(test_msg)
            results.append(f"Message sent to {agent_ids[0]} — OK")
        except Exception as e:
            results.append(f"Message send FAILED: {e}")

        monitor = self.agents.get("monitor")
        if monitor:
            try:
                status = await monitor.execute_task("health_check", {})
                alive = status.get("agents", {}).get("alive", 0)
                results.append(f"Health check: {alive}/{len(agent_ids)} agents alive")
            except Exception as e:
                results.append(f"Health check FAILED: {e}")

        memory_agent = self.agents.get("memory")
        if memory_agent:
            try:
                test_key = f"boot_test_{time.time()}"
                memory_agent.learn(test_key, {"boot": True}, confidence=1.0, tags=["test"])
                val = memory_agent.remember(test_key)
                if val and val.get("boot"):
                    results.append("Memory write/read cycle — OK")
                else:
                    results.append("Memory write/read — FAILED")
            except Exception as e:
                results.append(f"Memory test FAILED: {e}")

        return results

    async def _test_self_organization(self) -> List[str]:
        results = []
        coordinator = self.agents.get("coordinator")
        if coordinator:
            discovery = coordinator._discover_agents()
            by_type = discovery.get("by_type", {})
            types_present = list(by_type.keys())
            results.append(f"Agent discovery: {types_present}")

        planner = self.agents.get("planner")
        if planner:
            plan = await planner._create_plan("Test ecosystem health")
            results.append(f"Plan creation: {plan.get('plan_id', 'FAILED')}")

        evolution = self.agents.get("evolution")
        if evolution:
            analysis = evolution._analyze_ecosystem()
            results.append(f"Evolution analysis: health={analysis.get('health_score', 0)}%")

        return results

    async def _calculate_scores(self) -> Dict[str, float]:
        agents = self.kernel.get_agents()
        status = self.kernel.get_status()

        total_agents = len(agents)
        alive_agents = sum(1 for a in agents.values()
                          if (time.time() - a.last_heartbeat) < 60)
        total_possible = 7  # 7 core agent types

        # Communication Score: agents sending messages / total possible
        comm_score = min(100, (self.kernel._ecosystem_stats["total_messages"] / max(1, total_agents)) * 20)

        # Automation Score: alive agents / total registered
        auto_score = (alive_agents / max(1, total_agents)) * 100 if total_agents > 0 else 0

        # Reliability Score: tasks completed without error
        total_tasks = self.kernel._ecosystem_stats["total_tasks"]
        total_errors = self.kernel._ecosystem_stats["total_errors"]
        rel_score = 100 - (total_errors / max(1, total_tasks + total_errors)) * 100 if total_tasks > 0 else 100

        # Knowledge Score: knowledge entries and patterns
        mem_stats = self.memory.snapshot()
        knowledge_count = mem_stats["knowledge"]["total_entries"]
        learning_count = mem_stats["learning"]["total_patterns"]
        know_score = min(100, (knowledge_count + learning_count * 2) / 2)

        # Scalability Score: agent diversity / max types
        types_present = set(a.agent_type for a in agents.values())
        scal_score = (len(types_present) / total_possible) * 100

        # Evolution Score: healthy agents, knowledge growth, adaptations
        evo_score = (alive_agents / max(1, total_agents)) * 50
        if knowledge_count > 0:
            evo_score += 25
        if len(types_present) >= 5:
            evo_score += 25

        return {
            "Communication": round(comm_score, 1),
            "Automation": round(auto_score, 1),
            "Reliability": round(rel_score, 1),
            "Knowledge": round(know_score, 1),
            "Scalability": round(scal_score, 1),
            "Evolution": round(evo_score, 1),
        }

    def _generate_report(self, scores: Dict[str, float]) -> Dict[str, Any]:
        return {
            "ecosystem_report": {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "node_id": self.kernel.node_id if self.kernel else "unknown",
                "boot_time_s": round(time.time() - self.start_time, 1),
            },
            "agents": {
                "total": len(self.kernel.get_agents()) if self.kernel else 0,
                "types": list(set(a.agent_type for a in self.kernel.get_agents().values())) if self.kernel else [],
                "agent_ids": list(self.kernel.get_agents().keys()) if self.kernel else [],
            },
            "memory": self.memory.snapshot() if self.memory else {},
            "stats": self.kernel._ecosystem_stats if self.kernel else {},
            "scores": scores,
            "boot_log": self.boot_log,
        }

    async def shutdown(self) -> None:
        """Graceful shutdown of the ecosystem."""
        self.log("Shutting down ecosystem...")
        for name, agent in self.agents.items():
            try:
                await agent.stop()
            except Exception as e:
                logger.warning("Error stopping", name=name)
        if self.hardening:
            await self.hardening.stop()
            self.log("  Hardening layer stopped")
        if self.kernel:
            await self.kernel.stop()
        if self.memory:
            self.memory.close()
        self.log("Ecosystem shutdown complete.")


async def main_loop(launcher: EcosystemLauncher) -> None:
    """After boot, run the ecosystem autonomously."""
    logger.info("Ecosystem entering autonomous operation mode")
    logger.info("Commands: status, agents, memory, scores, tasks, shutdown")

    while launcher.kernel and launcher.kernel.running:
        command = await asyncio.get_event_loop().run_in_executor(
            None, lambda: input("\necosystem> ").strip().lower()
        )

        if command == "status":
            s = launcher.kernel.get_status()
            print(json.dumps(s, indent=2, default=str))

        elif command == "agents":
            agents = launcher.kernel.get_agents()
            for aid, rec in sorted(agents.items()):
                alive = "ALIVE" if rec.alive else "DEAD"
                print(f"  [{alive}] {aid:25s} type={rec.agent_type:15s} "
                      f"tasks={rec.tasks_completed} status={rec.status}")

        elif command == "memory":
            if launcher.memory:
                print(json.dumps(launcher.memory.snapshot(), indent=2))

        elif command == "scores":
            scores = await launcher._calculate_scores()
            for name, score in scores.items():
                bar = "█" * int(score / 5) + "░" * (20 - int(score / 5))
                print(f"  {name:20s} [{bar}] {score:.1f}%")

        elif command == "tasks":
            tasks = launcher.kernel._tasks
            print(f"  Total tasks: {len(tasks)}")
            for tid, t in sorted(tasks.items())[:10]:
                print(f"  [{t.status:8s}] {tid[:16]:16s} → {t.assigned_to or 'unassigned'}")

        elif command == "broadcast":
            msg = input("  Message to broadcast: ")
            broadcast = EILMessage.broadcast("human", msg)
            await launcher.kernel.send_message(broadcast)
            print("  Broadcast sent.")

        elif command in ("exit", "quit", "shutdown"):
            break

        elif command == "help":
            print("  status     - Ecosystem status")
            print("  agents     - List all agents")
            print("  memory     - Memory statistics")
            print("  scores     - Ecosystem scores")
            print("  tasks      - Task queue")
            print("  broadcast  - Send message to all agents")
            print("  shutdown   - Stop ecosystem")
            print("  help       - This menu")

    await launcher.shutdown()


async def main(ghost_bridge: bool = False):
    launcher = EcosystemLauncher()
    success = await launcher.boot(ghost_bridge=ghost_bridge)
    if success:
        await main_loop(launcher)
    else:
        logger.error("Ecosystem boot FAILED")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
