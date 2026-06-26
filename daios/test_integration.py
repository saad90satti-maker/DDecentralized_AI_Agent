"""Quick integration test for DAIOS."""

import asyncio
import sys
import os

test_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(test_dir)
sys.path.insert(0, parent_dir)
os.chdir(test_dir)

from daios.kernel.config import DAIOSConfig
from daios.main import run_simulation


async def test():
    print("Starting DAIOS integration test...\n")
    config = DAIOSConfig(simulation_tick_interval=0.3, max_agents=6, log_level="WARNING")
    kernel = await run_simulation(config, max_ticks=8)

    print("\n=== FINAL STATUS ===")
    s = kernel.get_status()
    print(f"Ticks:            {s['tick']}")
    print(f"Agents active:    {s['agents']['active']}")
    print(f"Agents list:      {s['agents']['list']}")
    print(f"Resources:        {s['resources']}")
    print(f"Total Tasks:      {s['total_tasks']}")
    print(f"Total Discoveries:{s['total_discoveries']}")
    print(f"Uptime:           {s['uptime_s']:.1f}s")

    assert s["tick"] > 0, "Ticks did not advance"
    assert s["agents"]["active"] == 6, f"Expected 6 agents, got {s['agents']['active']}"
    assert len(s["agents"]["list"]) == 6, f"Expected 6 agent IDs"
    assert "research-01" in s["agents"]["list"], "Research agent missing"
    assert "planner-01" in s["agents"]["list"], "Planner agent missing"
    assert "memory-01" in s["agents"]["list"], "Memory agent missing"

    print("\n=== ALL ASSERTIONS PASSED ===")
    print("TEST PASSED")


if __name__ == "__main__":
    asyncio.run(test())
