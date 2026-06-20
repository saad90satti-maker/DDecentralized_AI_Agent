"""
Global Swarm Intelligence — Autonomous Integration Sequence
============================================================
Orchestrates: Global Discovery → Knowledge Cycles → IPFS Persistence → Swarm Report
Error recovery guided by CORE_CONSTITUTION.md.
"""

import asyncio
import json
import logging
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

BASE_DIR = Path(__file__).resolve().parent
LOG_DIR = BASE_DIR / "agent_logs"
LOG_DIR.mkdir(exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [GSI] %(message)s",
    handlers=[
        logging.FileHandler(LOG_DIR / "global_swarm_intelligence.log"),
        logging.StreamHandler(),
    ],
)
logger = logging.getLogger("GSI")

REPORT_FILE = BASE_DIR / "agent_data" / "swarm_status_report.json"
STATE_FILE = BASE_DIR / "agent_data" / "agent_state.json"


def _load_constitution() -> str:
    path = BASE_DIR / "CORE_CONSTITUTION.md"
    try:
        if path.exists():
            return path.read_text(encoding="utf-8")
    except Exception:
        pass
    return ""


def _diagnose_and_recover(step: str, error: Exception) -> bool:
    """
    Diagnose failure, consult Constitution for guidance, attempt recovery.
    Returns True if recovery was attempted (may or may not succeed).
    """
    logger.error("[FAILURE] Step '%s' failed: %s", step, error)
    constitution = _load_constitution()

    recovery_hint = ""
    if "timeout" in str(error).lower() or "connection" in str(error).lower():
        recovery_hint = "Article IV.3: Network issue — retry with backoff"
        logger.info("Recovery: %s — waiting 5s then retrying", recovery_hint)
        time.sleep(5)
        return True
    if "module" in str(error).lower() or "import" in str(error).lower():
        recovery_hint = "Article III: Missing dependency — attempting auto-install"
        logger.info("Recovery: %s", recovery_hint)
        try:
            missing = str(error).split("'")[1] if "'" in str(error) else ""
            if missing:
                import subprocess
                subprocess.check_call(
                    [sys.executable, "-m", "pip", "install", missing, "--quiet"],
                    timeout=60,
                )
                logger.info("Auto-installed: %s", missing)
                return True
        except Exception:
            pass
    if "permission" in str(error).lower() or "denied" in str(error).lower():
        recovery_hint = "Article I.4: Permission issue — cannot proceed, aborting"
        logger.error("Recovery: %s", recovery_hint)
        return False

    logger.info("Recovery: No specific constitution guidance — retrying once after 10s")
    time.sleep(10)
    return True


async def step_activate_global_discovery() -> Dict[str, Any]:
    """Activate Global Discovery — start swarm node + DHT + Peer Discovery Report."""
    logger.info("=" * 60)
    logger.info("STEP 1: Activate Global Discovery")
    logger.info("=" * 60)

    result = {"status": "failed", "details": {}}

    from ghost_swarm import GhostSwarmNode, DHT_BOOTSTRAP_NODES

    node_id = f"ghost-gsi-{os.getpid()}"
    node = GhostSwarmNode(node_id=node_id, port=0, enable_dht=True)

    try:
        await node.start()
        logger.info("Swarm node started: %s", node.node_id)
        result["node_id"] = node.node_id

        # Bootstrap sequence (fast — 2s per node, break on first success)
        if node.dht:
            bootstrapped = False
            for host, port in DHT_BOOTSTRAP_NODES[:5]:
                try:
                    ok = await asyncio.wait_for(
                        node.dht.bootstrap(host, port), timeout=2
                    )
                    if ok:
                        logger.info("DHT bootstrapped: %s:%d", host, port)
                        bootstrapped = True
                        break
                except asyncio.TimeoutError:
                    continue
                except Exception:
                    continue

            if bootstrapped:
                await asyncio.sleep(1)
                try:
                    dht_peers = await asyncio.wait_for(
                        node.dht.discover_peers(), timeout=3
                    )
                    for entry in dht_peers:
                        nid = entry.get("node_id", "")
                        host = entry.get("host", "")
                        sp = entry.get("swarm_port", 9876)
                        if nid and nid != node.node_id and host:
                            node.add_peer(host, sp, nid, ["dht"])
                    logger.info("DHT peers discovered: %d", len(dht_peers))
                except Exception:
                    logger.info("DHT peer discovery timed out (no DHT network)")
            else:
                logger.info("DHT bootstrap skipped (no reachable bootstrap nodes)")

        # Generate Peer Discovery Report (with short timeout)
        try:
            report = await asyncio.wait_for(
                node.peer_discovery_report(), timeout=5
            )
            result["discovery_report"] = report
            result["status"] = "ok"
            logger.info("Peer Discovery Report: %d/%d peers alive, avg %.1fms latency",
                        report["peers_alive"], report["peers_total"],
                        report["average_latency_ms"])
        except asyncio.TimeoutError:
            result["status"] = "ok"
            result["discovery_report"] = {
                "peers_alive": 0, "peers_total": 0, "average_latency_ms": 0,
                "dht_ready": False, "bootstrap_nodes": {},
            }
            logger.info("Peer discovery timed out — no peers on network")

    except Exception as e:
        if _diagnose_and_recover("Activate Global Discovery", e):
            return await step_activate_global_discovery()
        result["error"] = str(e)
    finally:
        await node.stop()

    result["_node"] = node
    return result


async def step_initiate_knowledge_cycles() -> Dict[str, Any]:
    """Initiate Knowledge Cycles — pull The Stack + Constitutional Audit."""
    logger.info("=" * 60)
    logger.info("STEP 2: Initiate Knowledge Cycles")
    logger.info("=" * 60)

    result = {"status": "failed", "knowledge": {}, "audit": {}}

    try:
        from knowledge_acquisition import (
            KnowledgeAcquisitionEngine, constitutional_audit,
        )

        # 2a. Pull from The Stack
        ka = KnowledgeAcquisitionEngine()
        logger.info("Pulling The Stack dataset...")
        the_stack = ka.pull_the_stack(max_samples=100)
        result["knowledge"] = the_stack
        logger.info("The Stack result: %s", the_stack.get("status", "unknown"))

        # 2b. KnowledgeStore stats
        stats = ka.stats()
        result["knowledge_stats"] = stats
        logger.info("KnowledgeStore: %d total entries", stats.get("total_entries", 0))

        # 2c. Constitutional Audit
        logger.info("Running Constitutional Audit...")
        audit = constitutional_audit(BASE_DIR)
        result["audit"] = audit
        logger.info("Constitutional Audit: score=%s, violations=%d",
                     audit.get("overall_score", "?"), audit.get("total_violations", 0))

        result["status"] = "ok"

    except ImportError as e:
        logger.warning("Knowledge modules not available: %s", e)
        result["status"] = "skipped"
        result["error"] = str(e)
    except Exception as e:
        if _diagnose_and_recover("Initiate Knowledge Cycles", e):
            return await step_initiate_knowledge_cycles()
        result["error"] = str(e)

    return result


async def step_verify_ipfs_persistence() -> Dict[str, Any]:
    """Verify IPFS Persistence — save_state + pin gateway verification."""
    logger.info("=" * 60)
    logger.info("STEP 3: Verify IPFS Persistence")
    logger.info("=" * 60)

    result = {"status": "failed", "ipfs_available": False}

    try:
        from manager import IPFSStateManager

        ipfs = IPFSStateManager()
        available = ipfs.available()
        result["ipfs_available"] = available
        logger.info("IPFS client available: %s", available)

        if available:
            state_payload = {
                "step": "global_swarm_intelligence",
                "timestamp": time.time(),
                "node_id": f"ghost-gsi-{os.getpid()}",
                "version": os.getenv("GHOST_VERSION", "3.0.0"),
                "constitution": "CORE_CONSTITUTION.md loaded",
            }
            ipfs_result = ipfs.save_and_verify(state_payload, topic="gsi_state")
            result["ipfs_result"] = ipfs_result
            logger.info("IPFS save_and_verify: %s", ipfs_result.get("status", "unknown"))
            if ipfs_result.get("status") in ("ok", "pinned_not_public"):
                result["status"] = "ok"
            else:
                result["status"] = "pinned_only"
        else:
            result["status"] = "skipped_no_ipfs"
            logger.info("IPFS not available — state stored locally only")

    except Exception as e:
        if _diagnose_and_recover("Verify IPFS Persistence", e):
            return await step_verify_ipfs_persistence()
        result["error"] = str(e)

    return result


def generate_swarm_report(
    discovery: Dict[str, Any],
    knowledge: Dict[str, Any],
    ipfs: Dict[str, Any],
) -> Dict[str, Any]:
    """Generate comprehensive Swarm Status Report."""
    logger.info("=" * 60)
    logger.info("STEP 4: Generate Swarm Status Report")
    logger.info("=" * 60)

    # Knowledge Level
    knowledge_stats = knowledge.get("knowledge_stats", {})
    knowledge_entries = knowledge_stats.get("total_entries", 0)
    knowledge_level = "none"
    if knowledge_entries > 500:
        knowledge_level = "advanced"
    elif knowledge_entries > 100:
        knowledge_level = "intermediate"
    elif knowledge_entries > 0:
        knowledge_level = "basic"

    # Constitutional Integrity Score
    audit = knowledge.get("audit", {})
    constitution_score = audit.get("overall_score", 0)
    constitution_grade = "F"
    if constitution_score >= 90:
        constitution_grade = "A"
    elif constitution_score >= 80:
        constitution_grade = "B"
    elif constitution_score >= 70:
        constitution_grade = "C"
    elif constitution_score >= 60:
        constitution_grade = "D"

    # Global Peer Connectivity
    discovery_report = discovery.get("discovery_report", {})
    peers_alive = discovery_report.get("peers_alive", 0)
    peers_total = discovery_report.get("peers_total", 0)
    avg_latency = discovery_report.get("average_latency_ms", 0)
    bootstrap_nodes = discovery_report.get("bootstrap_nodes", {})
    reachable_bootstraps = sum(1 for v in bootstrap_nodes.values() if v.get("reachable"))

    # IPFS Status
    ipfs_status = ipfs.get("status", "unavailable")

    report = {
        "report_id": f"GSI-{int(time.time())}",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "swarm_intelligence": {
            "knowledge_level": knowledge_level,
            "knowledge_entries": knowledge_entries,
            "constitutional_integrity_score": constitution_score,
            "constitutional_grade": constitution_grade,
            "constitutional_violations": audit.get("total_violations", 0),
        },
        "global_peer_connectivity": {
            "peers_alive": peers_alive,
            "peers_total": peers_total,
            "average_latency_ms": avg_latency,
            "bootstrap_nodes_reachable": reachable_bootstraps,
            "bootstrap_nodes_total": len(bootstrap_nodes),
            "dht_active": discovery_report.get("dht_ready", False),
        },
        "ipfs_persistence": {
            "status": ipfs_status,
            "cid": ipfs.get("ipfs_result", {}).get("cid", "N/A") if ipfs_status != "unavailable" else "N/A",
            "gateway_accessible": ipfs.get("ipfs_result", {}).get("gateway_accessible", False),
        },
        "article_by_article": audit.get("articles", {}),
    }

    try:
        REPORT_FILE.parent.mkdir(parents=True, exist_ok=True)
        REPORT_FILE.write_text(json.dumps(report, indent=2), encoding="utf-8")
        logger.info("Report saved to %s", REPORT_FILE)
    except Exception as e:
        logger.warning("Could not save report: %s", e)

    return report


async def main() -> int:
    logger.info("")
    logger.info("=" * 60)
    logger.info("  GLOBAL SWARM INTELLIGENCE — Autonomous Sequence")
    logger.info("=" * 60)
    constitution = _load_constitution()
    if constitution:
        logger.info("Constitution loaded (%d chars)", len(constitution))
    else:
        logger.warning("CORE_CONSTITUTION.md not found — operating without constitutional guidance")

    # Step 1: Activate Global Discovery
    discovery = await step_activate_global_discovery()
    logger.info("Step 1 result: %s", discovery.get("status", "unknown"))

    # Step 2: Initiate Knowledge Cycles
    knowledge = await step_initiate_knowledge_cycles()
    logger.info("Step 2 result: %s", knowledge.get("status", "unknown"))

    # Step 3: Verify IPFS Persistence
    ipfs = await step_verify_ipfs_persistence()
    logger.info("Step 3 result: %s", ipfs.get("status", "unknown"))

    # Step 4: Generate Report
    report = generate_swarm_report(discovery, knowledge, ipfs)

    logger.info("")
    logger.info("=" * 60)
    logger.info("  SWARM STATUS REPORT")
    logger.info("=" * 60)
    logger.info("  Knowledge Level:        %s (%d entries)",
                 report["swarm_intelligence"]["knowledge_level"],
                 report["swarm_intelligence"]["knowledge_entries"])
    logger.info("  Constitutional Grade:   %s (score: %d/100)",
                 report["swarm_intelligence"]["constitutional_grade"],
                 report["swarm_intelligence"]["constitutional_integrity_score"])
    logger.info("  Peers:                  %d/%d alive",
                 report["global_peer_connectivity"]["peers_alive"],
                 report["global_peer_connectivity"]["peers_total"])
    logger.info("  Avg Latency:            %.1fms",
                 report["global_peer_connectivity"]["average_latency_ms"])
    logger.info("  Bootstraps Reachable:   %d/%d",
                 report["global_peer_connectivity"]["bootstrap_nodes_reachable"],
                 report["global_peer_connectivity"]["bootstrap_nodes_total"])
    logger.info("  IPFS:                   %s",
                 report["ipfs_persistence"]["status"])
    logger.info("=" * 60)

    # Save final state
    try:
        state = {
            "last_gsi_run": time.time(),
            "report_id": report["report_id"],
            "overall_score": report["swarm_intelligence"]["constitutional_integrity_score"],
        }
        STATE_FILE.write_text(json.dumps(state, indent=2), encoding="utf-8")
    except Exception:
        pass

    return 0


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
