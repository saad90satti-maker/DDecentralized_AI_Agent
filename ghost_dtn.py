"""
Ghost DTN — Delay-Tolerant Networking Bundle Protocol (RFC 9171)
=================================================================
Enables store-and-forward messaging, custody transfer, ephemeral
peer discovery, and multi-hop routing for the Ghost Swarm.

Architecture:
  +--------------------------------------------------------------+
  |                     DTN Node                                  |
  |  +--------------+  +-------------+  +---------------------+  |
  |  | Bundle Store |  | Custody     |  | DTN Router          |  |
  |  | (persistent) |  | Manager     |  | (link-state +       |  |
  |  |              |  |             |  |  multi-hop)         |  |
  |  +--------------+  +-------------+  +---------------------+  |
  |  +--------------+  +-------------+  +---------------------+  |
  |  | Ephemeral    |  | Bundle      |  | TCP/UDP Transport   |  |
  |  | Discovery    |  | Protocol    |  | Layer               |  |
  |  +--------------+  +-------------+  +---------------------+  |
  +--------------------------------------------------------------+

Protocol Flow:
  1. Application submits payload to DTN node
  2. DTN wraps in a Bundle (primary block + payload block)
  3. Router selects next-hop (direct or via intermediate)
  4. Custody manager tracks transfer lifecycle
  5. If peer unreachable → store in BundleStore (store-and-forward)
  6. On peer contact → forward all pending bundles
  7. Receiver sends custody signal (accept/release)
  8. Complete bundles delivered to application callback

Usage:
  from ghost_dtn import DTNNode
  node = DTNNode(node_id="alpha", identity=identity)
  await node.start(host="0.0.0.0", port=9880)

  # Send with custody transfer
  bundle_id = await node.send(
      payload={"type": "task", "data": {...}},
      destination="beta",
      custody_transfer=True,
  )

  # Receive bundles
  @node.on_bundle
  async def handler(bundle):
      print(f"Received: {bundle.payload}")
"""

import asyncio
import functools
import hashlib
import json
import logging
import os
import random
import socket
import struct
import time
import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

logger = logging.getLogger("GhostDTN")

# ---------------------------------------------------------------------------
# Constants (RFC 9171 aligned)
# ---------------------------------------------------------------------------
DTN_PORT = int(os.getenv("DTN_PORT", "9880"))
DTN_DISCOVERY_PORT = int(os.getenv("DTN_DISCOVERY_PORT", "9881"))
BUNDLE_STORE_DIR = Path(__file__).resolve().parent / "agent_data" / "dtn"
BUNDLE_STORE_DIR.mkdir(parents=True, exist_ok=True)

DTN_PROTOCOL_VERSION = 7  # RFC 9171 Bundle Protocol version 7
MAX_BUNDLE_SIZE = 1024 * 1024  # 1MB default
DEFAULT_TTL = 3600 * 24  # 24 hours
CUSTODY_TIMEOUT = 60  # seconds before custody re-transfer
ROUTING_UPDATE_INTERVAL = 30  # seconds between route table broadcasts
LINK_PROBE_INTERVAL = 15  # seconds between link probes
STORE_FLUSH_INTERVAL = 10  # seconds between store-and-forward retry
MAX_HOP_COUNT = 32  # max multi-hop hops
EPHEMERAL_TIMEOUT = 120  # seconds before ephemeral peer is forgotten
CUSTODY_RETRY_MAX = 5  # max custody transfer retries

# Bundle block types (RFC 9171 §4.5)
BLOCK_TYPE_PRIMARY = 1
BLOCK_TYPE_PAYLOAD = 2
BLOCK_TYPE_CUSTODY_SIGNAL = 3
BLOCK_TYPE_BUNDLE_STATUS = 4
BLOCK_TYPE_PREVIOUS_NODE = 7

# Bundle status flags (RFC 9171 §6.1)
STATUS_NO_INFO = 0
STATUS_RECEIVED = 1
STATUS_CUSTODY_ACCEPTED = 2
STATUS_FORWARDED = 4
STATUS_DELIVERED = 8
STATUS_DELETED = 16

# Custody signal reasons
CUSTODY_ACCEPT = 0
CUSTODY_REDUNDANT = 1
CUSTODY_CAPACITY = 2
CUSTODY_UNREACHABLE = 3


class LinkType(Enum):
    TCP = "tcp"
    UDP = "udp"
    EPHEMERAL = "ephemeral"
    LOOPBACK = "loopback"


class BundleStatus(Enum):
    PENDING = "pending"
    IN_FLIGHT = "in_flight"
    CUSTODY_ACCEPTED = "custody_accepted"
    DELIVERED = "delivered"
    EXPIRED = "expired"
    DELETED = "deleted"


# ---------------------------------------------------------------------------
# Bundle Data Structures (RFC 9171 §4.3 - §4.5)
# ---------------------------------------------------------------------------

@dataclass
class PrimaryBlock:
    """Bundle primary block — immutable identification and routing info."""
    bundle_id: str
    version: int = DTN_PROTOCOL_VERSION
    source: str = ""
    destination: str = ""
    report_to: str = ""
    creation_timestamp: float = 0.0
    lifetime: float = DEFAULT_TTL
    fragment: bool = False
    fragment_offset: int = 0
    total_length: int = 0
    custody_transfer: bool = False
    singleton: bool = True
    hop_count: int = 0
    max_hops: int = MAX_HOP_COUNT
    payload_length: int = 0

    @property
    def expires_at(self) -> float:
        return self.creation_timestamp + self.lifetime

    @property
    def is_expired(self) -> bool:
        return time.time() > self.expires_at

    def to_dict(self) -> Dict[str, Any]:
        return {
            "bundle_id": self.bundle_id,
            "version": self.version,
            "source": self.source,
            "destination": self.destination,
            "report_to": self.report_to,
            "creation_timestamp": self.creation_timestamp,
            "lifetime": self.lifetime,
            "fragment": self.fragment,
            "fragment_offset": self.fragment_offset,
            "total_length": self.total_length,
            "custody_transfer": self.custody_transfer,
            "singleton": self.singleton,
            "hop_count": self.hop_count,
            "max_hops": self.max_hops,
            "payload_length": self.payload_length,
        }

    @staticmethod
    def from_dict(d: Dict[str, Any]) -> "PrimaryBlock":
        return PrimaryBlock(**{k: v for k, v in d.items()
                               if k in PrimaryBlock.__dataclass_fields__})


@dataclass
class PayloadBlock:
    """Bundle payload block — the actual data being carried."""
    block_type: int = BLOCK_TYPE_PAYLOAD
    payload: Dict[str, Any] = field(default_factory=dict)
    security_context: Optional[str] = None

    def to_bytes(self) -> bytes:
        return json.dumps(self.payload, default=str).encode("utf-8")

    @staticmethod
    def from_bytes(data: bytes) -> "PayloadBlock":
        return PayloadBlock(payload=json.loads(data.decode("utf-8")))


@dataclass
class CustodySignal:
    """Custody transfer signal — acceptance or release notice."""
    bundle_id: str
    signal_type: int = CUSTODY_ACCEPT  # accept | redundant | capacity | unreachable
    owner: str = ""  # node_id of current custodian
    timestamp: float = 0.0
    reason: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "bundle_id": self.bundle_id,
            "signal_type": self.signal_type,
            "owner": self.owner,
            "timestamp": self.timestamp or time.time(),
            "reason": self.reason,
        }

    @staticmethod
    def from_dict(d: Dict[str, Any]) -> "CustodySignal":
        return CustodySignal(**{k: v for k, v in d.items()
                                 if k in CustodySignal.__dataclass_fields__})


@dataclass
class BundleStatusReport:
    """Status report for bundle tracking (RFC 9171 §6.1)."""
    bundle_id: str
    status: int = STATUS_NO_INFO
    node_id: str = ""
    timestamp: float = 0.0
    reason: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "bundle_id": self.bundle_id,
            "status": self.status,
            "node_id": self.node_id,
            "timestamp": self.timestamp or time.time(),
            "reason": self.reason,
        }


@dataclass
class DTNBundle:
    """Complete DTN bundle: primary block + payload + extension blocks."""
    primary: PrimaryBlock
    payload: PayloadBlock = field(default_factory=PayloadBlock)
    custody_signal: Optional[CustodySignal] = None
    status_report: Optional[BundleStatusReport] = None
    previous_node: str = ""
    current_custodian: str = ""
    custody_retries: int = 0
    bundle_status: BundleStatus = BundleStatus.PENDING

    @property
    def bundle_id(self) -> str:
        return self.primary.bundle_id

    def to_dict(self) -> Dict[str, Any]:
        d = {
            "primary": self.primary.to_dict(),
            "payload": {"block_type": self.payload.block_type, "data": self.payload.payload},
            "previous_node": self.previous_node,
            "current_custodian": self.current_custodian,
            "custody_retries": self.custody_retries,
            "status": self.bundle_status.value,
        }
        if self.custody_signal:
            d["custody_signal"] = self.custody_signal.to_dict()
        if self.status_report:
            d["status_report"] = self.status_report.to_dict()
        return d

    @staticmethod
    def from_dict(d: Dict[str, Any]) -> "DTNBundle":
        primary = PrimaryBlock.from_dict(d["primary"])
        pd = d.get("payload", {})
        payload = PayloadBlock(block_type=pd.get("block_type", BLOCK_TYPE_PAYLOAD),
                                payload=pd.get("data", {}))
        bundle = DTNBundle(primary=primary, payload=payload,
                            previous_node=d.get("previous_node", ""),
                            current_custodian=d.get("current_custodian", ""),
                            custody_retries=d.get("custody_retries", 0),
                            bundle_status=BundleStatus(d.get("status", "pending")))
        if "custody_signal" in d:
            bundle.custody_signal = CustodySignal.from_dict(d["custody_signal"])
        if "status_report" in d:
            bundle.status_report = BundleStatusReport.from_dict(d["status_report"])
        return bundle

    def serialize(self) -> Dict[str, Any]:
        """Full serialization for storage or transport."""
        return self.to_dict()

    @staticmethod
    def deserialize(data: Dict[str, Any]) -> "DTNBundle":
        return DTNBundle.from_dict(data)


# ---------------------------------------------------------------------------
# Bundle Factory
# ---------------------------------------------------------------------------

def create_bundle(
    payload: Dict[str, Any],
    source: str,
    destination: str,
    custody_transfer: bool = True,
    lifetime: float = DEFAULT_TTL,
    max_hops: int = MAX_HOP_COUNT,
) -> DTNBundle:
    """Create a new DTN bundle ready for transmission."""
    bundle_id = f"{source}->{destination}--{uuid.uuid4().hex[:16]}"
    now = time.time()
    primary = PrimaryBlock(
        bundle_id=bundle_id,
        source=source,
        destination=destination,
        creation_timestamp=now,
        lifetime=lifetime,
        custody_transfer=custody_transfer,
        max_hops=max_hops,
        payload_length=len(json.dumps(payload)),
    )
    payload_block = PayloadBlock(payload=payload)
    return DTNBundle(primary=primary, payload=payload_block,
                      bundle_status=BundleStatus.PENDING)


# ---------------------------------------------------------------------------
# Bundle Store — Persistent Store-and-Forward
# ---------------------------------------------------------------------------

class BundleStore:
    """
    Persistent JSON-backed store for bundles awaiting delivery.
    Implements the 'storage' component of store-and-forward DTN.
    """

    def __init__(self, store_dir: Path = BUNDLE_STORE_DIR):
        self._dir = store_dir
        self._dir.mkdir(parents=True, exist_ok=True)
        self._bundles: Dict[str, DTNBundle] = {}  # bundle_id -> bundle
        self._load_all()

    def _path_for(self, bundle_id: str) -> Path:
        safe = bundle_id.replace("->", "_").replace("--", "_")
        return self._dir / f"{safe}.json"

    def _load_all(self) -> None:
        """Load all bundles from disk."""
        for fpath in self._dir.glob("*.json"):
            try:
                data = json.loads(fpath.read_text(encoding="utf-8"))
                bundle = DTNBundle.deserialize(data)
                if not bundle.primary.is_expired:
                    self._bundles[bundle.bundle_id] = bundle
                else:
                    fpath.unlink(missing_ok=True)
            except Exception as e:
                logger.debug("Failed to load bundle %s: %s", fpath.name, e)

    def save(self, bundle: DTNBundle) -> None:
        """Persist a bundle to disk."""
        self._bundles[bundle.bundle_id] = bundle
        try:
            self._path_for(bundle.bundle_id).write_text(
                json.dumps(bundle.serialize(), indent=2), encoding="utf-8"
            )
        except Exception as e:
            logger.warning("Bundle save failed: %s", e)

    def get(self, bundle_id: str) -> Optional[DTNBundle]:
        return self._bundles.get(bundle_id)

    def remove(self, bundle_id: str) -> None:
        self._bundles.pop(bundle_id, None)
        try:
            self._path_for(bundle_id).unlink(missing_ok=True)
        except Exception:
            pass

    def list_pending(self, destination: Optional[str] = None) -> List[DTNBundle]:
        """List bundles pending delivery (PENDING or IN_FLIGHT status)."""
        results = []
        for b in self._bundles.values():
            if b.bundle_status in (BundleStatus.PENDING, BundleStatus.IN_FLIGHT):
                if destination is None or b.primary.destination == destination:
                    if not b.primary.is_expired:
                        results.append(b)
        return results

    def list_for_forwarding(self, node_id: str) -> List[DTNBundle]:
        """List bundles that should be forwarded through or to this node."""
        results = []
        for b in self._bundles.values():
            if b.bundle_status in (BundleStatus.PENDING, BundleStatus.IN_FLIGHT,
                                    BundleStatus.CUSTODY_ACCEPTED):
                if not b.primary.is_expired:
                    dest = b.primary.destination
                    if dest == node_id or dest == "*" or dest == "":
                        results.append(b)
        return results

    def expire_stale(self) -> int:
        """Remove expired bundles. Returns count removed."""
        expired = [bid for bid, b in self._bundles.items() if b.primary.is_expired]
        for bid in expired:
            b = self._bundles[bid]
            b.bundle_status = BundleStatus.EXPIRED
            self.remove(bid)
        return len(expired)

    @property
    def pending_count(self) -> int:
        return len([b for b in self._bundles.values()
                     if b.bundle_status == BundleStatus.PENDING])

    @property
    def total_count(self) -> int:
        return len(self._bundles)

    def stats(self) -> Dict[str, Any]:
        counts = defaultdict(int)
        for b in self._bundles.values():
            counts[b.bundle_status.value] += 1
        return {
            "total": self.total_count,
            **dict(counts),
        }


# ---------------------------------------------------------------------------
# Link State — Ephemeral Peer Representation
# ---------------------------------------------------------------------------

@dataclass
class LinkState:
    """Dynamic state of a network link to a DTN peer."""
    node_id: str
    host: str
    port: int
    link_type: LinkType = LinkType.TCP
    last_seen: float = 0.0
    first_seen: float = 0.0
    rtt_ms: float = 0.0
    quality: float = 1.0  # 0.0 (dead) to 1.0 (perfect)
    hop_count: int = 1    # distance in hops from self
    routes: Set[str] = field(default_factory=set)  # destinations reachable via this peer
    is_ephemeral: bool = True

    @property
    def is_alive(self) -> bool:
        return (time.time() - self.last_seen) < EPHEMERAL_TIMEOUT

    def age_quality(self) -> None:
        """Decay link quality over time since last contact."""
        dt = time.time() - self.last_seen
        if dt > EPHEMERAL_TIMEOUT:
            self.quality = max(0.0, self.quality - 0.1 * (dt / EPHEMERAL_TIMEOUT))
        if self.quality < 0.01:
            self.quality = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "node_id": self.node_id,
            "host": self.host,
            "port": self.port,
            "link_type": self.link_type.value,
            "last_seen": self.last_seen,
            "first_seen": self.first_seen,
            "rtt_ms": self.rtt_ms,
            "quality": self.quality,
            "hop_count": self.hop_count,
            "routes": list(self.routes),
            "is_ephemeral": self.is_ephemeral,
        }


# ---------------------------------------------------------------------------
# Ephemeral Peer Discovery
# ---------------------------------------------------------------------------

class EphemeralDiscovery:
    """
    Discovers DTN peers without hardcoded seeds using:
      1. UDP multicast heartbeats on local network
      2. Passive listening on TCP discovery port
      3. Active TCP probes to newly discovered peers
      4. Route table exchange for multi-hop discovery
    """

    def __init__(self, node_id: str, identity: Any,
                 discovery_port: int = DTN_DISCOVERY_PORT,
                 dtn_port: int = DTN_PORT):
        self.node_id = node_id
        self._identity = identity
        self._discovery_port = discovery_port
        self._dtn_port = dtn_port
        self._running = False
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._on_peer_discovered: Optional[Callable] = None
        self._known_links: Dict[str, LinkState] = {}
        self._route_table: Dict[str, List[str]] = {}  # destination -> [next_hops]
        self._udp_sock: Optional[socket.socket] = None

        # Active discovery probe queue
        self._probe_queue: asyncio.Queue[str] = asyncio.Queue()

    def on_peer_discovered(self, callback: Callable) -> None:
        self._on_peer_discovered = callback

    def _sign_message(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        raw = json.dumps(payload, sort_keys=True)
        payload["signature"] = self._identity.sign(raw)
        payload["sender_id"] = self.node_id
        payload["sender_pubkey"] = self._identity.public_key_hex()
        return payload

    @staticmethod
    def _verify_message(msg: Dict[str, Any]) -> bool:
        from node_identity import NodeIdentity
        sig = msg.pop("signature", "")
        if not sig:
            return False
        pubkey = msg.get("sender_pubkey", "")
        if not pubkey:
            return False
        raw = json.dumps(msg, sort_keys=True)
        ok = NodeIdentity.verify(raw, sig, pubkey)
        msg["signature"] = sig  # restore
        return ok

    # ------------------------------------------------------------------
    # Active Discovery
    # ------------------------------------------------------------------

    async def start(self, loop: Optional[asyncio.AbstractEventLoop] = None) -> None:
        self._running = True
        self._loop = loop or asyncio.get_event_loop()
        asyncio.create_task(self._udp_beacon())
        asyncio.create_task(self._udp_listener())
        asyncio.create_task(self._probe_processor())
        asyncio.create_task(self._cleanup_loop())

    async def stop(self) -> None:
        self._running = False
        if self._udp_sock:
            try:
                self._udp_sock.close()
            except Exception:
                pass

    def probe(self, host: str) -> None:
        """Queue a peer for active probing."""
        self._probe_queue.put_nowait(host)

    # ------------------------------------------------------------------
    # Link Management
    # ------------------------------------------------------------------

    def upsert_link(self, node_id: str, host: str, port: int,
                    hop_count: int = 1, routes: Optional[Set[str]] = None) -> LinkState:
        existing = self._known_links.get(node_id)
        if existing:
            existing.host = host
            existing.port = port
            existing.last_seen = time.time()
            existing.hop_count = min(existing.hop_count, hop_count)
            existing.quality = min(1.0, existing.quality + 0.1)
            if routes:
                existing.routes.update(routes)
            return existing
        link = LinkState(
            node_id=node_id,
            host=host,
            port=port,
            last_seen=time.time(),
            first_seen=time.time(),
            hop_count=hop_count,
            routes=routes or set(),
        )
        self._known_links[node_id] = link
        logger.debug("Discovered ephemeral peer: %s @ %s:%d (hops=%d)",
                      node_id, host, port, hop_count)
        if self._on_peer_discovered:
            self._on_peer_discovered(node_id, host, port)
        return link

    def remove_link(self, node_id: str) -> None:
        self._known_links.pop(node_id, None)
        self._route_table.pop(node_id, None)

    def get_link(self, node_id: str) -> Optional[LinkState]:
        return self._known_links.get(node_id)

    @property
    def known_peers(self) -> int:
        return sum(1 for ls in self._known_links.values() if ls.is_alive)

    @property
    def links(self) -> List[LinkState]:
        return [ls for ls in self._known_links.values() if ls.is_alive]

    # ------------------------------------------------------------------
    # UDP Beacon — LAN broadcast + multicast
    # ------------------------------------------------------------------

    async def _udp_beacon(self) -> None:
        """Periodically broadcast presence on the local network."""
        beacon_addr = os.getenv("DTN_BEACON_ADDR", "255.255.255.255")
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

        while self._running:
            await asyncio.sleep(LINK_PROBE_INTERVAL)
            msg = self._sign_message({
                "type": "dtn_beacon",
                "node_id": self.node_id,
                "dtn_port": self._dtn_port,
                "routes": list(self._route_table.keys()),
                "hop_count": 0,
                "timestamp": time.time(),
            })
            try:
                sock.sendto(json.dumps(msg).encode(), (beacon_addr, self._discovery_port))
            except Exception:
                pass

    async def _udp_listener(self) -> None:
        """Listen for UDP beacons from other DTN nodes."""
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind(("", self._discovery_port))
        sock.setblocking(False)
        self._udp_sock = sock
        loop = asyncio.get_event_loop()

        while self._running:
            try:
                data, addr = await loop.sock_recvfrom(sock, 2048)
                msg = json.loads(data.decode().strip())
                if not self._verify_message(msg.copy()):
                    logger.debug("Invalid signature on beacon from %s", addr[0])
                    continue
                if msg.get("type") != "dtn_beacon":
                    continue
                sender = msg.get("node_id", "")
                if sender == self.node_id:
                    continue
                dtn_port = msg.get("dtn_port", self._dtn_port)
                hop_count = msg.get("hop_count", 0) + 1
                routes = set(msg.get("routes", []))

                self.upsert_link(sender, addr[0], dtn_port,
                                 hop_count=hop_count, routes=routes)
            except (BlockingIOError, json.JSONDecodeError):
                await asyncio.sleep(0.1)
            except Exception:
                pass

    # ------------------------------------------------------------------
    # Active TCP Probing
    # ------------------------------------------------------------------

    async def _probe_processor(self) -> None:
        """Process queued probes and attempt TCP handshake."""
        while self._running:
            try:
                host = await asyncio.wait_for(
                    self._probe_queue.get(), timeout=LINK_PROBE_INTERVAL
                )
                await self._probe_peer(host)
            except asyncio.TimeoutError:
                continue
            except Exception:
                pass

    async def _probe_peer(self, host: str) -> bool:
        """Send a TCP probe to a peer's DTN port."""
        try:
            r, w = await asyncio.wait_for(
                asyncio.open_connection(host, self._dtn_port), timeout=5
            )
            probe = self._sign_message({
                "type": "dtn_probe",
                "node_id": self.node_id,
                "dtn_port": self._dtn_port,
                "timestamp": time.time(),
            })
            w.write((json.dumps(probe) + "\n").encode())
            await w.drain()
            resp_data = await asyncio.wait_for(r.readline(), timeout=5)
            w.close()

            resp = json.loads(resp_data.decode().strip())
            if resp.get("type") == "dtn_probe_ack":
                sender = resp.get("node_id", "")
                if sender and sender != self.node_id:
                    routes = set(resp.get("routes", []))
                    self.upsert_link(sender, host, self._dtn_port, routes=routes)
                    return True
        except Exception:
            pass
        return False

    # ------------------------------------------------------------------
    # Route Table Exchange
    # ------------------------------------------------------------------

    def update_route_table(self, destination: str, next_hop: str) -> None:
        if destination not in self._route_table:
            self._route_table[destination] = []
        if next_hop not in self._route_table[destination]:
            self._route_table[destination].append(next_hop)
            self._route_table[destination] = self._route_table[destination][:3]  # keep top 3

    def find_route(self, destination: str) -> Optional[str]:
        """Find the best next-hop for a destination."""
        if destination in self._route_table:
            for hop in self._route_table[destination]:
                if hop in self._known_links and self._known_links[hop].is_alive:
                    return hop
        # Fall back: scan all links for direct connection
        for node_id, ls in self._known_links.items():
            if ls.is_alive and destination in ls.routes:
                return node_id
            if ls.is_alive and destination == node_id:
                return node_id
        return None

    # ------------------------------------------------------------------
    # Cleanup
    # ------------------------------------------------------------------

    async def _cleanup_loop(self) -> None:
        while self._running:
            await asyncio.sleep(EPHEMERAL_TIMEOUT // 2)
            stale = [nid for nid, ls in self._known_links.items()
                     if not ls.is_alive]
            for nid in stale:
                logger.debug("Forgot stale ephemeral peer: %s", nid)
                self.remove_link(nid)

    def status(self) -> Dict[str, Any]:
        return {
            "peers_alive": self.known_peers,
            "total_known": len(self._known_links),
            "routes_tracked": len(self._route_table),
            "links": [ls.to_dict() for ls in self.links[:10]],
        }


# ---------------------------------------------------------------------------
# DTN Router — Multi-Hop Path Computation
# ---------------------------------------------------------------------------

class DTNRouter:
    """
    Multi-hop DTN routing with link-state awareness.

    Routing strategy:
      1. Direct delivery — if destination is a known peer, send directly
      2. Route table lookup — if destination is in route table, forward via next-hop
      3. Gossip flood — if destination unknown, broadcast to all known peers
         (limited by TTL/hop count)
      4. Store-and-forward — if no route available, store for later delivery
    """

    def __init__(self, node_id: str, discovery: EphemeralDiscovery):
        self.node_id = node_id
        self._discovery = discovery

    def route_bundle(self, bundle: DTNBundle) -> Optional[str]:
        """
        Determine the next-hop node_id for a bundle.
        Returns None if no route is available (store-and-forward).
        """
        dest = bundle.primary.destination

        # Direct delivery
        link = self._discovery.get_link(dest)
        if link and link.is_alive:
            return dest

        # Route table lookup
        next_hop = self._discovery.find_route(dest)
        if next_hop:
            return next_hop

        # Broadcast/gossip flood to all known peers (with hop check)
        if bundle.primary.hop_count < bundle.primary.max_hops:
            alive = self._discovery.links
            if alive:
                # Pick the peer with the best quality
                best = max(alive, key=lambda ls: ls.quality)
                return best.node_id

        return None

    def get_route_info(self) -> Dict[str, Any]:
        """Return routing table for advertising to peers."""
        info = {}
        for node_id, ls in self._discovery._known_links.items():
            if ls.is_alive:
                info[node_id] = {
                    "host": ls.host,
                    "port": ls.port,
                    "hops": ls.hop_count,
                    "quality": ls.quality,
                }
        return info


# ---------------------------------------------------------------------------
# Custody Manager
# ---------------------------------------------------------------------------

class CustodyManager:
    """
    Manages custody transfer lifecycle (RFC 9171 §5.11).

    Flow:
      1. Sender sends bundle with custody_transfer=True
      2. Receiver accepts custody → sends CUSTODY_ACCEPT signal
      3. Sender releases custody on receipt of signal
      4. If custody signal not received within timeout → retransmit
      5. Receiver sends CUSTODY_RELEASE on final delivery
    """

    def __init__(self, node_id: str, store: BundleStore):
        self.node_id = node_id
        self._store = store
        self._pending_signals: Dict[str, CustodySignal] = {}  # bundle_id -> signal waiting for ack
        self._custody_accepted: Set[str] = set()  # bundle_ids we hold custody for

    def accept_custody(self, bundle: DTNBundle) -> CustodySignal:
        """Accept custody of a bundle. Returns signal to send back."""
        self._custody_accepted.add(bundle.bundle_id)
        bundle.current_custodian = self.node_id
        bundle.bundle_status = BundleStatus.CUSTODY_ACCEPTED
        self._store.save(bundle)
        return CustodySignal(
            bundle_id=bundle.bundle_id,
            signal_type=CUSTODY_ACCEPT,
            owner=self.node_id,
            timestamp=time.time(),
            reason="Custody accepted",
        )

    def release_custody(self, bundle_id: str, reason: str = "Delivered") -> CustodySignal:
        """Release custody after delivery. Returns signal to send back."""
        self._custody_accepted.discard(bundle_id)
        return CustodySignal(
            bundle_id=bundle_id,
            signal_type=CUSTODY_ACCEPT,
            owner=self.node_id,
            timestamp=time.time(),
            reason=reason,
        )

    def handle_signal(self, signal: CustodySignal, bundle: DTNBundle) -> None:
        """Process an incoming custody signal."""
        if signal.signal_type == CUSTODY_ACCEPT:
            logger.debug("Custody accepted for %s by %s", bundle.bundle_id, signal.owner)
            bundle.bundle_status = BundleStatus.CUSTODY_ACCEPTED
            bundle.current_custodian = signal.owner
            self._store.save(bundle)
            self._pending_signals.pop(bundle.bundle_id, None)
        elif signal.signal_type in (CUSTODY_REDUNDANT, CUSTODY_CAPACITY, CUSTODY_UNREACHABLE):
            logger.warning("Custody refused for %s by %s: %s",
                           bundle.bundle_id, signal.owner, signal.reason)
            bundle.bundle_status = BundleStatus.PENDING
            bundle.custody_retries += 1
            self._store.save(bundle)

    def needs_retransmit(self, bundle: DTNBundle) -> bool:
        """Check if a custody bundle needs retransmission."""
        if not bundle.primary.custody_transfer:
            return False
        if bundle.custody_retries >= CUSTODY_RETRY_MAX:
            return False
        if bundle.bundle_status == BundleStatus.CUSTODY_ACCEPTED:
            return False
        if bundle.bundle_status == BundleStatus.DELIVERED:
            return False
        return True

    @property
    def custody_count(self) -> int:
        return len(self._custody_accepted)


# ---------------------------------------------------------------------------
# DTN Node — Main Orchestrator
# ---------------------------------------------------------------------------

class DTNNode:
    """
    Main DTN node that integrates store-and-forward, custody transfer,
    ephemeral discovery, and multi-hop routing into a single async service.

    Usage:
        node = DTNNode(node_id="alpha", identity=identity)
        await node.start()

        # Send a bundle
        bid = await node.send({"msg": "hello"}, destination="beta")

        # Receive bundles via callback
        @node.on_bundle
        async def handler(bundle):
            print(bundle.payload.payload)
    """

    def __init__(self, node_id: str, identity: Any,
                 store_dir: Path = BUNDLE_STORE_DIR,
                 dtn_port: int = DTN_PORT,
                 discovery_port: int = DTN_DISCOVERY_PORT):
        self.node_id = node_id
        self._identity = identity
        self._dtn_port = dtn_port
        self._discovery_port = discovery_port

        # Sub-components
        self.store = BundleStore(store_dir=store_dir)
        self.discovery = EphemeralDiscovery(node_id, identity,
                                             discovery_port=discovery_port,
                                             dtn_port=dtn_port)
        self.router = DTNRouter(node_id, self.discovery)
        self.custody = CustodyManager(node_id, self.store)

        # Server
        self._server: Optional[asyncio.AbstractServer] = None
        self._running = False

        # Bundle delivery callback
        self._bundle_handler: Optional[Callable] = None

        # In-flight delivery tracking
        self._in_flight: Dict[str, float] = {}  # bundle_id -> sent_at

        # Link discovery callback (sync wrapper for the async handler)
        self.discovery.on_peer_discovered(self._on_peer_found_sync)

    # ------------------------------------------------------------------
    # Callback Registration
    # ------------------------------------------------------------------

    def on_bundle(self, handler: Callable) -> None:
        self._bundle_handler = handler

    async def _on_peer_found(self, node_id: str, host: str, port: int) -> None:
        """Callback when a new ephemeral peer is discovered."""
        logger.info("DTN peer discovered: %s @ %s:%d", node_id, host, port)
        pending = self.store.list_pending(destination=node_id)
        for bundle in pending:
            await self._forward_bundle(bundle, node_id, host, port)

    def _on_peer_found_sync(self, node_id: str, host: str, port: int) -> None:
        """Synchronous entry point for peer discovery callback.
        Spawns an async task so the coroutine is actually executed."""
        if self._running:
            asyncio.create_task(self._on_peer_found(node_id, host, port))

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self, host: str = "0.0.0.0", port: Optional[int] = None) -> None:
        self._running = True
        listen_port = port or self._dtn_port

        self._server = await asyncio.start_server(
            self._handle_connection, host, listen_port
        )
        logger.info("DTN node %s listening on %s:%d", self.node_id, host, listen_port)

        # Start sub-components
        await self.discovery.start()

        # Background loops
        asyncio.create_task(self._store_flush_loop())
        asyncio.create_task(self._custody_retransmit_loop())
        asyncio.create_task(self._expiry_loop())

    async def stop(self) -> None:
        self._running = False
        await self.discovery.stop()
        if self._server:
            self._server.close()
            await self._server.wait_closed()

    # ------------------------------------------------------------------
    # Send API
    # ------------------------------------------------------------------

    async def send(self, payload: Dict[str, Any], destination: str,
                   custody_transfer: bool = True,
                   lifetime: float = DEFAULT_TTL) -> str:
        """Create and send a DTN bundle. Returns bundle_id."""
        bundle = create_bundle(
            payload=payload,
            source=self.node_id,
            destination=destination,
            custody_transfer=custody_transfer,
            lifetime=lifetime,
        )
        self.store.save(bundle)
        await self._attempt_delivery(bundle)
        return bundle.bundle_id

    async def send_bundle(self, bundle: DTNBundle) -> None:
        """Send a pre-constructed bundle (used for forwarding)."""
        self.store.save(bundle)
        await self._attempt_delivery(bundle)

    # ------------------------------------------------------------------
    # Connection Handler (TCP Transport)
    # ------------------------------------------------------------------

    async def _handle_connection(self, reader: asyncio.StreamReader,
                                  writer: asyncio.StreamWriter) -> None:
        peer_addr = writer.get_extra_info("peername")
        try:
            data = await asyncio.wait_for(reader.readline(), timeout=30)
            if not data:
                writer.close()
                return

            msg = json.loads(data.decode().strip())
            msg_type = msg.get("type", "")

            if msg_type == "dtn_probe":
                await self._handle_probe(msg, writer, peer_addr)
            elif msg_type == "dtn_bundle":
                await self._handle_bundle(msg, writer, peer_addr)
            elif msg_type == "dtn_custody_signal":
                await self._handle_custody_signal(msg, writer, peer_addr)
            elif msg_type == "dtn_bundle_request":
                await self._handle_bundle_request(msg, writer, peer_addr)
            else:
                logger.debug("Unknown DTN message type: %s", msg_type)

        except (asyncio.TimeoutError, json.JSONDecodeError, ConnectionResetError):
            pass
        except Exception as e:
            logger.debug("DTN connection error: %s", e)
        finally:
            writer.close()

    async def _handle_probe(self, msg: Dict[str, Any], writer: asyncio.StreamWriter,
                             peer_addr: Tuple) -> None:
        sender = msg.get("node_id", "")
        if sender == self.node_id:
            return

        ack = {
            "type": "dtn_probe_ack",
            "node_id": self.node_id,
            "routes": list(self.router.get_route_info().keys()),
            "timestamp": time.time(),
        }
        raw = json.dumps(ack)
        self.discovery.upsert_link(sender, peer_addr[0], self._dtn_port)

        writer.write((raw + "\n").encode())
        await writer.drain()

        # Flush pending bundles for this peer
        pending = self.store.list_pending(destination=sender)
        for bundle in pending:
            await self._forward_bundle_now(bundle, sender, peer_addr[0], self._dtn_port, writer)

    async def _handle_bundle(self, msg: Dict[str, Any], writer: asyncio.StreamWriter,
                              peer_addr: Tuple) -> None:
        bundle = DTNBundle.deserialize(msg["bundle"])
        bundle.previous_node = msg.get("sender", "")

        # Discover the sender as an ephemeral peer
        sender = msg.get("sender", bundle.previous_node)
        if sender and sender != self.node_id:
            self.discovery.upsert_link(sender, peer_addr[0], self._dtn_port)

        # Update route table based on previous_node
        if sender:
            self.discovery.update_route_table(sender, sender)

        # Check if this bundle is for us
        dest = bundle.primary.destination
        if dest == self.node_id or dest == "*" or dest == "":
            # Deliver locally
            await self._deliver_bundle(bundle)
            if bundle.primary.custody_transfer:
                signal = self.custody.accept_custody(bundle)
                signal_msg = {
                    "type": "dtn_custody_signal",
                    "signal": signal.to_dict(),
                    "bundle_id": bundle.bundle_id,
                }
                writer.write((json.dumps(signal_msg) + "\n").encode())
                await writer.drain()
            else:
                ack = {"type": "dtn_ack", "bundle_id": bundle.bundle_id}
                writer.write((json.dumps(ack) + "\n").encode())
                await writer.drain()
        else:
            # Multi-hop forward
            bundle.primary.hop_count += 1
            if bundle.primary.hop_count > bundle.primary.max_hops:
                logger.warning("Bundle %s exceeded max hops, dropping", bundle.bundle_id)
                return

            self.store.save(bundle)
            if bundle.primary.custody_transfer:
                signal = self.custody.accept_custody(bundle)
                signal_msg = {
                    "type": "dtn_custody_signal",
                    "signal": signal.to_dict(),
                    "bundle_id": bundle.bundle_id,
                }
                writer.write((json.dumps(signal_msg) + "\n").encode())
                await writer.drain()

            await self._attempt_delivery(bundle)

    async def _handle_custody_signal(self, msg: Dict[str, Any],
                                      writer: asyncio.StreamWriter,
                                      peer_addr: Tuple) -> None:
        signal = CustodySignal.from_dict(msg["signal"])
        bundle = self.store.get(signal.bundle_id)
        if bundle:
            self.custody.handle_signal(signal, bundle)
            ack = {"type": "dtn_signal_ack", "bundle_id": signal.bundle_id}
            writer.write((json.dumps(ack) + "\n").encode())
            await writer.drain()

    async def _handle_bundle_request(self, msg: Dict[str, Any],
                                      writer: asyncio.StreamWriter,
                                      peer_addr: Tuple) -> None:
        """Peer is requesting pending bundles."""
        sender = msg.get("node_id", "")
        bundles = self.store.list_for_forwarding(sender)
        for bundle in bundles[:10]:  # limit to 10 per request
            resp = {
                "type": "dtn_bundle",
                "sender": self.node_id,
                "bundle": bundle.serialize(),
            }
            writer.write((json.dumps(resp) + "\n").encode())
            await writer.drain()

    # ------------------------------------------------------------------
    # Bundle Delivery
    # ------------------------------------------------------------------

    async def _deliver_bundle(self, bundle: DTNBundle) -> None:
        """Deliver a bundle to the local application."""
        if bundle.bundle_status == BundleStatus.DELIVERED:
            return
        bundle.bundle_status = BundleStatus.DELIVERED
        self.store.remove(bundle.bundle_id)
        logger.info("Bundle %s delivered", bundle.bundle_id)

        # Release custody back to previous custodian
        if bundle.current_custodian and bundle.current_custodian != self.node_id:
            signal = self.custody.release_custody(bundle.bundle_id, "Delivered")
            await self.send_signal(signal, bundle.current_custodian)

        if self._bundle_handler:
            try:
                if asyncio.iscoroutinefunction(self._bundle_handler):
                    await self._bundle_handler(bundle)
                else:
                    self._bundle_handler(bundle)
            except Exception as e:
                logger.error("Bundle handler error: %s", e)

    async def send_signal(self, signal: CustodySignal, destination: str) -> None:
        """Send a custody signal to a specific peer."""
        link = self.discovery.get_link(destination)
        if not link or not link.is_alive:
            logger.debug("Cannot send signal to %s: peer unreachable", destination)
            return
        try:
            r, w = await asyncio.wait_for(
                asyncio.open_connection(link.host, link.port), timeout=5
            )
            msg = {
                "type": "dtn_custody_signal",
                "signal": signal.to_dict(),
                "bundle_id": signal.bundle_id,
            }
            w.write((json.dumps(msg) + "\n").encode())
            await w.drain()
            await asyncio.wait_for(r.readline(), timeout=5)
            w.close()
        except Exception as e:
            logger.debug("Signal send failed: %s", e)

    # ------------------------------------------------------------------
    # Delivery Attempt
    # ------------------------------------------------------------------

    async def _attempt_delivery(self, bundle: DTNBundle) -> bool:
        """Try to deliver or forward a bundle. Returns True if forwarded."""
        if bundle.primary.is_expired:
            bundle.bundle_status = BundleStatus.EXPIRED
            self.store.remove(bundle.bundle_id)
            return False

        dest = bundle.primary.destination

        # Short-circuit: if destination is local, deliver directly
        if dest == self.node_id or dest == "*" or dest == "":
            await self._deliver_bundle(bundle)
            return True

        next_hop = self.router.route_bundle(bundle)
        if next_hop is None:
            logger.debug("Bundle %s queued (no route to %s)",
                         bundle.bundle_id, dest)
            return False

        link = self.discovery.get_link(next_hop)
        if not link or not link.is_alive:
            return False

        return await self._forward_bundle(bundle, next_hop, link.host, link.port)

    async def _forward_bundle(self, bundle: DTNBundle, next_hop: str,
                               host: str, port: int) -> bool:
        """Forward a bundle to a specific peer."""
        bundle.bundle_status = BundleStatus.IN_FLIGHT
        bundle.previous_node = self.node_id
        self._in_flight[bundle.bundle_id] = time.time()
        self.store.save(bundle)

        try:
            r, w = await asyncio.wait_for(
                asyncio.open_connection(host, port), timeout=5
            )
            return await self._forward_bundle_now(bundle, next_hop, host, port, w)
        except Exception as e:
            logger.debug("Forward %s to %s failed: %s", bundle.bundle_id, next_hop, e)
            bundle.bundle_status = BundleStatus.PENDING
            self.store.save(bundle)
            return False

    async def _forward_bundle_now(self, bundle: DTNBundle, next_hop: str,
                                   host: str, port: int,
                                   writer: asyncio.StreamWriter) -> bool:
        """Write a bundle to an already-open connection."""
        msg = {
            "type": "dtn_bundle",
            "sender": self.node_id,
            "bundle": bundle.serialize(),
        }
        try:
            writer.write((json.dumps(msg) + "\n").encode())
            await writer.drain()

            # Wait for ack or custody signal
            resp_data = await asyncio.wait_for(writer.readline(), timeout=10)
            resp = json.loads(resp_data.decode().strip())
            rtype = resp.get("type", "")
            if rtype == "dtn_custody_signal":
                signal = CustodySignal.from_dict(resp["signal"])
                self.custody.handle_signal(signal, bundle)
            elif rtype == "dtn_ack":
                bundle.bundle_status = BundleStatus.CUSTODY_ACCEPTED
                self.store.save(bundle)

            self._in_flight.pop(bundle.bundle_id, None)
            self.discovery.upsert_link(next_hop, host, port)
            return True
        except Exception as e:
            logger.debug("Forward write failed: %s", e)
            bundle.bundle_status = BundleStatus.PENDING
            self.store.save(bundle)
            return False

    # ------------------------------------------------------------------
    # Background Loops
    # ------------------------------------------------------------------

    async def _store_flush_loop(self) -> None:
        """Periodically retry delivery of stored bundles."""
        while self._running:
            await asyncio.sleep(STORE_FLUSH_INTERVAL)
            pending = self.store.list_pending()
            for bundle in pending:
                if bundle.primary.is_expired:
                    self.store.remove(bundle.bundle_id)
                    continue
                await self._attempt_delivery(bundle)

    async def _custody_retransmit_loop(self) -> None:
        """Retransmit bundles whose custody signal was not received."""
        while self._running:
            await asyncio.sleep(CUSTODY_TIMEOUT // 2)
            for bundle in self.store.list_pending():
                if self.custody.needs_retransmit(bundle):
                    logger.debug("Retransmitting bundle %s (retry %d/%d)",
                                 bundle.bundle_id, bundle.custody_retries,
                                 CUSTODY_RETRY_MAX)
                    await self._attempt_delivery(bundle)

    async def _expiry_loop(self) -> None:
        """Periodically clean up expired bundles."""
        while self._running:
            await asyncio.sleep(60)
            removed = self.store.expire_stale()
            if removed:
                logger.debug("Expired %d stale bundles", removed)

    # ------------------------------------------------------------------
    # Status
    # ------------------------------------------------------------------

    @property
    def status(self) -> Dict[str, Any]:
        return {
            "node_id": self.node_id,
            "running": self._running,
            "pending_bundles": self.store.pending_count,
            "total_bundles": self.store.total_count,
            "custody_accepted": self.custody.custody_count,
            "in_flight": len(self._in_flight),
            "links": self.discovery.status(),
            "routes": list(self.router.get_route_info().keys()),
        }
