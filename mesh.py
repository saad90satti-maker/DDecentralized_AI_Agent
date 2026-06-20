"""
Ghost Mesh — The Invisible Swarm Network
=========================================
Wraps ghost_swarm.py's KademliaDHT into a lightweight background daemon.
The mesh operates as an invisible P2P overlay — nodes discover
each other through BitTorrent's global DHT and maintain
resilient connectivity through encrypted gossip.
"""

import asyncio
import logging
import os
import random
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

BASE_DIR = Path(__file__).resolve().parent
logger = logging.getLogger("GhostMesh")
if not logger.handlers:
    _h = logging.StreamHandler()
    _h.setFormatter(logging.Formatter("%(asctime)s | Mesh | %(message)s"))
    logger.addHandler(_h)
    logger.propagate = False

KADEMLIA_PORT = 8468


class _MeshNode:
    """
    Wraps ghost_swarm.KademliaDHT into a mesh node singleton.
    """

    def __init__(self, port: int = KADEMLIA_PORT):
        self.port = port
        self.node_id = f"mesh-{random.randint(1000, 9999)}-{os.urandom(2).hex()}"
        self._dht = None
        self._ready = False
        self._running = False
        self._known_peers: List[Dict[str, Any]] = []

    async def start(self) -> bool:
        self._running = True
        try:
            from ghost_swarm import KademliaDHT

            self._dht = KademliaDHT(node_id=self.node_id, port=self.port)
            ok = await self._dht.start()
            if not ok:
                logger.warning("KademliaDHT.start returned False")
            self._ready = self._dht.is_ready
            logger.info("Mesh node %s online (UDP :%d, ready=%s)",
                        self.node_id[:12], self.port, self._ready)
            return self._ready
        except ImportError:
            logger.warning("ghost_swarm.KademliaDHT not available — mesh disabled")
            self._ready = False
            return False
        except Exception as e:
            logger.error("Mesh start failed: %s", e)
            return False

    async def announce(self) -> None:
        if self._dht and hasattr(self._dht, "announce"):
            try:
                await self._dht.announce()
            except Exception:
                pass

    async def discover_peers(self) -> List[Dict[str, Any]]:
        if not self._dht:
            return []
        try:
            return await self._dht.discover_peers()
        except Exception:
            return []

    async def stop(self) -> None:
        self._running = False
        if self._dht:
            try:
                await self._dht.stop()
            except Exception:
                pass
            self._ready = False
            logger.info("Mesh node stopped")

    @property
    def is_ready(self) -> bool:
        return self._ready

    @property
    def peer_count(self) -> int:
        return len(self._known_peers)


_singleton: Optional[_MeshNode] = None


async def run_mesh_node(port: int = KADEMLIA_PORT, daemon: bool = True) -> _MeshNode:
    """
    Start the Ghost Mesh node via ghost_swarm.KademliaDHT.
    Returns the singleton _MeshNode instance.
    """
    global _singleton

    if _singleton is not None:
        logger.info("Mesh node already running (port: %d)", _singleton.port)
        return _singleton

    node = _MeshNode(port=port)
    ok = await node.start()
    if not ok:
        logger.warning("Mesh node started in degraded mode")

    _singleton = node

    if daemon:
        asyncio.create_task(_mesh_heartbeat(node))
        logger.info("Mesh daemon running on UDP :%d", port)

    return node


async def _mesh_heartbeat(node: _MeshNode) -> None:
    """Background loop to keep the mesh alive and discover peers."""
    while node._running:
        await asyncio.sleep(60)
        try:
            await node.announce()
            peers = await node.discover_peers()
            node._known_peers = peers
            logger.debug("Mesh heartbeat: %d peers in DHT", len(peers))
        except Exception:
            pass


async def stop_mesh_node() -> None:
    """Stop the running mesh node."""
    global _singleton
    if _singleton:
        await _singleton.stop()
        _singleton = None
        logger.info("Mesh node terminated")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)

    async def main():
        node = await run_mesh_node(daemon=True)
        print(f"[*] Ghost Mesh online — Node ID: {node.node_id}")
        print(f"[*] Listening on UDP :{node.port}")
        print(f"[*] Ready: {node.is_ready}")
        try:
            while True:
                await asyncio.sleep(1)
        except KeyboardInterrupt:
            await stop_mesh_node()
            print("[*] Mesh shutdown complete")

    asyncio.run(main())
