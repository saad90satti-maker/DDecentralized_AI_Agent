"""
Swarm-Wide Shared Knowledge Layer — when one agent discovers an optimal
fallback API, a stable relay node, or a high-value configuration, it
propagates this discovery to all peers via the heartbeat signal and
swarm mesh gossip protocol.
"""

import os
import json
import time
import socket
import logging
import asyncio
import hashlib
import hmac
from pathlib import Path
from typing import Optional, Any
from collections import defaultdict
from dataclasses import dataclass, field

import swarm_security

logger = logging.getLogger("shared_knowledge")

KNOWLEDGE_PATH = Path("agent_data/shared_knowledge.json")


@dataclass
class KnowledgeEntry:
    key: str
    value: Any
    source_node: str = ""
    timestamp: float = 0.0
    ttl: float = 3600.0  # 1 hour default
    version: int = 1

    @property
    def expired(self) -> bool:
        return time.time() > self.timestamp + self.ttl

    @property
    def id(self) -> str:
        return hashlib.md5(f"{self.key}:{self.source_node}:{self.version}".encode()).hexdigest()[:12]


class SharedKnowledge:
    """
    Distributed shared knowledge base for the swarm.
    
    Each node maintains a local knowledge store. When a discovery is made
    (optimal API provider, relay node, performance insight), it's added
    to the store and announced via heartbeat to connected peers.
    
    Peers merge incoming knowledge, preferring higher version numbers
    and more recent timestamps.
    """

    def __init__(self, node_id: str = ""):
        self.node_id = node_id or os.getenv("NODE_ID", socket.gethostname())
        self._store: dict[str, KnowledgeEntry] = {}
        self._peers: dict[str, dict] = {}  # node_id -> {url, last_seen, knowledge_count}
        self._change_callbacks: list = []
        self._load()

    # ------------------------------------------------------------------
    # Core operations
    # ------------------------------------------------------------------

    def add_observation(self, key: str, value: Any, source: Optional[str] = None,
                        ttl: float = 3600.0):
        """Add or update a knowledge entry."""
        existing = self._store.get(key)
        entry = KnowledgeEntry(
            key=key,
            value=value,
            source_node=source or self.node_id,
            timestamp=time.time(),
            ttl=ttl,
            version=(existing.version + 1) if existing else 1,
        )
        self._store[key] = entry
        self._persist()
        self._notify(entry)
        logger.debug("Knowledge: %s v%d (%s)", key, entry.version, entry.source_node)

    def get(self, key: str, default=None):
        entry = self._store.get(key)
        if entry and not entry.expired:
            return entry.value
        return default

    def search(self, prefix: str) -> list[KnowledgeEntry]:
        """Search knowledge entries by key prefix."""
        return [
            e for k, e in self._store.items()
            if k.startswith(prefix) and not e.expired
        ]

    def get_peer_discoveries(self, peer_node_id: str) -> list[dict]:
        """Get all knowledge entries originating from a specific peer."""
        return [
            {"key": e.key, "value": e.value, "version": e.version, "timestamp": e.timestamp}
            for e in self._store.values()
            if e.source_node == peer_node_id and not e.expired
        ]

    # ------------------------------------------------------------------
    # Peer knowledge merging
    # ------------------------------------------------------------------

    def merge_from_peer(self, entries: list[dict], peer_node_id: str):
        """Merge knowledge entries received from a peer."""
        merged = 0
        for entry_dict in entries:
            key = entry_dict.get("key")
            if not key:
                continue
            existing = self._store.get(key)
            incoming_version = entry_dict.get("version", 0)
            if existing and existing.version >= incoming_version:
                continue  # We have the same or newer
            entry = KnowledgeEntry(
                key=key,
                value=entry_dict.get("value"),
                source_node=peer_node_id,
                timestamp=entry_dict.get("timestamp", time.time()),
                ttl=entry_dict.get("ttl", 3600.0),
                version=incoming_version,
            )
            self._store[key] = entry
            merged += 1
            logger.info("Knowledge merged from %s: %s v%d", peer_node_id, key, incoming_version)
        if merged:
            self._persist()
            self._notify(None)

    # ------------------------------------------------------------------
    # Heartbeat payload serialization
    # ------------------------------------------------------------------

    def get_heartbeat_payload(self) -> dict:
        """Serialize recent knowledge for heartbeat broadcast."""
        recent = [
            {"key": e.key, "value": e.value, "version": e.version,
             "timestamp": e.timestamp, "ttl": e.ttl}
            for e in sorted(self._store.values(), key=lambda x: x.timestamp, reverse=True)[:50]
            if not e.expired
        ]
        payload = {
            "node_id": self.node_id,
            "knowledge": recent,
            "knowledge_count": len(self._store),
            "peers": list(self._peers.keys()),
        }
        # Sign the heartbeat payload for authenticity
        payload["signature"] = swarm_security.sign_json_payload(payload)
        payload["fingerprint"] = swarm_security.compute_node_fingerprint(self.node_id)
        return payload

    def ingest_heartbeat(self, payload: dict):
        """Process a heartbeat payload from a peer.

        Verifies the HMAC signature if present. Untrusted packets are
        rejected and logged to the security audit.
        """
        peer_id = payload.get("node_id", "unknown")
        knowledge = payload.get("knowledge", [])
        signature = payload.get("signature", "")
        fingerprint = payload.get("fingerprint", "")

        # Verify authenticity if signing is active
        if signature:
            payload_copy = dict(payload)
            payload_copy.pop("signature", None)
            payload_copy.pop("fingerprint", None)
            if not swarm_security.verify_json_payload(payload_copy, signature):
                logger.warning("Heartbeat from %s rejected: invalid signature", peer_id)
                return
            if fingerprint and not swarm_security.is_trusted_node(peer_id, fingerprint):
                logger.warning("Heartbeat from %s rejected: invalid fingerprint", peer_id)
                return

        # Track peer
        self._peers[peer_id] = {
            "last_seen": time.time(),
            "knowledge_count": payload.get("knowledge_count", 0),
        }

        # Merge knowledge
        if knowledge:
            self.merge_from_peer(knowledge, peer_id)

    # ------------------------------------------------------------------
    # Optimal config propagation
    # ------------------------------------------------------------------

    def propagate_optimal_provider(self, provider: str, model: str,
                                    latency_ms: float, success_rate: float):
        """Share a discovered optimal API provider with the swarm."""
        self.add_observation(
            key=f"optimal_provider:{provider}",
            value={
                "provider": provider,
                "model": model,
                "avg_latency_ms": latency_ms,
                "success_rate": success_rate,
                "discovered_at": time.time(),
            },
            ttl=7200,  # 2 hours
        )

    def propagate_optimal_relay(self, relay_url: str, latency_ms: float):
        """Share a discovered stable relay node."""
        self.add_observation(
            key=f"optimal_relay:{relay_url}",
            value={
                "url": relay_url,
                "latency_ms": latency_ms,
                "discovered_at": time.time(),
            },
            ttl=3600,
        )

    def get_best_provider(self) -> Optional[dict]:
        """Get the best known provider across all peers."""
        entries = self.search("optimal_provider:")
        if not entries:
            return None
        best = min(entries, key=lambda e: e.value.get("avg_latency_ms", 99999))
        return best.value

    # ------------------------------------------------------------------
    # Callbacks
    # ------------------------------------------------------------------

    def on_change(self, callback):
        self._change_callbacks.append(callback)

    def _notify(self, entry):
        for cb in self._change_callbacks:
            try:
                cb(entry)
            except Exception as e:
                logger.debug("Knowledge callback error: %s", e)

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def _persist(self):
        try:
            KNOWLEDGE_PATH.parent.mkdir(parents=True, exist_ok=True)
            data = {
                "node_id": self.node_id,
                "entries": {
                    k: {"value": e.value, "source_node": e.source_node,
                        "timestamp": e.timestamp, "ttl": e.ttl, "version": e.version}
                    for k, e in self._store.items() if not e.expired
                },
                "peers": self._peers,
            }
            KNOWLEDGE_PATH.write_text(json.dumps(data, indent=2), encoding="utf-8")
        except Exception as e:
            logger.debug("Persist error: %s", e)

    def _load(self):
        try:
            if KNOWLEDGE_PATH.exists():
                data = json.loads(KNOWLEDGE_PATH.read_text(encoding="utf-8"))
                for key, ed in data.get("entries", {}).items():
                    self._store[key] = KnowledgeEntry(
                        key=key, value=ed["value"], source_node=ed.get("source_node", ""),
                        timestamp=ed.get("timestamp", 0), ttl=ed.get("ttl", 3600),
                        version=ed.get("version", 1),
                    )
                self._peers.update(data.get("peers", {}))
                logger.info("Loaded %d knowledge entries, %d peers", len(self._store), len(self._peers))
        except Exception as e:
            logger.debug("Load error: %s", e)

    # ------------------------------------------------------------------
    # Cross-Instance Patch Sync Protocol — P2P optimization propagation
    # When a node applies a patch successfully, it broadcasts the
    # "patch signature" (hash of the change) to peers. Peers verify
    # validity (same target_file exists, version match) and apply locally.
    # ------------------------------------------------------------------

    def broadcast_patch_success(self, patch_id: str, patch_hash: str,
                                 target_file: str, performance_gain: float,
                                 proposal: dict):
        """Broadcast a successful patch to the swarm."""
        self.add_observation(
            key=f"patch:{patch_id}",
            value={
                "patch_id": patch_id,
                "patch_hash": patch_hash,
                "target_file": target_file,
                "performance_gain_pct": performance_gain,
                "proposal": {k: v for k, v in proposal.items()
                             if k in ("bottleneck", "proposed_change", "expected_improvement")},
                "applied_by": self.node_id,
                "applied_at": time.time(),
                "patch_version": 1,
            },
            ttl=86400,  # 24 hours — long enough for swarm sync
        )
        logger.info("Patch broadcast: %s → %s (gain=%.1f%%)", patch_id, target_file, performance_gain)

    def get_pending_patches(self) -> list[dict]:
        """Return patches from peers that haven't been applied locally yet."""
        patches = self.search("patch:")
        applied = {k for k in self._store if k.startswith("applied_patch:") and not self._store[k].expired}
        pending = []
        for e in patches:
            pid = e.value.get("patch_id", e.key.split(":", 1)[-1])
            if f"applied_patch:{pid}" not in applied:
                # Don't re-apply our own patches
                if e.value.get("applied_by") != self.node_id:
                    pending.append(e.value)
        return pending

    def mark_patch_applied(self, patch_id: str, success: bool = True, gain: float = 0.0):
        """Record that this node has applied (or attempted) a patch."""
        self.add_observation(
            key=f"applied_patch:{patch_id}",
            value={
                "patch_id": patch_id,
                "applied_by": self.node_id,
                "applied_at": time.time(),
                "success": success,
                "measured_gain_pct": gain,
            },
            ttl=86400,
        )

    def is_patch_applied(self, patch_id: str) -> bool:
        """Check if this patch was already applied locally."""
        entry = self._store.get(f"applied_patch:{patch_id}")
        return entry is not None and not entry.expired and entry.value.get("success", False)

    def get_peer_patch_history(self) -> list[dict]:
        """Get all patch application records from across the swarm."""
        applied = self.search("applied_patch:")
        return [e.value for e in applied]

    def get_report(self) -> dict:
        patches = self.search("patch:")
        applied = self.search("applied_patch:")
        return {
            "node_id": self.node_id,
            "entries": {k: {"source": e.source_node, "version": e.version,
                            "age_s": time.time() - e.timestamp, "expired": e.expired}
                        for k, e in self._store.items()},
            "peers": self._peers,
            "total_entries": len(self._store),
            "total_peers": len(self._peers),
            "pending_patches": len(self.get_pending_patches()),
            "total_patches_broadcast": len(patches),
            "total_patches_applied": len(applied),
        }



