import asyncio
import logging
import os
import subprocess
import time
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional
from uuid import uuid4

from dashboard_instrumentation import MetricsStore
from email_agent import EmailResponder
from security_utils import parse_command_safely, sanitize_for_logging, validate_command
from browser_controller import BrowserController

logger = logging.getLogger("ExecutionCore")


class TaskType(str, Enum):
    SYSTEM = "system"
    BROWSER = "browser"
    EMAIL = "email"
    LLM = "llm"


class TaskPriority(int, Enum):
    HIGH = 0
    MEDIUM = 1
    LOW = 2


@dataclass(order=True)
class PipelineTask:
    sort_index: int = field(init=False, repr=False)
    priority: TaskPriority = TaskPriority.MEDIUM
    created_at: float = field(default_factory=time.time)
    id: str = field(default_factory=lambda: str(uuid4()))
    type: TaskType = TaskType.SYSTEM
    payload: Dict[str, Any] = field(default_factory=dict)
    max_attempts: int = 3
    attempts: int = 0
    status: str = "pending"
    result: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        self.sort_index = self.priority


class ExecutionCoordinator:
    def __init__(self, metrics: MetricsStore, email_responder: Optional[EmailResponder] = None):
        self.metrics = metrics
        self.email_responder = email_responder
        self.queue: asyncio.PriorityQueue[PipelineTask] = asyncio.PriorityQueue()
        self.shutdown_event = asyncio.Event()

        cpu_count = max(2, os.cpu_count() or 4)
        self.network_workers = min(32, cpu_count * 4)
        self.browser_workers = min(6, cpu_count)
        self.cpu_workers = max(2, cpu_count)

        self.thread_executor = ThreadPoolExecutor(max_workers=self.network_workers)
        self.process_executor = ProcessPoolExecutor(max_workers=self.cpu_workers)

        self.workers: List[asyncio.Task[Any]] = []
        self.public_webhook = os.getenv("PUBLIC_WEBHOOK_URL")

    async def start(self) -> None:
        self.metrics.record_system_event("engine_start", {"cpu_workers": self.cpu_workers, "network_workers": self.network_workers, "browser_workers": self.browser_workers})
        for _ in range(self.browser_workers + self.network_workers // 4):
            self.workers.append(asyncio.create_task(self._worker_loop()))
        self.workers.append(asyncio.create_task(self._heartbeat_loop()))
        self.metrics.record_system_event("engine_started", {"active_workers": len(self.workers)})

    async def stop(self) -> None:
        self.shutdown_event.set()
        for worker in self.workers:
            worker.cancel()
        await asyncio.gather(*self.workers, return_exceptions=True)
        self.thread_executor.shutdown(wait=False)
        self.process_executor.shutdown(wait=False)
        self.metrics.record_system_event("engine_stopped", {})

    async def submit_task(self, task: PipelineTask) -> str:
        if task.attempts >= task.max_attempts:
            task.status = "dead"
            self.metrics.record_task_event("dead", task)
            return task.id

        await self.queue.put(task)
        self.metrics.record_task_event("queued", task)
        return task.id

    async def _worker_loop(self) -> None:
        while not self.shutdown_event.is_set():
            try:
                task = await asyncio.wait_for(self.queue.get(), timeout=3.0)
            except asyncio.TimeoutError:
                continue

            task.attempts += 1
            task.status = "running"
            self.metrics.record_task_event("started", task)
            start_ts = time.time()

            try:
                if task.type == TaskType.BROWSER:
                    output = await self._run_browser_task(task)
                elif task.type == TaskType.EMAIL:
                    output = await self._run_email_task(task)
                elif task.type == TaskType.LLM:
                    output = await self._run_llm_task(task)
                else:
                    output = await self._run_system_task(task)

                task.result = output
                task.status = "succeeded" if output.get("status") == "success" else "failed"
            except Exception as exc:
                task.status = "error"
                task.result = {"status": "error", "message": str(exc)}
                logger.exception("Worker failed task %s", task.id)

            latency = time.time() - start_ts
            self.metrics.record_task_event(task.status, task, latency=latency)
            await self._publish_task_state(task)

            if task.status != "succeeded" and task.attempts < task.max_attempts:
                retry_delay = min(30, 2 ** task.attempts)
                self.metrics.record_system_event("task_retry_scheduled", {"task_id": task.id, "delay": retry_delay})
                await asyncio.sleep(retry_delay)
                await self.submit_task(task)

            self.queue.task_done()

    async def _run_system_task(self, task: PipelineTask) -> Dict[str, Any]:
        command = task.payload.get("command", "")
        valid, message = validate_command(command)
        if not valid:
            return {"status": "failed", "message": message}

        args = parse_command_safely(command)
        if not args:
            return {"status": "failed", "message": "Invalid command syntax"}

        result = await asyncio.to_thread(self._safe_subprocess_run, args)
        return result

    def _safe_subprocess_run(self, args: List[str]) -> Dict[str, Any]:
        try:
            completed = subprocess.run(
                args,
                capture_output=True,
                text=True,
                timeout=120,
                check=False,
            )
            stdout = completed.stdout.strip()
            stderr = completed.stderr.strip()
            return {
                "status": "success" if completed.returncode == 0 else "failed",
                "command": " ".join(args),
                "stdout": stdout,
                "stderr": sanitize_for_logging(stderr),
                "returncode": completed.returncode,
            }
        except subprocess.TimeoutExpired as exc:
            return {"status": "timeout", "message": str(exc)}

    async def _run_browser_task(self, task: PipelineTask) -> Dict[str, Any]:
        browser_config = task.payload.get("browser_config", {})
        init_keys = {"headless", "user_data_dir", "viewport", "user_agent", "locale", "timezone_id"}
        init_args = {k: v for k, v in browser_config.items() if k in init_keys}
        async with BrowserController(**init_args) as browser:
            if browser_config.get("action") == "login":
                return await browser.ensure_login(
                    login_url=browser_config["login_url"],
                    email_selector=browser_config["email_selector"],
                    password_selector=browser_config["password_selector"],
                    submit_selector=browser_config["submit_selector"],
                    credentials=browser_config["credentials"],
                    success_selector=browser_config.get("success_selector"),
                )
            steps = browser_config.get("steps", [])
            if steps:
                result = await browser.execute_workflow(steps)
                return result.to_dict()
            return {"status": "error", "message": "No workflow steps provided"}

    async def _run_email_task(self, task: PipelineTask) -> Dict[str, Any]:
        if not self.email_responder:
            return {"status": "failed", "message": "Email responder not configured"}
        return await self.email_responder.process_email_payload(task.payload)

    async def _run_llm_task(self, task: PipelineTask) -> Dict[str, Any]:
        return {"status": "failed", "message": "LLM task routing is not configured"}

    async def _publish_task_state(self, task: PipelineTask) -> None:
        event = {
            "task_id": task.id,
            "type": task.type,
            "status": task.status,
            "attempts": task.attempts,
            "priority": task.priority.name,
            "result": "succeeded" if task.status == "succeeded" else "failed",
            "timestamp": datetime.utcnow().isoformat() + "Z",
        }
        await self.metrics.publish_state(event)

    async def _heartbeat_loop(self) -> None:
        while not self.shutdown_event.is_set():
            queue_size = self.queue.qsize()
            self.metrics.record_system_event("heartbeat", {"queue_size": queue_size, "active_workers": len(self.workers)})
            if self.public_webhook:
                await self.metrics.publish_webhook({"type": "heartbeat", "queue_size": queue_size, "active_workers": len(self.workers)})
            await asyncio.sleep(5)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    metrics = MetricsStore()
    coordinator = ExecutionCoordinator(metrics=metrics)

    async def main():
        await coordinator.start()
        await asyncio.sleep(1)
        task = PipelineTask(type=TaskType.SYSTEM, payload={"command": "echo hello world"})
        await coordinator.submit_task(task)
        await asyncio.sleep(10)
        await coordinator.stop()

    asyncio.run(main())
