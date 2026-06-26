#!/usr/bin/env python3
"""
██╗    ██╗ █████╗ ██╗  ██╗███████╗███╗   ██╗
██║    ██║██╔══██╗██║ ██╔╝██╔════╝████╗  ██║
██║ █╗ ██║███████║█████╔╝ █████╗  ██╔██╗ ██║
██║███╗██║██╔══██║██╔═██╗ ██╔══╝  ██║╚██╗██║
╚███╔███╔╝██║  ██║██║  ██╗███████╗██║ ╚████║
 ╚══╝╚══╝ ╚═╝  ╚═╝╚═╝  ╚═╝╚══════╝╚═╝  ╚═══╝

  PROJECT OMEGA — ECOSYSTEM AWAKENING
  Decentralized AI Ecosystem Launcher

Usage:
  python awaken.py          Interactive shell
  python awaken.py --boot   Boot and show status, then enter shell
  python awaken.py --demo   Run the full demo sequence
"""

import argparse
import asyncio
import json
import sys
import time
from pathlib import Path

# Ensure we can import from this directory
sys.path.insert(0, str(Path(__file__).resolve().parent))

from ecosystem_kernel import EcosystemKernel, EILMessage
from ecosystem_shared_memory import EcosystemMemory
from ecosystem_launcher import EcosystemLauncher


def print_banner():
    print(r"""
   ___  ___  _  _  ___   ___  _  _  ___  ___
  / _ \/ _ \| \| |/ __| | _ \| \| |/ _ \|   \
 | (_) | (_) | .` | (__  |   /| .` | (_) | |) |
  \___/\___/|_|\_|\___| |_|_\|_|\_|\___/|___/

  DECENTRALIZED AI ECOSYSTEM
  Agents communicating | Tasks routing | Knowledge sharing
""")


async def run_demo():
    """Run the full ecosystem demo."""
    demo_path = Path(__file__).resolve().parent / "ecosystem_demo.py"
    import importlib.util
    spec = importlib.util.spec_from_file_location("ecosystem_demo", demo_path)
    demo_mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(demo_mod)
    await demo_mod.demo()


async def run_interactive(ghost_bridge: bool = False):
    """Boot the ecosystem and enter interactive shell."""
    print_banner()
    if ghost_bridge:
        print("  [PRODUCTION MODE] Bridging Ghost production components...\n")
    print("  Booting ecosystem...\n")

    launcher = EcosystemLauncher()
    await launcher.boot(ghost_bridge=ghost_bridge)

    kernel = launcher.kernel
    memory = launcher.memory

    print("\n  Ecosystem is LIVE. Type 'help' for commands, 'exit' to shutdown.\n")

    while kernel and kernel.running:
        try:
            cmd = await asyncio.get_event_loop().run_in_executor(
                None, lambda: input("ecosystem> ").strip()
            )
        except (EOFError, KeyboardInterrupt):
            print()
            break

        if not cmd:
            continue

        parts = cmd.split(maxsplit=1)
        command = parts[0].lower()
        args = parts[1] if len(parts) > 1 else ""

        if command in ("exit", "quit", "q"):
            break

        elif command == "status":
            s = kernel.get_status()
            print(f"\n  Kernel:     {s['ecosystem']['node_id']}")
            print(f"  Uptime:     {s['ecosystem']['uptime_s']:.0f}s")
            print(f"  Ticks:      {s['ecosystem']['tick']}")
            print(f"  Agents:     {s['agents']['alive']}/{s['agents']['total']} alive")
            print(f"  Tasks:      {s['tasks']['done']} done, {s['tasks']['active']} active, "
                  f"{s['tasks']['failed']} failed")
            print(f"  Messages:   {s['stats']['total_messages']}")
            print(f"  Errors:     {s['stats']['total_errors']}")
            print(f"  CPU:        {s.get('cpu_percent', '?')}%")
            print(f"  Memory:     {s.get('memory_percent', '?')}% ({s.get('memory_available_gb', '?')}GB free)")

        elif command == "agents":
            agents = kernel.get_agents()
            print(f"\n  Agents ({len(agents)}):")
            for aid, rec in sorted(agents.items()):
                alive = "ALIVE" if rec.alive else "DEAD"
                print(f"  [{alive}] {aid:30s} type={rec.agent_type:15s} "
                      f"tasks={rec.tasks_completed} status={rec.status}")

        elif command == "memory":
            stats = memory.snapshot()
            print(f"\n  Knowledge entries: {stats['knowledge']['total_entries']}")
            print(f"  Observations:      {stats['observations']['total']}")
            print(f"  Learning patterns: {stats['learning']['total_patterns']}")
            print(f"  Agent memories:    {stats['agent_memory_count']}")

        elif command == "scores":
            scores = await launcher._calculate_scores()
            print()
            for name, score in scores.items():
                bar = "#" * int(score / 5) + "-" * (20 - int(score / 5))
                print(f"  {name:20s} [{bar}] {score:.1f}%")

        elif command == "task":
            if not args:
                print("  Usage: task <agent_type> <description>")
                continue
            parts = args.strip().split(maxsplit=1)
            if len(parts) < 2:
                print("  Usage: task <agent_type> <description>")
                continue
            dst, desc = parts
            msg = EILMessage(src="human", dst=dst, type="task", task=desc,
                             priority=5, sender_type="human")
            task_id = await kernel.submit_task(msg)
            print(f"  Task submitted: {task_id[:16]}...")

        elif command == "tasks":
            tasks = kernel._tasks
            print(f"\n  Tasks ({len(tasks)}):")
            for tid, t in sorted(tasks.items())[:15]:
                print(f"  [{t.status:8s}] {tid[:20]:20s} agent={t.assigned_to or 'unassigned':25s} "
                      f"task={t.msg.task[:50]}")

        elif command == "broadcast":
            if not args:
                print("  Usage: broadcast <message>")
                continue
            msg = EILMessage.broadcast("human", args, sender_type="human")
            await kernel.send_message(msg)
            print("  Broadcast sent to all agents.")

        elif command == "discover":
            agents = kernel.get_agents()
            by_type = {}
            for aid, rec in agents.items():
                by_type.setdefault(rec.agent_type, []).append(aid)
            print(f"\n  Agent types ({len(by_type)}):")
            for atype, aids in sorted(by_type.items()):
                print(f"  {atype:15s}: {len(aids)} agent(s)")

        elif command == "plan":
            if not args:
                print("  Usage: plan <goal>")
                continue
            planner_aid = kernel._routing_table.get("planner")
            if planner_aid:
                msg = EILMessage(src="human", dst=planner_aid, type="task",
                                 task=f"create_plan: {args}", priority=8,
                                 result={"goal": args}, sender_type="human")
                await kernel.submit_task(msg)
                print(f"  Plan request submitted for: {args[:80]}")
            else:
                print("  No planner agent available")

        elif command == "help":
            print("""
  status     - Ecosystem status
  agents     - List all agents
  memory     - Memory statistics
  scores     - Ecosystem scores (0-100%)
  tasks      - Show task queue
  task       - Submit task: task <agent_type> <description>
  plan       - Create plan: plan <goal description>
  broadcast  - Send message to all agents
  discover   - Show agent type distribution
  exit       - Shutdown ecosystem
  help       - This menu
""")

        else:
            print(f"  Unknown command: {command}. Type 'help'.")

    await launcher.shutdown()
    print("  Ecosystem shutdown complete.")


def main():
    parser = argparse.ArgumentParser(description="Ecosystem Awakening")
    parser.add_argument("--mode", choices=["interactive", "demo", "boot"],
                        default="interactive",
                        help="Run mode (default: interactive)")
    parser.add_argument("--production", action="store_true",
                        help="Boot with Ghost production component bridging")
    args = parser.parse_args()

    if args.mode == "demo":
        asyncio.run(run_demo())
    elif args.mode == "boot":
        print_banner()
        launcher = EcosystemLauncher()
        asyncio.run(launcher.boot(ghost_bridge=args.production))
        print("\n  Boot complete. Use --mode interactive for the shell.")
    else:
        asyncio.run(run_interactive(ghost_bridge=args.production))


if __name__ == "__main__":
    main()
