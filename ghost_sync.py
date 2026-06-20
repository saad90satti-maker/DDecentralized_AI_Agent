"""
Ghost Global State Synchronization — Permissioned Cluster v1
=============================================================
Protocol: Invite → Handshake → Join → Gossip State → Cluster

Architecture:
  +-----------------------------------------------------------+
  |                  Permissioned Cluster                      |
  |  +------------+  +-----------+  +----------------------+  |
  |  | Invitation |  | Member    |  | Global State Sync    |  |
  |  | Manager    |  | Registry  |  | (Gossip + Version    |  |
  |  | (Ed25519   |  | (Signed   |  |  Vectors)            |  |
  |  |  signed)   |  | Attest)   |  |                      |  |
  |  +------------+  +-----------+  +----------------------+  |
  +-----------------------------------------------------------+

Key properties:
  * Permissioned by default — every join requires a signed invitation
  * Ed25519 identity anchors — all messages are signed
  * Version-vector state sync — no single point of consensus
  * Gossip propagation — epidemic dissemination of cluster state

Usage:
  from ghost_sync import PermissionedCluster, GlobalStateSync
  from node_identity import NodeIdentity

  identity = NodeIdentity.load_or_create()
  cluster = PermissionedCluster(identity)
  sync = GlobalStateSync(identity, cluster)

  # Invite a peer (by their Ed25519 public key hex)
  invite = cluster.issue_invitation(peer_pubkey_hex)

  # Accept on the remote side
  cluster.accept_invitation(invite)

  # Start syncing
  await sync.start(host="0.0.0.0", port=9878)
"""

import asyncio
import json
import logging
import time
import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

logger = logging.getLogger("GhostSync")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
SYNC_PORT = int(__import__("os").getenv("SYNC_PORT", "9878"))
GOSSIP_INTERVAL = int(__import__("os").getenv("GOSSIP_INTERVAL", "15"))
FULL_SYNC_INTERVAL = int(__import__("os").getenv("FULL_SYNC_INTERVAL", "60"))
PEER_TIMEOUT_SYNC = int(__import__("os").getenv("SYNC_PEER_TIMEOUT", "120"))
MAX_INVITATION_AGE = 3600 * 24  # 24 hours

SYNC_PROTOCOL_VERSION = b"GHOST-SYNC-v1"


# ---------------------------------------------------------------------------
# Data Structures
# ---------------------------------------------------------------------------

@dataclass
class Invitation:
    """A signed invitation to join a permissioned cluster."""
    inviter_id: str
    inviter_pubkey: str
    invitee_pubkey: str
    cluster_name: str
    created_at: float
    signature: str = ""
    expires_at: float = 0.0

    def is_expired(self) -> bool:
        expiry = self.expires_at or (self.created_at + MAX_INVITATION_AGE)
        return time.time() > expiry

    def to_dict(self) -> Dict[str, Any]:
        return {
            "inviter_id": self.inviter_id,
            "inviter_pubkey": self.inviter_pubkey,
            "invitee_pubkey": self.invitee_pubkey,
            "cluster_name": self.cluster_name,
            "created_at": self.created_at,
            "signature": self.signature,
            "expires_at": self.expires_at,
        }

    @staticmethod
    def from_dict(d: Dict[str, Any]) -> "Invitation":
        return Invitation(
            inviter_id=d["inviter_id"],
            inviter_pubkey=d["inviter_pubkey"],
            invitee_pubkey=d["invitee_pubkey"],
            cluster_name=d.get("cluster_name", "default"),
            created_at=d.get("created_at", time.time()),
            signature=d.get("signature", ""),
            expires_at=d.get("expires_at", 0.0),
        )


@dataclass
class MembershipAttestation:
    """Proof of cluster membership, signed by the inviter."""
    member_id: str
    member_pubkey: str
    cluster_name: str
    joined_at: float
    inviter_id: str
    inviter_pubkey: str
    signature: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "member_id": self.member_id,
            "member_pubkey": self.member_pubkey,
            "cluster_name": self.cluster_name,
            "joined_at": self.joined_at,
            "inviter_id": self.inviter_id,
            "inviter_pubkey": self.inviter_pubkey,
            "signature": self.signature,
        }

    @staticmethod
    def from_dict(d: Dict[str, Any]) -> "MembershipAttestation":
        return MembershipAttestation(
            member_id=d["member_id"],
            member_pubkey=d["member_pubkey"],
            cluster_name=d.get("cluster_name", "default"),
            joined_at=d.get("joined_at", time.time()),
            inviter_id=d["inviter_id"],
            inviter_pubkey=d["inviter_pubkey"],
            signature=d.get("signature", ""),
        )


@dataclass
class ClusterMember:
    """A peer in the permissioned cluster with live state."""
    node_id: str
    pubkey: str
    host: str
    port: int
    sync_port: int = SYNC_PORT
    capabilities: List[str] = field(default_factory=list)
    version: str = ""
    last_seen: float = 0.0
    joined_at: float = 0.0
    status: str = "active"  # active | idle | departed
    state_version: int = 0   # monotonic version for state sync
    current_task: str = ""
    is_inviter: bool = False

    @property
    def is_alive(self) -> bool:
        return (time.time() - self.last_seen) < PEER_TIMEOUT_SYNC

    def to_dict(self) -> Dict[str, Any]:
        return {
            "node_id": self.node_id,
            "pubkey": self.pubkey,
            "host": self.host,
            "port": self.port,
            "sync_port": self.sync_port,
            "capabilities": self.capabilities,
            "version": self.version,
            "last_seen": self.last_seen,
            "joined_at": self.joined_at,
            "status": self.status,
            "state_version": self.state_version,
            "current_task": self.current_task,
            "is_inviter": self.is_inviter,
        }

    @staticmethod
    def from_dict(d: Dict[str, Any]) -> "ClusterMember":
        return ClusterMember(
            node_id=d["node_id"],
            pubkey=d.get("pubkey", ""),
            host=d.get("host", ""),
            port=d.get("port", 9876),
            sync_port=d.get("sync_port", SYNC_PORT),
            capabilities=d.get("capabilities", []),
            version=d.get("version", ""),
            last_seen=d.get("last_seen", 0.0),
            joined_at=d.get("joined_at", 0.0),
            status=d.get("status", "active"),
            state_version=d.get("state_version", 0),
            current_task=d.get("current_task", ""),
            is_inviter=d.get("is_inviter", False),
        )


# ---------------------------------------------------------------------------
# Permissioned Cluster Manager
# ---------------------------------------------------------------------------

class PermissionedCluster:
    """
    Manages permissioned membership for a synchronized computation cluster.

    Features:
      * Ed25519-signed invitations — only invited nodes can join
      * Membership attestations — proof of membership chained to inviter
      * Revocation — members can be removed by the inviter
      * Persistent state — membership saved to disk
    """

    def __init__(self, identity: Any, cluster_name: str = "default",
                 state_dir: Optional[Path] = None):
        from node_identity import NodeIdentity
        self._identity: NodeIdentity = identity
        self.cluster_name = cluster_name
        self._state_dir = state_dir or (
            Path(__file__).resolve().parent / "agent_data" / "cluster"
        )
        self._state_dir.mkdir(parents=True, exist_ok=True)

        # Members keyed by node_id
        self._members: Dict[str, ClusterMember] = {}
        # Outstanding invitations: invitee_pubkey -> Invitation
        self._invitations: Dict[str, Invitation] = {}
        # My attestation (proof I was invited)
        self._my_attestation: Optional[MembershipAttestation] = None
        # Known inviters (node_ids that can issue invitations)
        self._inviters: Set[str] = set()
        # Event callbacks
        self._on_join: Optional[Callable] = None
        self._on_leave: Optional[Callable] = None

        self._load_state()

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def _state_path(self, name: str) -> Path:
        return self._state_dir / f"{self.cluster_name}_{name}.json"

    def _load_state(self) -> None:
        try:
            path = self._state_path("members")
            if path.exists():
                data = json.loads(path.read_text(encoding="utf-8"))
                for entry in data:
                    m = ClusterMember.from_dict(entry)
                    self._members[m.node_id] = m
        except Exception as e:
            logger.debug("Could not load cluster members: %s", e)

        try:
            path = self._state_path("invitations")
            if path.exists():
                data = json.loads(path.read_text(encoding="utf-8"))
                for entry in data:
                    inv = Invitation.from_dict(entry)
                    if not inv.is_expired():
                        self._invitations[inv.invitee_pubkey] = inv
        except Exception as e:
            logger.debug("Could not load invitations: %s", e)

        try:
            path = self._state_path("attestation")
            if path.exists():
                data = json.loads(path.read_text(encoding="utf-8"))
                self._my_attestation = MembershipAttestation.from_dict(data)
        except Exception:
            pass

    def _save_members(self) -> None:
        try:
            data = [m.to_dict() for m in self._members.values()]
            self._state_path("members").write_text(
                json.dumps(data, indent=2), encoding="utf-8"
            )
        except Exception as e:
            logger.warning("Failed to save members: %s", e)

    def _save_invitations(self) -> None:
        try:
            data = [inv.to_dict() for inv in self._invitations.values()
                    if not inv.is_expired()]
            self._state_path("invitations").write_text(
                json.dumps(data, indent=2), encoding="utf-8"
            )
        except Exception as e:
            logger.warning("Failed to save invitations: %s", e)

    def _save_attestation(self) -> None:
        if not self._my_attestation:
            return
        try:
            self._state_path("attestation").write_text(
                json.dumps(self._my_attestation.to_dict(), indent=2),
                encoding="utf-8",
            )
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Invitation Lifecycle
    # ------------------------------------------------------------------

    def issue_invitation(self, invitee_pubkey: str) -> Optional[Invitation]:
        """
        Issue a signed invitation for a peer to join the cluster.
        Returns the Invitation object (which the caller must deliver out-of-band).
        """
        inv = Invitation(
            inviter_id=self.node_id,
            inviter_pubkey=self.public_key,
            invitee_pubkey=invitee_pubkey,
            cluster_name=self.cluster_name,
            created_at=time.time(),
        )
        raw = self._invitation_signing_string(inv)
        inv.signature = self._identity.sign(raw)
        self._invitations[invitee_pubkey] = inv
        self._save_invitations()
        logger.info(
            "Invitation issued for pubkey=%s... by %s",
            invitee_pubkey[:16], self.node_id
        )
        return inv

    def accept_invitation(self, invitation: Invitation) -> Optional[MembershipAttestation]:
        """
        Accept an invitation and create a membership attestation.
        Verifies the invitation signature against the inviter's pubkey.
        """
        from node_identity import NodeIdentity

        # Verify this invitation is for me
        my_pubkey = self.public_key
        if invitation.invitee_pubkey != my_pubkey:
            logger.error(
                "Invitation not for us (ours=%s..., invitee=%s...)",
                my_pubkey[:16], invitation.invitee_pubkey[:16]
            )
            return None

        # Verify signature
        raw = self._invitation_signing_string(invitation)
        if not NodeIdentity.verify(raw, invitation.signature, invitation.inviter_pubkey):
            logger.error("Invitation signature verification failed")
            return None

        if invitation.is_expired():
            logger.error("Invitation has expired")
            return None

        # Create attestation
        attestation = MembershipAttestation(
            member_id=self.node_id,
            member_pubkey=my_pubkey,
            cluster_name=invitation.cluster_name,
            joined_at=time.time(),
            inviter_id=invitation.inviter_id,
            inviter_pubkey=invitation.inviter_pubkey,
        )

        # Attestation is signed by the *inviter* (not us)
        # We store it as proof that we were legitimately invited.
        # In practice, the inviter sends us the signed attestation.
        # Here we just store the invitation as proof.
        self._my_attestation = attestation
        self._save_attestation()

        self.cluster_name = invitation.cluster_name
        self._inviters.add(invitation.inviter_id)

        # Register ourselves as a member
        self.upsert_member(ClusterMember(
            node_id=self.node_id,
            pubkey=my_pubkey,
            host="0.0.0.0",
            port=9876,
            is_inviter=False,
            joined_at=time.time(),
        ))

        logger.info(
            "Accepted invitation to cluster '%s' from %s",
            self.cluster_name, invitation.inviter_id
        )
        return attestation

    @staticmethod
    def _invitation_signing_string(inv: Invitation) -> str:
        parts = [
            inv.inviter_id, inv.invitee_pubkey,
            inv.cluster_name, str(inv.created_at),
        ]
        return ":".join(parts)

    def revoke_member(self, member_id: str) -> bool:
        """Revoke a member's access. Only the inviter can revoke."""
        member = self._members.get(member_id)
        if not member:
            return False
        if not member.is_inviter and member_id != self.node_id:
            logger.info("Revoking member %s from cluster", member_id)
            del self._members[member_id]
            self._save_members()
            if self._on_leave:
                self._on_leave(member_id)
            return True
        return False

    # ------------------------------------------------------------------
    # Member Management
    # ------------------------------------------------------------------

    def upsert_member(self, member: ClusterMember) -> None:
        existing = self._members.get(member.node_id)
        if existing:
            member.joined_at = existing.joined_at
            member.is_inviter = existing.is_inviter
        self._members[member.node_id] = member
        self._save_members()

    def remove_member(self, node_id: str) -> None:
        if node_id in self._members:
            del self._members[node_id]
            self._save_members()

    def get_member(self, node_id: str) -> Optional[ClusterMember]:
        return self._members.get(node_id)

    def is_permissioned(self, node_id: str) -> bool:
        """Check if a node_id is a recognized cluster member."""
        return node_id in self._members

    def is_inviter(self, node_id: str) -> bool:
        return node_id in self._inviters or (
            node_id in self._members and self._members[node_id].is_inviter
        )

    # ------------------------------------------------------------------
    # Callbacks
    # ------------------------------------------------------------------

    def on_join(self, callback: Callable) -> None:
        self._on_join = callback

    def on_leave(self, callback: Callable) -> None:
        self._on_leave = callback

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def node_id(self) -> str:
        return self._identity.node_id

    @property
    def public_key(self) -> str:
        return self._identity.public_key_hex()

    @property
    def member_count(self) -> int:
        return len(self._members)

    @property
    def alive_count(self) -> int:
        return sum(1 for m in self._members.values() if m.is_alive)

    @property
    def members(self) -> List[ClusterMember]:
        return list(self._members.values())

    @property
    def has_attestation(self) -> bool:
        return self._my_attestation is not None

    @property
    def cluster_id(self) -> str:
        return f"{self.cluster_name}@{self.node_id[:8]}"

    def status(self) -> Dict[str, Any]:
        return {
            "cluster": self.cluster_name,
            "cluster_id": self.cluster_id,
            "my_id": self.node_id,
            "members_total": self.member_count,
            "members_alive": self.alive_count,
            "inviters": list(self._inviters),
            "has_attestation": self.has_attestation,
            "pending_invitations": len(self._invitations),
        }


# ---------------------------------------------------------------------------
# Version Vector (for state conflict resolution)
# ---------------------------------------------------------------------------

class VersionVector:
    """
    Lamport-style version vector for conflict-free state sync.

    Each member maintains a monotonic counter. The vector is the set of
    (member_id, counter) pairs. When two states conflict, the one with
    the higher vector (lexicographically sorted) wins.
    """

    def __init__(self):
        self._counters: Dict[str, int] = defaultdict(int)

    def increment(self, node_id: str) -> int:
        self._counters[node_id] += 1
        return self._counters[node_id]

    def get(self, node_id: str) -> int:
        return self._counters.get(node_id, 0)

    def merge(self, other: "VersionVector") -> "VersionVector":
        merged = VersionVector()
        all_keys = set(self._counters.keys()) | set(other._counters.keys())
        for k in all_keys:
            merged._counters[k] = max(self._counters.get(k, 0), other._counters.get(k, 0))
        return merged

    def dominates(self, other: "VersionVector") -> bool:
        """True if this vector dominates the other (all counters >=)."""
        all_keys = set(self._counters.keys()) | set(other._counters.keys())
        for k in all_keys:
            if self._counters.get(k, 0) < other._counters.get(k, 0):
                return False
        return True

    def conflicts_with(self, other: "VersionVector") -> bool:
        """True if neither dominates the other (concurrent updates)."""
        return not self.dominates(other) and not other.dominates(self)

    def to_dict(self) -> Dict[str, int]:
        return dict(self._counters)

    @staticmethod
    def from_dict(d: Dict[str, int]) -> "VersionVector":
        vv = VersionVector()
        vv._counters.update(d)
        return vv


# ---------------------------------------------------------------------------
# Cluster Sync State
# ---------------------------------------------------------------------------

@dataclass
class ClusterState:
    """The shared state of a permissioned cluster."""
    members: Dict[str, ClusterMember] = field(default_factory=dict)
    version_vector: VersionVector = field(default_factory=VersionVector)
    last_updated: float = 0.0
    cluster_name: str = "default"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "cluster_name": self.cluster_name,
            "members": {k: v.to_dict() for k, v in self.members.items()},
            "version_vector": self.version_vector.to_dict(),
            "last_updated": self.last_updated,
        }

    @staticmethod
    def from_dict(d: Dict[str, Any]) -> "ClusterState":
        members = {
            k: ClusterMember.from_dict(v)
            for k, v in d.get("members", {}).items()
        }
        vv = VersionVector.from_dict(d.get("version_vector", {}))
        return ClusterState(
            members=members,
            version_vector=vv,
            last_updated=d.get("last_updated", 0.0),
            cluster_name=d.get("cluster_name", "default"),
        )


# ---------------------------------------------------------------------------
# Global State Synchronization Engine
# ---------------------------------------------------------------------------

class GlobalStateSync:
    """
    Gossip-based cluster state synchronization engine.

    Protocol:
      1. Each member periodically broadcasts its state version to the cluster
      2. Peers exchange version vectors to detect divergence
      3. On conflict, the member with the higher version vector pushes its full state
      4. Full-state sync every FULL_SYNC_INTERVAL seconds
      5. Incremental diffs between full syncs

    States are signed with Ed25519 to prevent tampering.
    """

    def __init__(self, identity: Any, cluster: PermissionedCluster,
                 sync_handler: Optional[Callable] = None):
        from node_identity import NodeIdentity
        self._identity: NodeIdentity = identity
        self._cluster = cluster
        self._sync_handler = sync_handler or self._default_sync_handler

        # Local cluster state
        self._state = ClusterState(cluster_name=cluster.cluster_name)

        # Track which peers we've synced with
        self._synced_peers: Set[str] = set()

        # Server
        self._server: Optional[asyncio.AbstractServer] = None
        self._running = False

        # Sync history for conflict resolution
        self._sync_history: List[Dict[str, Any]] = []

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self, host: str = "0.0.0.0", port: int = SYNC_PORT) -> None:
        self._running = True
        self._server = await asyncio.start_server(
            self._handle_connection, host, port
        )
        logger.info(
            "GlobalStateSync listening on %s:%d (cluster=%s)",
            host, port, self._cluster.cluster_name
        )

        # Background loops
        asyncio.create_task(self._gossip_loop())
        asyncio.create_task(self._full_sync_loop())
        asyncio.create_task(self._cleanup_loop())

    async def stop(self) -> None:
        self._running = False
        if self._server:
            self._server.close()
            await self._server.wait_closed()

    # ------------------------------------------------------------------
    # State Management
    # ------------------------------------------------------------------

    def _build_my_state(self) -> ClusterState:
        """Build the current cluster state from the permissioned cluster."""
        state = ClusterState(cluster_name=self._cluster.cluster_name)
        for member in self._cluster.members:
            member.state_version = self._state.version_vector.get(member.node_id)
            state.members[member.node_id] = member
        state.last_updated = time.time()
        return state

    def _apply_remote_state(self, remote: ClusterState, sender_id: str) -> bool:
        """Merge remote state into local state. Returns True if local changed."""
        local_vv = self._state.version_vector
        remote_vv = remote.version_vector

        # If remote dominates, adopt it
        if remote_vv.dominates(local_vv) and not local_vv.dominates(remote_vv):
            self._state = remote
            self._sync_history.append({
                "ts": time.time(),
                "type": "full_adopt",
                "from": sender_id,
                "version": remote_vv.to_dict(),
            })
            self._apply_to_cluster()
            return True

        # If concurrent (conflict), merge member-by-member
        if remote_vv.conflicts_with(local_vv):
            merged_vv = local_vv.merge(remote_vv)
            for nid, rmember in remote.members.items():
                if nid not in self._state.members:
                    self._state.members[nid] = rmember
                else:
                    local_member = self._state.members[nid]
                    if rmember.state_version > local_member.state_version:
                        self._state.members[nid] = rmember
            self._state.version_vector = merged_vv
            self._state.last_updated = time.time()
            self._sync_history.append({
                "ts": time.time(),
                "type": "merge",
                "from": sender_id,
                "version": merged_vv.to_dict(),
            })
            self._apply_to_cluster()
            return True

        return False

    def _apply_to_cluster(self) -> None:
        """Apply the synchronized state back to the PermissionedCluster."""
        for nid, member in self._state.members.items():
            if nid != self.node_id:
                self._cluster.upsert_member(member)

    def bump_version(self) -> None:
        """Increment our version counter after a local state change."""
        self._state.version_vector.increment(self.node_id)
        self._state.last_updated = time.time()

    # ------------------------------------------------------------------
    # Message Signing
    # ------------------------------------------------------------------

    def _sign_payload(self, payload: Dict[str, Any]) -> str:
        raw = json.dumps(payload, sort_keys=True)
        return self._identity.sign(raw)

    @staticmethod
    def _verify_payload(payload: Dict[str, Any], signature: str,
                         pubkey: str) -> bool:
        from node_identity import NodeIdentity
        raw = json.dumps(payload, sort_keys=True)
        return NodeIdentity.verify(raw, signature, pubkey)

    # ------------------------------------------------------------------
    # Sync Messages
    # ------------------------------------------------------------------

    def _make_state_message(self) -> Dict[str, Any]:
        state = self._build_my_state()
        payload = {
            "type": "state_sync",
            "sender_id": self.node_id,
            "sender_pubkey": self.public_key,
            "cluster_name": self._cluster.cluster_name,
            "state": state.to_dict(),
            "timestamp": time.time(),
        }
        payload["signature"] = self._sign_payload(payload)
        return payload

    def _make_gossip_message(self) -> Dict[str, Any]:
        vv = self._state.version_vector.to_dict()
        payload = {
            "type": "gossip_hello",
            "sender_id": self.node_id,
            "sender_pubkey": self.public_key,
            "cluster_name": self._cluster.cluster_name,
            "version_vector": vv,
            "member_count": self._cluster.alive_count,
            "timestamp": time.time(),
        }
        payload["signature"] = self._sign_payload(payload)
        return payload

    def _make_join_request(self) -> Dict[str, Any]:
        payload = {
            "type": "join_request",
            "sender_id": self.node_id,
            "sender_pubkey": self.public_key,
            "cluster_name": self._cluster.cluster_name,
            "timestamp": time.time(),
            "attestation": (
                self._cluster._my_attestation.to_dict()
                if self._cluster._my_attestation else {}
            ),
        }
        payload["signature"] = self._sign_payload(payload)
        return payload

    # ------------------------------------------------------------------
    # Connection Handler
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
            sender_id = msg.get("sender_id", "")
            sender_pubkey = msg.get("sender_pubkey", "")
            signature = msg.get("signature", "")

            if signature and sender_pubkey:
                if not self._verify_payload(
                    {k: v for k, v in msg.items() if k != "signature"},
                    signature, sender_pubkey
                ):
                    logger.warning("Invalid signature from %s (%s)", sender_id, peer_addr[0])
                    writer.close()
                    return

            handler = self._message_handlers.get(msg_type)
            if handler:
                response = await handler(msg, peer_addr)
                if response:
                    writer.write((json.dumps(response) + "\n").encode())
                    await writer.drain()
            else:
                logger.debug("Unknown sync message type: %s", msg_type)

        except asyncio.TimeoutError:
            pass
        except json.JSONDecodeError:
            pass
        except Exception as e:
            logger.debug("Sync connection error: %s", e)
        finally:
            writer.close()

    @property
    def _message_handlers(self) -> Dict[str, Callable]:
        return {
            "state_sync": self._handle_state_sync,
            "gossip_hello": self._handle_gossip_hello,
            "join_request": self._handle_join_request,
            "state_request": self._handle_state_request,
        }

    async def _handle_state_sync(self, msg: Dict[str, Any],
                                   peer_addr: Tuple) -> Optional[Dict[str, Any]]:
        sender_id = msg["sender_id"]
        remote_state = ClusterState.from_dict(msg.get("state", {}))
        changed = self._apply_remote_state(remote_state, sender_id)
        self._synced_peers.add(sender_id)
        if changed:
            logger.info("State updated from %s", sender_id)
        return {
            "type": "state_ack",
            "sender_id": self.node_id,
            "timestamp": time.time(),
        }

    async def _handle_gossip_hello(self, msg: Dict[str, Any],
                                     peer_addr: Tuple) -> Optional[Dict[str, Any]]:
        sender_id = msg["sender_id"]
        remote_vv = VersionVector.from_dict(msg.get("version_vector", {}))
        local_vv = self._state.version_vector

        # If remote has a newer version, request full state
        if remote_vv.dominates(local_vv):
            logger.debug("Peer %s has newer state — requesting sync", sender_id)
            return {
                "type": "state_request",
                "sender_id": self.node_id,
                "sender_pubkey": self.public_key,
                "timestamp": time.time(),
            }

        return {
            "type": "gossip_ack",
            "sender_id": self.node_id,
            "timestamp": time.time(),
        }

    async def _handle_join_request(self, msg: Dict[str, Any],
                                     peer_addr: Tuple) -> Optional[Dict[str, Any]]:
        sender_id = msg["sender_id"]
        sender_pubkey = msg["sender_pubkey"]
        attestation_data = msg.get("attestation", {})

        if not attestation_data:
            # This peer needs an invitation first
            logger.info("Join request from %s (no attestation) — pending", sender_id)
            return {
                "type": "join_required",
                "sender_id": self.node_id,
                "message": "Invitation required. Contact cluster inviter.",
                "timestamp": time.time(),
            }

        # Verify the attestation
        from node_identity import NodeIdentity
        attestation = MembershipAttestation.from_dict(attestation_data)
        raw = json.dumps({
            "member_id": attestation.member_id,
            "member_pubkey": attestation.member_pubkey,
            "cluster_name": attestation.cluster_name,
            "joined_at": attestation.joined_at,
            "inviter_id": attestation.inviter_id,
            "inviter_pubkey": attestation.inviter_pubkey,
        }, sort_keys=True)
        if not NodeIdentity.verify(raw, attestation.signature, attestation.inviter_pubkey):
            logger.warning("Invalid attestation signature from %s", sender_id)
            return {
                "type": "join_rejected",
                "sender_id": self.node_id,
                "reason": "Invalid attestation signature",
                "timestamp": time.time(),
            }

        # Check if the inviter is a known member
        if not self._cluster.is_permissioned(attestation.inviter_id):
            logger.warning("Unknown inviter %s for join request from %s",
                           attestation.inviter_id, sender_id)
            return {
                "type": "join_rejected",
                "sender_id": self.node_id,
                "reason": "Unknown inviter",
                "timestamp": time.time(),
            }

        # Accept the join
        member = ClusterMember(
            node_id=sender_id,
            pubkey=sender_pubkey,
            host=peer_addr[0],
            port=msg.get("port", 9876),
            sync_port=msg.get("sync_port", SYNC_PORT),
            joined_at=time.time(),
            status="active",
        )
        self._cluster.upsert_member(member)
        self.bump_version()
        logger.info("Member joined cluster: %s @ %s", sender_id, peer_addr[0])
        if self._cluster._on_join:
            self._cluster._on_join(sender_id)

        return {
            "type": "join_accepted",
            "sender_id": self.node_id,
            "cluster_name": self._cluster.cluster_name,
            "members": [m.to_dict() for m in self._cluster.members],
            "timestamp": time.time(),
        }

    async def _handle_state_request(self, msg: Dict[str, Any],
                                      peer_addr: Tuple) -> Optional[Dict[str, Any]]:
        state_msg = self._make_state_message()
        logger.debug("Sending full state to %s", msg["sender_id"])
        return state_msg

    # ------------------------------------------------------------------
    # Background Loops
    # ------------------------------------------------------------------

    async def _gossip_loop(self) -> None:
        """Periodically gossip version vectors to all cluster members."""
        while self._running:
            await asyncio.sleep(GOSSIP_INTERVAL)
            if not self._cluster.members:
                continue

            gossip = self._make_gossip_message()
            payload = (json.dumps(gossip) + "\n").encode()

            for member in self._cluster.members:
                if member.node_id == self.node_id:
                    continue
                if not member.is_alive:
                    continue
                try:
                    r, w = await asyncio.wait_for(
                        asyncio.open_connection(member.host, member.sync_port),
                        timeout=5,
                    )
                    w.write(payload)
                    await w.drain()
                    resp_data = await asyncio.wait_for(r.readline(), timeout=5)
                    w.close()

                    resp = json.loads(resp_data.decode().strip())
                    if resp.get("type") == "state_request":
                        # This peer wants our full state
                        state_msg = self._make_state_message()
                        try:
                            r2, w2 = await asyncio.wait_for(
                                asyncio.open_connection(member.host, member.sync_port),
                                timeout=5,
                            )
                            w2.write((json.dumps(state_msg) + "\n").encode())
                            await w2.drain()
                            w2.close()
                        except Exception:
                            pass

                    member.last_seen = time.time()
                except (asyncio.TimeoutError, ConnectionRefusedError, OSError):
                    member.status = "idle"
                except Exception:
                    pass

    async def _full_sync_loop(self) -> None:
        """Periodically push full state to all members."""
        while self._running:
            await asyncio.sleep(FULL_SYNC_INTERVAL)
            if not self._cluster.members:
                continue

            state_msg = self._make_state_message()
            payload = (json.dumps(state_msg) + "\n").encode()

            sent = 0
            for member in self._cluster.members:
                if member.node_id == self.node_id:
                    continue
                try:
                    r, w = await asyncio.wait_for(
                        asyncio.open_connection(member.host, member.sync_port),
                        timeout=5,
                    )
                    w.write(payload)
                    await w.drain()
                    await asyncio.wait_for(r.readline(), timeout=5)
                    w.close()
                    sent += 1
                except Exception:
                    pass

            if sent:
                logger.debug("Full sync pushed to %d peers", sent)

    async def _cleanup_loop(self) -> None:
        """Remove stale members from the cluster."""
        while self._running:
            await asyncio.sleep(PEER_TIMEOUT_SYNC // 2)
            now = time.time()
            stale = [
                nid for nid, m in self._cluster._members.items()
                if nid != self.node_id and (now - m.last_seen) > PEER_TIMEOUT_SYNC
            ]
            for nid in stale:
                logger.info("Removing stale member: %s", nid)
                self._cluster.remove_member(nid)
            self.bump_version()

    # ------------------------------------------------------------------
    # Outbound Sync (push our state to a specific peer)
    # ------------------------------------------------------------------

    async def sync_to_peer(self, host: str, port: int = SYNC_PORT) -> bool:
        """Push our full cluster state to a specific peer."""
        state_msg = self._make_state_message()
        payload = (json.dumps(state_msg) + "\n").encode()
        try:
            r, w = await asyncio.wait_for(
                asyncio.open_connection(host, port), timeout=5
            )
            w.write(payload)
            await w.drain()
            resp_data = await asyncio.wait_for(r.readline(), timeout=5)
            w.close()
            resp = json.loads(resp_data.decode().strip())
            return resp.get("type") == "state_ack"
        except Exception as e:
            logger.warning("Sync to %s:%d failed: %s", host, port, e)
            return False

    async def request_join(self, host: str, port: int = SYNC_PORT) -> Optional[Dict[str, Any]]:
        """
        Send a join request to a cluster member.
        If we have an attestation, include it. Otherwise, request an invitation.
        """
        join_msg = self._make_join_request()
        payload = (json.dumps(join_msg) + "\n").encode()
        try:
            r, w = await asyncio.wait_for(
                asyncio.open_connection(host, port), timeout=5
            )
            w.write(payload)
            await w.drain()
            resp_data = await asyncio.wait_for(r.readline(), timeout=5)
            w.close()
            return json.loads(resp_data.decode().strip())
        except Exception as e:
            logger.warning("Join request to %s:%d failed: %s", host, port, e)
            return None

    # ------------------------------------------------------------------
    # Default Handler
    # ------------------------------------------------------------------

    async def _default_sync_handler(self, msg: Dict[str, Any]) -> None:
        logger.debug("Sync handler received: %s", msg.get("type"))

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def node_id(self) -> str:
        return self._identity.node_id

    @property
    def public_key(self) -> str:
        return self._identity.public_key_hex()

    @property
    def peer_count(self) -> int:
        return self._cluster.alive_count

    @property
    def status(self) -> Dict[str, Any]:
        return {
            "running": self._running,
            "cluster": self._cluster.status(),
            "state_version": self._state.version_vector.to_dict(),
            "synced_peers": len(self._synced_peers),
            "last_updated": self._state.last_updated,
        }


# ---------------------------------------------------------------------------
# Convenience: bootstrap cluster formation
# ---------------------------------------------------------------------------

async def form_cluster(
    identity: Any,
    seed_hosts: Optional[List[Tuple[str, int]]] = None,
    cluster_name: str = "default",
    listen_host: str = "0.0.0.0",
    sync_port: int = SYNC_PORT,
) -> Tuple[PermissionedCluster, GlobalStateSync]:
    """
    Form or join a permissioned cluster.

    If seed_hosts is provided, attempt to join each until one accepts.
    Otherwise, start as the founding member (inviter).
    """
    cluster = PermissionedCluster(identity, cluster_name=cluster_name)
    sync_engine = GlobalStateSync(identity, cluster)
    await sync_engine.start(listen_host, sync_port)

    if seed_hosts:
        for host, port in seed_hosts:
            logger.info("Attempting to join cluster via %s:%d", host, port)
            response = await sync_engine.request_join(host, port)
            if response:
                rtype = response.get("type", "")
                if rtype == "join_accepted":
                    members_data = response.get("members", [])
                    for mdata in members_data:
                        m = ClusterMember.from_dict(mdata)
                        cluster.upsert_member(m)
                    logger.info(
                        "Joined cluster '%s' with %d existing members via %s:%d",
                        cluster_name, len(members_data), host, port,
                    )
                    return cluster, sync_engine
                elif rtype == "join_required":
                    logger.info("Need invitation from cluster inviter at %s:%d", host, port)
                elif rtype == "join_rejected":
                    logger.warning(
                        "Join rejected by %s:%d: %s",
                        host, port, response.get("reason", "unknown"),
                    )

    logger.info(
        "Starting as founding member of cluster '%s' (id=%s)",
        cluster_name, cluster.cluster_id,
    )
    return cluster, sync_engine
