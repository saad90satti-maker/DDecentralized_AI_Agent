"""DAIOS CLI — human control interface for monitoring and commanding the simulation."""

import sys
import json
import cmd
import asyncio
import logging
from typing import Dict, Any, Optional

logger = logging.getLogger("daios.cli")


class DAIOSShell(cmd.Cmd):
    intro = """
=============================================
  DAIOS - Decentralized AI OS Shell
  Type 'help' or '?' for available commands
=============================================
"""
    prompt = "daios> "

    def __init__(self, kernel=None):
        super().__init__()
        self._kernel = kernel
        self._running = True

    def set_kernel(self, kernel):
        self._kernel = kernel

    def do_status(self, arg):
        """Show system status"""
        if not self._kernel:
            print("Kernel not running")
            return
        s = self._kernel.get_status()
        print(f"\n=== DAIOS Status (Tick {s['tick']}) ===")
        print(f"  Kernel:     {s['kernel']}")
        print(f"  Phase:      {s['phase']}")
        print(f"  Agents:     {s['agents']['active']} active ({s['agents']['total_created']} total)")
        print(f"  Uptime:     {s['uptime_s']:.0f}s")
        print(f"  Tasks:      {s['total_tasks']}")
        print(f"  Discoveries:{s['total_discoveries']}")
        print(f"  Resources:  {json.dumps(s['resources'], indent=4)}")
        perf = s.get("performance", {})
        if perf:
            print(f"\n  Performance:")
            print(f"    Avg Tick: {perf.get('avg_tick_duration_ms', '?')}ms")
            print(f"    CPU:      {perf.get('latest_cpu', '?')}%")
            print(f"    Mem:      {perf.get('latest_memory_mb', '?')}MB")

    def do_agents(self, arg):
        """List all agents and their status"""
        if not self._kernel:
            return
        agents = self._kernel.get_all_agents()
        if not agents:
            print("No agents registered")
            return
        print(f"\n=== Agents ({len(agents)}) ===")
        for aid in sorted(agents.keys()):
            a = agents[aid]
            s = a.get_status() if hasattr(a, "get_status") else {}
            print(f"  {aid:25s} | {s.get('type','?'):15s} | energy={s.get('energy',0):.0f} "
                  f"| tasks={s.get('tasks_completed',0)} | status={s.get('status','?')}")

    def do_world(self, arg):
        """Show simulation world status"""
        if not self._kernel:
            return
        world = getattr(self._kernel, "_world", None)
        if not world:
            print("World not initialized")
            return
        w = world.get_status()
        print(f"\n=== World (Tick {w['tick']}) ===")
        print(f"  GDP:      {w['economy']['gdp']:.0f}")
        print(f"  Innov:    {w['economy']['innovation_index']:.1f}")
        print(f"  Research: ")
        for r in w.get("research", []):
            status = "✓" if r.get("completed") else f"{r.get('progress',0)*100:.0f}%"
            print(f"    {r['title'][:45]:45s} [{status}]")
        print(f"\n  Communities:")
        for c in w.get("communities", []):
            print(f"    {c['name']:15s} | pop={c['size']} | happy={c['happiness']} | tech={c['tech']}")

    def do_memory(self, arg):
        """Show memory statistics"""
        if not self._kernel:
            return
        for aid, a in self._kernel.get_all_agents().items():
            if getattr(a, "agent_type", "") == "memory":
                s = a.get_status() if hasattr(a, "get_status") else {}
                print(f"\n=== Memory Agent ===")
                print(f"  Observations:  {s.get('observations', 0)}")
                print(f"  Tasks:         {s.get('tasks_completed', 0)}")
                print(f"  Energy:        {s.get('energy', 0):.1f}")
                return
        print("No memory agent found")

    def do_hypotheses(self, arg):
        """Show hypothesis engine status"""
        k = self._kernel
        if not k or not hasattr(k, "_hypothesis_engine"):
            print("Hypothesis engine not available")
            return
        summary = k._hypothesis_engine.rank_by_usefulness()
        print(f"\n=== Hypotheses ({len(summary)}) ===")
        for h in summary[:10]:
            check = "✓" if h.get("verified") else "○"
            print(f"  {check} {h['title'][:55]:55s} | score={h['score']:.2f} conf={h['confidence']:.2f}")

    def do_tasks(self, arg):
        """Show available world tasks"""
        k = self._kernel
        world = getattr(k, "_world", None) if k else None
        if not world:
            return
        tasks = world.get_available_tasks()
        print(f"\n=== Available Tasks ({len(tasks)}) ===")
        for t in tasks[:10]:
            print(f"  [{t['community']}] {t['description'][:50]:50s} reward={t['reward']:.0f}")

    def do_propose(self, arg):
        """Propose a new agent: propose <type> <reason>"""
        if not arg:
            print("Usage: propose <agent_type> <reason>")
            return
        parts = arg.strip().split(maxsplit=1)
        agent_type = parts[0]
        reason = parts[1] if len(parts) > 1 else "Manual request"
        factory = getattr(self._kernel, "_agent_factory", None) if self._kernel else None
        if factory:
            pid = factory.propose_new_agent(agent_type, reason, "cli_user")
            if pid:
                print(f"Proposal created: {pid}")
                print(f"  Type: {agent_type}")
                print(f"  Use:  approve {pid}")
            else:
                print(f"Unknown agent type: {agent_type}")
        else:
            print("Agent factory not available")

    def do_approve(self, arg):
        """Approve a pending agent proposal: approve <proposal_id>"""
        if not arg:
            print("Usage: approve <proposal_id>")
            return
        factory = getattr(self._kernel, "_agent_factory", None) if self._kernel else None
        if factory:
            aid = factory.approve_creation(arg.strip())
            if aid:
                print(f"Agent created: {aid}")
            else:
                print(f"Proposal not found: {arg}")
        else:
            print("Agent factory not available")

    def do_pending(self, arg):
        """Show pending agent creation proposals"""
        factory = getattr(self._kernel, "_agent_factory", None) if self._kernel else None
        if factory:
            pending = factory.get_pending_approvals()
            if not pending:
                print("No pending approvals")
                return
            print(f"\n=== Pending Approvals ({len(pending)}) ===")
            for p in pending:
                print(f"  {p['id']:30s} | {p['agent_type']:15s} | {p['reason'][:40]} | by {p['requested_by']}")
        else:
            print("Agent factory not available")

    def do_checkpoint(self, arg):
        """Save a system checkpoint"""
        if self._kernel:
            path = self._kernel.state_mgr.save_checkpoint()
            print(f"Checkpoint saved: {path}")

    def do_exploration(self, arg):
        """Show exploration system"""
        k = self._kernel
        if not k or not hasattr(k, "_hypothesis_engine"):
            print("Exploration system not available")
            return
        summary = k._hypothesis_engine.summary()
        print(f"\n=== Exploration ===")
        for k_, v in summary.items():
            if k_ != "top_hypotheses":
                print(f"  {k_}: {v}")
        print("\n  Top hypotheses:")
        for h in summary.get("top_hypotheses", []):
            print(f"    {h['title'][:55]:55s} score={h['score']}")

    def do_pause(self, arg):
        """Pause the simulation"""
        print("Simulation pause not implemented in CLI mode")

    def do_resume(self, arg):
        """Resume the simulation"""
        print("Simulation resume not implemented in CLI mode")

    def do_exit(self, arg):
        """Exit the DAIOS shell"""
        print("Shutting down...")
        self._running = False
        return True

    def do_quit(self, arg):
        return self.do_exit(arg)

    def do_EOF(self, arg):
        return self.do_exit(arg)

    def emptyline(self):
        pass


def run_cli(kernel=None):
    shell = DAIOSShell(kernel)
    try:
        shell.cmdloop()
    except KeyboardInterrupt:
        print("\nShutdown requested")
    return shell._running
