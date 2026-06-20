"""
Delay-Tolerant Networking (DTN) — Interplanetary-grade store-and-forward.
Bundles are buffered persistently until a handshake-free link (radio/laser/
satellite) becomes available. Implements Bundle Protocol (RFC 5050) semantics.
"""

import asyncio
import json
import os
import struct
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Set

from logging_system import get_logger

logger = get_logger("Stealth.DTN")

_BASE_DIR = Path(__file__).resolve().parent.parent
_BUNDLE_STORE = _BASE_DIR / "agent_data" / "dtn_bundles"


@dataclass
class DTNBundle:
    """
    A DTN bundle (RFC 5050 compatible) — carries opaque payload with
    custody transfer semantics. Indefinite TTL for deep-space persistence.
    """
    bundle_id: str
    source: str
    destination: str
    payload: bytes
    creation_timestamp: float = 0.0
    custody_count: int = 0
    hop_count: int = 0
    priority: int = 1
    expiration: float = float("inf")
    fragment: bool = False
    fragment_offset: int = 0
    fragment_length: int = 0
    custom_headers: Dict[str, str] = field(default_factory=dict)

    def __post_init__(self):
        if not self.creation_timestamp:
            self.creation_timestamp = time.time()

    @property
    def age(self) -> float:
        return time.time() - self.creation_timestamp

    @property
    def expired(self) -> bool:
        return time.time() > self.expiration

    @property
    def is_fragment(self) -> bool:
        return self.fragment

    def to_bytes(self) -> bytes:
        headers = json.dumps({
            "id": self.bundle_id,
            "src": self.source,
            "dst": self.destination,
            "ts": self.creation_timestamp,
            "custody": self.custody_count,
            "hop": self.hop_count,
            "pri": self.priority,
            "exp": self.expiration,
            "frag": self.fragment,
            "foff": self.fragment_offset,
            "flen": self.fragment_length,
            "ch": self.custom_headers,
        }).encode("utf-8")

        return (
            struct.pack("!I", len(headers)) +
            headers +
            struct.pack("!I", len(self.payload)) +
            self.payload
        )

    @staticmethod
    def from_bytes(data: bytes) -> Optional["DTNBundle"]:
        try:
            off = 0
            hdr_len = struct.unpack_from("!I", data, off)[0]
            off += 4

            headers = json.loads(data[off:off + hdr_len].decode("utf-8"))
            off += hdr_len

            payload_len = struct.unpack_from("!I", data, off)[0]
            off += 4
            payload = data[off:off + payload_len]

            return DTNBundle(
                bundle_id=headers["id"],
                source=headers["src"],
                destination=headers["dst"],
                payload=payload,
                creation_timestamp=headers["ts"],
                custody_count=headers.get("custody", 0),
                hop_count=headers.get("hop", 0),
                priority=headers.get("pri", 1),
                expiration=headers.get("exp", float("inf")),
                fragment=headers.get("frag", False),
                fragment_offset=headers.get("foff", 0),
                fragment_length=headers.get("flen", 0),
                custom_headers=headers.get("ch", {}),
            )
        except (IndexError, json.JSONDecodeError, struct.error, KeyError):
            return None

    def serialize(self) -> bytes:
        return self.to_bytes()

    @staticmethod
    def deserialize(data: bytes) -> Optional["DTNBundle"]:
        return DTNBundle.from_bytes(data)


class BundleStore:
    """Persistent, crash-safe bundle storage on disk."""

    def __init__(self, store_path: Optional[Path] = None):
        self.path = store_path or _BUNDLE_STORE
        self.path.mkdir(parents=True, exist_ok=True)
        self._lock = asyncio.Lock()

    async def save(self, bundle: DTNBundle) -> None:
        async with self._lock:
            bundle_path = self.path / f"{bundle.bundle_id}.bundle"
            try:
                bundle_path.write_bytes(bundle.to_bytes())
                logger.debug("DTN: bundle %s saved (%d bytes)",
                             bundle.bundle_id[:12], len(bundle.payload))
            except Exception as e:
                logger.error("DTN: failed to save bundle %s: %s",
                             bundle.bundle_id[:12], e)

    async def load(self, bundle_id: str) -> Optional[DTNBundle]:
        bundle_path = self.path / f"{bundle_id}.bundle"
        try:
            if bundle_path.exists():
                data = bundle_path.read_bytes()
                return DTNBundle.from_bytes(data)
        except Exception as e:
            logger.warning("DTN: failed to load bundle %s: %s", bundle_id[:12], e)
        return None

    async def delete(self, bundle_id: str) -> None:
        async with self._lock:
            bundle_path = self.path / f"{bundle_id}.bundle"
            try:
                if bundle_path.exists():
                    bundle_path.unlink()
            except Exception as e:
                logger.warning("DTN: failed to delete bundle %s: %s",
                               bundle_id[:12], e)

    async def list_bundles(self) -> List[str]:
        return [p.stem for p in self.path.glob("*.bundle")]

    async def count(self) -> int:
        return len([p for p in self.path.glob("*.bundle")])


class DelayTolerantNetwork:
    """
    DTN engine — indefinitely buffers outbound bundles until a link becomes
    available. No handshake required: bundles are forwarded opportunistically.
    Implements custody transfer: each hop takes responsibility.
    """

    def __init__(self, node_id: str = "ghost-dtn", store: Optional[BundleStore] = None):
        self.node_id = node_id
        self.store = store or BundleStore()
        self._running = False
        self._task: Optional[asyncio.Task] = None
        self._link_available: Optional[Callable[[], bool]] = None
        self._transmit_hook: Optional[Callable[[DTNBundle], Any]] = None
        self._pending_acks: Set[str] = set()

    def set_link_detector(self, detector: Callable[[], bool]) -> None:
        """Set a callback that returns True when a radio/laser/satellite link is available."""
        self._link_available = detector

    def set_transmit_hook(self, hook: Callable[[DTNBundle], Any]) -> None:
        """Set a callback that physically transmits a bundle over the available link."""
        self._transmit_hook = hook

    async def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._forwarding_loop())
        logger.info("DTN: engine started (node=%s, store=%s)",
                     self.node_id, self.store.path)

    async def stop(self) -> None:
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("DTN: engine stopped (%d bundles in store)",
                     await self.store.count())

    async def enqueue(self, destination: str, payload: bytes,
                       priority: int = 1, fragment: bool = False,
                       ttl: Optional[float] = None) -> str:
        bundle_id = str(uuid.uuid4())
        bundle = DTNBundle(
            bundle_id=bundle_id,
            source=self.node_id,
            destination=destination,
            payload=payload,
            priority=priority,
            expiration=(time.time() + ttl) if ttl else float("inf"),
            fragment=fragment,
        )
        await self.store.save(bundle)
        logger.info("DTN: enqueued bundle %s -> %s (%d bytes, pri=%d)",
                     bundle_id[:12], destination, len(payload), priority)
        return bundle_id

    async def _forwarding_loop(self) -> None:
        while self._running:
            try:
                link_ok = self._link_available() if self._link_available else False
                if link_ok and self._transmit_hook:
                    await self._forward_queued()
                else:
                    await self._maintenance()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.warning("DTN: forwarding loop error: %s", e)

            await asyncio.sleep(5)

    async def _forward_queued(self) -> None:
        bundle_ids = await self.store.list_bundles()
        if not bundle_ids:
            return

        bundles: List[DTNBundle] = []
        for bid in bundle_ids:
            b = await self.store.load(bid)
            if b and not b.expired:
                bundles.append(b)
            elif b and b.expired:
                await self.store.delete(bid)

        bundles.sort(key=lambda b: (-b.priority, b.creation_timestamp))

        for bundle in bundles[:10]:
            try:
                bundle.custody_count += 1
                bundle.hop_count += 1

                if asyncio.iscoroutinefunction(self._transmit_hook):
                    await self._transmit_hook(bundle)
                else:
                    self._transmit_hook(bundle)

                await self.store.delete(bundle.bundle_id)
                logger.info("DTN: forwarded bundle %s -> %s (hop=%d, custody=%d)",
                             bundle.bundle_id[:12], bundle.destination,
                             bundle.hop_count, bundle.custody_count)
            except Exception as e:
                logger.warning("DTN: failed to forward bundle %s: %s — re-queued",
                               bundle.bundle_id[:12], e)

    async def _maintenance(self) -> None:
        bundle_ids = await self.store.list_bundles()
        expired = 0
        for bid in bundle_ids:
            b = await self.store.load(bid)
            if b and b.expired:
                await self.store.delete(bid)
                expired += 1
        if expired:
            logger.debug("DTN: purged %d expired bundles", expired)

    async def receive_bundle(self, data: bytes) -> Optional[DTNBundle]:
        bundle = DTNBundle.from_bytes(data)
        if bundle:
            logger.info("DTN: received bundle %s from %s (%d bytes, hop=%d)",
                         bundle.bundle_id[:12], bundle.source,
                         len(bundle.payload), bundle.hop_count)
            if bundle.destination == self.node_id:
                return bundle
            else:
                await self.store.save(bundle)
                logger.info("DTN: forwarded bundle %s -> %s (custody transfer)",
                             bundle.bundle_id[:12], bundle.destination)
        return None

    @property
    def status(self) -> Dict[str, Any]:
        return {
            "node_id": self.node_id,
            "running": self._running,
            "bundles_queued": None,
            "link_available": self._link_available() if self._link_available else False,
            "transmit_hook_set": self._transmit_hook is not None,
        }

    async def bundle_count(self) -> int:
        return await self.store.count()
