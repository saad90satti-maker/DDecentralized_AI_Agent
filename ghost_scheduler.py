"""
Ghost Scheduler — Cron-like periodic task execution.
Runs in the background, triggers tasks on configurable intervals.
"""

import asyncio
import json
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger("GhostScheduler")

SCHEDULE_FILE = Path(__file__).resolve().parent / "agent_data" / "ghost_schedule.json"


@dataclass
class ScheduledJob:
    job_id: str
    name: str
    interval_s: float
    handler: str  # function name or module path
    payload: Dict[str, Any] = field(default_factory=dict)
    enabled: bool = True
    last_run: float = 0.0
    run_count: int = 0
    max_runs: int = 0  # 0 = unlimited

    @property
    def next_run(self) -> float:
        return self.last_run + self.interval_s

    @property
    def is_due(self) -> bool:
        if not self.enabled:
            return False
        if self.max_runs > 0 and self.run_count >= self.max_runs:
            return False
        return time.time() >= self.next_run

    def to_dict(self) -> Dict[str, Any]:
        return {
            "job_id": self.job_id,
            "name": self.name,
            "interval_s": self.interval_s,
            "handler": self.handler,
            "payload": self.payload,
            "enabled": self.enabled,
            "last_run": self.last_run,
            "run_count": self.run_count,
            "max_runs": self.max_runs,
        }

    @staticmethod
    def from_dict(d: Dict[str, Any]) -> "ScheduledJob":
        return ScheduledJob(**{k: v for k, v in d.items()
                               if k in ScheduledJob.__dataclass_fields__})


class JobStore:
    """Persistent JSON store for scheduled jobs."""

    def __init__(self, path: Optional[Path] = None):
        self._path = path or SCHEDULE_FILE
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._jobs: Dict[str, ScheduledJob] = {}
        self._load()

    def _load(self) -> None:
        try:
            if self._path.exists():
                data = json.loads(self._path.read_text(encoding="utf-8"))
                for entry in data:
                    job = ScheduledJob.from_dict(entry)
                    self._jobs[job.job_id] = job
        except Exception:
            pass

    def save(self) -> None:
        try:
            data = [j.to_dict() for j in self._jobs.values()]
            self._path.write_text(json.dumps(data, indent=2), encoding="utf-8")
        except Exception as e:
            logger.warning("JobStore save failed: %s", e)

    def add(self, job: ScheduledJob) -> None:
        self._jobs[job.job_id] = job
        self.save()

    def remove(self, job_id: str) -> bool:
        if job_id in self._jobs:
            del self._jobs[job_id]
            self.save()
            return True
        return False

    def list_jobs(self) -> List[ScheduledJob]:
        return list(self._jobs.values())

    def get_due(self) -> List[ScheduledJob]:
        return [j for j in self._jobs.values() if j.is_due]


class GhostScheduler:
    """Periodic task scheduler with handler registry."""

    def __init__(self):
        self._jobs = JobStore()
        self._handlers: Dict[str, Callable] = {}
        self._running = False

    def register(self, name: str, handler: Callable) -> None:
        self._handlers[name] = handler

    def schedule(self, name: str, interval_s: float, payload: Optional[Dict[str, Any]] = None,
                 max_runs: int = 0) -> str:
        job_id = f"job-{name}-{int(time.time())}"
        job = ScheduledJob(
            job_id=job_id,
            name=name,
            interval_s=interval_s,
            handler=name,
            payload=payload or {},
            max_runs=max_runs,
        )
        self._jobs.add(job)
        logger.info("Scheduled: %s every %.0fs", name, interval_s)
        return job_id

    def remove_job(self, job_id: str) -> bool:
        return self._jobs.remove(job_id)

    def list_jobs(self) -> List[Dict[str, Any]]:
        return [j.to_dict() for j in self._jobs.list_jobs()]

    async def start(self) -> None:
        self._running = True
        logger.info("Ghost Scheduler online (%d jobs)", len(self._jobs.list_jobs()))
        while self._running:
            due_jobs = self._jobs.get_due()
            for job in due_jobs:
                await self._run_job(job)
            await asyncio.sleep(1)

    async def stop(self) -> None:
        self._running = False

    async def _run_job(self, job: ScheduledJob) -> None:
        handler = self._handlers.get(job.handler)
        if not handler:
            logger.warning("No handler for job %s: %s", job.job_id, job.handler)
            return

        job.last_run = time.time()
        job.run_count += 1
        self._jobs.save()

        try:
            if asyncio.iscoroutinefunction(handler):
                await handler(job.payload)
            else:
                await asyncio.get_event_loop().run_in_executor(None, lambda: handler(job.payload))
            logger.info("Job %s executed: %s", job.job_id, job.name)
        except Exception as e:
            logger.warning("Job %s failed: %s", job.job_id, e)
