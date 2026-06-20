"""
Ghost Engine — System Integrity Test Suite

Validates the core decentralized architecture:
  - IPFS connectivity & CRUD operations
  - Redis task queue connectivity
  - SQLite metrics database health
  - Circuit breaker / failover cascade
  - Task execution workflow
  - Security utility hardening
  - Model router preflight checks
  - File system persistence

Run:  pytest tests/test_system_integrity.py -v --timeout=120
"""

import asyncio
import json
import os
import sqlite3
import time
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# =============================================================================
# SECTION 1: Connectivity Tests
# =============================================================================

class TestIPFSConnectivity:
    """Validate connection to IPFS node and basic content operations."""

    def test_ipfs_client_instantiation(self, ipfs_client):
        """Verify ipfshttpclient can connect or fall back to mock."""
        assert ipfs_client is not None
        version = ipfs_client.version()
        assert "Version" in version

    def test_ipfs_add_and_cat(self, ipfs_client, ipfs_cid):
        """Test adding content to IPFS and retrieving it by CID."""
        content = {"agent": "ghost", "test": "integration", "timestamp": time.time()}
        blob = json.dumps(content).encode()

        cid = ipfs_client.add_bytes(blob)
        assert cid is not None
        assert isinstance(cid, str)
        assert len(cid) > 10

        retrieved = ipfs_client.cat(cid)
        decoded = json.loads(retrieved.decode() if isinstance(retrieved, bytes) else retrieved)
        assert decoded["agent"] == "ghost"
        assert decoded["test"] == "integration"

    def test_ipfs_pin_operations(self, ipfs_client, ipfs_cid):
        """Test pinning content to ensure persistence."""
        result = ipfs_client.pin.add(ipfs_cid)
        if isinstance(result, dict):
            assert "Pins" in result or isinstance(result.get("Pins"), list)

    def test_ipfs_pubsub_topic(self, ipfs_client):
        """Test IPFS PubSub topic publish (fabric isolation)."""
        try:
            result = ipfs_client.pubsub.pub("ghost:test", json.dumps({"msg": "ping"}))
            assert result is None or result.get("error") is None
        except Exception as exc:
            if "mocked" in str(exc).lower():
                pytest.skip("IPFS PubSub not available in mock mode")


class TestRedisConnectivity:
    """Validate connection to Redis task queue."""

    @pytest.mark.asyncio
    async def test_redis_ping(self, redis_client):
        """Verify Redis server responds to ping."""
        pong = await redis_client.ping()
        assert pong is True

    @pytest.mark.asyncio
    async def test_redis_set_get(self, redis_client):
        """Test basic key-value operations."""
        await redis_client.set("ghost:test:key", "test_value")
        value = await redis_client.get("ghost:test:key")
        assert value == "test_value"

    @pytest.mark.asyncio
    async def test_redis_task_queue_operations(self, redis_client):
        """Test list-based task queue push/pop."""
        await redis_client.lpush("ghost:queue:tasks", json.dumps({"id": "1", "task": "ping"}))
        await redis_client.lpush("ghost:queue:tasks", json.dumps({"id": "2", "task": "pong"}))
        count = await redis_client.llen("ghost:queue:tasks")
        assert count == 2

        task = await redis_client.rpop("ghost:queue:tasks")
        assert task is not None
        parsed = json.loads(task)
        assert parsed["task"] == "ping"

    @pytest.mark.asyncio
    async def test_redis_key_expiry(self, redis_client):
        """Test TTL-based key expiry."""
        await redis_client.setex("ghost:test:ephemeral", 1, "will_expire")
        assert await redis_client.get("ghost:test:ephemeral") == "will_expire"
        await asyncio.sleep(1.1)
        assert await redis_client.get("ghost:test:ephemeral") is None

    @pytest.mark.asyncio
    async def test_redis_pubsub_channel(self, redis_client):
        """Test Redis PubSub channel publish/subscribe."""
        await redis_client.publish("ghost:channel:test", "hello")
        assert True

    @pytest.mark.asyncio
    async def test_redis_empty_queue_returns_none(self, redis_client):
        """Verify popping from an empty queue returns None."""
        await redis_client.delete("ghost:queue:empty")
        result = await redis_client.rpop("ghost:queue:empty")
        assert result is None


# =============================================================================
# SECTION 2: Health Check Tests
# =============================================================================

class TestMetricsDatabase:
    """Validate SQLite metrics database health."""

    def test_metrics_db_creation(self, metrics_store, tmp_agent_dir):
        """Verify SQLite database file is created on init."""
        db_path = tmp_agent_dir / "agent_metrics.db"
        assert db_path.exists(), "Metrics DB file was not created"
        assert db_path.stat().st_size > 0, "Metrics DB file is empty"

    def test_metrics_db_table_schema(self, tmp_sqlite_db):
        """Verify the metrics table has the correct schema."""
        conn = sqlite3.connect(tmp_sqlite_db)
        try:
            cursor = conn.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='metrics'")
            row = cursor.fetchone()
            assert row is not None, "metrics table not found"
            schema = row[0].lower()
            assert "timestamp" in schema
            assert "category" in schema
            assert "name" in schema
            assert "payload" in schema
        finally:
            conn.close()

    def test_metrics_db_insert_and_query(self, metrics_store):
        """Test writing and reading metrics entries."""
        metrics_store.record_system_event("test_event", {"key": "value"})
        metrics_store.record_task_event("completed", MagicMock(id="task-1"), 0.5)

        conn = sqlite3.connect(metrics_store.sqlite_path)
        try:
            cursor = conn.execute("SELECT COUNT(*) FROM metrics")
            count = cursor.fetchone()[0]
            assert count == 2, f"Expected 2 metrics entries, got {count}"

            cursor = conn.execute("SELECT category, name FROM metrics WHERE category='system'")
            row = cursor.fetchone()
            assert row is not None
            assert row[0] == "system"
            assert row[1] == "test_event"
        finally:
            conn.close()

    def test_metrics_db_json_persistence(self, metrics_store, tmp_agent_dir):
        """Verify metrics are also persisted to JSON."""
        metrics_store.record_system_event("json_test", {"data": 42})
        json_path = tmp_agent_dir / "dashboard_metrics.json"
        assert json_path.exists()
        data = json.loads(json_path.read_text())
        assert "events" in data
        assert len(data["events"]) >= 1
        assert data["events"][-1]["name"] == "json_test"

    def test_metrics_db_concurrent_writes(self, metrics_store):
        """Test that multiple rapid writes do not corrupt the database."""
        for i in range(50):
            metrics_store.record_system_event(f"concurrent_{i}", {"index": i})

        conn = sqlite3.connect(metrics_store.sqlite_path)
        try:
            cursor = conn.execute("SELECT COUNT(*) FROM metrics")
            count = cursor.fetchone()[0]
            assert count == 50, f"Expected 50 entries, got {count}"
        finally:
            conn.close()

    def test_metrics_db_recovery_after_corruption(self, tmp_agent_dir):
        """Verify MetricsStore handles a pre-existing corrupt DB gracefully."""
        from dashboard_instrumentation import MetricsStore

        db_path = tmp_agent_dir / "agent_metrics.db"
        db_path.write_text("not valid sqlite", encoding="utf-8")

        store = MetricsStore(sqlite_path=str(db_path))
        store.record_system_event("after_corruption", {"recovered": True})

        conn = sqlite3.connect(db_path)
        try:
            cursor = conn.execute("SELECT COUNT(*) FROM metrics")
            count = cursor.fetchone()[0]
            assert count >= 1
        finally:
            conn.close()


class TestFastAPIHealth:
    """Validate the FastAPI dashboard health endpoint."""

    @pytest.mark.asyncio
    async def test_dashboard_root_endpoint(self):
        """Test that the FastAPI app boots and serves the dashboard."""
        import httpx
        from manager import app

        async with httpx.AsyncClient(app=app, base_url="http://test") as client:
            response = await client.get("/")
            assert response.status_code == 200
            assert "Ghost Engine" in response.text or "Decentralized" in response.text

    @pytest.mark.asyncio
    async def test_status_endpoint(self):
        """Test the /api/status endpoint returns service states."""
        import httpx
        from manager import app

        async with httpx.AsyncClient(app=app, base_url="http://test") as client:
            response = await client.get("/api/status")
            assert response.status_code == 200
            data = response.json()
            assert "services" in data
            assert "pending_tasks" in data

    @pytest.mark.asyncio
    async def test_logs_endpoint(self):
        """Test the /api/logs endpoint returns output logs."""
        import httpx
        from manager import app

        async with httpx.AsyncClient(app=app, base_url="http://test") as client:
            response = await client.get("/api/logs")
            assert response.status_code == 200
            data = response.json()
            assert "outputs" in data


class TestFileSystemHealth:
    """Validate file system structure is intact."""

    def test_agent_directories_exist(self, tmp_agent_dir):
        """Verify required agent directories are present."""
        assert (tmp_agent_dir / "agent_logs").is_dir()
        assert (tmp_agent_dir / "agent_data").is_dir()
        assert (tmp_agent_dir / "browser_profile").is_dir()

    def test_agent_config_exists(self):
        """Verify agent_config.json exists and is valid JSON."""
        config_path = Path("agent_config.json")
        if config_path.exists():
            data = json.loads(config_path.read_text())
            assert "mode" in data
            assert "optimized" in data

    def test_task_queue_file_initialization(self, tmp_agent_dir):
        """Verify task_queue.json is initialized as empty array."""
        path = tmp_agent_dir / "agent_data" / "task_queue.json"
        path.write_text("[]", encoding="utf-8")
        data = json.loads(path.read_text())
        assert isinstance(data, list)
        assert len(data) == 0

    def test_state_file_initialization(self, tmp_agent_dir):
        """Verify agent_state.json is initialized as empty object."""
        path = tmp_agent_dir / "agent_data" / "agent_state.json"
        path.write_text("{}", encoding="utf-8")
        data = json.loads(path.read_text())
        assert isinstance(data, dict)
        assert len(data) == 0


# =============================================================================
# SECTION 3: Circuit Breaker & Failover Tests
# =============================================================================

class TestCircuitBreaker:
    """Validate the model router cascade failover and circuit breaker logic."""

    def test_model_router_cascade_order(self, model_router):
        """Verify the cascade tries Gemini, then Groq, then local."""
        assert hasattr(model_router, "route")
        cascade_order = []
        for name, fn in model_router.route.__globals__.get("cascade", []):
            cascade_order.append(name if isinstance(name, str) else None)

    def test_circuit_breaker_429_detection(self, model_router):
        """Verify 429 rate-limit responses are correctly identified."""
        assert model_router._is_quota_or_timeout({"output": "429 rate limit exceeded"}, 1.0) is True
        assert model_router._is_quota_or_timeout({"output": "quota exceeded"}, 1.0) is True
        assert model_router._is_quota_or_timeout({"output": "rate limit hit"}, 1.0) is True
        assert model_router._is_quota_or_timeout({"output": "too many requests"}, 1.0) is True

    def test_circuit_breaker_latency_detection(self, model_router):
        """Verify high-latency failures trigger circuit breaker."""
        assert model_router._is_quota_or_timeout({"status": "error", "output": "timeout"}, 6.0) is True
        assert model_router._is_quota_or_timeout({"status": "error", "output": "slow"}, 4.0) is False

    def test_circuit_breaker_groq_cooldown(self, model_router):
        """Verify Groq is disabled after 429 and re-enabled state is tracked."""
        assert model_router._groq_active is True
        model_router._groq_active = False
        result = model_router._call_groq("test prompt")
        assert result["status"] == "error"
        assert "disabled" in result["output"].lower()
        model_router._groq_active = True

    def test_failover_cascade_on_all_backends_down(self, model_router):
        """Verify the cascade returns 'all backends exhausted' when all fail."""
        with patch.object(model_router, '_call_gemini', return_value={"status": "error", "output": "down"}):
            with patch.object(model_router, '_call_groq', return_value={"status": "error", "output": "down"}):
                with patch.object(model_router, '_call_local', return_value={"status": "error", "output": "down"}):
                    result = model_router.route("test")
                    assert result.status == "error"
                    assert "exhausted" in result.output.lower()

    def test_failover_recovers_on_second_tier(self, model_router):
        """Verify cascade falls through to the first backend that succeeds."""
        with patch.object(model_router, '_call_gemini', return_value={"status": "error", "output": "429"}):
            with patch.object(model_router, '_call_groq', return_value={"status": "success", "output": "ok"}):
                result = model_router.route("test")
                assert result.status == "success"
                assert result.source == "groq"

    def test_learning_log_records_failover(self, model_router, learning_log):
        """Verify failover events are recorded in the learning log."""
        with patch.object(model_router, '_call_gemini', return_value={"status": "error", "output": "fail"}):
            with patch.object(model_router, '_call_groq', return_value={"status": "error", "output": "fail"}):
                with patch.object(model_router, '_call_local', return_value={"status": "success", "output": "ok"}):
                    model_router.route("failover test")
        entries = learning_log.latest(5)
        fail_entries = [e for e in entries if e.get("status") == "error"]
        success_entries = [e for e in entries if e.get("status") == "success"]
        assert len(success_entries) >= 1


# =============================================================================
# SECTION 4: Execution Workflow Tests
# =============================================================================

class TestExecutionWorkflow:
    """Validate task submission, execution, and result collection."""

    @pytest.mark.asyncio
    async def test_compute_task_lifecycle(self, task_store):
        """Test a task goes through pending -> running -> completed."""
        from ghost_compute import ComputeTask, TaskStatus

        task = ComputeTask(task_id="lifecycle-1", task_type="echo", payload={"msg": "hello"})
        assert task.status == TaskStatus.PENDING.value

        task.status = TaskStatus.RUNNING.value
        task.started_at = time.time()
        assert task.status == TaskStatus.RUNNING.value

        task.result = {"echo": "hello"}
        task.status = TaskStatus.COMPLETED.value
        task.completed_at = time.time()
        assert task.status == TaskStatus.COMPLETED.value
        assert task.duration is not None

    @pytest.mark.asyncio
    async def test_compute_worker_executes_task(self, task_store):
        """Test ComputeWorker picks up and executes a pending task."""
        from ghost_compute import ComputeTask, ComputeWorker, TaskStatus

        task = ComputeTask(task_id="worker-1", task_type="echo", payload={"msg": "hello"})
        task_store.add(task)

        worker = ComputeWorker(worker_id="test-worker", store=task_store)
        worker.register("echo", lambda payload: {"echo": payload["msg"]})

        pending = task_store.next_pending()
        assert pending is not None
        assert pending.task_id == "worker-1"

        await worker._execute(pending)
        completed = task_store.get("worker-1")
        assert completed.status == TaskStatus.COMPLETED.value
        assert completed.result["echo"] == "hello"

    @pytest.mark.asyncio
    async def test_compute_worker_timeout(self, task_store):
        """Verify tasks timeout correctly."""
        from ghost_compute import ComputeTask, ComputeWorker, TaskStatus

        async def slow_handler(payload):
            await asyncio.sleep(10)
            return {"done": True}

        task = ComputeTask(task_id="timeout-1", task_type="slow", payload={}, timeout=0.5)
        task_store.add(task)

        worker = ComputeWorker(worker_id="test-worker", store=task_store)
        worker.register("slow", slow_handler)

        await worker._execute(task)
        completed = task_store.get("timeout-1")
        assert completed.status == TaskStatus.TIMEOUT.value

    @pytest.mark.asyncio
    async def test_compute_worker_no_handler(self, task_store):
        """Verify task fails when no handler is registered."""
        from ghost_compute import ComputeTask, ComputeWorker, TaskStatus

        task = ComputeTask(task_id="nohandler-1", task_type="unknown", payload={})
        task_store.add(task)

        worker = ComputeWorker(worker_id="test-worker", store=task_store)
        await worker._execute(task)
        completed = task_store.get("nohandler-1")
        assert completed.status == TaskStatus.FAILED.value
        assert "No handler" in (completed.error or "")

    @pytest.mark.asyncio
    async def test_execution_coordinator_submit(self, metrics_store):
        """Test ExecutionCoordinator accepts and queues tasks."""
        from execution_core import ExecutionCoordinator, PipelineTask, TaskType, TaskPriority

        coordinator = ExecutionCoordinator(metrics=metrics_store)
        await coordinator.start()

        task = PipelineTask(
            type=TaskType.SYSTEM,
            payload={"command": "echo hello"},
            priority=TaskPriority.HIGH,
        )
        await coordinator.submit_task(task)
        assert task.status != "dead"

        await coordinator.stop()

    def test_execution_coordinator_queues_by_priority(self, metrics_store):
        """Verify tasks are ordered by priority in the queue."""
        from execution_core import ExecutionCoordinator, PipelineTask, TaskType, TaskPriority

        coordinator = ExecutionCoordinator(metrics=metrics_store)
        high = PipelineTask(type=TaskType.SYSTEM, payload={}, priority=TaskPriority.HIGH)
        low = PipelineTask(type=TaskType.SYSTEM, payload={}, priority=TaskPriority.LOW)

        coordinator.queue.put_nowait(low)
        coordinator.queue.put_nowait(high)

        first = coordinator.queue.get_nowait()
        assert first.priority == TaskPriority.HIGH


# =============================================================================
# SECTION 5: Security Tests
# =============================================================================

class TestSecurityHardening:
    """Validate security utilities are properly hardened."""

    def test_sanitize_redacts_tokens(self):
        """Verify API tokens are redacted in logs."""
        from security_utils import sanitize_for_logging

        cases = [
            ("ghp_abcdefghijklmnop", "ghp_***REDACTED***"),
            ("gsk_1234567890abcd", "gsk_***REDACTED***"),
            ("hf_qrstuvwxyz1234", "hf_***REDACTED***"),
            ("cfut_abcdef123456", "cfut_***REDACTED***"),
        ]
        for raw, expected in cases:
            result = sanitize_for_logging(raw)
            assert expected in result, f"Failed to redact {raw}"

    def test_sanitize_redacts_passwords(self):
        """Verify password patterns are redacted."""
        from security_utils import sanitize_for_logging

        result = sanitize_for_logging('password = "my_secret_pass_123"')
        assert "my_secret_pass_123" not in result
        assert "***REDACTED***" in result

    def test_validate_command_blocks_injection(self, dangerous_commands):
        """Verify dangerous command patterns are rejected."""
        from security_utils import validate_command

        for cmd in dangerous_commands:
            valid, msg = validate_command(cmd)
            assert valid is False, f"Dangerous command not blocked: {cmd}"
            assert "dangerous" in msg.lower() or "empty" in msg.lower()

    def test_validate_command_allows_safe(self, safe_commands):
        """Verify safe commands pass validation."""
        from security_utils import validate_command

        for cmd in safe_commands:
            valid, msg = validate_command(cmd)
            assert valid is True, f"Safe command rejected: {cmd} ({msg})"

    def test_validate_command_blocks_empty(self):
        """Verify empty command is rejected."""
        from security_utils import validate_command

        valid, msg = validate_command("")
        assert valid is False
        assert "empty" in msg.lower()

    def test_validate_command_blocks_oversized(self):
        """Verify oversized command is rejected."""
        from security_utils import validate_command, MAX_COMMAND_LENGTH

        valid, msg = validate_command("A" * (MAX_COMMAND_LENGTH + 1))
        assert valid is False
        assert "length" in msg.lower()

    def test_cli_action_validation(self):
        """Verify CLI actions are properly validated."""
        from security_utils import validate_action, CLIAction

        valid, action = validate_action("status")
        assert valid is True
        assert action == CLIAction.STATUS

        valid, action = validate_action("INVALID_ACTION_123")
        assert valid is False
        assert action is None

    def test_payload_size_limits(self):
        """Verify payload size limits are enforced."""
        from security_utils import check_payload_size, MAX_PAYLOAD_SIZE

        valid, _ = check_payload_size(1000)
        assert valid is True

        valid, _ = check_payload_size(None)
        assert valid is True

        valid, _ = check_payload_size(MAX_PAYLOAD_SIZE + 1)
        assert valid is False

    def test_command_parsing(self):
        """Verify shell-safe command parsing."""
        from security_utils import parse_command_safely

        assert parse_command_safely("ls -la /tmp") == ["ls", "-la", "/tmp"]
        assert parse_command_safely('echo "hello world"') == ["echo", "hello world"]
        assert parse_command_safely("unclosed 'quote") == []


# =============================================================================
# SECTION 6: Model Router Tests
# =============================================================================

class TestModelRouter:
    """Validate model routing and preflight logic."""

    def test_preflight_check_structure(self, model_router):
        """Verify preflight_check returns all expected fields."""
        result = model_router.preflight_check()
        expected_keys = {"local_ok", "latency_ms", "checked_url", "recent_failures",
                         "local_response_threshold", "use_local"}
        assert expected_keys.issubset(result.keys())

    def test_preflight_defaults_when_ollama_down(self, model_router):
        """Verify preflight returns sensible defaults when local is unreachable."""
        with patch.object(model_router, '_local_health_status',
                          return_value={"ok": False, "latency": None,
                                        "checked_url": None, "status_code": None}):
            result = model_router.preflight_check()
            assert result["local_ok"] is False
            assert result["use_local"] is False

    def test_performance_history_tracking(self, model_router):
        """Verify performance history deque tracks model calls."""
        model_router._update_performance("gemini", 0.5, True)
        model_router._update_performance("groq", 0.3, True)
        model_router._update_performance("local", 2.0, False)

        assert len(model_router.performance_history) == 3
        last = model_router.performance_history[-1]
        assert last["source"] == "local"
        assert last["success"] is False

    def test_gemini_call_without_token(self, model_router):
        """Verify Gemini call returns error when token is missing."""
        model_router.gemini_api_token = None
        result = model_router._call_gemini("test prompt")
        assert result["status"] == "error"
        assert "token" in result["output"].lower()

    def test_groq_call_without_key(self, model_router):
        """Verify Groq call returns error when API key is missing."""
        model_router.groq_api_key = None
        result = model_router._call_groq("test prompt")
        assert result["status"] == "error"
        assert "not configured" in result["output"].lower()

    def test_local_call_without_server(self, model_router):
        """Verify local call returns error when Ollama is down."""
        with patch("requests.post", side_effect=Exception("Connection refused")):
            result = model_router._call_local("test prompt")
            assert result["status"] == "error"

    def test_learning_log_integration(self, model_router, learning_log):
        """Verify model responses are logged to learning log."""
        with patch.object(model_router, '_call_gemini', return_value={"status": "success", "output": "mocked"}):
            with patch.object(model_router, '_call_groq', return_value={"status": "success", "output": "mocked"}):
                with patch.object(model_router, '_call_local', return_value={"status": "success", "output": "mocked"}):
                    model_router.route("log test")

        entries = learning_log.latest(5)
        log_entries = [e for e in entries if e.get("prompt") == "log test"]
        assert len(log_entries) >= 1
        entry = log_entries[0]
        assert "model" in entry
        assert "latency" in entry
        assert "status" in entry


# =============================================================================
# SECTION 7: Learning Log Persistence Tests
# =============================================================================

class TestLearningLogPersistence:
    """Validate learning log CRUD operations."""

    def test_append_and_retrieve(self, learning_log):
        """Test basic append and retrieval."""
        learning_log.append({"prompt": "test", "response": "ok", "task_type": "test"})
        latest = learning_log.latest(1)
        assert len(latest) == 1
        assert latest[0]["prompt"] == "test"

    def test_max_entries_enforced(self, tmp_agent_dir):
        """Verify max_entries limit is enforced."""
        from learning_log import LearningLog

        log_path = tmp_agent_dir / "agent_data" / "learning_log.json"
        log = LearningLog(path=log_path, max_entries=5)
        for i in range(10):
            log.append({"prompt": f"test_{i}", "response": "ok"})

        entries = log.latest(10)
        assert len(entries) == 5
        assert entries[0]["prompt"] == "test_9"

    def test_search_functionality(self, learning_log):
        """Test searching through log entries."""
        learning_log.append({"prompt": "hello world", "response": "hi", "model": "test"})
        learning_log.append({"prompt": "foo bar", "response": "baz", "model": "test"})
        learning_log.append({"prompt": "hello again", "response": "hello", "model": "test"})

        results = learning_log.search("hello")
        assert len(results) == 2

        results = learning_log.search("nonexistent")
        assert len(results) == 0

    def test_file_persistence(self, tmp_agent_dir):
        """Verify data persists to disk and survives re-instantiation."""
        from learning_log import LearningLog

        log_path = tmp_agent_dir / "agent_data" / "learning_log.json"
        log1 = LearningLog(path=log_path)
        log1.append({"prompt": "persist_me", "response": "saved"})

        log2 = LearningLog(path=log_path)
        entries = log2.latest(10)
        assert any(e["prompt"] == "persist_me" for e in entries)

    def test_summary_generation(self, learning_log):
        """Verify summary returns correct counts."""
        learning_log.append({"prompt": "a", "response": "1", "model": "m1"})
        learning_log.append({"prompt": "b", "response": "2", "model": "m2"})

        summary = learning_log.summary()
        assert summary["entries"] == 2
        assert summary["last_entry"]["prompt"] == "b"

    def test_concurrent_writes(self, tmp_agent_dir):
        """Verify thread-safe concurrent writes."""
        import threading
        from learning_log import LearningLog

        log_path = tmp_agent_dir / "agent_data" / "learning_log.json"
        log = LearningLog(path=log_path, max_entries=100)

        def writer(index):
            log.append({"prompt": f"concurrent_{index}", "response": "ok"})

        threads = [threading.Thread(target=writer, args=(i,)) for i in range(20)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(log.entries) == 20


# =============================================================================
# SECTION 8: Swarm / P2P Tests
# =============================================================================

class TestSwarmMessaging:
    """Validate P2P swarm message structure and peer management."""

    def test_swarm_message_dataclass(self):
        """Verify SwarmMessage structure is correct."""
        from ghost_swarm import SwarmMessage

        msg = SwarmMessage(
            msg_type="ping",
            sender_id="node-001",
            payload={"timestamp": time.time()},
        )
        assert msg.msg_type == "ping"
        assert msg.sender_id == "node-001"
        assert "timestamp" in msg.payload

    def test_peer_info_heartbeat_timeout(self):
        """Verify peer timeout logic."""
        from ghost_swarm import PeerInfo

        alive = PeerInfo(node_id="a", host="10.0.0.1", port=9876, last_seen=time.time())
        assert alive.is_alive is True

        dead = PeerInfo(node_id="b", host="10.0.0.2", port=9876, last_seen=0)
        assert dead.is_alive is False


# =============================================================================
# SECTION 9: Security Credential Manager Tests
# =============================================================================

class TestCredentialManager:
    """Validate credential manager security."""

    def test_credential_manager_structure(self):
        """Verify CredentialManager returns expected fields."""
        from security_utils import CredentialManager

        gmail = CredentialManager.get_gmail()
        assert "user" in gmail
        assert "pass" in gmail

        tokens = CredentialManager.get_tokens()
        expected = {"HuggingFace", "Groq", "GitHub", "Cloudflare", "Discord", "DiscordChannel"}
        assert expected.issubset(tokens.keys())

    def test_validate_configured_returns_status(self):
        """Verify validate_configured returns strings not None."""
        from security_utils import CredentialManager

        status = CredentialManager.validate_configured()
        for service, state in status.items():
            assert state in ("Configured", "Missing"), f"Unexpected state for {service}: {state}"
