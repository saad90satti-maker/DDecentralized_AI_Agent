"""
Ecosystem Boot Test — Quick verification that the ecosystem kernel starts and agents communicate.
"""
import asyncio
import sys
sys.path.insert(0, '.')

from ecosystem_launcher import EcosystemLauncher

async def test():
    launcher = EcosystemLauncher()
    success = await launcher.boot()
    if success:
        print()
        print("=" * 60)
        print("  BOOT SUCCESS: ECOSYSTEM IS ALIVE")
        print("=" * 60)
        scores = await launcher._calculate_scores()
        print()
        print("ECOSYSTEM SCORES:")
        for name, score in scores.items():
            bar = "#" * int(score / 5) + "-" * (20 - int(score / 5))
            print(f"  {name:20s} [{bar}] {score:.1f}%")
        print()
        s = launcher.kernel.get_status()
        print(f"  Agents alive:  {s['agents']['alive']}/{s['agents']['total']}")
        print(f"  Tasks:         {s['tasks']}")
        print(f"  Stats:         {s['stats']}")
    await launcher.shutdown()

if __name__ == "__main__":
    asyncio.run(test())
