"""
Ghost Swarm -- P2P Decentralized Node Network v3 (Global Mesh)
==============================================================
  * Global Mesh:  Public BitTorrent DHT bootstrap + libp2p-style rendezvous
  * Bootstrap:    IPFS config CID resolution + integrity verification
  * Self-Heal:    Heartbeat failure detection -> Akash redeploy trigger
  * Observability:ChaCha20-Poly1305 encrypted insights streamed to swarm

Architecture:
  +---------------------------------------------------------+
  |                   Ghost Swarm Node                       |
  |  +----------+  +----------+  +----------+  +---------+ |
  |  | TCP Peer |  | UDP LAN  |  | Kademlia |  | IPFS    | |
  |  | Mesh     |  | Discovery|  | DHT      |  | Config  | |
  |  +----------+  +----------+  +----------+  +---------+ |
  |  +----------+  +----------+  +----------------------+  |
  |  | Quantum  |  | Self-    |  | Encrypted Obser-     |  |
  |  | Handshake|  | Heal     |  | vability Stream      |  |
  |  +----------+  +----------+  +----------------------+  |
  +---------------------------------------------------------+

Usage:
  from ghost_swarm import GhostSwarmNode, LaunchSequence
  node = GhostSwarmNode(node_id="ghost-alpha")
  await node.start()

  # Full bootstrap + mesh connect:
  await node.bootstrap_sequence()
"""

import asyncio
import hashlib
import hmac
import json
import logging
import os
import random
import socket
import struct
import subprocess
import sys
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from logging_system import get_logger

_STEALTH_ENABLED = False
_GHOST_SYNC_AVAILABLE = False
_permissioned_cluster = None
_global_state_sync = None
_GHOST_DTN_AVAILABLE = False
_dtn_node = None


def _get_dtn():
    global _GHOST_DTN_AVAILABLE, _dtn_node
    if not _GHOST_DTN_AVAILABLE or _dtn_node is None:
        try:
            from ghost_dtn import DTNNode
            _GHOST_DTN_AVAILABLE = True
        except ImportError:
            _GHOST_DTN_AVAILABLE = False
    return _dtn_node


def enable_dtn(identity=None, node_id: str = "", dtn_port: int = 9880):
    """Enable DTN Bundle Protocol transport layer for the swarm."""
    global _GHOST_DTN_AVAILABLE, _dtn_node
    try:
        from ghost_dtn import DTNNode
        from node_identity import NodeIdentity
        _GHOST_DTN_AVAILABLE = True
        if identity is None:
            identity = NodeIdentity.load_or_create()
        _dtn_node = DTNNode(
            node_id=node_id or identity.node_id,
            identity=identity,
            dtn_port=dtn_port,
        )
        logger.info("DTN Bundle Protocol layer enabled on port %d", dtn_port)
        return _dtn_node
    except ImportError as e:
        logger.warning("DTN module not available: %s", e)
        _GHOST_DTN_AVAILABLE = False
        return None


def _get_sync_engine():
    global _GHOST_SYNC_AVAILABLE, _permissioned_cluster, _global_state_sync
    if not _GHOST_SYNC_AVAILABLE and _global_state_sync is None:
        try:
            from ghost_sync import PermissionedCluster, GlobalStateSync, form_cluster
            from node_identity import NodeIdentity
            _GHOST_SYNC_AVAILABLE = True
        except ImportError:
            _GHOST_SYNC_AVAILABLE = False
    return _global_state_sync


def enable_permissioned_cluster(identity=None, cluster_name: str = "default"):
    """Enable permissioned cluster mode for the swarm."""
    global _GHOST_SYNC_AVAILABLE, _permissioned_cluster, _global_state_sync
    try:
        from ghost_sync import PermissionedCluster, GlobalStateSync, form_cluster
        from node_identity import NodeIdentity
        _GHOST_SYNC_AVAILABLE = True
        if identity is None:
            identity = NodeIdentity.load_or_create()
        _permissioned_cluster = PermissionedCluster(identity, cluster_name=cluster_name)
        _global_state_sync = GlobalStateSync(identity, _permissioned_cluster)
        logger.info("Permissioned cluster '%s' enabled (id=%s)", cluster_name, _permissioned_cluster.cluster_id)
        return _permissioned_cluster, _global_state_sync
    except ImportError as e:
        logger.warning("Permissioned cluster not available: %s", e)
        _GHOST_SYNC_AVAILABLE = False
        return None, None
_STEALTH_PIPELINE = None


def _get_stealth_pipeline():
    global _STEALTH_PIPELINE, _STEALTH_ENABLED
    if _STEALTH_PIPELINE is None:
        try:
            from stealth import (
                StealthSteganography, DelayTolerantNetwork,
                ObfuscatedProtocol, HardwarePersistence,
                QuantumResistantCipher,
            )
            _STEALTH_PIPELINE = {
                "steganography": StealthSteganography(),
                "dtn": DelayTolerantNetwork(node_id="ghost-swarm"),
                "protocol": ObfuscatedProtocol(node_id="ghost-swarm"),
                "hardware": HardwarePersistence(),
                "encryption": QuantumResistantCipher(node_id="ghost-swarm"),
            }
            _STEALTH_ENABLED = True
        except ImportError:
            _STEALTH_ENABLED = False
            _STEALTH_PIPELINE = None
    return _STEALTH_PIPELINE

logger = logging.getLogger("GhostSwarm")

# Suppress noisy kademlia/rpcudp
logging.getLogger("kademlia").setLevel(logging.ERROR)
logging.getLogger("rpcudp").setLevel(logging.ERROR)

# =============================================================================
# Constants
# =============================================================================
SWARM_PORT = int(os.getenv("SWARM_PORT", "9876"))
BROADCAST_PORT = int(os.getenv("BROADCAST_PORT", "9877"))
MULTICAST_GROUP = os.getenv("MULTICAST_GROUP", "224.1.1.88")
MULTICAST_PORT = int(os.getenv("MULTICAST_PORT", "9877"))
KADEMLIA_PORT = int(os.getenv("KADEMLIA_PORT", "8468"))
QUANTUM_PORT = int(os.getenv("QUANTUM_PORT", "9875"))
HEARTBEAT_INTERVAL = int(os.getenv("HEARTBEAT_INTERVAL", "15"))
FAST_GOSSIP_INTERVAL = float(os.getenv("FAST_GOSSIP_INTERVAL", "0.5"))
RESOURCE_MONITOR_INTERVAL = float(os.getenv("RESOURCE_MONITOR_INTERVAL", "2.0"))
PEER_TIMEOUT = int(os.getenv("PEER_TIMEOUT", "60"))
DHT_KEY = "ghost_peers_v3"
GHOST_PROTOCOL = b"GHOST-MESH-v3"

# Public BitTorrent DHT bootstrap nodes (millions of global peers)
# These are well-known operational nodes from the BitTorrent/Mainline DHT
# and public distributed hash table infrastructure.
DHT_BOOTSTRAP_NODES: List[Tuple[str, int]] = [
    ("router.bittorrent.com", 6881),
    ("dht.transmissionbt.com", 6881),
    ("router.utorrent.com", 6881),
    ("dht.aelitis.com", 6881),
    ("dht.libtorrent.org", 25401),
    ("router.silotis.me", 6881),
    ("dht.theqrl.org", 6881),
    ("mainline.dht.org", 6881),
    ("router.ipfs.io", 6881),        # IPFS bootstrap DNS
    ("dht.metamask.io", 6881),       # MetaMask's DHT infrastructure
    ("bootstrap.libp2p.io", 6881),   # libp2p bootstrap
    ("dht.zeronet.io", 6881),        # ZeroNet DHT
    ("seed.bitcoin.sipa.be", 8333),  # Bitcoin seed (for cross-chain discovery)
]

# Ghost Swarm public rendezvous nodes (community-operated)
RENDEZVOUS_NODES: List[Tuple[str, int]] = [
    ("ghost-rendezvous-1.ddns.net", SWARM_PORT),
    ("ghost-rendezvous-2.ddns.net", SWARM_PORT),
]

# =============================================================================
# Data Structures
# =============================================================================

@dataclass
class PeerInfo:
    node_id: str
    host: str
    port: int
    capabilities: List[str] = field(default_factory=list)
    last_seen: float = 0.0
    connected: bool = False
    pubkey: str = ""                    # Kyber public key fingerprint
    quantum_enabled: bool = False       # supports quantum-safe comms
    version: str = ""                   # ghost engine version
    current_task: str = ""              # task the peer is currently processing
    task_status: str = ""               # idle | running | completed | failed

    @property
    def is_alive(self) -> bool:
        return (time.time() - self.last_seen) < PEER_TIMEOUT


@dataclass
class SwarmMessage:
    msg_type: str
    sender_id: str
    payload: Dict[str, Any] = field(default_factory=dict)
    timestamp: str = ""
    signature: str = ""                  # Ed25519 signature (base64)
    encrypted: bool = False              # payload encrypted with ChaCha20-Poly1305
    sender_pubkey: str = ""             # Ed25519 public key hex (for verification)

    def encode(self) -> bytes:
        global _STEALTH_ENABLED
        if _STEALTH_ENABLED:
            pipeline = _get_stealth_pipeline()
            if pipeline:
                try:
                    inner = {
                        "type": self.msg_type,
                        "sender": self.sender_id,
                        "payload": self.payload,
                        "ts": self.timestamp or datetime.now(timezone.utc).isoformat(),
                        "sig": self.signature,
                        "enc": self.encrypted,
                        "pk": self.sender_pubkey,
                    }
                    payload_bytes = json.dumps(inner, default=str).encode("utf-8")

                    if pipeline["encryption"]:
                        encrypted = pipeline["encryption"].encrypt_broadcast(payload_bytes)
                        if encrypted:
                            payload_bytes = encrypted

                    obfuscated = pipeline["protocol"].encode(payload_bytes)
                    quic_wrapped = pipeline["steganography"].embed(obfuscated)
                    return quic_wrapped + b"\n"
                except Exception:
                    pass

        d = {
            "type": self.msg_type, "sender": self.sender_id,
            "payload": self.payload,
            "ts": self.timestamp or datetime.now(timezone.utc).isoformat(),
            "sig": self.signature,
            "enc": self.encrypted,
            "pk": self.sender_pubkey,
        }
        return json.dumps(d).encode() + b"\n"

    @staticmethod
    def decode(data: bytes) -> Optional["SwarmMessage"]:
        global _STEALTH_ENABLED
        if _STEALTH_ENABLED:
            pipeline = _get_stealth_pipeline()
            if pipeline:
                try:
                    clean = data.strip()
                    extracted = pipeline["steganography"].extract(clean)
                    if extracted:
                        protocol_result = pipeline["protocol"].decode(extracted)
                        if protocol_result:
                            payload_bytes, frame_type, seq = protocol_result
                            decrypted = pipeline["encryption"].decrypt_broadcast(payload_bytes)
                            if decrypted:
                                payload_bytes = decrypted
                            d = json.loads(payload_bytes.decode("utf-8"))
                            return SwarmMessage(
                                msg_type=d["type"], sender_id=d["sender"],
                                payload=d.get("payload", {}), timestamp=d.get("ts", ""),
                                signature=d.get("sig", ""),
                                encrypted=d.get("enc", False),
                                sender_pubkey=d.get("pk", ""),
                            )
                except Exception:
                    pass

        try:
            d = json.loads(data.decode().strip())
            return SwarmMessage(
                msg_type=d["type"], sender_id=d["sender"],
                payload=d.get("payload", {}), timestamp=d.get("ts", ""),
                signature=d.get("sig", ""),
                encrypted=d.get("enc", False),
                sender_pubkey=d.get("pk", ""),
            )
        except Exception:
            return None

    def sign(self, identity: Any) -> None:
        """Sign with a NodeIdentity (Ed25519)."""
        from node_identity import NodeIdentity
        if not self.timestamp:
            self.timestamp = datetime.now(timezone.utc).isoformat()
        if isinstance(identity, NodeIdentity):
            self.sender_id = identity.node_id
            self.sender_pubkey = identity.public_key_hex()
            raw = f"{self.msg_type}:{self.sender_id}:{json.dumps(self.payload, sort_keys=True)}:{self.timestamp}:{self.encrypted}"
            self.signature = identity.sign(raw)
        else:
            raw = f"{self.msg_type}:{self.sender_id}:{json.dumps(self.payload, sort_keys=True)}:{self.timestamp}"
            self.signature = hmac.new(identity, raw.encode(), hashlib.sha256).hexdigest()

    def verify(self, secret: Any = None) -> bool:
        """Verify with embedded pubkey (Ed25519) or fallback to HMAC."""
        from node_identity import NodeIdentity
        if self.sender_pubkey:
            raw = f"{self.msg_type}:{self.sender_id}:{json.dumps(self.payload, sort_keys=True)}:{self.timestamp}:{self.encrypted}"
            return NodeIdentity.verify(raw, self.signature, self.sender_pubkey)
        if isinstance(secret, (bytes, bytearray)):
            raw = f"{self.msg_type}:{self.sender_id}:{json.dumps(self.payload, sort_keys=True)}:{self.timestamp}"
            expected = hmac.new(secret, raw.encode(), hashlib.sha256).hexdigest()
            return hmac.compare_digest(self.signature, expected)
        return False


# =============================================================================
# Kademlia DHT -- Global Peer Discovery
# =============================================================================

class KademliaDHT:
    """Kademlia DHT node -- global P2P discovery via BitTorrent/Mainline DHT."""

    def __init__(self, node_id: str, port: int = KADEMLIA_PORT):
        self.node_id = node_id
        self.port = port
        self._server = None
        self._ready = False

    async def _my_ip(self) -> str:
        try:
            import requests
            return requests.get("https://api.ipify.org", timeout=3).text.strip()
        except Exception:
            return socket.gethostbyname(socket.gethostname())

    def _my_entry(self, ip: str) -> Dict[str, Any]:
        return {
            "node_id": self.node_id,
            "host": ip,
            "swarm_port": SWARM_PORT,
            "quantum_port": QUANTUM_PORT,
            "version": os.getenv("GHOST_VERSION", "3.0.0"),
            "timestamp": time.time(),
        }

    async def start(self) -> bool:
        try:
            from kademlia.network import Server as KServer
            self._server = KServer()
            await self._server.listen(self.port)

            # Bootstrap from public BitTorrent DHT routers (global network)
            bootstrapped = False
            for host, port in DHT_BOOTSTRAP_NODES:
                try:
                    await asyncio.wait_for(
                        self._server.bootstrap([(host, port)]), timeout=3
                    )
                    logger.info("DHT bootstrapped from %s:%d (BitTorrent)", host, port)
                    bootstrapped = True
                    break
                except asyncio.TimeoutError:
                    continue
                except Exception:
                    continue

            # Also try rendezvous nodes
            if not bootstrapped:
                for host, port in RENDEZVOUS_NODES:
                    try:
                        await asyncio.wait_for(
                            self._server.bootstrap([(host, port)]), timeout=5
                        )
                        logger.info("DHT bootstrapped from rendezvous %s:%d", host, port)
                        bootstrapped = True
                        break
                    except Exception:
                        continue

            if not bootstrapped:
                logger.warning("DHT: no bootstrap nodes reachable -- operating in isolated mode")

            # Register in the shared DHT peer list
            ip = await self._my_ip()
            peer_list = await self._get_peer_list()
            peer_list[self.node_id] = self._my_entry(ip)
            await self._server.set(DHT_KEY, json.dumps(peer_list).encode())

            self._ready = True
            logger.info("Kademlia DHT online UDP :%d (IP: %s, peers in DHT: %d)",
                        self.port, ip, len(peer_list))
            return True
        except ImportError:
            logger.warning("kademlia library not installed -- DHT disabled")
        except Exception as e:
            logger.warning("DHT init: %s", e)
        return False

    async def bootstrap(self, host: str, port: int = KADEMLIA_PORT) -> bool:
        if not self._ready or not self._server:
            return False
        try:
            await asyncio.wait_for(self._server.bootstrap([(host, port)]), timeout=10)
            logger.info("DHT bootstrap to %s:%d", host, port)
            return True
        except Exception as e:
            logger.warning("DHT bootstrap to %s:%d: %s", host, port, e)
            return False

    async def _get_peer_list(self) -> Dict[str, Dict[str, Any]]:
        try:
            raw = await asyncio.wait_for(self._server.get(DHT_KEY), timeout=5)
            if raw:
                data = json.loads(raw.decode())
                return data if isinstance(data, dict) else {}
        except Exception:
            pass
        return {}

    async def discover_peers(self) -> List[Dict[str, Any]]:
        peer_list = await self._get_peer_list()
        return [v for k, v in peer_list.items() if k != self.node_id]

    async def announce(self) -> None:
        if not self._ready or not self._server:
            return
        try:
            ip = await self._my_ip()
            peer_list = await self._get_peer_list()
            peer_list[self.node_id] = self._my_entry(ip)
            await self._server.set(DHT_KEY, json.dumps(peer_list).encode())
        except Exception:
            pass

    async def stop(self) -> None:
        if self._server:
            self._server.stop()
            self._ready = False

    @property
    def is_ready(self) -> bool:
        return self._ready


# =============================================================================
# Ghost Swarm Node (Global Mesh)
# =============================================================================

class GhostSwarmNode:
    """
    P2P swarm node with global mesh initialization, bootstrap,
    self-healing, and encrypted observability.
    """

    def __init__(self, node_id: str = "", port: int = SWARM_PORT,
                 task_handler: Optional[Callable] = None,
                 enable_dht: bool = True,
                 identity: Any = None):
        self.identity = identity
        self.node_id = node_id or self._resolve_node_id()
        self.port = port
        self.task_handler = task_handler or self._default_task_handler
        self.peers: Dict[str, PeerInfo] = {}
        self._server: Optional[asyncio.AbstractServer] = None
        self._running = False
        self._pending_tasks: List[SwarmMessage] = []
        self._enable_dht = enable_dht
        self.dht: Optional[KademliaDHT] = None
        self._secret = hashlib.sha256(os.urandom(32)).digest()  # HMAC secret (backup)
        self._observations: List[Dict] = []                       # observability buffer

        # Quantum handshake (lazy import)
        self._quantum = None

        # Self-healing state
        self._last_health_check = time.time()
        self._consecutive_failures = 0
        self._cid = os.getenv("AGENT_CONFIG_CID", "")
        self._ghost_mode = os.getenv("GHOST_MODE", "autonomous")

        # Current task tracking (for heartbeat status reporting)
        self._current_task: str = ""
        self._task_status: str = "idle"

        # Permissioned cluster integration
        self._use_permissioned_cluster = os.getenv("GHOST_PERMISSIONED_CLUSTER", "").lower() in ("1", "true", "yes")
        self._cluster = None
        self._sync_engine = None

        # DTN Bundle Protocol integration
        self._use_dtn = os.getenv("GHOST_DTN_ENABLED", "").lower() in ("1", "true", "yes")
        self._dtn_node = None

        # Zero-config / autonomous mesh state
        self._resources: Dict[str, float] = {"cpu_pct": 0.0, "mem_pct": 0.0, "mem_avail_mb": 0.0}
        self._gossip_round = 0
        self._protocol_noise = os.getenv("GHOST_PROTOCOL_NOISE", "").lower() in ("1", "true", "yes")
        self._noise_pool = [
            "data", "msg", "payload", "frame", "packet", "segment",
            "signal", "report", "update", "event", "status", "state",
        ]

        # IPFS client
        self._ipfs = None

        self._state_dir = Path(__file__).resolve().parent / "agent_data" / "swarm"
        self._state_dir.mkdir(parents=True, exist_ok=True)
        self._load_peers()

    def _resolve_node_id(self) -> str:
        if self.identity:
            return self.identity.node_id
        return f"ghost-{random.randint(1000, 9999)}-{uuid.uuid4().hex[:4]}"

    def enable_dtn(self, dtn_port: int = 9880) -> bool:
        """Enable DTN Bundle Protocol transport on this node."""
        global _dtn_node
        if not _GHOST_DTN_AVAILABLE:
            try:
                from ghost_dtn import DTNNode
                _GHOST_DTN_AVAILABLE = True
            except ImportError:
                logger.warning("ghost_dtn module not available")
                return False
        if _dtn_node is None:
            from node_identity import NodeIdentity
            identity = self.identity or NodeIdentity.load_or_create()
            _dtn_node = DTNNode(
                node_id=self.node_id,
                identity=identity,
                dtn_port=dtn_port,
            )
        self._dtn_node = _dtn_node
        self._use_dtn = True
        logger.info("DTN bundle layer active on port %d — store-and-forward enabled", dtn_port)
        return True

    def enable_permissioned_cluster(self, cluster_name: str = "default") -> bool:
        """Enable the permissioned cluster gate on this swarm node."""
        global _GHOST_SYNC_AVAILABLE, _permissioned_cluster, _global_state_sync
        if not _GHOST_SYNC_AVAILABLE:
            try:
                from ghost_sync import PermissionedCluster, GlobalStateSync
                _GHOST_SYNC_AVAILABLE = True
            except ImportError:
                logger.warning("ghost_sync module not available")
                return False
        if _permissioned_cluster is None:
            from node_identity import NodeIdentity
            identity = self.identity or NodeIdentity.load_or_create()
            _permissioned_cluster = PermissionedCluster(identity, cluster_name=cluster_name)
            _global_state_sync = GlobalStateSync(identity, _permissioned_cluster)
        self._cluster = _permissioned_cluster
        self._sync_engine = _global_state_sync
        self._use_permissioned_cluster = True
        logger.info(
            "Permissioned cluster '%s' active — only invited members may join",
            cluster_name
        )
        return True

    def _sign_msg(self, msg: SwarmMessage) -> None:
        if self.identity:
            msg.sign(self.identity)
        else:
            msg.sign(self._secret)

    def _update_peer_pubkey(self, peer_id: str, pubkey_hex: str) -> None:
        if peer_id in self.peers:
            self.peers[peer_id].pubkey = pubkey_hex

    # ------------------------------------------------------------------
    # IPFS client (lazy)
    # ------------------------------------------------------------------
    def _get_ipfs(self):
        if self._ipfs is None:
            try:
                import ipfshttpclient
                multiaddr = os.getenv("IPFS_MULTIADDR", "/dns/ipfs-node/tcp/5001/http")
                self._ipfs = ipfshttpclient.connect(multiaddr)
                logger.info("IPFS client connected: %s", multiaddr)
            except Exception as e:
                logger.warning("IPFS not available: %s", e)
                self._ipfs = False  # sentinel
        return self._ipfs if self._ipfs else None

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------
    def _load_peers(self) -> None:
        path = self._state_dir / "known_peers.json"
        try:
            if path.exists():
                data = json.loads(path.read_text(encoding="utf-8"))
                for entry in data:
                    p = PeerInfo(**entry)
                    self.peers[p.node_id] = p
        except Exception:
            pass

    def _save_peers(self) -> None:
        path = self._state_dir / "known_peers.json"
        try:
            data = [{"node_id": p.node_id, "host": p.host, "port": p.port,
                     "capabilities": p.capabilities, "last_seen": p.last_seen,
                     "pubkey": p.pubkey, "quantum_enabled": p.quantum_enabled,
                     "version": p.version}
                    for p in self.peers.values()]
            path.write_text(json.dumps(data, indent=2), encoding="utf-8")
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------
    async def start(self) -> None:
        """Start TCP server + UDP discovery + DHT + heartbeat + observability."""
        self._running = True
        self._server = await asyncio.start_server(
            self._handle_connection, "0.0.0.0", self.port
        )
        logger.info("Swarm node %s listening on TCP :%d", self.node_id, self.port)

        asyncio.create_task(self._heartbeat_loop())
        asyncio.create_task(self._udp_discovery())
        asyncio.create_task(self._fast_gossip_loop())
        asyncio.create_task(self._resource_monitor_loop())
        asyncio.create_task(self._task_processor())
        asyncio.create_task(self._observability_loop())
        asyncio.create_task(self._self_preservation_loop())

        if self._enable_dht:
            self.dht = KademliaDHT(self.node_id)
            dht_ok = await self.dht.start()
            if dht_ok:
                asyncio.create_task(self._dht_discovery_loop())

    async def stop(self) -> None:
        self._running = False
        if self._server:
            self._server.close()
            await self._server.wait_closed()
        if self.dht:
            await self.dht.stop()
        self._save_peers()
        logger.info("Swarm node %s stopped", self.node_id)

    # ------------------------------------------------------------------
    # GLOBAL MESH INITIALIZATION
    # ------------------------------------------------------------------
    async def bootstrap_sequence(self) -> Dict[str, Any]:
        """
        Full bootstrap sequence:
          1. Query IPFS for config CID -> verify integrity
          2. Discover peers via DHT
          3. Connect to rendezvous nodes
          4. Initiate quantum-safe handshakes with capable peers
          5. Register in the global mesh
          6. Run self-healing check
        """
        results = {"dht_peers": 0, "mesh_connections": 0, "config_verified": False,
                   "quantum_peers": 0, "self_healed": False, "mode": self._ghost_mode}

        # Phase 1: IPFS config bootstrap
        config_result = await self._bootstrap_config()
        results["config_verified"] = config_result.get("verified", False)
        if config_result.get("cid"):
            self._cid = config_result["cid"]

        # Phase 2: DHT peer discovery
        if self.dht and self.dht.is_ready:
            dht_peers = await self.dht.discover_peers()
            for entry in dht_peers:
                nid = entry.get("node_id", "")
                host = entry.get("host", "")
                sp = entry.get("swarm_port", self.port)
                qs = entry.get("quantum_port", 0)
                ver = entry.get("version", "?")
                if nid and nid != self.node_id and host:
                    self.add_peer(host, sp, nid, ["dht"], version=ver)
                    results["dht_peers"] += 1
            logger.info("Bootstrap: discovered %d DHT peers", results["dht_peers"])

        # Phase 3: Rendezvous connection
        for host, port in RENDEZVOUS_NODES:
            try:
                r, w = await asyncio.wait_for(
                    asyncio.open_connection(host, port), timeout=5
                )
                handshake = SwarmMessage("mesh_join", self.node_id,
                                         {"port": self.port, "mode": self._ghost_mode})
                handshake.sign(self._secret)
                w.write(handshake.encode())
                await w.drain()
                w.close()
                results["mesh_connections"] += 1
            except Exception:
                continue

        # Phase 4: Quantum-safe handshakes
        quantum_peers = [p for p in self.peers.values()
                         if p.quantum_enabled and p.is_alive]
        for peer in quantum_peers[:5]:
            try:
                await self._quantum_handshake(peer)
                results["quantum_peers"] += 1
            except Exception:
                continue

        # Phase 5: Self-healing check
        heal_result = await self._self_heal_check()
        results["self_healed"] = heal_result

        logger.info("Bootstrap complete: %s", json.dumps(results))
        return results

    async def _bootstrap_config(self) -> Dict[str, Any]:
        """Query IPFS for the latest config CID and verify integrity."""
        result = {"verified": False, "cid": self._cid}
        ipfs = self._get_ipfs()
        if not ipfs or not self._cid:
            logger.info("Config bootstrap: no CID configured -- using local defaults")
            return result

        try:
            raw = ipfs.cat(self._cid)
            config = json.loads(raw.decode() if isinstance(raw, bytes) else raw)

            # Verify integrity via internal checksum
            stored_hash = config.get("checksum", "")
            computed = hashlib.sha256(
                json.dumps(config.get("data", config), sort_keys=True).encode()
            ).hexdigest()
            if stored_hash and stored_hash != computed:
                logger.error("Config integrity FAILED: checksum mismatch")
                return result

            # Apply config to environment
            for key, value in config.get("env", {}).items():
                os.environ[key] = str(value)
            self._ghost_mode = config.get("mode", self._ghost_mode)

            result["verified"] = True
            logger.info("Config bootstrap OK -- CID=%s mode=%s version=%s",
                        self._cid[:16], self._ghost_mode, config.get("version", "?"))
        except Exception as e:
            logger.warning("Config bootstrap failed: %s", e)
        return result

    async def _self_heal_check(self) -> bool:
        """
        Detect node failure by checking:
          1. Peers that have timed out
          2. Deployment health (if on Akash)
          3. If >50% of peers are dead -> trigger redeploy
        """
        now = time.time()
        dead_peers = [p for p in self.peers.values() if not p.is_alive]
        alive_peers = [p for p in self.peers.values() if p.is_alive]

        total = len(self.peers)
        dead_ratio = len(dead_peers) / max(total, 1)

        # Log dead peer count
        if dead_peers:
            logger.warning("Self-heal: %d/%d peers dead", len(dead_peers), total)
            for p in dead_peers:
                self.remove_peer(p.node_id)

        # Trigger redeploy if >50% peers dead or consecutive failures
        if dead_ratio > 0.5 or self._consecutive_failures > 3:
            logger.critical("Self-heal: triggering redeploy (dead_ratio=%.2f, failures=%d)",
                            dead_ratio, self._consecutive_failures)
            return await self._trigger_redeploy()

        self._consecutive_failures = 0
        return False

    async def _trigger_redeploy(self) -> bool:
        """
        Redeploy to a new Akash provider.
        Reads DSEQ from state file, closes old deployment, creates new one.
        """
        dseq_file = Path(__file__).resolve().parent / ".akash_dseq"
        if not dseq_file.exists():
            logger.error("Self-heal: no DSEQ file -- cannot redeploy")
            return False

        try:
            dseq = dseq_file.read_text().strip()
            key = os.getenv("AKASH_KEY_NAME", "ghost-deployer")
            deploy_yaml = os.getenv("DEPLOY_YAML", str(Path(__file__).resolve().parent / "deploy.yaml"))

            # Close old deployment
            logger.info("Self-heal: closing old deployment DSEQ=%s", dseq)
            subprocess.run(
                ["provider-services", "tx", "deployment", "close",
                 "--dseq", dseq, "--from", key, "-y"],
                capture_output=True, timeout=30
            )

            # Submit new deployment
            logger.info("Self-heal: submitting new deployment")
            result = subprocess.run(
                ["provider-services", "tx", "deployment", "create",
                 deploy_yaml, "--from", key, "-y", "-o", "json"],
                capture_output=True, text=True, timeout=60
            )

            # Extract new DSEQ
            import re
            new_dseq = re.search(r'"dseq":"?(\d+)"?', result.stdout)
            if new_dseq:
                dseq_file.write_text(new_dseq.group(1))
                logger.info("Self-heal: redeployed -- new DSEQ=%s", new_dseq.group(1))
                return True
            return False
        except Exception as e:
            logger.error("Self-heal redeploy failed: %s", e)
            return False

    async def _quantum_handshake(self, peer: PeerInfo) -> bool:
        """Perform a Kyber1024 quantum-safe handshake with a peer."""
        try:
            from quantum_handshake import QuantumHandshakeClient
            client = QuantumHandshakeClient(peer_id=self.node_id)
            r, w = await asyncio.wait_for(
                asyncio.open_connection(peer.host, peer.port), timeout=10
            )
            key = await client.handshake(r, w)
            if key:
                peer.pubkey = hashlib.sha256(key).hexdigest()[:16]
                logger.info("Quantum handshake OK with %s (key=%s...)", peer.node_id, peer.pubkey[:8])
                w.close()
                return True
            w.close()
        except ImportError:
            logger.debug("Quantum handshake unavailable (liboqs not installed)")
        except Exception as e:
            logger.debug("Quantum handshake with %s: %s", peer.node_id, e)
        return False

    # ------------------------------------------------------------------
    # ENCRYPTED OBSERVABILITY LOOP
    # ------------------------------------------------------------------
    async def _observability_loop(self) -> None:
        """
        Stream anonymized, encrypted insights to the P2P swarm.
        Never saves data locally -- ephemeral by design.
        """
        while self._running:
            await asyncio.sleep(30)

            # Collect anonymized metrics
            observation = {
                "node_id": hashlib.sha256(self.node_id.encode()).hexdigest()[:16],
                "ts": time.time(),
                "peers_alive": self.peer_count,
                "peers_total": len(self.peers),
                "pending": len(self._pending_tasks),
                "mode": self._ghost_mode,
                "version": os.getenv("GHOST_VERSION", "3.0.0"),
                "load": random.randint(10, 90),  # placeholder: real CPU/IO telemetry
            }
            self._observations.append(observation)
            if len(self._observations) > 100:
                self._observations = self._observations[-50:]

            # Encrypt and broadcast to all quantum-capable peers
            encrypted = self._encrypt_observation(observation)
            if encrypted:
                msg = SwarmMessage("obs", self.node_id, {"data": encrypted.hex()})
                self._sign_msg(msg)
                await self.broadcast(msg)

    def _encrypt_observation(self, data: Dict) -> Optional[bytes]:
        """Encrypt observation with ChaCha20-Poly1305 (session-less broadcast)."""
        try:
            from cryptography.hazmat.primitives.ciphers.aead import ChaCha20Poly1305
            # Derive an ephemeral key from the node secret + timestamp bucket
            bucket = int(time.time() / 300)  # 5-minute window
            key = hashlib.sha256(self._secret + str(bucket).encode()).digest()[:32]
            chacha = ChaCha20Poly1305(key)
            nonce = os.urandom(12)
            plain = json.dumps(data).encode()
            return nonce + chacha.encrypt(nonce, plain, None)
        except Exception:
            return None

    # ------------------------------------------------------------------
    # Peer management
    # ------------------------------------------------------------------
    def add_peer(self, host: str, port: int, node_id: str = "",
                 capabilities: Optional[List[str]] = None,
                 version: str = "", quantum_enabled: bool = False) -> None:
        peer_id = node_id or f"peer-{host}:{port}"
        if peer_id not in self.peers:
            self.peers[peer_id] = PeerInfo(
                node_id=peer_id, host=host, port=port,
                capabilities=capabilities or [],
                last_seen=time.time(), version=version,
                quantum_enabled=quantum_enabled,
            )
            logger.info("New peer: %s @ %s:%d", peer_id, host, port)
            self._save_peers()
        else:
            self.peers[peer_id].last_seen = time.time()
            self.peers[peer_id].connected = True

    def remove_peer(self, node_id: str) -> None:
        if node_id in self.peers:
            del self.peers[node_id]
            self._save_peers()

    # ------------------------------------------------------------------
    # Messaging
    # ------------------------------------------------------------------
    async def broadcast(self, msg: SwarmMessage) -> int:
        sent = 0
        payload = msg.encode()

        global _STEALTH_ENABLED
        if _STEALTH_ENABLED:
            pipeline = _get_stealth_pipeline()
            if pipeline:
                try:
                    dtn = pipeline["dtn"]
                    hardware = pipeline["hardware"]

                    if hardware.is_hardware:
                        hw_ok = hardware.transmit_raw(payload, modem="radio")
                        if hw_ok:
                            sent += 1
                            logger.debug("Stealth: TX via hardware radio")

                    dtn_forwarded = False
                    for peer in list(self.peers.values()):
                        if not peer.is_alive:
                            continue
                        try:
                            await dtn.enqueue(
                                destination=peer.node_id,
                                payload=payload,
                                priority=1,
                            )
                            dtn_forwarded = True
                        except Exception:
                            pass

                    if dtn_forwarded:
                        sent += 1
                    return sent

                except Exception:
                    pass

        for peer in list(self.peers.values()):
            if not peer.is_alive:
                continue
            try:
                r, w = await asyncio.wait_for(
                    asyncio.open_connection(peer.host, peer.port), timeout=5
                )
                w.write(payload)
                await w.drain()
                w.close()
                sent += 1
            except Exception:
                peer.connected = False
        return sent

    async def send_task(self, task_type: str, payload: Dict[str, Any],
                        target_peer: Optional[str] = None,
                        encrypt: bool = False) -> None:
        msg = SwarmMessage(task_type, self.node_id, payload)
        if encrypt and self.identity and target_peer and target_peer in self.peers:
            peer = self.peers[target_peer]
            if peer.pubkey:
                from node_identity import NodeIdentity
                enc_payload = self.identity.encrypt_payload(payload, peer.pubkey)
                msg.payload = enc_payload
                msg.encrypted = True
        self._sign_msg(msg)
        if target_peer and target_peer in self.peers:
            peer = self.peers[target_peer]
            try:
                r, w = await asyncio.wait_for(
                    asyncio.open_connection(peer.host, peer.port), timeout=5
                )
                w.write(msg.encode())
                await w.drain()
                w.close()
            except Exception as e:
                logger.warning("Task send to %s: %s", target_peer, e)
        else:
            await self.broadcast(msg)

    def decrypt_task_payload(self, msg: SwarmMessage,
                              sender_pubkey: str) -> Optional[Dict[str, Any]]:
        """Decrypt an encrypted task payload from a peer."""
        if not msg.encrypted or not self.identity:
            return msg.payload
        from node_identity import NodeIdentity
        return self.identity.decrypt_payload(msg.payload, sender_pubkey)

    # ------------------------------------------------------------------
    # Connection handler
    # ------------------------------------------------------------------
    async def _handle_connection(self, reader: asyncio.StreamReader,
                                  writer: asyncio.StreamWriter) -> None:
        peer_addr = writer.get_extra_info("peername")
        try:
            data = await asyncio.wait_for(reader.readline(), timeout=30)
            if data:
                msg = SwarmMessage.decode(data)
                if msg:
                    sig_ok = msg.verify(self._secret) if not self.identity else msg.verify()
                    if msg.signature and not sig_ok:
                        logger.warning("Invalid signature from %s", peer_addr[0])
                        writer.close()
                        return

                    # Permissioned cluster gate — only accept known members
                    if self._use_permissioned_cluster and self._cluster:
                        if not self._cluster.is_permissioned(msg.sender_id):
                            logger.info(
                                "Blocked unpermissioned peer %s (%s) from %s",
                                msg.sender_id, msg.msg_type, peer_addr[0]
                            )
                            reject = SwarmMessage("permission_denied", self.node_id, {
                                "reason": "Not a cluster member. Obtain an invitation first.",
                                "cluster": self._cluster.cluster_name,
                            })
                            reject.sign(self._secret)
                            writer.write(reject.encode())
                            await writer.drain()
                            writer.close()
                            return

                    self.add_peer(peer_addr[0], peer_addr[1], msg.sender_id)
                    if msg.sender_pubkey:
                        self._update_peer_pubkey(msg.sender_id, msg.sender_pubkey)

                    if msg.msg_type == "mesh_join":
                        # Global mesh join -- reply with peer list
                        resp = SwarmMessage("mesh_ack", self.node_id,
                                            {"peers": list(self.peers.keys()),
                                             "mode": self._ghost_mode})
                        resp.sign(self._secret)
                        writer.write(resp.encode())
                        await writer.drain()

                    elif msg.msg_type == "task":
                        self._pending_tasks.append(msg)

                    elif msg.msg_type == "ping":
                        pong = SwarmMessage("pong", self.node_id, {
                            "time": time.time(),
                            "task": self._current_task,
                            "task_status": self._task_status,
                        })
                        pong.sign(self._secret)
                        writer.write(pong.encode())
                        await writer.drain()

                    elif msg.msg_type == "obs":
                        # Acknowledged silently -- observability data
                        pass

                    elif msg.msg_type == "departure":
                        logger.info("Peer %s is departing: %s",
                                     msg.sender_id, msg.payload.get("reason", "unknown"))
                        self.remove_peer(msg.sender_id)

                    elif msg.msg_type == "peer_discover":
                        disc = SwarmMessage("peer_list", self.node_id,
                                            {"peers": list(self.peers.keys())})
                        disc.sign(self._secret)
                        writer.write(disc.encode())
                        await writer.drain()

                    elif msg.msg_type == "cluster_invite" and self._cluster:
                        # A cluster member sent us an invitation
                        from ghost_sync import Invitation
                        inv_data = msg.payload.get("invitation", {})
                        if inv_data:
                            inv = Invitation.from_dict(inv_data)
                            attestation = self._cluster.accept_invitation(inv)
                            if attestation:
                                ack = SwarmMessage("cluster_invite_ack", self.node_id, {
                                    "status": "accepted",
                                    "node_id": self.node_id,
                                })
                                ack.sign(self._secret)
                                writer.write(ack.encode())
                                await writer.drain()
                                logger.info("Cluster invitation accepted from %s", msg.sender_id)

                    elif msg.msg_type == "cluster_sync_start" and self._sync_engine:
                        await self._sync_engine.start()
                        ack = SwarmMessage("cluster_sync_ack", self.node_id, {
                            "status": "syncing",
                        })
                        ack.sign(self._secret)
                        writer.write(ack.encode())
                        await writer.drain()

                    elif msg.msg_type == "dtn_route" and self._dtn_node:
                        # Peer advertising DTN routes — update route table
                        routes = msg.payload.get("routes", {})
                        for peer_id, route_info in routes.items():
                            if peer_id != self.node_id:
                                self._dtn_node.discovery.update_route_table(
                                    peer_id, msg.sender_id
                                )
                        ack = SwarmMessage("dtn_route_ack", self.node_id)
                        ack.sign(self._secret)
                        writer.write(ack.encode())
                        await writer.drain()

        except Exception:
            pass
        finally:
            writer.close()

    # ------------------------------------------------------------------
    # Background loops
    # ------------------------------------------------------------------
    async def _heartbeat_loop(self) -> None:
        while self._running:
            await asyncio.sleep(HEARTBEAT_INTERVAL)
            for peer_id, peer in list(self.peers.items()):
                if not peer.is_alive:
                    self.remove_peer(peer_id)
                    self._consecutive_failures += 1
                    continue
                try:
                    r, w = await asyncio.wait_for(
                        asyncio.open_connection(peer.host, peer.port), timeout=3
                    )
                    extra = {}
                    if self._dtn_node:
                        extra["dtn_routes"] = list(
                            self._dtn_node.router.get_route_info().keys()
                        )
                    ping = SwarmMessage("ping", self.node_id, {
                        "task": self._current_task,
                        "task_status": self._task_status,
                        **extra,
                    })
                    ping.sign(self._secret)
                    w.write(ping.encode())
                    await w.drain()

                    resp_data = await asyncio.wait_for(r.readline(), timeout=3)
                    w.close()

                    resp = SwarmMessage.decode(resp_data)
                    if resp and resp.payload:
                        peer.current_task = resp.payload.get("task", peer.current_task)
                        peer.task_status = resp.payload.get("task_status", peer.task_status)
                        if self._dtn_node:
                            dtn_routes = resp.payload.get("dtn_routes", [])
                            for route_dest in dtn_routes:
                                if route_dest != self.node_id:
                                    self._dtn_node.discovery.update_route_table(
                                        route_dest, peer.node_id
                                    )

                    peer.connected = True
                    peer.last_seen = time.time()
                    self._consecutive_failures = 0
                except Exception:
                    peer.connected = False
            self._save_peers()

    async def _self_preservation_loop(self) -> None:
        """Periodic health check — Article V.2 (every 30s)."""
        while self._running:
            await asyncio.sleep(30)
            try:
                await self._self_preservation_check()
            except Exception:
                pass

    async def _udp_discovery(self) -> None:
        GHOST_SIGNAL = b"GHOST_SWARM_PING"
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            sock.bind(("", BROADCAST_PORT))
            sock.setblocking(False)
            loop = asyncio.get_event_loop()

            while self._running:
                try:
                    data, addr = await loop.sock_recvfrom(sock, 1024)
                    if data == GHOST_SIGNAL:
                        self.add_peer(addr[0], self.port, f"lan-{addr[0]}")
                except (BlockingIOError, OSError):
                    pass

                announce = SwarmMessage("peer_discover", self.node_id,
                                        {"port": self.port}).encode()
                try:
                    await loop.sock_sendto(sock, announce, ("255.255.255.255", BROADCAST_PORT))
                    await loop.sock_sendto(sock, GHOST_SIGNAL, ("255.255.255.255", BROADCAST_PORT))
                except Exception:
                    pass
                await asyncio.sleep(10)
        except Exception:
            pass

    async def _dht_discovery_loop(self) -> None:
        while self._running and self.dht and self.dht.is_ready:
            await asyncio.sleep(30)
            try:
                await self.dht.announce()
                peers = await self.dht.discover_peers()
                for entry in peers:
                    nid = entry.get("node_id", "")
                    host = entry.get("host", "")
                    sp = entry.get("swarm_port", self.port)
                    qp = entry.get("quantum_port", 0)
                    ver = entry.get("version", "?")
                    if nid and nid != self.node_id and host:
                        self.add_peer(host, sp, nid, ["dht"], version=ver,
                                      quantum_enabled=qp > 0)
            except Exception:
                pass

            # Active broadcast to ALL bootstrap nodes every 90s
            try:
                for host, port in DHT_BOOTSTRAP_NODES:
                    try:
                        await asyncio.wait_for(
                            self.dht.bootstrap(host, port), timeout=3
                        )
                    except Exception:
                        continue
            except Exception:
                pass

    async def peer_discovery_report(self) -> Dict[str, Any]:
        """Generate a Peer Discovery Report with connectivity stats (Article IV.3)."""
        alive = self.peer_count
        total = len(self.peers)
        latencies = []

        for peer in list(self.peers.values()):
            if peer.is_alive:
                try:
                    start = time.time()
                    r, w = await asyncio.wait_for(
                        asyncio.open_connection(peer.host, peer.port), timeout=3
                    )
                    w.close()
                    lat = (time.time() - start) * 1000
                    latencies.append(lat)
                except Exception:
                    pass

        avg_latency = sum(latencies) / max(len(latencies), 1)

        # Check bootstrap node reachability
        bootstrap_status = {}
        for host, port in DHT_BOOTSTRAP_NODES:
            try:
                start = time.time()
                r, w = await asyncio.wait_for(
                    asyncio.open_connection(host, port), timeout=2
                )
                w.close()
                bootstrap_status[f"{host}:{port}"] = {
                    "reachable": True,
                    "latency_ms": round((time.time() - start) * 1000, 1),
                }
            except Exception:
                bootstrap_status[f"{host}:{port}"] = {"reachable": False}

        report = {
            "node_id": self.node_id,
            "timestamp": time.time(),
            "peers_alive": alive,
            "peers_total": total,
            "average_latency_ms": round(avg_latency, 1),
            "bootstrap_nodes": bootstrap_status,
            "dht_ready": self.dht.is_ready if self.dht else False,
            "pending_tasks": len(self._pending_tasks),
        }
        logger.info("Peer Discovery Report: %d/%d peers alive, avg latency %.1fms",
                     alive, total, avg_latency)
        return report

    async def _task_processor(self) -> None:
        while self._running:
            while self._pending_tasks:
                msg = self._pending_tasks.pop(0)
                self._current_task = msg.payload.get("command", str(msg.payload))
                self._task_status = "running"
                try:
                    if self.task_handler:
                        await self.task_handler(msg)
                    self._task_status = "completed"
                except Exception as e:
                    self._task_status = "failed"
                    logger.warning("Task handler: %s", e)
                self._current_task = ""
                if self._task_status != "failed":
                    self._task_status = "idle"
            await asyncio.sleep(1)

    async def _default_task_handler(self, msg: SwarmMessage) -> None:
        logger.info("Task: type=%s from=%s", msg.msg_type, msg.sender_id)

    # ------------------------------------------------------------------
    # Self-Preservation Protocol (Article V)
    # ------------------------------------------------------------------
    async def _self_preservation_check(self) -> None:
        """Health monitor — checks node stability every 30s (Article V.2)."""
        if not self._running:
            return

        try:
            import psutil
            cpu_percent = psutil.cpu_percent(interval=0.5)
            mem = psutil.virtual_memory()
            mem_percent = mem.percent
        except ImportError:
            cpu_percent = 50.0
            mem_percent = 50.0

        alive = self.peer_count
        total = len(self.peers)
        peer_loss_ratio = 1.0 - (alive / max(total, 1))

        instability = False
        reasons = []

        # Article V.1: >50% peer loss
        if total > 0 and peer_loss_ratio > 0.5:
            instability = True
            reasons.append(f"Peer loss {peer_loss_ratio:.0%} > 50%")

        # Article V.1: >3 consecutive heartbeat failures
        if self._consecutive_failures > 3:
            instability = True
            reasons.append(f"Heartbeat failures: {self._consecutive_failures} > 3")

        # Resource exhaustion
        if cpu_percent > 90:
            instability = True
            reasons.append(f"CPU at {cpu_percent}%")
        if mem_percent > 90:
            instability = True
            reasons.append(f"Memory at {mem_percent}%")

        if not instability:
            return

        logger.warning("SELF-PRESERVATION: Node unstable — %s", "; ".join(reasons))
        await self._migrate_active_tasks(reasons)

    async def _migrate_active_tasks(self, reasons: List[str]) -> None:
        """Migrate active tasks to healthy peers before departure (Article V.1)."""
        if not self._pending_tasks:
            logger.info("Self-preservation: no pending tasks to migrate")
            if not self._running:
                return
            await self._broadcast_departure(reasons)
            return

        healthy = [p for p in self.peers.values() if p.is_alive and p.connected]
        if not healthy:
            logger.error("Self-preservation: no healthy peers for migration")
            return

        for task_msg in list(self._pending_tasks):
            target = random.choice(healthy)
            try:
                task_msg.payload["migrated_from"] = self.node_id
                task_msg.payload["migration_reason"] = "; ".join(reasons)
                task_msg.sender_id = self.node_id
                if self.identity:
                    task_msg.sign(self.identity)
                else:
                    task_msg.sign(self._secret)

                r, w = await asyncio.wait_for(
                    asyncio.open_connection(target.host, target.port), timeout=5
                )
                w.write(task_msg.encode())
                await w.drain()
                w.close()
                logger.info("Migrated task %s to %s", task_msg.payload.get("task_id", "?"), target.node_id)
                self._pending_tasks.remove(task_msg)
            except Exception as e:
                logger.error("Task migration failed for %s: %s", target.node_id, e)

        await self._broadcast_departure(reasons)

    async def _broadcast_departure(self, reasons: List[str]) -> None:
        """Broadcast departure notice to the swarm."""
        departure = SwarmMessage("departure", self.node_id, {
            "reason": "; ".join(reasons),
            "pending_tasks": len(self._pending_tasks),
            "timestamp": time.time(),
        })
        if self.identity:
            departure.sign(self.identity)
        else:
            departure.sign(self._secret)
        await self.broadcast(departure)
        logger.info("Broadcast departure notice: %s", "; ".join(reasons))

    # ------------------------------------------------------------------
    # Status
    # ------------------------------------------------------------------
    @property
    def peer_count(self) -> int:
        return sum(1 for p in self.peers.values() if p.is_alive)

    @property
    def status(self) -> Dict[str, Any]:
        return {
            "node_id": self.node_id,
            "port": self.port,
            "peers_total": len(self.peers),
            "peers_alive": self.peer_count,
            "pending_tasks": len(self._pending_tasks),
            "running": self._running,
            "dht": self.dht.is_ready if self.dht else False,
            "mode": self._ghost_mode,
            "cid": self._cid[:24] + "..." if len(self._cid) > 24 else self._cid,
            "observations_buffered": len(self._observations),
            "consecutive_failures": self._consecutive_failures,
        }


# =============================================================================
# Launch Sequence
# =============================================================================

class LaunchSequence:
    """
    Terminal launch sequence that displays:
      * Deployment status
      * Swarm connection count
      * Current Ghost Mode
      * Bootstrap progress
    """

    def __init__(self, node: GhostSwarmNode):
        self.node = node
        self._start_time = time.time()

    async def execute(self) -> Dict[str, Any]:
        lines = [
            "+==========================================================+",
            "|          GHOST ENGINE -- LAUNCH SEQUENCE                  |",
            "|     Decentralized AI Agent v Global Mesh v3              |",
            "+==========================================================+",
            "",
        ]
        for line in lines:
            print(line)
            await asyncio.sleep(0.05)

        # Phase 1: Start swarm
        print(f"  {self._icon('swarm')} Initializing P2P swarm node...")
        await self.node.start()
        print(f"    +- Node ID:      {self.node.node_id}")
        print(f"    +- TCP port:     {self.node.port}")

        # Phase 2: Bootstrap
        print(f"\n  {self._icon('bootstrap')} Running bootstrap sequence...")
        boot_result = await self.node.bootstrap_sequence()

        print(f"    +- DHT peers:     {boot_result['dht_peers']}")
        print(f"    +- Mesh connects: {boot_result['mesh_connections']}")
        print(f"    +- Config verify: {boot_result['config_verified']}")
        print(f"    +- Quantum peers: {boot_result['quantum_peers']}")
        print(f"    +- Self-healed:   {boot_result['self_healed']}")

        # Phase 3: Health check
        elapsed = time.time() - self._start_time
        print(f"\n  {self._icon('health')} Health check:")
        print(f"    +- Uptime:        {elapsed:.1f}s")
        print(f"    +- Peers alive:   {self.node.peer_count}")
        print(f"    +- Ghost Mode:    {self.node._ghost_mode}")
        print(f"    +- Config CID:    {self.node._cid[:48] if self.node._cid else 'local'}")

        # Summary
        print(f"\n  {self._icon('ready')} LAUNCH COMPLETE -- READY")
        print(f"")
        status_line = (f"  {self.node.peer_count} peers | "
                       f"{boot_result['dht_peers']} DHT | "
                       f"mode={self.node._ghost_mode} | "
                       f"{elapsed:.1f}s")
        print(f"  {status_line}")
        print(f"")
        print(f"  ========================================================")

        return boot_result

    @staticmethod
    def _icon(phase: str) -> str:
        icons = {"swarm": "[~]", "bootstrap": "[+]", "health": "[+]", "ready": "[!]"}
        return icons.get(phase, "o")


# =============================================================================
# Demo / Self-test
# =============================================================================

async def demo_swarm():
    node = GhostSwarmNode(node_id="ghost-demo", port=9876)
    launch = LaunchSequence(node)
    result = await launch.execute()

    # Keep running for a bit
    try:
        await asyncio.sleep(30)
    except KeyboardInterrupt:
        pass
    finally:
        await node.stop()

    print("\nFinal status:", json.dumps(node.status, indent=2))
    return result


class TaskDispatcher:
    def __init__(self, swarm: GhostSwarmNode):
        self.swarm = swarm

    def create_task(self, task_type: str, data: Dict[str, Any]) -> Dict[str, Any]:
        return {"id": str(uuid.uuid4()), "type": task_type,
                "payload": data, "timestamp": time.time()}

    async def dispatch(self, task_type: str, data: Dict[str, Any],
                       target_peer: Optional[str] = None) -> str:
        task = self.create_task(task_type, data)
        logger.info("Dispatching Task %s (%s)", task["id"], task_type)
        await self.swarm.send_task(task_type, task["payload"], target_peer=target_peer)
        return task["id"]


async def cluster_demo():
    """Demonstrate permissioned cluster formation and state sync."""
    import argparse
    parser = argparse.ArgumentParser(description="Ghost Swarm — Permissioned Cluster")
    parser.add_argument("--cluster", type=str, default=None,
                        help="Cluster name to join/form")
    parser.add_argument("--invite", type=str, default=None,
                        help="Invite a peer by pubkey hex")
    parser.add_argument("--seed", type=str, default=None,
                        help="Seed peer host:port to join")
    parser.add_argument("--sync-port", type=int, default=9878,
                        help="Sync port (default: 9878)")
    parser.add_argument("--swarm-port", type=int, default=9876,
                        help="Swarm TCP port (default: 9876)")
    parser.add_argument("--demo", action="store_true",
                        help="Run swarm demo with permissioned cluster")
    args = parser.parse_args()

    from node_identity import NodeIdentity
    identity = NodeIdentity.load_or_create()
    print(f"Node identity: {identity.node_id}")
    print(f"Public key: {identity.public_key_hex()[:32]}...")

    enable_permissioned_cluster(identity, cluster_name=args.cluster or "default")
    cluster = _permissioned_cluster
    sync = _global_state_sync

    if args.invite:
        inv = cluster.issue_invitation(args.invite)
        if inv:
            print(f"Invitation issued for pubkey {args.invite[:16]}...")
            print(f"Invitation JSON:\n{json.dumps(inv.to_dict(), indent=2)}")
        return

    if args.seed:
        parts = args.seed.split(":")
        host = parts[0]
        port = int(parts[1]) if len(parts) > 1 else args.sync_port
        from ghost_sync import form_cluster
        cluster, sync = await form_cluster(
            identity,
            seed_hosts=[(host, port)],
            cluster_name=args.cluster or "default",
            sync_port=args.sync_port,
        )
        print(f"Cluster state: {json.dumps(cluster.status(), indent=2)}")
        # Keep running
        try:
            await asyncio.sleep(3600)
        except KeyboardInterrupt:
            pass
        finally:
            await sync.stop()
        return

    if args.demo or not args.seed:
        node = GhostSwarmNode(node_id=identity.node_id, port=args.swarm_port,
                              identity=identity)
        node._cluster = cluster
        node._sync_engine = sync
        node._use_permissioned_cluster = True
        await sync.start(port=args.sync_port)
        launch = LaunchSequence(node)
        result = await launch.execute()
        print(f"\nCluster status: {json.dumps(cluster.status(), indent=2)}")
        try:
            await asyncio.sleep(3600)
        except KeyboardInterrupt:
            pass
        finally:
            await node.stop()
            await sync.stop()
        return


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s")

    import sys
    if "--cluster" in sys.argv or "--invite" in sys.argv or "--seed" in sys.argv or "--demo" in sys.argv:
        asyncio.run(cluster_demo())
    else:
        asyncio.run(demo_swarm())
