"""
Ghost Ledger — Distributed Blockchain Consensus for Swarm State
================================================================
A lightweight, append-only ledger that records swarm events
(NODE_ADDED, NODE_REMOVED, TASK_ASSIGNED) with cryptographic
linking. Each entry is hashed to the previous entry, forming
an immutable chain. The ledger is synced across the mesh via
the gossip protocol.
"""

import hashlib
import json
import logging
import os
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "agent_data"
DATA_DIR.mkdir(exist_ok=True)
LEDGER_FILE = DATA_DIR / "swarm_ledger.json"

logger = logging.getLogger("GhostLedger")
if not logger.handlers:
    _h = logging.StreamHandler()
    _h.setFormatter(logging.Formatter("%(asctime)s | Ledger | %(message)s"))
    logger.addHandler(_h)
    logger.propagate = False


@dataclass
class LedgerEntry:
    """A single entry in the swarm ledger."""
    index: int
    timestamp: str
    event: str             # NODE_ADDED | NODE_REMOVED | TASK_ASSIGNED | CONSENSUS
    data: Dict[str, Any]
    previous_hash: str
    hash: str = ""

    def compute_hash(self) -> str:
        raw = f"{self.index}:{self.timestamp}:{self.event}:{json.dumps(self.data, sort_keys=True)}:{self.previous_hash}"
        return hashlib.sha256(raw.encode()).hexdigest()

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "LedgerEntry":
        return cls(**d)


class SwarmLedger:
    """
    Immutable, append-only ledger for swarm consensus.
    Each entry is cryptographically chained to the previous one.
    The full ledger is gossiped across the mesh for distributed agreement.
    """

    def __init__(self):
        self._chain: List[LedgerEntry] = []
        self._load()

    # ── Genesis ──

    def _genesis(self) -> LedgerEntry:
        return LedgerEntry(
            index=0,
            timestamp=datetime.now(timezone.utc).isoformat(),
            event="GENESIS",
            data={"swarm": "Ghost Mesh", "version": "1.0.0"},
            previous_hash="0" * 64,
        )

    # ── Append ──

    def append(self, event: str, data: Dict[str, Any]) -> LedgerEntry:
        """Append a new entry to the ledger."""
        previous = self._chain[-1] if self._chain else self._genesis()
        entry = LedgerEntry(
            index=previous.index + 1,
            timestamp=datetime.now(timezone.utc).isoformat(),
            event=event,
            data=data,
            previous_hash=previous.hash or previous.compute_hash(),
        )
        entry.hash = entry.compute_hash()
        self._chain.append(entry)
        self._save()
        logger.info("Ledger: #%d %s (%s)", entry.index, event,
                     json.dumps(data).replace('"', "'")[:60])
        return entry

    # ── Queries ──

    def get_chain(self) -> List[LedgerEntry]:
        return self._chain

    def get_events(self, event_type: str) -> List[LedgerEntry]:
        return [e for e in self._chain if e.event == event_type]

    def get_node_count(self) -> int:
        """Count currently active nodes from ledger events."""
        added = len(self.get_events("NODE_ADDED"))
        removed = len(self.get_events("NODE_REMOVED"))
        return max(0, added - removed)

    def verify_chain(self) -> bool:
        """Verify the cryptographic integrity of the entire chain."""
        for i in range(1, len(self._chain)):
            current = self._chain[i]
            previous = self._chain[i - 1]
            expected_prev = previous.hash or previous.compute_hash()
            if current.previous_hash != expected_prev:
                logger.error("Chain broken at entry %d", current.index)
                return False
            if current.hash != current.compute_hash():
                logger.error("Hash mismatch at entry %d", current.index)
                return False
        return True

    def get_summary(self) -> Dict[str, Any]:
        total_nodes_added = len(self.get_events("NODE_ADDED"))
        total_nodes_removed = len(self.get_events("NODE_REMOVED"))
        return {
            "chain_length": len(self._chain),
            "active_nodes": max(0, total_nodes_added - total_nodes_removed),
            "total_nodes_added": total_nodes_added,
            "total_nodes_removed": total_nodes_removed,
            "chain_integrity": self.verify_chain(),
            "last_entry": self._chain[-1].to_dict() if self._chain else None,
        }

    # ── Persistence ──

    def _save(self) -> None:
        try:
            data = [e.to_dict() for e in self._chain]
            LEDGER_FILE.write_text(json.dumps(data, indent=2, default=str))
        except Exception as e:
            logger.error("Ledger save failed: %s", e)

    def _load(self) -> None:
        try:
            if LEDGER_FILE.exists():
                data = json.loads(LEDGER_FILE.read_text())
                self._chain = [LedgerEntry.from_dict(e) for e in data]
                logger.info("Ledger loaded: %d entries", len(self._chain))
        except Exception as e:
            logger.warning("Ledger load failed (starting fresh): %s", e)
            self._chain = []

    def merge(self, remote_chain: List[Dict[str, Any]]) -> int:
        """
        Merge a remote ledger chain into this one (gossip sync).
        Returns number of new entries merged.
        """
        remote = [LedgerEntry.from_dict(e) for e in remote_chain]
        if not remote:
            return 0

        # Find fork point
        local_indices = {e.index: e.hash for e in self._chain}
        merge_point = -1
        for i, entry in enumerate(remote):
            if entry.index in local_indices:
                if local_indices[entry.index] == entry.hash:
                    merge_point = i
                else:
                    break

        new_entries = remote[merge_point + 1:]
        if not new_entries:
            return 0

        for entry in new_entries:
            if entry.index > (self._chain[-1].index if self._chain else -1):
                self._chain.append(entry)

        self._save()
        logger.info("Ledger merged: %d new entries", len(new_entries))
        return len(new_entries)


# ── Module-level singleton ──

_ledger: Optional[SwarmLedger] = None


def get_ledger() -> SwarmLedger:
    """Get or create the swarm ledger singleton."""
    global _ledger
    if _ledger is None:
        _ledger = SwarmLedger()
    return _ledger


def update_ledger(event: str, data: Any) -> Dict[str, Any]:
    """
    Record an event in the swarm ledger.
    
    Args:
        event: Event type (NODE_ADDED, NODE_REMOVED, TASK_ASSIGNED, CONSENSUS)
        data: Event payload (string, dict, or list)
    
    Returns:
        The created LedgerEntry as a dict
    """
    ledger = get_ledger()
    if not isinstance(data, dict):
        data = {"value": str(data)}
    entry = ledger.append(event, data)
    return entry.to_dict()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)

    # Demo
    ledger = get_ledger()

    update_ledger("NODE_ADDED", {"host": "192.168.1.100", "node_id": "ghost-a1b2"})
    update_ledger("NODE_ADDED", {"host": "10.0.0.5", "node_id": "ghost-c3d4"})
    update_ledger("TASK_ASSIGNED", {"task_id": "t-001", "node": "ghost-a1b2", "command": "scan"})
    update_ledger("NODE_REMOVED", {"host": "10.0.0.5", "reason": "unreachable"})

    summary = ledger.get_summary()
    print(f"\nLedger Summary:")
    print(f"  Chain length: {summary['chain_length']}")
    print(f"  Active nodes: {summary['active_nodes']}")
    print(f"  Integrity: {'PASS' if summary['chain_integrity'] else 'FAIL'}")
    print(f"  Last entry: {json.dumps(summary['last_entry'], indent=2, default=str)}")
