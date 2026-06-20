"""
Test: P2P Swarm Task Distribution via JSON Queue + _handle_connection

Validates the end-to-end flow:
  1. Node 1 (manager.py) enqueues a 'hello_world' task to agent_data/task_queue.json
  2. A bridge process reads the queue, wraps it as a SwarmMessage("task", ...)
  3. Node 2 receives it via _handle_connection (simulated TCP stream)
  4. Node 2 adds it to _pending_tasks and the task handler processes it
"""

import asyncio
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# SECTION 1: Manager-side enqueue + JSON queue bridge
# ---------------------------------------------------------------------------

class TestManagerTaskQueue:
    """Validate that manager.py can enqueue tasks and they persist to JSON."""

    def test_enqueue_hello_world(self, tmp_agent_dir):
        """Push 'hello_world' into the JSON queue and verify it exists."""
        from manager import TaskManager

        task_file = tmp_agent_dir / "agent_data" / "task_queue.json"
        task_file.write_text("[]", encoding="utf-8")

        mgr = TaskManager()
        mgr.queue_file = task_file

        task = mgr.enqueue_task("hello_world")
        assert task["command"] == "hello_world"
        assert task["status"] == "pending"
        assert "id" in task

        tasks = json.loads(task_file.read_text(encoding="utf-8"))
        assert len(tasks) == 1
        assert tasks[0]["command"] == "hello_world"
        assert tasks[0]["status"] == "pending"

    def test_queue_to_swarm_message_conversion(self, tmp_agent_dir):
        """
        Read a task from the JSON queue and verify it converts to a
        valid SwarmMessage for P2P transport.
        """
        from ghost_swarm import SwarmMessage

        queue_path = tmp_agent_dir / "agent_data" / "task_queue.json"
        queue_path.write_text(
            json.dumps([{"id": 1001, "command": "hello_world", "status": "pending"}]),
            encoding="utf-8",
        )

        tasks = json.loads(queue_path.read_text(encoding="utf-8"))
        raw_task = tasks[0]

        msg = SwarmMessage(
            msg_type="task",
            sender_id="node-alpha",
            payload={
                "task_id": raw_task["id"],
                "command": raw_task["command"],
            },
        )
        assert msg.msg_type == "task"
        assert msg.payload["command"] == "hello_world"
        assert msg.payload["task_id"] == 1001

        msg.timestamp = datetime.now(timezone.utc).isoformat()
        encoded = msg.encode()
        decoded = SwarmMessage.decode(encoded)
        assert decoded is not None
        assert decoded.msg_type == "task"
        assert decoded.payload["command"] == "hello_world"


# ---------------------------------------------------------------------------
# SECTION 2: P2P receive via _handle_connection
# ---------------------------------------------------------------------------

class TestSwarmHandleConnection:
    """Simulate Node 2 receiving a task via _handle_connection."""

    @pytest.mark.asyncio
    async def test_task_received_via_handle_connection(self):
        """
        Create a mock TCP stream containing a SwarmMessage("task")
        and feed it to GhostSwarmNode._handle_connection.
        Verify the task lands in _pending_tasks.
        """
        from ghost_swarm import GhostSwarmNode, SwarmMessage

        node = GhostSwarmNode(node_id="node-beta", port=0, enable_dht=False)
        node._running = True

        msg = SwarmMessage(
            msg_type="task",
            sender_id="node-alpha",
            payload={"task_id": 1001, "command": "hello_world"},
        )
        msg.timestamp = datetime.now(timezone.utc).isoformat()
        msg.sign(node._secret)

        reader = AsyncMock(spec=asyncio.StreamReader)
        reader.readline.return_value = msg.encode()

        writer = AsyncMock(spec=asyncio.StreamWriter)
        writer.get_extra_info = MagicMock(side_effect=lambda key: {"peername": ("10.0.0.1", 9876)}.get(key))

        await node._handle_connection(reader, writer)

        assert len(node._pending_tasks) == 1
        received = node._pending_tasks[0]
        assert received.msg_type == "task"
        assert received.payload["command"] == "hello_world"
        assert received.sender_id == "node-alpha"

        writer.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_task_with_invalid_signature_rejected(self):
        """Messages with bad HMAC should be rejected, not added to queue."""
        from ghost_swarm import GhostSwarmNode, SwarmMessage

        node = GhostSwarmNode(node_id="node-beta", port=0, enable_dht=False)
        node._running = True

        msg = SwarmMessage(
            msg_type="task",
            sender_id="node-alpha",
            payload={"command": "hello_world"},
        )
        msg.timestamp = datetime.now(timezone.utc).isoformat()
        msg.sign(b"wrong-secret")

        reader = AsyncMock(spec=asyncio.StreamReader)
        reader.readline.return_value = msg.encode()

        writer = AsyncMock(spec=asyncio.StreamWriter)
        writer.get_extra_info = MagicMock(side_effect=lambda key: {"peername": ("10.0.0.1", 9876)}.get(key))

        await node._handle_connection(reader, writer)

        assert len(node._pending_tasks) == 0
        assert writer.close.call_count >= 1

    @pytest.mark.asyncio
    async def test_task_processor_invokes_handler(self):
        """
        After a task is received via _handle_connection, verify that
        _task_processor passes it to the registered handler.
        """
        from ghost_swarm import GhostSwarmNode, SwarmMessage

        handler = AsyncMock()
        node = GhostSwarmNode(
            node_id="node-beta", port=0, enable_dht=False,
            task_handler=handler,
        )
        node._running = True

        msg = SwarmMessage(
            msg_type="task",
            sender_id="node-alpha",
            payload={"task_id": 1001, "command": "hello_world"},
        )
        msg.timestamp = datetime.now(timezone.utc).isoformat()
        msg.sign(node._secret)

        reader = AsyncMock(spec=asyncio.StreamReader)
        reader.readline.return_value = msg.encode()

        writer = AsyncMock(spec=asyncio.StreamWriter)
        writer.get_extra_info = MagicMock(side_effect=lambda key: {"peername": ("10.0.0.1", 9876)}.get(key))

        await node._handle_connection(reader, writer)

        with patch.object(node, '_running', True):
            task = asyncio.create_task(node._task_processor())
            await asyncio.sleep(0.1)
            task.cancel()

        handler.assert_awaited_once()
        call_msg = handler.call_args[0][0]
        assert call_msg.payload["command"] == "hello_world"


# ---------------------------------------------------------------------------
# SECTION 3: End-to-end flow (integration)
# ---------------------------------------------------------------------------

@pytest.mark.integration
@pytest.mark.p2p
class TestEndToEndTaskDistribution:
    """
    Full integration: manager enqueues -> bridge reads -> P2P sends ->
    swarm receives via _handle_connection -> task processor executes.
    """

    @pytest.mark.asyncio
    async def test_full_task_distribution_flow(self, tmp_agent_dir):
        """
        End-to-end: manager.enqueue_task -> read from JSON -> wrap as
        SwarmMessage -> _handle_connection -> _pending_tasks.
        """
        from manager import TaskManager
        from ghost_swarm import GhostSwarmNode, SwarmMessage

        task_file = tmp_agent_dir / "agent_data" / "task_queue.json"
        task_file.write_text("[]", encoding="utf-8")

        mgr = TaskManager()
        mgr.queue_file = task_file
        mgr.output_file = tmp_agent_dir / "agent_logs" / "browser_output.json"

        enqueued = mgr.enqueue_task("hello_world")
        assert enqueued["command"] == "hello_world"

        tasks = json.loads(task_file.read_text(encoding="utf-8"))
        raw = tasks[0]

        node = GhostSwarmNode(node_id="node-beta", port=0, enable_dht=False)
        node._running = True

        msg = SwarmMessage(
            msg_type="task",
            sender_id="node-alpha",
            payload={"task_id": raw["id"], "command": raw["command"]},
        )
        msg.timestamp = datetime.now(timezone.utc).isoformat()
        msg.sign(node._secret)

        reader = AsyncMock(spec=asyncio.StreamReader)
        reader.readline.return_value = msg.encode()

        writer = AsyncMock(spec=asyncio.StreamWriter)
        writer.get_extra_info = MagicMock(side_effect=lambda key: {"peername": ("10.0.0.1", 9876)}.get(key))

        await node._handle_connection(reader, writer)

        assert len(node._pending_tasks) == 1
        received = node._pending_tasks[0]
        assert received.payload["command"] == "hello_world"
        assert received.payload["task_id"] == enqueued["id"]

    @pytest.mark.asyncio
    async def test_multiple_tasks_in_flight(self):
        """
        Verify that multiple tasks can be queued, sent, and received
        without collision.
        """
        from ghost_swarm import GhostSwarmNode, SwarmMessage

        node = GhostSwarmNode(node_id="node-beta", port=0, enable_dht=False)
        node._running = True

        tasks = [
            ("hello_world", 1001),
            ("echo test", 1002),
            ("ls -la", 1003),
        ]

        for cmd, tid in tasks:
            msg = SwarmMessage(
                msg_type="task",
                sender_id="node-alpha",
                payload={"task_id": tid, "command": cmd},
            )
            msg.timestamp = datetime.now(timezone.utc).isoformat()
            msg.sign(node._secret)

            reader = AsyncMock(spec=asyncio.StreamReader)
            reader.readline.return_value = msg.encode()

            writer = AsyncMock(spec=asyncio.StreamWriter)
            writer.get_extra_info = MagicMock(side_effect=lambda key: {"peername": ("10.0.0.1", 9876)}.get(key))

            await node._handle_connection(reader, writer)

        assert len(node._pending_tasks) == 3
        assert node._pending_tasks[0].payload["command"] == "hello_world"
        assert node._pending_tasks[1].payload["command"] == "echo test"
        assert node._pending_tasks[2].payload["command"] == "ls -la"
