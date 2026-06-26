"""Resource tracking — CPU, memory, message throughput monitoring."""

import time
import os
from typing import Dict, Any
from dataclasses import dataclass, field


@dataclass
class ResourceMetrics:
    cpu_percent: float = 0.0
    memory_mb: float = 0.0
    messages_per_tick: int = 0
    active_agents: int = 0
    tick_duration_ms: float = 0.0
    agent_energy_avg: float = 100.0


class ResourceTracker:
    def __init__(self):
        self._history: list = []
        self._tick_times: list = []
        self._messages_this_tick: int = 0
        self._last_tick_time: float = time.time()

    def record_message(self) -> None:
        self._messages_this_tick += 1

    def tick_start(self) -> None:
        self._last_tick_time = time.time()

    def tick_end(self) -> ResourceMetrics:
        duration = (time.time() - self._last_tick_time) * 1000
        self._tick_times.append(duration)

        metrics = ResourceMetrics(
            cpu_percent=self._get_cpu(),
            memory_mb=self._get_memory(),
            messages_per_tick=self._messages_this_tick,
            tick_duration_ms=round(duration, 2),
        )
        self._messages_this_tick = 0
        self._history.append(metrics)
        return metrics

    def _get_cpu(self) -> float:
        try:
            import psutil
            return psutil.cpu_percent(interval=0)
        except ImportError:
            return 0.0

    def _get_memory(self) -> float:
        try:
            import psutil
            return psutil.Process(os.getpid()).memory_info().rss / 1024 / 1024
        except ImportError:
            return 0.0

    def summary(self) -> Dict[str, Any]:
        if not self._history:
            return {"status": "no_data"}
        recent = self._history[-50:]
        avg_tick = sum(r.tick_duration_ms for r in recent) / len(recent)
        avg_msg = sum(r.messages_per_tick for r in recent) / len(recent)
        return {
            "avg_tick_duration_ms": round(avg_tick, 2),
            "avg_messages_per_tick": round(avg_msg, 1),
            "latest_cpu": self._history[-1].cpu_percent if self._history else 0,
            "latest_memory_mb": self._history[-1].memory_mb if self._history else 0,
            "total_ticks_tracked": len(self._history),
        }
