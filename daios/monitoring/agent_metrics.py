"""Agent Performance Metrics — detailed tracking of agent efficiency, output quality, and improvement."""

from typing import Dict, Any, List, Optional
from dataclasses import dataclass, field
import statistics


@dataclass
class AgentMetricsSnapshot:
    agent_id: str
    agent_type: str
    tick: int
    energy: float
    tasks_completed: int
    observations: int
    discoveries: int
    messages_sent: int
    response_time_ms: float = 0.0
    output_quality: float = 0.5
    credit_balance: Dict[str, float] = field(default_factory=dict)
    reputation_score: float = 50.0


class AgentMetricsTracker:
    def __init__(self):
        self._history: Dict[str, List[AgentMetricsSnapshot]] = {}
        self._max_history_per_agent: int = 200

    def record(self, snapshot: AgentMetricsSnapshot) -> None:
        self._history.setdefault(snapshot.agent_id, []).append(snapshot)
        if len(self._history[snapshot.agent_id]) > self._max_history_per_agent:
            self._history[snapshot.agent_id] = \
                self._history[snapshot.agent_id][-self._max_history_per_agent:]

    def get_agent_performance(self, agent_id: str) -> Dict[str, Any]:
        snapshots = self._history.get(agent_id, [])
        if not snapshots:
            return {"status": "no_data"}
        recent = snapshots[-20:]
        task_deltas = []
        for i in range(1, len(recent)):
            task_deltas.append(recent[i].tasks_completed - recent[i-1].tasks_completed)
        avg_task_rate = statistics.mean(task_deltas) if task_deltas else 0
        return {
            "agent_id": agent_id,
            "agent_type": snapshots[-1].agent_type if snapshots else "?",
            "current_energy": snapshots[-1].energy,
            "total_tasks": snapshots[-1].tasks_completed,
            "total_discoveries": snapshots[-1].discoveries,
            "avg_tasks_per_tick": round(avg_task_rate, 2),
            "reputation": round(snapshots[-1].reputation_score, 1),
            "credit_balance": snapshots[-1].credit_balance,
            "output_quality": round(snapshots[-1].output_quality, 2),
        }

    def get_leaderboard(self, metric: str = "tasks_completed",
                        top_n: int = 10) -> List[Dict[str, Any]]:
        scores = []
        for agent_id, snapshots in self._history.items():
            if not snapshots:
                continue
            latest = snapshots[-1]
            task_rate = 0
            if len(snapshots) > 1:
                recent = snapshots[-10:]
                deltas = [recent[i].tasks_completed - recent[i-1].tasks_completed
                          for i in range(1, len(recent))]
                task_rate = statistics.mean(deltas) if deltas else 0
            scores.append({
                "agent_id": agent_id,
                "type": latest.agent_type,
                "tasks": latest.tasks_completed,
                "discoveries": latest.discoveries,
                "energy": latest.energy,
                "task_rate": round(task_rate, 2),
                "quality": round(latest.output_quality, 2),
            })
        reverse = metric not in ("response_time_ms",)
        scores.sort(key=lambda x: x.get(metric, 0), reverse=reverse)
        return scores[:top_n]

    def system_summary(self) -> Dict[str, Any]:
        if not self._history:
            return {"agents_tracked": 0}
        latest = [s[-1] for s in self._history.values()]
        total_tasks = sum(s.tasks_completed for s in latest)
        total_discoveries = sum(s.discoveries for s in latest)
        avg_energy = statistics.mean(s.energy for s in latest) if latest else 0
        return {
            "agents_tracked": len(self._history),
            "total_tasks": total_tasks,
            "total_discoveries": total_discoveries,
            "avg_energy": round(avg_energy, 1),
            "top_by_tasks": self.get_leaderboard("tasks", 3),
            "top_by_discoveries": self.get_leaderboard("discoveries", 3),
        }
