"""
Ghost Compute — Distributed Task Queue + Result Collection.
Workers pull tasks from a shared queue, execute them, and store results.
No central server required — peers share the queue via P2P messages.
"""

import asyncio
import json
import logging
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger("GhostCompute")

TASK_DB_PATH = Path(__file__).resolve().parent / "agent_data" / "ghost_tasks.json"


class TaskStatus(Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    TIMEOUT = "timeout"


class TaskPriority(Enum):
    LOW = 0
    NORMAL = 1
    HIGH = 2
    CRITICAL = 3


@dataclass
class ComputeTask:
    task_id: str
    task_type: str
    payload: Dict[str, Any]
    priority: int = TaskPriority.NORMAL.value
    status: str = TaskStatus.PENDING.value
    result: Any = None
    error: Optional[str] = None
    created_at: float = 0.0
    started_at: Optional[float] = None
    completed_at: Optional[float] = None
    worker_id: Optional[str] = None
    timeout: float = 120.0

    def __post_init__(self):
        if self.created_at == 0.0:
            self.created_at = time.time()

    @property
    def duration(self) -> Optional[float]:
        if self.started_at and self.completed_at:
            return round(self.completed_at - self.started_at, 3)
        return None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "task_id": self.task_id,
            "task_type": self.task_type,
            "payload": self.payload,
            "priority": self.priority,
            "status": self.status,
            "result": self.result,
            "error": self.error,
            "created_at": self.created_at,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "worker_id": self.worker_id,
            "timeout": self.timeout,
            "duration": self.duration,
        }

    @staticmethod
    def from_dict(d: Dict[str, Any]) -> "ComputeTask":
        return ComputeTask(**{k: v for k, v in d.items()
                              if k in ComputeTask.__dataclass_fields__})


class TaskStore:
    """Persistent JSON-backed task store."""

    def __init__(self, path: Optional[Path] = None):
        self._path = path or TASK_DB_PATH
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._tasks: Dict[str, ComputeTask] = {}
        self._load()

    def _load(self) -> None:
        try:
            if self._path.exists():
                data = json.loads(self._path.read_text(encoding="utf-8"))
                for entry in data:
                    t = ComputeTask.from_dict(entry)
                    self._tasks[t.task_id] = t
        except Exception:
            pass

    def save(self) -> None:
        try:
            data = [t.to_dict() for t in self._tasks.values()]
            self._path.write_text(json.dumps(data, indent=2), encoding="utf-8")
        except Exception as e:
            logger.warning("TaskStore save failed: %s", e)

    def add(self, task: ComputeTask) -> None:
        self._tasks[task.task_id] = task
        self.save()

    def get(self, task_id: str) -> Optional[ComputeTask]:
        return self._tasks.get(task_id)

    def next_pending(self) -> Optional[ComputeTask]:
        pending = [t for t in self._tasks.values() if t.status == TaskStatus.PENDING.value]
        pending.sort(key=lambda t: t.priority, reverse=True)
        return pending[0] if pending else None

    def update(self, task: ComputeTask) -> None:
        self._tasks[task.task_id] = task
        self.save()

    def completed(self) -> List[ComputeTask]:
        return [t for t in self._tasks.values() if t.status == TaskStatus.COMPLETED.value]

    def failed(self) -> List[ComputeTask]:
        return [t for t in self._tasks.values() if t.status == TaskStatus.FAILED.value]

    def pending_count(self) -> int:
        return sum(1 for t in self._tasks.values() if t.status == TaskStatus.PENDING.value)

    def stats(self) -> Dict[str, Any]:
        all_tasks = list(self._tasks.values())
        completed = [t for t in all_tasks if t.status == TaskStatus.COMPLETED.value]
        durations = [t.duration for t in completed if t.duration]
        return {
            "total": len(all_tasks),
            "pending": sum(1 for t in all_tasks if t.status == TaskStatus.PENDING.value),
            "running": sum(1 for t in all_tasks if t.status == TaskStatus.RUNNING.value),
            "completed": len(completed),
            "failed": sum(1 for t in all_tasks if t.status == TaskStatus.FAILED.value),
            "avg_duration_s": round(sum(durations) / len(durations), 3) if durations else 0,
        }


class ComputeWorker:
    """Pulls tasks from the store, executes them, stores results."""

    def __init__(self, worker_id: str = "", store: Optional[TaskStore] = None):
        self.worker_id = worker_id or f"worker-{uuid.uuid4().hex[:8]}"
        self.store = store or TaskStore()
        self._handlers: Dict[str, Callable] = {}
        self._running = False
        self._loop: Optional[asyncio.AbstractEventLoop] = None

    def register(self, task_type: str, handler: Callable) -> None:
        self._handlers[task_type] = handler

    async def start(self) -> None:
        self._running = True
        logger.info("Compute worker %s online (%d handlers)", self.worker_id, len(self._handlers))
        while self._running:
            task = self.store.next_pending()
            if task:
                await self._execute(task)
            await asyncio.sleep(0.5)

    async def stop(self) -> None:
        self._running = False

    async def _execute(self, task: ComputeTask) -> None:
        task.status = TaskStatus.RUNNING.value
        task.worker_id = self.worker_id
        task.started_at = time.time()
        self.store.update(task)

        handler = self._handlers.get(task.task_type)
        if not handler:
            task.status = TaskStatus.FAILED.value
            task.error = f"No handler for task_type: {task.task_type}"
            task.completed_at = time.time()
            self.store.update(task)
            logger.warning("No handler for task %s type=%s", task.task_id, task.task_type)
            return

        try:
            if asyncio.iscoroutinefunction(handler):
                result = await asyncio.wait_for(handler(task.payload), timeout=task.timeout)
            else:
                result = await asyncio.get_event_loop().run_in_executor(
                    None, lambda: handler(task.payload)
                )
            task.result = result
            task.status = TaskStatus.COMPLETED.value
            logger.info("Task %s completed in %.3fs", task.task_id, task.duration or 0)
        except asyncio.TimeoutError:
            task.status = TaskStatus.TIMEOUT.value
            task.error = f"Timeout after {task.timeout}s"
            logger.warning("Task %s timed out", task.task_id)
        except Exception as e:
            task.status = TaskStatus.FAILED.value
            task.error = str(e)[:500]
            logger.warning("Task %s failed: %s", task.task_id, e)

        task.completed_at = time.time()
        self.store.update(task)


class ComputeMaster:
    """High-level API for dispatching and querying tasks."""

    def __init__(self, store: Optional[TaskStore] = None):
        self.store = store or TaskStore()
        self._workers: Dict[str, ComputeWorker] = {}

    def submit(self, task_type: str, payload: Dict[str, Any],
               priority: int = TaskPriority.NORMAL.value,
               timeout: float = 120.0) -> str:
        task = ComputeTask(
            task_id=str(uuid.uuid4()),
            task_type=task_type,
            payload=payload,
            priority=priority,
            timeout=timeout,
        )
        self.store.add(task)
        logger.info("Task submitted: %s (type=%s, priority=%d)", task.task_id, task_type, priority)
        return task.task_id

    def get_result(self, task_id: str) -> Optional[Dict[str, Any]]:
        task = self.store.get(task_id)
        return task.to_dict() if task else None

    def wait_result(self, task_id: str, timeout: float = 60.0) -> Optional[Dict[str, Any]]:
        start = time.time()
        while time.time() - start < timeout:
            task = self.store.get(task_id)
            if task and task.status in (TaskStatus.COMPLETED.value, TaskStatus.FAILED.value, TaskStatus.TIMEOUT.value):
                return task.to_dict()
            time.sleep(0.5)
        return None

    def list_tasks(self, status: Optional[str] = None) -> List[Dict[str, Any]]:
        tasks = list(self.store._tasks.values())
        if status:
            tasks = [t for t in tasks if t.status == status]
        return [t.to_dict() for t in tasks]

    def start_worker(self, num_workers: int = 1) -> None:
        for i in range(num_workers):
            w = ComputeWorker(store=self.store)
            self._workers[w.worker_id] = w

    async def run_workers(self) -> None:
        tasks = [asyncio.create_task(w.start()) for w in self._workers.values()]
        if tasks:
            await asyncio.gather(*tasks)

    @property
    def stats(self) -> Dict[str, Any]:
        return self.store.stats()
