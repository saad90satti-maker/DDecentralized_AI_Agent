"""
Ecosystem Autonomous Demo — Shows agents communicating, routing tasks, sharing knowledge.
"""
import asyncio
import sys
import time
import json
sys.path.insert(0, '.')

from ecosystem_launcher import EcosystemLauncher
from ecosystem_kernel import EILMessage


async def demo():
    launcher = EcosystemLauncher()
    await launcher.boot()

    kernel = launcher.kernel

    print("\n" + "=" * 70)
    print("  PHASE 1: INTER-AGENT COMMUNICATION")
    print("=" * 70)

    # Demo 1: Planner creates a plan -> sends tasks to other agents
    planner = launcher.agents.get("planner")
    plan = await planner._create_plan("Optimize system performance")
    print(f"\n  Planner created plan: {plan['plan_id']}")
    print(f"  Goal: {plan['goal']}")
    print(f"  Steps: {len(plan['steps'])}")
    for step in plan['steps']:
        print(f"    Step {step['step']}: {step['action']:15s} -> {step['description']}")

    # Demo 2: Monitor checks health
    monitor = launcher.agents.get("monitor")
    health = await monitor.execute_task("agents_status", {})
    print(f"\n  Monitor health check: {health['total']} agents, {health['alive']} alive")

    # Demo 3: Memory agent stores knowledge
    memory_agent = launcher.agents.get("memory")
    memory_agent.learn("ecosystem:boot:success", {
        "boot_time": time.time(),
        "agents_count": len(kernel.get_agents()),
        "version": "1.0",
    }, confidence=1.0, tags=["ecosystem", "boot", "success"])

    stored = memory_agent.remember("ecosystem:boot:success")
    print(f"\n  Memory stored and retrieved: {stored['agents_count']} agents at boot")

    # Demo 4: Evolution agent analyzes ecosystem
    evolution = launcher.agents.get("evolution")
    analysis = evolution._analyze_ecosystem()
    print(f"\n  Evolution analysis:")
    print(f"    Agent count: {analysis['agent_count']}")
    print(f"    Health score: {analysis['health_score']}%")
    print(f"    Suggestions: {len(analysis.get('suggestions', []))}")
    for s in analysis.get('suggestions', []):
        print(f"      -> {s}")

    # Demo 5: Coordinator discovers and balances
    coordinator = launcher.agents.get("coordinator")
    discovery = coordinator._discover_agents()
    print(f"\n  Agent discovery ({discovery['total']} total):")
    for atype, agents_list in discovery['by_type'].items():
        print(f"    {atype:15s}: {agents_list}")

    print("\n" + "=" * 70)
    print("  PHASE 2: TASK ROUTING AND EXECUTION")
    print("=" * 70)

    # Route tasks through the kernel to different agents
    tasks = [
        ("monitor", "health_check", {"scope": "full"}, 5),
        ("memory", "store", {"key": "test:routing", "value": {"test": True}, "tags": ["test"]}, 3),
        ("evolution", "suggest", {}, 2),
        ("coordinator", "balance_load", {}, 4),
        ("planner", "evaluate", {"plan": plan}, 6),
    ]

    task_ids = []
    for dst, task, params, priority in tasks:
        msg = EILMessage(
            src="demo", dst=dst, type="task", task=f"{task}",
            priority=priority, result=params, sender_type="demo",
        )
        task_id = await kernel.submit_task(msg)
        task_ids.append((dst, task, task_id))
        print(f"\n  Task submitted: [{task_id[:12]}] {dst} -> {task}")

    # Give workers time to process
    await asyncio.sleep(5.0)

    print(f"\n  Task results:")
    for dst, task, tid in task_ids:
        task_record = kernel._tasks.get(tid)
        if task_record:
            print(f"    [{task_record.status:8s}] {task:25s} -> {task_record.assigned_to or 'unassigned'}")

    print("\n" + "=" * 70)
    print("  PHASE 3: SHARED KNOWLEDGE NETWORK")
    print("=" * 70)

    # Add more knowledge from different agents
    for agent_name, agent in launcher.agents.items():
        agent.learn(f"{agent_name}:capabilities", agent._capabilities,
                     confidence=0.9, tags=[agent_name, "capabilities"])

    search_results = memory_agent.search_knowledge("capabilities")
    print(f"\n  Knowledge search 'capabilities': {len(search_results)} results")
    for r in search_results[:5]:
        print(f"    {r.get('key', '')[:50]:50s} source={r.get('source', '?')} "
              f"conf={r.get('confidence', 0)}")

    stats = launcher.memory.snapshot()
    print(f"\n  Memory totals:")
    print(f"    Knowledge entries: {stats['knowledge']['total_entries']}")
    print(f"    Learning patterns: {stats['learning']['total_patterns']}")
    print(f"    Agent memories:    {stats['agent_memory_count']}")

    print("\n" + "=" * 70)
    print("  PHASE 4: FINAL ECOSYSTEM SCORES")
    print("=" * 70)

    scores = await launcher._calculate_scores()
    for name, score in scores.items():
        bar = "#" * int(score / 5) + "-" * (20 - int(score / 5))
        print(f"  {name:20s} [{bar}] {score:.1f}%")

    s = kernel.get_status()
    print(f"\n  Ecosystem Stats:")
    print(f"    Uptime:       {s['ecosystem']['uptime_s']:.1f}s")
    print(f"    Ticks:        {s['ecosystem']['tick']}")
    print(f"    Total msgs:   {s['stats']['total_messages']}")
    print(f"    Total tasks:  {s['stats']['total_tasks']}")
    print(f"    Total learns: {s['stats']['total_learns']}")
    print(f"    Total errors: {s['stats']['total_errors']}")

    await launcher.shutdown()

if __name__ == "__main__":
    asyncio.run(demo())
