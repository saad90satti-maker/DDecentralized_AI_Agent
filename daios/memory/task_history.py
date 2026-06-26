"""Task History — tracks all completed work and maintains decision history."""

import json
import time
from pathlib import Path
from typing import Dict, Any, List, Optional
from dataclasses import dataclass, field, asdict


@dataclass
class TaskRecord:
    id: str
    agent_id: str
    description: str
    status: str
    tick_created: int
    tick_completed: int = 0
    duration_ticks: int = 0
    outcome: str = "pending"
    details: Dict[str, Any] = field(default_factory=dict)
    tags: List[str] = field(default_factory=list)


@dataclass
class DecisionRecord:
    id: str
    agent_id: str
    decision: str
    rationale: str
    alternatives: List[str]
    tick: int
    outcome: str = "pending"
    timestamp: float = field(default_factory=time.time)


class TaskHistory:
    def __init__(self, data_dir: str):
        self.data_dir = Path(data_dir)
        self._tasks: List[TaskRecord] = []
        self._decisions: List[DecisionRecord] = []
        self._max_tasks: int = 1000
        self._max_decisions: int = 500

    def record_task(self, agent_id: str, description: str, tick: int,
                    tags: Optional[List[str]] = None) -> str:
        tid = f"task-{agent_id}-{int(time.time()*1000)}"
        self._tasks.append(TaskRecord(
            id=tid, agent_id=agent_id, description=description,
            status="active", tick_created=tick, tags=tags or [],
        ))
        if len(self._tasks) > self._max_tasks:
            self._tasks = self._tasks[-self._max_tasks:]
        return tid

    def complete_task(self, task_id: str, outcome: str = "success",
                      tick: int = 0, details: Optional[Dict] = None) -> None:
        for task in self._tasks:
            if task.id == task_id:
                task.status = "completed"
                task.tick_completed = tick
                task.duration_ticks = tick - task.tick_created
                task.outcome = outcome
                if details:
                    task.details.update(details)
                break

    def record_decision(self, agent_id: str, decision: str, rationale: str,
                        alternatives: List[str], tick: int) -> str:
        did = f"dec-{agent_id}-{int(time.time()*1000)}"
        self._decisions.append(DecisionRecord(
            id=did, agent_id=agent_id, decision=decision,
            rationale=rationale, alternatives=alternatives, tick=tick,
        ))
        if len(self._decisions) > self._max_decisions:
            self._decisions = self._decisions[-self._max_decisions:]
        return did

    def get_tasks_by_agent(self, agent_id: str) -> List[TaskRecord]:
        return [t for t in self._tasks if t.agent_id == agent_id]

    def get_recent_tasks(self, n: int = 20) -> List[TaskRecord]:
        return self._tasks[-n:]

    def get_active_tasks(self) -> List[TaskRecord]:
        return [t for t in self._tasks if t.status == "active"]

    def get_decisions(self, agent_id: Optional[str] = None, n: int = 20) -> List[DecisionRecord]:
        decisions = self._decisions
        if agent_id:
            decisions = [d for d in decisions if d.agent_id == agent_id]
        return decisions[-n:]

    def summary(self) -> Dict[str, Any]:
        total = len(self._tasks)
        completed = sum(1 for t in self._tasks if t.status == "completed")
        active = sum(1 for t in self._tasks if t.status == "active")
        avg_duration = 0
        completed_tasks = [t for t in self._tasks if t.duration_ticks > 0]
        if completed_tasks:
            avg_duration = sum(t.duration_ticks for t in completed_tasks) / len(completed_tasks)
        return {
            "total_tasks": total,
            "completed": completed,
            "active": active,
            "avg_duration_ticks": round(avg_duration, 1),
            "total_decisions": len(self._decisions),
        }

    def save(self, path: Optional[str] = None) -> str:
        path = path or str(self.data_dir / "task_history.json")
        Path(path).write_text(json.dumps({
            "tasks": [asdict(t) for t in self._tasks],
            "decisions": [asdict(d) for d in self._decisions],
        }, indent=2))
        return path

    def load(self, path: str) -> None:
        data = json.loads(Path(path).read_text())
        self._tasks = [TaskRecord(**t) for t in data.get("tasks", [])]
        self._decisions = [DecisionRecord(**d) for d in data.get("decisions", [])]
