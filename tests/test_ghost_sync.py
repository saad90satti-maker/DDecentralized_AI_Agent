"""Tests for Ghost Global State Synchronization — Permissioned Cluster."""

import json
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from node_identity import NodeIdentity


# =============================================================================
# PermissionedCluster Tests
# =============================================================================

class TestPermissionedCluster:
    def setup_method(self):
        self._tmpdir_a = Path(tempfile.mkdtemp())
        self._tmpdir_b = Path(tempfile.mkdtemp())
        self.identity_a = NodeIdentity.generate()
        self.identity_b = NodeIdentity.generate()
        from ghost_sync import PermissionedCluster
        self.cluster_a = PermissionedCluster(
            self.identity_a, cluster_name="test-cluster",
            state_dir=self._tmpdir_a,
        )
        self.cluster_b = PermissionedCluster(
            self.identity_b, cluster_name="test-cluster",
            state_dir=self._tmpdir_b,
        )

    def teardown_method(self):
        import shutil
        shutil.rmtree(self._tmpdir_a, ignore_errors=True)
        shutil.rmtree(self._tmpdir_b, ignore_errors=True)

    def test_issue_invitation(self):
        inv = self.cluster_a.issue_invitation(self.identity_b.public_key_hex())
        assert inv is not None
        assert inv.inviter_id == self.cluster_a.node_id
        assert inv.invitee_pubkey == self.identity_b.public_key_hex()
        assert inv.cluster_name == "test-cluster"
        assert inv.signature != ""

    def test_accept_invitation(self):
        pub_b = self.identity_b.public_key_hex()
        inv = self.cluster_a.issue_invitation(pub_b)

        attestation = self.cluster_b.accept_invitation(inv)
        assert attestation is not None
        assert attestation.member_id == self.cluster_b.node_id
        assert attestation.inviter_id == self.cluster_a.node_id

    def test_accept_invitation_wrong_recipient(self):
        identity_c = NodeIdentity.generate()
        inv = self.cluster_a.issue_invitation(identity_c.public_key_hex())
        # Try to accept with wrong identity
        attestation = self.cluster_b.accept_invitation(inv)
        assert attestation is None

    def test_member_after_accept(self):
        pub_b = self.identity_b.public_key_hex()
        inv = self.cluster_a.issue_invitation(pub_b)
        self.cluster_b.accept_invitation(inv)
        # Cluster B should have itself as a member after accepting
        assert self.cluster_b.member_count >= 1
        assert self.cluster_b.is_permissioned(self.cluster_b.node_id)

    def test_is_permissioned(self):
        assert not self.cluster_a.is_permissioned("unknown-node")
        assert not self.cluster_a.is_permissioned(self.cluster_b.node_id)
        # After inviting and accepting, cluster A adds B
        pub_b = self.identity_b.public_key_hex()
        inv = self.cluster_a.issue_invitation(pub_b)
        self.cluster_b.accept_invitation(inv)
        # Cluster A manually adds B as member
        from ghost_sync import ClusterMember
        self.cluster_a.upsert_member(ClusterMember(
            node_id=self.cluster_b.node_id,
            pubkey=pub_b,
            host="10.0.0.2",
            port=9876,
        ))
        assert self.cluster_a.is_permissioned(self.cluster_b.node_id)

    def test_upsert_member_preserves_inviter_flag(self):
        from ghost_sync import ClusterMember
        member = ClusterMember(
            node_id="test-node",
            pubkey="deadbeef",
            host="10.0.0.1",
            port=9876,
            is_inviter=True,
            joined_at=time.time(),
        )
        self.cluster_a.upsert_member(member)
        stored = self.cluster_a.get_member("test-node")
        assert stored is not None
        assert stored.is_inviter is True

        # Upsert again without inviter flag should preserve it
        member2 = ClusterMember(
            node_id="test-node",
            pubkey="deadbeef",
            host="10.0.0.2",
            port=9876,
        )
        self.cluster_a.upsert_member(member2)
        stored2 = self.cluster_a.get_member("test-node")
        assert stored2.is_inviter is True  # preserved

    def test_revoke_member(self):
        from ghost_sync import ClusterMember
        member = ClusterMember(
            node_id="test-node",
            pubkey="deadbeef",
            host="10.0.0.1",
            port=9876,
            is_inviter=False,
        )
        self.cluster_a.upsert_member(member)
        assert self.cluster_a.member_count == 1
        self.cluster_a.revoke_member("test-node")
        assert self.cluster_a.member_count == 0


# =============================================================================
# VersionVector Tests
# =============================================================================

class TestVersionVector:
    def test_increment(self):
        from ghost_sync import VersionVector
        vv = VersionVector()
        assert vv.increment("node-a") == 1
        assert vv.increment("node-a") == 2
        assert vv.increment("node-b") == 1

    def test_merge(self):
        from ghost_sync import VersionVector
        vv1 = VersionVector()
        vv1.increment("node-a")
        vv1.increment("node-a")
        vv1.increment("node-b")

        vv2 = VersionVector()
        vv2.increment("node-a")
        vv2.increment("node-c")

        merged = vv1.merge(vv2)
        assert merged.get("node-a") == 2
        assert merged.get("node-b") == 1
        assert merged.get("node-c") == 1

    def test_dominates(self):
        from ghost_sync import VersionVector
        vv1 = VersionVector()
        vv1.increment("a")
        vv1.increment("a")
        vv1.increment("b")

        vv2 = VersionVector()
        vv2.increment("a")

        assert vv1.dominates(vv2)
        assert not vv2.dominates(vv1)

    def test_conflicts_with(self):
        from ghost_sync import VersionVector
        vv1 = VersionVector()
        vv1.increment("a")

        vv2 = VersionVector()
        vv2.increment("b")

        assert vv1.conflicts_with(vv2)
        assert vv2.conflicts_with(vv1)

    def test_serialize_roundtrip(self):
        from ghost_sync import VersionVector
        vv = VersionVector()
        vv.increment("a")
        vv.increment("b")
        vv.increment("a")

        d = vv.to_dict()
        vv2 = VersionVector.from_dict(d)
        assert vv2.get("a") == 2
        assert vv2.get("b") == 1


# =============================================================================
# Invitation / MembershipAttestation Serialization
# =============================================================================

class TestInvitation:
    def test_to_dict_roundtrip(self):
        from ghost_sync import Invitation
        inv = Invitation(
            inviter_id="node-a",
            inviter_pubkey="abcdef",
            invitee_pubkey="123456",
            cluster_name="test",
            created_at=time.time(),
            signature="sig123",
        )
        d = inv.to_dict()
        inv2 = Invitation.from_dict(d)
        assert inv2.inviter_id == inv.inviter_id
        assert inv2.invitee_pubkey == inv.invitee_pubkey
        assert inv2.signature == inv.signature

    def test_is_expired(self):
        from ghost_sync import Invitation, MAX_INVITATION_AGE
        inv = Invitation(
            inviter_id="node-a",
            inviter_pubkey="abcdef",
            invitee_pubkey="123456",
            cluster_name="test",
            created_at=time.time() - MAX_INVITATION_AGE - 3600,
        )
        assert inv.is_expired()


class TestMembershipAttestation:
    def test_to_dict_roundtrip(self):
        from ghost_sync import MembershipAttestation
        att = MembershipAttestation(
            member_id="node-b",
            member_pubkey="123456",
            cluster_name="test",
            joined_at=time.time(),
            inviter_id="node-a",
            inviter_pubkey="abcdef",
            signature="sig789",
        )
        d = att.to_dict()
        att2 = MembershipAttestation.from_dict(d)
        assert att2.member_id == att.member_id
        assert att2.inviter_id == att.inviter_id
        assert att2.signature == att.signature


# =============================================================================
# Integration: full invite → accept → sync flow
# =============================================================================

@pytest.mark.asyncio
async def test_full_invite_accept_flow():
    """Test the full invitation and acceptance lifecycle."""
    tmpdir_a = Path(tempfile.mkdtemp())
    tmpdir_b = Path(tempfile.mkdtemp())
    identity_a = NodeIdentity.generate()
    identity_b = NodeIdentity.generate()

    from ghost_sync import PermissionedCluster, GlobalStateSync, ClusterMember

    cluster_a = PermissionedCluster(identity_a, cluster_name="integration-test",
                                     state_dir=tmpdir_a)
    cluster_b = PermissionedCluster(identity_b, cluster_name="integration-test",
                                     state_dir=tmpdir_b)

    # Phase 1: A invites B
    pub_b = identity_b.public_key_hex()
    inv = cluster_a.issue_invitation(pub_b)
    assert inv is not None
    assert inv.signature != ""

    # Phase 2: B accepts
    attestation = cluster_b.accept_invitation(inv)
    assert attestation is not None
    assert cluster_b.has_attestation
    assert cluster_b.is_permissioned(cluster_b.node_id)

    # Phase 3: A adds B as a member
    cluster_a.upsert_member(ClusterMember(
        node_id=cluster_b.node_id,
        pubkey=pub_b,
        host="10.0.0.2",
        port=9876,
        joined_at=time.time(),
    ))
    assert cluster_a.is_permissioned(cluster_b.node_id)

    # Phase 4: State sync engines acknowledge each other
    sync_a = GlobalStateSync(identity_a, cluster_a)
    sync_b = GlobalStateSync(identity_b, cluster_b)

    await sync_a.start(host="127.0.0.1", port=0)  # let OS assign
    await sync_b.start(host="127.0.0.1", port=0)

    # Get actual ports
    port_a = sync_a._server.sockets[0].getsockname()[1]
    port_b = sync_b._server.sockets[0].getsockname()[1]

    # B syncs to A (B has newer state)
    sync_a._state.version_vector.increment(identity_b.node_id)
    result = await sync_b.sync_to_peer("127.0.0.1", port_a)
    assert result, "State sync should succeed"

    await sync_a.stop()
    await sync_b.stop()
    import shutil
    shutil.rmtree(tmpdir_a, ignore_errors=True)
    shutil.rmtree(tmpdir_b, ignore_errors=True)


@pytest.mark.asyncio
async def test_permissioned_swarm_rejects_unauthorized():
    """Test that a permissioned swarm node rejects uninvited peers."""
    from ghost_swarm import GhostSwarmNode, enable_permissioned_cluster
    from node_identity import NodeIdentity

    identity = NodeIdentity.generate()

    # Clear module-level globals for isolated test
    import ghost_swarm
    ghost_swarm._permissioned_cluster = None
    ghost_swarm._global_state_sync = None

    node = GhostSwarmNode(node_id=identity.node_id, identity=identity,
                           port=0, enable_dht=False)
    node.enable_permissioned_cluster("test-cluster")
    await node.start()
    actual_port = node._server.sockets[0].getsockname()[1]

    # Start an unauthorized peer
    identity_evil = NodeIdentity.generate()
    from ghost_swarm import SwarmMessage
    evil_msg = SwarmMessage("mesh_join", identity_evil.node_id, {})
    evil_msg.sign(identity_evil)

    import asyncio
    try:
        r, w = await asyncio.wait_for(
            asyncio.open_connection("127.0.0.1", actual_port), timeout=5
        )
        w.write(evil_msg.encode())
        await w.drain()
        resp_data = await asyncio.wait_for(r.readline(), timeout=5)
        w.close()
        resp = SwarmMessage.decode(resp_data)
        assert resp is not None
        assert resp.msg_type == "permission_denied", \
            f"Expected permission_denied, got {resp.msg_type}"
    finally:
        await node.stop()
