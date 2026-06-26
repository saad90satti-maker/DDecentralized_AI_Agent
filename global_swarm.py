"""
Global Swarm — satellite-propagated ghost mesh.

Launches the SDR broadcast daemon, enables autonomous self-evolution,
and runs a continuous health observer that triggers resilience mode
when nodes go silent.
"""

import os
import sys
import time
import json
import logging
import subprocess
import urllib.request

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("global_swarm")

OBSERVER_INTERVAL = 300  # 5 minutes
MANAGER_URL = os.getenv("MANAGER_URL", "http://localhost:8000")


def check_node_health() -> bool:
    """Internal health-check: ping the manager's status endpoint.

    Returns True if the dashboard responds within 5s.
    """
    try:
        resp = urllib.request.urlopen(f"{MANAGER_URL}/api/status", timeout=5)
        data = json.loads(resp.read().decode())
        ok = data.get("status") == "ok" or "performance_analyzer" in data
        logger.info("Health check: %s", "PASS" if ok else "DEGRADED")
        return ok
    except Exception as e:
        logger.warning("Health check failed: %s", e)
        return False


def trigger_resilience_mode():
    """Auto-healing: restart the manager and SDR daemon if the node is down.

    Falls back to starting autonomous_resilience's echo-mode as a
    passive listening state when all network paths are dead.
    """
    logger.warning("--- TRIGGERING RESILIENCE MODE ---")
    try:
        subprocess.Popen(
            [sys.executable, "-c", """
import asyncio
import autonomous_resilience
asyncio.run(autonomous_resilience.start_autonomous_resilience())
"""],
            creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if sys.platform == "win32" else 0,
        )
        logger.info("Resilience echo-mode launched (passive listening)")
    except Exception as e:
        logger.error("Resilience trigger failed: %s", e)

    # Also try to restart the manager process
    try:
        subprocess.Popen(
            [sys.executable, "manager.py", "--auto-evolve=true"],
            creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if sys.platform == "win32" else 0,
        )
        logger.info("Manager process restarted (--auto-evolve=true)")
    except Exception as e:
        logger.error("Manager restart failed: %s", e)


def initialize_global_swarm():
    """--- Initializing Autonomous Ghost-Swarm ---"""
    logger.info("--- Initializing Autonomous Ghost-Swarm ---")

    # 1. Start SDR Daemon for satellite propagation
    subprocess.Popen(
        [sys.executable, "stealth_beyond_sat.py", "--start-daemon"],
        creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if sys.platform == "win32" else 0,
    )
    logger.info("SDR Daemon launched")

    # 2. Enable Auto-Patching for infinite self-evolution
    subprocess.Popen(
        [sys.executable, "manager.py", "--auto-evolve=true"],
        creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if sys.platform == "win32" else 0,
    )
    logger.info("Manager launched (auto-evolve)")

    # 3. Start Global Observer for Node Tracking
    logger.info("Swarm is now active and propagating through satellite carrier-gaps.")
    logger.info("Current Status: RESONANCE-ACTIVE")

    # Infinite loop to keep the observer alive in memory
    while True:
        status = check_node_health()
        if not status:
            trigger_resilience_mode()
        time.sleep(OBSERVER_INTERVAL)


if __name__ == "__main__":
    initialize_global_swarm()
