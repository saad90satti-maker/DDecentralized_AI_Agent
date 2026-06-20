"""
Swarm node entrypoint for Docker.
Connects to SEED_PEER if provided, writes status to /shared/status.json
"""
import asyncio
import json
import logging
import os
import signal
import sys
import time
from pathlib import Path

sys.path.insert(0, "/app")
from ghost_swarm import GhostSwarmNode, SwarmMessage

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)
logger = logging.getLogger("swarm-entry")

NODE_ID = os.getenv("NODE_ID", f"ghost-docker-{os.getpid()}")
SWARM_PORT = int(os.getenv("SWARM_PORT", "9876"))
SEED_PEER = os.getenv("SEED_PEER", "")
ENABLE_DHT = os.getenv("ENABLE_DHT", "0") == "1"


async def discover_seed(node: GhostSwarmNode, seed: str):
    """Connect to seed peer and exchange mesh_join handshake."""
    host, _, port_str = seed.partition(":")
    port = int(port_str) if port_str else SWARM_PORT

    logger.info("Attempting seed discovery: %s:%d", host, port)

    for attempt in range(15):
        try:
            r, w = await asyncio.wait_for(
                asyncio.open_connection(host, port), timeout=5
            )
            msg = SwarmMessage("mesh_join", node.node_id, {
                "port": node.port, "mode": node._ghost_mode
            })
            msg.sign(node._secret)
            w.write(msg.encode())
            await w.drain()

            resp_data = await asyncio.wait_for(r.readline(), timeout=5)
            w.close()

            resp = SwarmMessage.decode(resp_data)
            if resp:
                node.add_peer(host, port, resp.sender_id,
                              capabilities=["mesh"], version=resp.payload.get("mode", "?"))
                logger.info("Seed peer %s added to routing table", resp.sender_id)

                known_peers = resp.payload.get("peers", [])
                if known_peers:
                    logger.info("Seed shared %d additional peers", len(known_peers))
                return True
        except asyncio.TimeoutError:
            logger.warning("Seed attempt %d/15 timed out", attempt + 1)
        except (ConnectionRefusedError, OSError) as e:
            logger.warning("Seed attempt %d/15: %s", attempt + 1, e)
        except Exception as e:
            logger.warning("Seed attempt %d/15: %s", attempt + 1, e)

        await asyncio.sleep(2)

    logger.error("Could not connect to seed peer %s:%d after 15 attempts", host, port)
    return False


async def write_status(node: GhostSwarmNode):
    """Periodically write node status to shared file."""
    while True:
        await asyncio.sleep(5)
        try:
            status = node.status
            status["timestamp"] = time.time()
            peers_info = []
            for pid, p in node.peers.items():
                peers_info.append({
                    "node_id": pid,
                    "host": p.host,
                    "port": p.port,
                    "alive": p.is_alive,
                    "last_seen": p.last_seen,
                    "capabilities": p.capabilities,
                    "version": p.version,
                })
            status["peers"] = peers_info
            safe_id = node.node_id.replace(" ", "_").replace(":", "_")
            Path(f"/shared/status_{safe_id}.json").write_text(
                json.dumps(status, indent=2, default=str)
            )
        except Exception:
            pass


async def main():
    logger.info("Starting swarm node: %s on port %d", NODE_ID, SWARM_PORT)

    node = GhostSwarmNode(
        node_id=NODE_ID,
        port=SWARM_PORT,
        enable_dht=ENABLE_DHT,
    )

    await node.start()
    logger.info("Swarm node listening on TCP :%d", SWARM_PORT)

    asyncio.create_task(write_status(node))

    if SEED_PEER:
        await discover_seed(node, SEED_PEER)

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

    logger.info("Node %s ready. Peer count: %d", node.node_id, len(node.peers))
    await stop_event.wait()
    await node.stop()


if __name__ == "__main__":
    asyncio.run(main())
