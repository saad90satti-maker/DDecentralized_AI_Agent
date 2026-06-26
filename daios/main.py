"""DAIOS Entry Point — initializes kernel, agents, world, exploration, API, and CLI."""

import asyncio
import logging
import sys
import argparse
from typing import Optional

from daios.kernel.kernel_node import KernelNode
from daios.kernel.config import DAIOSConfig
from daios.communication.message_bus import MessageBus
from daios.simulation.world import SimulationWorld
from daios.exploration.hypothesis_engine import HypothesisEngine
from daios.growth.agent_factory import AgentFactory

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
)
logger = logging.getLogger("daios")


async def create_default_agents(kernel, bus):
    from daios.agents.research_agent import ResearchAgent
    from daios.agents.planner_agent import PlannerAgent
    from daios.agents.builder_agent import BuilderAgent
    from daios.agents.auditor_agent import AuditorAgent
    from daios.agents.memory_agent import MemoryAgent
    from daios.agents.communication_agent import CommunicationAgent

    agent_classes = [
        ("research-01", ResearchAgent),
        ("planner-01", PlannerAgent),
        ("builder-01", BuilderAgent),
        ("auditor-01", AuditorAgent),
        ("memory-01", MemoryAgent),
        ("comm-01", CommunicationAgent),
    ]

    for agent_id, cls in agent_classes:
        try:
            agent = cls(agent_id, kernel)
            await kernel.register_agent(agent_id, agent)
            logger.info("  ✓ %s (%s)", agent_id, cls.agent_type)
        except Exception as e:
            logger.error("  ✗ %s: %s", agent_id, e)


async def run_simulation(config: DAIOSConfig, use_api: bool = False, use_cli: bool = False,
                         max_ticks: int = 0):
    kernel = KernelNode(config)
    bus = MessageBus(kernel)
    world = SimulationWorld(config)
    hypothesis_engine = HypothesisEngine()
    agent_factory = AgentFactory(kernel)

    kernel._world = world
    kernel._hypothesis_engine = hypothesis_engine
    kernel._agent_factory = agent_factory
    kernel._bus = bus

    await kernel.start()
    await create_default_agents(kernel, bus)

    kernel.state_mgr.state.phase = "operational"

    if use_cli:
        from daios.api.cli import DAIOSShell
        shell = DAIOSShell(kernel)
        shell.cmdloop()
    else:
        tick_count = 0
        try:
            while kernel.state_mgr.state.kernel_status == "running":
                await asyncio.sleep(1)
                tick_count += 1
                world_update = world.tick_update()
                if world_update.get("events"):
                    for event in world_update["events"]:
                        logger.info("[WORLD] %s", event)
                        kernel.state_mgr.state.total_tasks_completed += 1
                if tick_count % 5 == 0:
                    for aid, agent in kernel.get_all_agents().items():
                        s = getattr(agent, "get_status", lambda: {})()
                        if s.get("discoveries", 0) > 0:
                            kernel.state_mgr.state.total_discoveries += s["discoveries"]
                            setattr(agent, "_discovery_count", 0)
                if max_ticks > 0 and tick_count >= max_ticks:
                    logger.info("Reached max ticks (%d), stopping", max_ticks)
                    break
        except KeyboardInterrupt:
            logger.info("Keyboard interrupt received")

    await kernel.stop()
    logger.info("DAIOS simulation ended after %d ticks", kernel.state_mgr.state.tick)
    return kernel


def run_api_server(config: DAIOSConfig):
    import threading
    from daios.api.rest_api import init, start_api

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    kernel = loop.run_until_complete(run_simulation(config))

    def start_api_thread():
        init(kernel)
        start_api(port=config.dashboard_port)

    t = threading.Thread(target=start_api_thread, daemon=True)
    t.start()
    logger.info("DAIOS API server running on port %d", config.dashboard_port)

    try:
        loop.run_forever()
    except KeyboardInterrupt:
        pass
    finally:
        loop.run_until_complete(kernel.stop())
        loop.close()


def main():
    parser = argparse.ArgumentParser(description="DAIOS — Decentralized AI Operating System")
    parser.add_argument("--mode", choices=["sim", "api", "cli", "cloud"], default="sim",
                        help="Running mode (default: sim)")
    parser.add_argument("--tick", type=float, default=None,
                        help="Simulation tick interval in seconds")
    parser.add_argument("--agents", type=int, default=None,
                        help="Maximum number of agents")
    parser.add_argument("--port", type=int, default=None,
                        help="API dashboard port")
    parser.add_argument("--seed", type=int, default=None,
                        help="Simulation world seed")
    parser.add_argument("--log-level", default=None,
                        help="Logging level (DEBUG, INFO, WARNING)")
    args = parser.parse_args()

    config = DAIOSConfig.from_env()
    if args.tick:
        config.simulation_tick_interval = args.tick
    if args.agents:
        config.max_agents = args.agents
    if args.port:
        config.dashboard_port = args.port
    if args.seed:
        config.simulation_world_seed = args.seed
    if args.log_level:
        config.log_level = args.log_level
        logging.getLogger().setLevel(getattr(logging, args.log_level.upper(), logging.INFO))

    print(f"""
{'='*60}
  DAIOS v0.1.0 - Simulation Engine
  Mode: {args.mode}
  Tick: {config.simulation_tick_interval:.1f}s
  Max Agents: {config.max_agents}
  Port: {config.dashboard_port}
{'='*60}
""")

    if args.mode == "api" or args.mode == "cloud":
        run_api_server(config)
    elif args.mode == "cli":
        asyncio.run(run_simulation(config, use_cli=True))
    else:
        asyncio.run(run_simulation(config, use_api=False, use_cli=False))


if __name__ == "__main__":
    main()
