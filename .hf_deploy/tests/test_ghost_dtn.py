"""Tests for Ghost DTN — Delay-Tolerant Networking Bundle Protocol."""

import asyncio
import tempfile
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from node_identity import NodeIdentity


# =============================================================================
# Bundle Protocol — Data Structures
# =============================================================================

class TestPrimaryBlock:
    def test_creation(self):
        from ghost_dtn import PrimaryBlock
        pb = PrimaryBlock(
            bundle_id="test-bundle-001",
            source="node-a",
            destination="node-b",
        )
        assert pb.version == 7
        assert pb.bundle_id == "test-bundle-001"
        assert pb.source == "node-a"
        assert pb.destination == "node-b"

    def test_expiry(self):
        from ghost_dtn import PrimaryBlock
        pb = PrimaryBlock(
            bundle_id="expired-test",
            source="a", destination="b",
            creation_timestamp=time.time() - 100,
            lifetime=1,  # 1 second
        )
        assert pb.is_expired

    def test_not_expired(self):
        from ghost_dtn import PrimaryBlock
        pb = PrimaryBlock(
            bundle_id="fresh-test",
            source="a", destination="b",
            creation_timestamp=time.time(),
            lifetime=3600,
        )
        assert not pb.is_expired

    def test_to_dict_roundtrip(self):
        from ghost_dtn import PrimaryBlock
        pb = PrimaryBlock(
            bundle_id="rt-test",
            source="a", destination="b",
            custody_transfer=True,
            max_hops=32,
        )
        d = pb.to_dict()
        pb2 = PrimaryBlock.from_dict(d)
        assert pb2.bundle_id == pb.bundle_id
        assert pb2.custody_transfer == pb.custody_transfer
        assert pb2.max_hops == pb.max_hops


class TestPayloadBlock:
    def test_serialize_roundtrip(self):
        from ghost_dtn import PayloadBlock
        pb = PayloadBlock(payload={"msg": "hello", "val": 42})
        data = pb.to_bytes()
        pb2 = PayloadBlock.from_bytes(data)
        assert pb2.payload == pb.payload


class TestCustodySignal:
    def test_to_dict_roundtrip(self):
        from ghost_dtn import CustodySignal
        cs = CustodySignal(
            bundle_id="bundle-001",
            signal_type=0,
            owner="node-a",
            reason="Accepted",
        )
        d = cs.to_dict()
        cs2 = CustodySignal.from_dict(d)
        assert cs2.bundle_id == cs.bundle_id
        assert cs2.owner == cs.owner


class TestDTNBundle:
    def test_create_bundle(self):
        from ghost_dtn import create_bundle, BundleStatus
        bundle = create_bundle(
            payload={"type": "ping"},
            source="alpha",
            destination="beta",
        )
        assert bundle.primary.source == "alpha"
        assert bundle.primary.destination == "beta"
        assert bundle.primary.version == 7
        assert bundle.bundle_status == BundleStatus.PENDING
        assert bundle.bundle_id is not None

    def test_serialize_roundtrip(self):
        from ghost_dtn import create_bundle, DTNBundle
        original = create_bundle(
            payload={"cmd": "exec", "args": ["ls"]},
            source="node-a",
            destination="node-b",
            custody_transfer=True,
        )
        data = original.serialize()
        restored = DTNBundle.deserialize(data)
        assert restored.primary.bundle_id == original.primary.bundle_id
        assert restored.primary.source == original.primary.source
        assert restored.payload.payload == original.payload.payload
        assert restored.primary.custody_transfer == original.primary.custody_transfer

    def test_hop_count_increment(self):
        from ghost_dtn import create_bundle
        bundle = create_bundle({"x": 1}, "a", "b")
        assert bundle.primary.hop_count == 0
        bundle.primary.hop_count += 1
        assert bundle.primary.hop_count == 1

    def test_expiry(self):
        from ghost_dtn import create_bundle
        bundle = create_bundle({"x": 1}, "a", "b", lifetime=0.01)
        assert not bundle.primary.is_expired
        time.sleep(0.02)
        assert bundle.primary.is_expired


# =============================================================================
# Bundle Store
# =============================================================================

class TestBundleStore:
    def setup_method(self):
        self._tmpdir = Path(tempfile.mkdtemp())
        from ghost_dtn import BundleStore
        self.store = BundleStore(store_dir=self._tmpdir)

    def teardown_method(self):
        import shutil
        shutil.rmtree(self._tmpdir, ignore_errors=True)

    def test_save_and_get(self):
        from ghost_dtn import create_bundle
        bundle = create_bundle({"msg": "hello"}, "a", "b")
        self.store.save(bundle)
        retrieved = self.store.get(bundle.bundle_id)
        assert retrieved is not None
        assert retrieved.payload.payload == bundle.payload.payload

    def test_remove(self):
        from ghost_dtn import create_bundle
        bundle = create_bundle({"msg": "remove-me"}, "a", "b")
        self.store.save(bundle)
        self.store.remove(bundle.bundle_id)
        assert self.store.get(bundle.bundle_id) is None

    def test_list_pending(self):
        from ghost_dtn import create_bundle, BundleStatus
        b1 = create_bundle({"x": 1}, "a", "b")
        b2 = create_bundle({"y": 2}, "a", "c")
        b3 = create_bundle({"z": 3}, "a", "b")
        b3.bundle_status = BundleStatus.DELIVERED
        self.store.save(b1)
        self.store.save(b2)
        self.store.save(b3)

        pending_b = self.store.list_pending(destination="b")
        assert len(pending_b) == 1
        assert pending_b[0].bundle_id == b1.bundle_id

        all_pending = self.store.list_pending()
        assert len(all_pending) == 2

    def test_expire_stale(self):
        from ghost_dtn import create_bundle
        bundle = create_bundle({"x": 1}, "a", "b", lifetime=0.01)
        self.store.save(bundle)
        time.sleep(0.02)
        removed = self.store.expire_stale()
        assert removed >= 1

    def test_persistence_across_instances(self):
        from ghost_dtn import create_bundle, BundleStore
        bundle = create_bundle({"persist": True}, "a", "b")
        self.store.save(bundle)
        bid = bundle.bundle_id

        store2 = BundleStore(store_dir=self._tmpdir)
        restored = store2.get(bid)
        assert restored is not None
        assert restored.payload.payload == {"persist": True}


# =============================================================================
# Ephemeral Discovery
# =============================================================================

class TestEphemeralDiscovery:
    def setup_method(self):
        self.identity = NodeIdentity.generate()
        from ghost_dtn import EphemeralDiscovery
        self.discovery = EphemeralDiscovery(
            node_id=self.identity.node_id,
            identity=self.identity,
            discovery_port=0,  # system-assigned
            dtn_port=9880,
        )

    def test_upsert_link(self):
        ls = self.discovery.upsert_link("peer-a", "10.0.0.1", 9880)
        assert ls.node_id == "peer-a"
        assert ls.host == "10.0.0.1"
        assert ls.quality == 1.0

    def test_upsert_link_updates_existing(self):
        self.discovery.upsert_link("peer-a", "10.0.0.1", 9880)
        ls = self.discovery.upsert_link("peer-a", "10.0.0.2", 9880)
        assert ls.host == "10.0.0.2"  # updated
        assert ls.quality > 0.0

    def test_get_link(self):
        self.discovery.upsert_link("peer-a", "10.0.0.1", 9880)
        ls = self.discovery.get_link("peer-a")
        assert ls is not None
        assert ls.node_id == "peer-a"

    def test_remove_link(self):
        self.discovery.upsert_link("peer-a", "10.0.0.1", 9880)
        self.discovery.remove_link("peer-a")
        assert self.discovery.get_link("peer-a") is None

    def test_link_alive_timeout(self):
        from ghost_dtn import EPHEMERAL_TIMEOUT
        self.discovery.upsert_link("peer-a", "10.0.0.1", 9880)
        ls = self.discovery.get_link("peer-a")
        assert ls.is_alive
        # Manually set last_seen far in the past
        ls.last_seen = time.time() - EPHEMERAL_TIMEOUT - 10
        assert not ls.is_alive

    def test_find_route_direct(self):
        self.discovery.upsert_link("peer-a", "10.0.0.1", 9880)
        hop = self.discovery.find_route("peer-a")
        assert hop == "peer-a"

    def test_find_route_via_table(self):
        from ghost_dtn import EPHEMERAL_TIMEOUT
        self.discovery.upsert_link("router", "10.0.0.2", 9880)
        self.discovery.update_route_table("peer-z", "router")
        hop = self.discovery.find_route("peer-z")
        assert hop == "router"

    def test_find_route_unknown(self):
        hop = self.discovery.find_route("nonexistent")
        assert hop is None


# =============================================================================
# DTN Router
# =============================================================================

class TestDTNRouter:
    def setup_method(self):
        self.identity = NodeIdentity.generate()
        from ghost_dtn import EphemeralDiscovery, DTNRouter
        self.discovery = EphemeralDiscovery(
            node_id=self.identity.node_id,
            identity=self.identity,
        )
        self.router = DTNRouter(self.identity.node_id, self.discovery)
        # Add some peers
        self.discovery.upsert_link("peer-a", "10.0.0.1", 9880)
        self.discovery.upsert_link("peer-b", "10.0.0.2", 9880)
        self.discovery.upsert_link("peer-c", "10.0.0.3", 9880)

    def test_route_direct(self):
        from ghost_dtn import create_bundle
        bundle = create_bundle({"x": 1}, "self", "peer-a")
        next_hop = self.router.route_bundle(bundle)
        assert next_hop == "peer-a"

    def test_route_unknown_store_and_forward(self):
        from ghost_dtn import create_bundle
        bundle = create_bundle({"x": 1}, "self", "unknown-peer")
        next_hop = self.router.route_bundle(bundle)
        # Should pick best quality peer for flood
        assert next_hop is not None

    def test_get_route_info(self):
        info = self.router.get_route_info()
        assert "peer-a" in info
        assert "peer-b" in info


# =============================================================================
# Custody Manager
# =============================================================================

class TestCustodyManager:
    def setup_method(self):
        self._tmpdir = Path(tempfile.mkdtemp())
        from ghost_dtn import BundleStore, CustodyManager
        self.store = BundleStore(store_dir=self._tmpdir)
        self.custody = CustodyManager("node-a", self.store)

    def teardown_method(self):
        import shutil
        shutil.rmtree(self._tmpdir, ignore_errors=True)

    def test_accept_custody(self):
        from ghost_dtn import create_bundle, BundleStatus
        bundle = create_bundle({"x": 1}, "a", "b", custody_transfer=True)
        self.store.save(bundle)
        signal = self.custody.accept_custody(bundle)
        assert signal.signal_type == 0  # ACCEPT
        assert signal.owner == "node-a"
        assert bundle.bundle_status == BundleStatus.CUSTODY_ACCEPTED
        assert bundle.current_custodian == "node-a"

    def test_release_custody(self):
        from ghost_dtn import create_bundle
        bundle = create_bundle({"x": 1}, "a", "b", custody_transfer=True)
        self.store.save(bundle)
        self.custody.accept_custody(bundle)
        signal = self.custody.release_custody(bundle.bundle_id)
        assert signal.bundle_id == bundle.bundle_id

    def test_needs_retransmit(self):
        from ghost_dtn import create_bundle, BundleStatus
        bundle = create_bundle({"x": 1}, "a", "b", custody_transfer=True)
        bundle.bundle_status = BundleStatus.PENDING
        assert self.custody.needs_retransmit(bundle)
        # After custody accepted, no retransmit needed
        self.custody.accept_custody(bundle)
        assert not self.custody.needs_retransmit(bundle)
        # After delivery, no retransmit
        bundle.bundle_status = BundleStatus.DELIVERED
        assert not self.custody.needs_retransmit(bundle)

    def test_handle_signal_accept(self):
        from ghost_dtn import create_bundle, CustodySignal, BundleStatus
        bundle = create_bundle({"x": 1}, "a", "b", custody_transfer=True)
        self.store.save(bundle)
        signal = CustodySignal(bundle_id=bundle.bundle_id, signal_type=0, owner="node-b")
        self.custody.handle_signal(signal, bundle)
        assert bundle.bundle_status == BundleStatus.CUSTODY_ACCEPTED
        assert bundle.current_custodian == "node-b"

    def test_handle_signal_refuse(self):
        from ghost_dtn import create_bundle, CustodySignal, BundleStatus
        bundle = create_bundle({"x": 1}, "a", "b", custody_transfer=True)
        bundle.bundle_status = BundleStatus.IN_FLIGHT
        self.store.save(bundle)
        signal = CustodySignal(bundle_id=bundle.bundle_id, signal_type=2, owner="node-b",
                                reason="Capacity full")
        self.custody.handle_signal(signal, bundle)
        assert bundle.bundle_status == BundleStatus.PENDING
        assert bundle.custody_retries == 1


# =============================================================================
# DTN Node — Integration Tests
# =============================================================================

@pytest.mark.asyncio
async def test_dtn_node_send_and_receive():
    """Test full DTN bundle send/receive between two nodes."""
    tmpdir_a = Path(tempfile.mkdtemp())
    tmpdir_b = Path(tempfile.mkdtemp())
    identity_a = NodeIdentity.generate()
    identity_b = NodeIdentity.generate()

    from ghost_dtn import DTNNode

    node_a = DTNNode(
        node_id=identity_a.node_id,
        identity=identity_a,
        store_dir=tmpdir_a,
        dtn_port=0,  # OS-assigned
    )
    node_b = DTNNode(
        node_id=identity_b.node_id,
        identity=identity_b,
        store_dir=tmpdir_b,
        dtn_port=0,
    )

    received_bundles = []
    seen_ids = set()

    @node_b.on_bundle
    async def handler(bundle):
        if bundle.bundle_id not in seen_ids:
            seen_ids.add(bundle.bundle_id)
            received_bundles.append(bundle)

    # Start both nodes
    await node_a.start(host="127.0.0.1", port=0)
    await node_b.start(host="127.0.0.1", port=0)

    # Get actual ports
    port_a = node_a._server.sockets[0].getsockname()[1]
    port_b = node_b._server.sockets[0].getsockname()[1]

    # Manually link them (simulate ephemeral discovery)
    node_a.discovery.upsert_link(identity_b.node_id, "127.0.0.1", port_b)
    node_b.discovery.upsert_link(identity_a.node_id, "127.0.0.1", port_a)

    # Send a bundle from A to B
    bid = await node_a.send(
        payload={"type": "ping", "seq": 1},
        destination=identity_b.node_id,
        custody_transfer=True,
    )
    assert bid is not None

    # Wait for delivery
    await asyncio.sleep(2)

    assert len(received_bundles) == 1
    assert received_bundles[0].payload.payload == {"type": "ping", "seq": 1}
    assert received_bundles[0].primary.source == identity_a.node_id

    await node_a.stop()
    await node_b.stop()
    import shutil
    shutil.rmtree(tmpdir_a, ignore_errors=True)
    shutil.rmtree(tmpdir_b, ignore_errors=True)


@pytest.mark.asyncio
async def test_dtn_multi_hop():
    """Test bundle routing through an intermediate node."""
    tmpdirs = [Path(tempfile.mkdtemp()) for _ in range(3)]
    identities = [NodeIdentity.generate() for _ in range(3)]

    from ghost_dtn import DTNNode

    nodes = []
    for i, ident in enumerate(identities):
        node = DTNNode(
            node_id=ident.node_id,
            identity=ident,
            store_dir=tmpdirs[i],
            dtn_port=0,
        )
        nodes.append(node)

    received = []

    @nodes[2].on_bundle
    async def handler(bundle):
        received.append(bundle)

    # Start all nodes
    for i, node in enumerate(nodes):
        await node.start(host="127.0.0.1", port=0)

    ports = [n._server.sockets[0].getsockname()[1] for n in nodes]

    # Setup topology: A <-> B <-> C (A cannot see C directly)
    nodes[0].discovery.upsert_link(identities[1].node_id, "127.0.0.1", ports[1])  # A sees B
    nodes[1].discovery.upsert_link(identities[0].node_id, "127.0.0.1", ports[0])  # B sees A
    nodes[1].discovery.upsert_link(identities[2].node_id, "127.0.0.1", ports[2])  # B sees C
    nodes[2].discovery.upsert_link(identities[1].node_id, "127.0.0.1", ports[1])  # C sees B

    # Advertise routes through B
    nodes[1].discovery.update_route_table(identities[2].node_id, identities[2].node_id)

    # Send from A to C (must go through B)
    bid = await nodes[0].send(
        payload={"type": "multi-hop", "from": "A", "to": "C"},
        destination=identities[2].node_id,
    )
    assert bid is not None

    await asyncio.sleep(3)

    assert len(received) == 1, f"Expected 1 bundle, got {len(received)}"
    assert received[0].payload.payload["to"] == "C"
    assert received[0].primary.hop_count >= 1  # at least 1 hop

    # Cleanup
    for node in nodes:
        await node.stop()
    import shutil
    for td in tmpdirs:
        shutil.rmtree(td, ignore_errors=True)


@pytest.mark.asyncio
async def test_dtn_store_and_forward():
    """Test that bundles are stored and delivered when peer comes online."""
    tmpdir_a = Path(tempfile.mkdtemp())
    tmpdir_b = Path(tempfile.mkdtemp())
    identity_a = NodeIdentity.generate()
    identity_b = NodeIdentity.generate()

    from ghost_dtn import DTNNode

    node_a = DTNNode(
        node_id=identity_a.node_id,
        identity=identity_a,
        store_dir=tmpdir_a,
        dtn_port=0,
    )
    node_b = DTNNode(
        node_id=identity_b.node_id,
        identity=identity_b,
        store_dir=tmpdir_b,
        dtn_port=0,
    )

    received = []

    @node_b.on_bundle
    async def handler(bundle):
        received.append(bundle)

    # Start only node A (B is offline)
    await node_a.start(host="127.0.0.1", port=0)
    port_a = node_a._server.sockets[0].getsockname()[1]

    # Send bundle to B while B is offline
    bid = await node_a.send(
        payload={"type": "store-forward", "msg": "offline-test"},
        destination=identity_b.node_id,
    )
    assert bid is not None

    # Bundle should be stored (pending), not delivered
    pending = node_a.store.list_pending(destination=identity_b.node_id)
    assert len(pending) >= 1

    # Now start B and link them
    await node_b.start(host="127.0.0.1", port=0)
    port_b = node_b._server.sockets[0].getsockname()[1]

    node_a.discovery.upsert_link(identity_b.node_id, "127.0.0.1", port_b)
    node_b.discovery.upsert_link(identity_a.node_id, "127.0.0.1", port_a)

    # Wait for store flush to deliver
    await asyncio.sleep(3)

    assert len(received) >= 1
    assert received[0].payload.payload["msg"] == "offline-test"

    await node_a.stop()
    await node_b.stop()
    import shutil
    shutil.rmtree(tmpdir_a, ignore_errors=True)
    shutil.rmtree(tmpdir_b, ignore_errors=True)
