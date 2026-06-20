"""
Public Global Node — Join the Ghost Engine P2P Network.

Run this script on any machine with Python 3.11+:
    python run_public_node.py

What happens:
  1. Generates a persistent Ed25519 identity (saved to node_identity.json)
  2. Bootstraps into the global BitTorrent Mainline DHT
  3. Announces itself via the 'ghost_peers_v3' DHT key
  4. Connects to discovered peers over encrypted P2P channels
  5. Registers task handlers for shared distributed execution
  6. Processes tasks from the swarm autonomously

Security:
  - All P2P messages are signed with Ed25519 (your node_identity.json is your key)
  - Task payloads are encrypted with ChaCha20-Poly1305 per-peer
  - Your private key never leaves your machine
"""

import argparse
import asyncio
import json
import logging
import os
import signal
import sys
import time
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)
logger = logging.getLogger("public-node")

sys.path.insert(0, str(Path(__file__).resolve().parent))

from ghost_compute import ComputeMaster, TaskStore
from ghost_swarm import GhostSwarmNode, LaunchSequence, SwarmMessage
from node_identity import NodeIdentity


# =============================================================================
# Task Handlers
# =============================================================================

async def handle_echo(payload: dict) -> dict:
    """Echo task — returns what it receives."""
    logger.info("Echo task: %s", payload)
    return {"echo": payload.get("message", ""), "status": "ok"}


async def handle_shell(payload: dict) -> dict:
    """Shell command execution task."""
    import subprocess
    cmd = payload.get("command", "")
    if not cmd:
        return {"error": "no command", "status": "failed"}
    try:
        result = subprocess.run(cmd, shell=True, capture_output=True,
                                text=True, timeout=int(payload.get("timeout", 30)))
        return {
            "stdout": result.stdout.strip(),
            "stderr": result.stderr.strip(),
            "returncode": result.returncode,
            "status": "ok" if result.returncode == 0 else "failed",
        }
    except subprocess.TimeoutExpired:
        return {"error": "timeout", "status": "failed"}
    except Exception as e:
        return {"error": str(e), "status": "failed"}


async def handle_ping(_payload: dict) -> dict:
    """Ping — health check."""
    return {"pong": True, "time": time.time()}


# =============================================================================
# Encrypted swarm task handler (bridges swarm tasks to compute worker)
# =============================================================================

class PublicNode:
    """
    Orchestrates the full public node lifecycle:
      identity → swarm → compute → tasks
    """

    def __init__(self, identity: NodeIdentity, port: int = 9876,
                 enable_dht: bool = True, host: str = "0.0.0.0"):
        self.identity = identity
        self.port = port
        self.enable_dht = enable_dht
        self.host = host

        # Compute infrastructure
        self.task_store = TaskStore()
        self.compute = ComputeMaster(store=self.task_store)
        self._registered_handlers = False

        # Swarm node (created in start())
        self.swarm: Optional[GhostSwarmNode] = None
        self._running = False

    async def start(self):
        self._running = True

        logger.info("=" * 60)
        logger.info("  Public Global Node — Ghost Engine")
        logger.info("  Node ID: %s", self.identity.node_id)
        logger.info("  Pubkey:  %s", self.identity.public_key_hex()[:32])
        logger.info("=" * 60)

        self.swarm = GhostSwarmNode(
            node_id=self.identity.node_id,
            port=self.port,
            enable_dht=self.enable_dht,
            identity=self.identity,
            task_handler=self._on_swarm_task,
        )
        await self.swarm.start()
        logger.info("Swarm node listening on TCP :%d", self.port)

        launch = LaunchSequence(self.swarm)
        await launch.execute()

        # Register compute task handlers
        self._register_handlers()

        # Log identity info
        ident_file = Path("node_identity.json")
        if ident_file.exists():
            logger.info("Identity file: %s (KEEP THIS SAFE — it is your node key)", ident_file.resolve())

        logger.info("Node ready. Waiting for tasks from the swarm...")

    def _register_handlers(self):
        self.compute.start_worker(num_workers=2)
        self.compute._workers.get(next(iter(self.compute._workers)), None)
        for wid, worker in self.compute._workers.items():
            worker.register("echo", handle_echo)
            worker.register("shell", handle_shell)
            worker.register("ping", handle_ping)
        logger.info("Registered %d task handlers across %d workers",
                     3, len(self.compute._workers))

    async def _on_swarm_task(self, msg: SwarmMessage):
        """Bridge a P2P swarm task into the compute worker."""
        logger.info("Received swarm task: type=%s from=%s", msg.msg_type, msg.sender_id)
        if msg.msg_type != "task":
            return

        payload = msg.payload
        if msg.encrypted and self.identity:
            decrypted = self.swarm.decrypt_task_payload(msg, msg.sender_pubkey)
            if decrypted is None:
                logger.warning("Failed to decrypt task payload from %s", msg.sender_id)
                return
            payload = decrypted

        command = payload.get("command", "")
        task_type = payload.get("task_type", "shell")
        task_id = self.compute.submit(
            task_type=task_type,
            payload={"command": command, **payload},
            timeout=float(payload.get("timeout", 120)),
        )
        logger.info("Task %s submitted to compute worker (type=%s)", task_id, task_type)

    async def run_compute(self):
        """Run compute workers until stopped."""
        await self.compute.run_workers()

    async def stop(self):
        self._running = False
        if self.swarm:
            await self.swarm.stop()
        logger.info("Public node stopped")


async def main():
    parser = argparse.ArgumentParser(description="Ghost Engine Public Global Node")
    parser.add_argument("--port", type=int, default=int(os.getenv("SWARM_PORT", "9876")),
                        help="P2P swarm TCP port")
    parser.add_argument("--no-dht", action="store_true",
                        help="Disable DHT bootstrap (LAN-only mode)")
    parser.add_argument("--identity", type=str, default="node_identity.json",
                        help="Path to node identity file")
    parser.add_argument("--http-port", type=int, default=0,
                        help="Optional HTTP health endpoint port (0 = disabled)")
    args = parser.parse_args()

    identity = NodeIdentity.load_or_create(Path(args.identity))
    logger.info("Loaded identity: %s", identity.node_id)

    node = PublicNode(
        identity=identity,
        port=args.port,
        enable_dht=not args.no_dht,
    )

    try:
        await node.start()

        stop_event = asyncio.Event()

        def shutdown():
            logger.info("Shutting down...")
            stop_event.set()

        loop = asyncio.get_event_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                loop.add_signal_handler(sig, shutdown)
            except NotImplementedError:
                pass

        compute_task = asyncio.create_task(node.run_compute())
        await stop_event.wait()
        compute_task.cancel()
    except KeyboardInterrupt:
        pass
    finally:
        await node.stop()

    logger.info("Public node exited. Goodbye.")


if __name__ == "__main__":
    asyncio.run(main())
