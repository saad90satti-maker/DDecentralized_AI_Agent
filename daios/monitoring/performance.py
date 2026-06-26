"""Performance monitoring — metrics collection, dashboard data."""

import time
import statistics
from typing import Dict, Any, List
from dataclasses import dataclass, field


@dataclass
class AgentMetrics:
    agent_id: str
    agent_type: str
    tasks_completed: int = 0
    messages_sent: int = 0
    messages_received: int = 0
    observations_made: int = 0
    discoveries_made: int = 0
    avg_response_time_ms: float = 0.0
    energy_usage: float = 0.0


class PerformanceMonitor:
    def __init__(self):
        self._agent_metrics: Dict[str, AgentMetrics] = {}
        self._tick_times: List[float] = []
        self._message_latencies: List[float] = []
        self._start_time: float = time.time()

    def register_agent(self, agent_id: str, agent_type: str) -> None:
        self._agent_metrics[agent_id] = AgentMetrics(agent_id=agent_id, agent_type=agent_type)

    def record_tick(self, duration_ms: float) -> None:
        self._tick_times.append(duration_ms)
        if len(self._tick_times) > 100:
            self._tick_times = self._tick_times[-100:]

    def record_message_latency(self, latency_ms: float) -> None:
        self._message_latencies.append(latency_ms)
        if len(self._message_latencies) > 200:
            self._message_latencies = self._message_latencies[-200:]

    def update_agent(self, agent_id: str, **updates) -> None:
        if agent_id in self._agent_metrics:
            for k, v in updates.items():
                setattr(self._agent_metrics[agent_id], k, v)

    def get_dashboard_data(self) -> Dict[str, Any]:
        avg_tick = statistics.mean(self._tick_times[-20:]) if self._tick_times else 0
        avg_latency = statistics.mean(self._message_latencies[-20:]) if self._message_latencies else 0
        total_tasks = sum(m.tasks_completed for m in self._agent_metrics.values())
        total_msgs = sum(m.messages_sent for m in self._agent_metrics.values())
        uptime = time.time() - self._start_time

        return {
            "uptime_s": round(uptime, 1),
            "avg_tick_ms": round(avg_tick, 2),
            "avg_message_latency_ms": round(avg_latency, 2),
            "total_tasks_completed": total_tasks,
            "total_messages": total_msgs,
            "active_agents": len(self._agent_metrics),
            "agents": {aid: {"type": m.agent_type, "tasks": m.tasks_completed,
                             "msgs": m.messages_sent}
                       for aid, m in self._agent_metrics.items()},
        }

    def summary(self) -> Dict[str, Any]:
        return {
            "agents_tracked": len(self._agent_metrics),
            "ticks_measured": len(self._tick_times),
            "messages_measured": len(self._message_latencies),
        }
