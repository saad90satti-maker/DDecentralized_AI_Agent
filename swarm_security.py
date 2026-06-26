"""
Swarm Security Layer — node authentication, packet signing, mesh integrity.

Ensures only authenticated nodes can communicate within the swarm mesh.
Every heartbeat and knowledge exchange packet is signed with a shared
secret key using HMAC-SHA256.
"""

import os
import time
import json
import hmac
import socket
import hashlib
import logging
from typing import Optional

logger = logging.getLogger("swarm_security")

# SWARM_SECRET is the shared symmetric key for HMAC signing.
# Set via env var SWARM_SECRET; falls back to "default-swarm-secret-change-me"
# in development. All nodes in the mesh must share the same secret.
SWARM_SECRET = os.getenv("SWARM_SECRET", "default-swarm-secret-change-me")


# ---------------------------------------------------------------------------
# Core signing
# ---------------------------------------------------------------------------

def sign_packet(packet: str, key: str = SWARM_SECRET) -> str:
    """Sign a packet string with HMAC-SHA256 using the shared secret."""
    if isinstance(packet, str):
        packet = packet.encode("utf-8")
    if isinstance(key, str):
        key = key.encode("utf-8")
    return hmac.new(key, packet, hashlib.sha256).hexdigest()


def verify_packet(packet: str, signature: str, key: str = SWARM_SECRET) -> bool:
    """Verify a packet's HMAC-SHA256 signature."""
    expected = sign_packet(packet, key)
    # Constant-time comparison to prevent timing attacks
    return hmac.compare_digest(expected, signature)


def sign_json_payload(payload: dict, key: str = SWARM_SECRET) -> str:
    """Serialize a dict to canonical JSON and sign it."""
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return sign_packet(canonical, key)


def verify_json_payload(payload: dict, signature: str, key: str = SWARM_SECRET) -> bool:
    """Verify the HMAC signature of a JSON payload."""
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return verify_packet(canonical, signature, key)


# ---------------------------------------------------------------------------
# GhostSignal Obfuscation Layer — ISP-proof DPI bypass
# ---------------------------------------------------------------------------

def ghost_xor_obfuscate(data: bytes, key: str = SWARM_SECRET) -> bytes:
    """XOR-encrypt payload bytes with the shared secret key.

    This makes the payload appear as random noise to deep-packet inspection.
    Combined with HMAC signing, it provides confidentiality + integrity.
    """
    if isinstance(key, str):
        key = key.encode("utf-8")
    return bytes(d ^ key[i % len(key)] for i, d in enumerate(data))


def ghost_xor_deobfuscate(data: bytes, key: str = SWARM_SECRET) -> bytes:
    """Reverse XOR obfuscation (symmetric — same operation)."""
    return ghost_xor_obfuscate(data, key)


def ghost_encrypt_packet(packet: str, key: str = SWARM_SECRET) -> dict:
    """Full GhostSignal packet encryption: XOR body + HMAC signature.

    Returns a dict with 'ciphertext' (hex), 'signature' (hex), and
    'fingerprint' that can be transmitted over any carrier (HTTP, UDP,
    multicast, satellite NULL-packet). The recipient reverses the
    process with ghost_decrypt_packet().
    """
    raw = packet.encode("utf-8") if isinstance(packet, str) else packet
    obfuscated = ghost_xor_obfuscate(raw, key)
    sig = hmac.new(key.encode("utf-8") if isinstance(key, str) else key,
                   obfuscated, hashlib.sha256).hexdigest()
    return {
        "ciphertext": obfuscated.hex(),
        "signature": sig,
        "fingerprint": compute_node_fingerprint(os.getenv("NODE_ID", socket.gethostname()), key),
    }


def ghost_decrypt_packet(encrypted: dict, key: str = SWARM_SECRET) -> Optional[str]:
    """Decrypt a GhostSignal-encrypted packet.

    Verifies HMAC first, then XOR-decrypts the body.
    Returns the plaintext string, or None if signature is invalid.
    """
    if isinstance(key, str):
        key = key.encode("utf-8")
    try:
        obfuscated = bytes.fromhex(encrypted["ciphertext"])
        sig = encrypted["signature"]
        expected_sig = hmac.new(key, obfuscated, hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected_sig, sig):
            logger.warning("GhostSignal: packet rejected — bad HMAC")
            return None
        plain = ghost_xor_deobfuscate(obfuscated, key.decode("utf-8") if isinstance(key, bytes) else key)
        return plain.decode("utf-8")
    except Exception as e:
        logger.debug("GhostSignal decrypt error: %s", e)
        return None


# ---------------------------------------------------------------------------
# Node identity and authentication
# ---------------------------------------------------------------------------

def compute_node_fingerprint(node_data: str, secret: str = SWARM_SECRET) -> str:
    """Unique fingerprint for a node based on its identifier data."""
    raw = node_data.encode("utf-8") + secret.encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def is_trusted_node(node_id: str, peer_fingerprint: str, secret: str = SWARM_SECRET) -> bool:
    """Check whether a peer node has a valid fingerprint for its claimed identity."""
    expected = compute_node_fingerprint(node_id, secret)
    return hmac.compare_digest(expected, peer_fingerprint)


# ---------------------------------------------------------------------------
# SwarmSecurityAudit — full node lifecycle manager
# ---------------------------------------------------------------------------

class SwarmSecurityAudit:
    """Ensures only authenticated nodes can communicate within the mesh.

    Maintains a trust registry of verified peer fingerprints. Nodes that
    fail verification are isolated (removed from the peer list) and
    flagged in the audit log.
    """

    def __init__(self, secret_key: str = SWARM_SECRET):
        self.secret_key = secret_key
        self._trusted_nodes: dict[str, dict] = {}  # node_id -> {fingerprint, first_seen, last_seen}
        self._isolated_nodes: list[str] = []
        self._audit_log: list[dict] = []

    def verify_node(self, node_data: str) -> str:
        """Compute a unique fingerprint for a node.

        Used on the *receiving* side to confirm that a connecting node
        possesses the shared secret.
        """
        node_id = hashlib.sha256(
            node_data.encode("utf-8") + self.secret_key.encode("utf-8")
        ).hexdigest()
        return node_id

    def register_node(self, node_id: str, fingerprint: str) -> bool:
        """Register a node if its fingerprint is valid.

        Returns True if the node is trusted and added to the registry.
        """
        if is_trusted_node(node_id, fingerprint, self.secret_key):
            self._trusted_nodes[node_id] = {
                "fingerprint": fingerprint,
                "first_seen": time.time(),
                "last_seen": time.time(),
            }
            self._audit_log.append({
                "event": "node_registered",
                "node_id": node_id,
                "timestamp": time.time(),
            })
            logger.info("Trusted node registered: %s", node_id)
            return True
        else:
            self._audit_log.append({
                "event": "node_rejected",
                "node_id": node_id,
                "reason": "invalid_fingerprint",
                "timestamp": time.time(),
            })
            logger.warning("Node rejected (invalid fingerprint): %s", node_id)
            return False

    def audit_mesh(self, active_nodes: list[str]):
        """Check integrity of all connected peers.

        Any node whose fingerprint is missing or invalid is immediately
        isolated from the swarm.
        """
        for node_id in active_nodes:
            if node_id not in self._trusted_nodes:
                self.isolate_node(node_id)
                logger.warning("Alert: Untrusted node %s isolated from swarm.", node_id)

    def is_trusted(self, node_id: str) -> bool:
        return node_id in self._trusted_nodes

    def isolate_node(self, node_id: str):
        """Remove a node from the trust registry and flag it."""
        self._isolated_nodes.append(node_id)
        self._trusted_nodes.pop(node_id, None)
        self._audit_log.append({
            "event": "node_isolated",
            "node_id": node_id,
            "timestamp": time.time(),
        })

    def get_own_fingerprint(self) -> str:
        """Return this node's own fingerprint for outgoing announcements."""
        return compute_node_fingerprint(
            os.getenv("NODE_ID", socket.gethostname()),
            self.secret_key,
        )

    def get_status(self) -> dict:
        return {
            "trusted_nodes": len(self._trusted_nodes),
            "isolated_nodes": len(self._isolated_nodes),
            "audit_log_entries": len(self._audit_log),
            "recent_audit": self._audit_log[-5:] if self._audit_log else [],
        }



