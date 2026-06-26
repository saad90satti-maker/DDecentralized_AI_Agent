"""
Meta-Cognitive Performance Analyzer — tracks ToolRegistry intervention
success rates over time. Flags underperforming tools for deep diagnostics
and autonomous configuration re-compilation.
"""

import os
import json
import time
import math
import logging
import asyncio
from pathlib import Path
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger("performance_analyzer")

ANALYTICS_PATH = Path("agent_logs/performance_analytics.json")
PROPOSALS_PATH = Path("agent_logs/optimization_proposals")


@dataclass
class ToolRecord:
    tool_name: str
    success: bool
    latency_ms: float
    component: str = ""
    detail: str = ""
    timestamp: float = 0.0


@dataclass
class ToolStats:
    tool_name: str
    total_calls: int = 0
    successes: int = 0
    failures: int = 0
    latencies: list = field(default_factory=list)
    last_called: float = 0.0
    consecutive_failures: int = 0

    @property
    def success_rate(self) -> float:
        if self.total_calls == 0:
            return 0.0
        return self.successes / self.total_calls

    @property
    def avg_latency(self) -> float:
        if not self.latencies:
            return 0.0
        return sum(self.latencies) / len(self.latencies)

    @property
    def p95_latency(self) -> float:
        if not self.latencies:
            return 0.0
        sorted_l = sorted(self.latencies)
        idx = min(int(len(sorted_l) * 0.95), len(sorted_l) - 1)
        return sorted_l[idx]


class PerformanceAnalyzer:
    """
    Meta-cognitive loop that tracks tool intervention outcomes.
    When a tool's success rate drops below threshold or its latency
    spikes, the analyzer flags it for deep diagnostic and can trigger
    autonomous configuration re-compilation.

    Integrates with SharedKnowledge to propagate findings across peers.
    """

    def __init__(self, decay_window: int = 50, rate_threshold: float = 0.4):
        self.decay_window = decay_window
        self.rate_threshold = rate_threshold  # Below 40% = flagged
        self._stats: dict[str, ToolStats] = defaultdict(lambda: ToolStats(tool_name=""))
        self._history: list[ToolRecord] = []
        self._flagged: set[str] = set()
        self._shared_knowledge = None

    def set_shared_knowledge(self, sk):
        self._shared_knowledge = sk

    # ------------------------------------------------------------------
    # Recording
    # ------------------------------------------------------------------

    def record(self, tool_name: str, success: bool, latency_ms: float = 0.0,
               component: str = "", detail: str = ""):
        now = time.time()
        rec = ToolRecord(
            tool_name=tool_name, success=success, latency_ms=latency_ms,
            component=component, detail=detail, timestamp=now,
        )
        self._history.append(rec)
        self._trim_history()

        stats = self._stats[tool_name]
        stats.tool_name = tool_name
        stats.total_calls += 1
        stats.last_called = now

        if success:
            stats.successes += 1
            stats.consecutive_failures = 0
        else:
            stats.failures += 1
            stats.consecutive_failures += 1

        if latency_ms > 0:
            stats.latencies.append(latency_ms)
            if len(stats.latencies) > self.decay_window:
                stats.latencies = stats.latencies[-self.decay_window:]

        # Check if this tool should be flagged
        self._evaluate_tool(tool_name)

        # Persist
        self._persist()

    def _trim_history(self, max_records: int = 500):
        if len(self._history) > max_records:
            self._history = self._history[-max_records:]

    # ------------------------------------------------------------------
    # Evaluation
    # ------------------------------------------------------------------

    def _evaluate_tool(self, tool_name: str):
        stats = self._stats[tool_name]
        if stats.total_calls < 3:
            return  # Not enough data

        reasons = []

        # Low success rate
        if stats.success_rate < self.rate_threshold:
            reasons.append(f"success_rate={stats.success_rate:.0%} below threshold {self.rate_threshold:.0%}")

        # High consecutive failures
        if stats.consecutive_failures >= 3:
            reasons.append(f"{stats.consecutive_failures} consecutive failures")

        # Latency spike (p95 > 3x average of all tools)
        all_avg = self._global_avg_latency()
        if all_avg > 0 and stats.p95_latency > all_avg * 3:
            reasons.append(f"p95_latency={stats.p95_latency:.0f}ms > 3x global avg ({all_avg:.0f}ms)")

        if reasons:
            self._flagged.add(tool_name)
            logger.warning("Performance flag: %s — %s", tool_name, "; ".join(reasons))

            # Propagate to shared knowledge
            if self._shared_knowledge:
                self._shared_knowledge.add_observation(
                    key=f"flag:{tool_name}",
                    value={
                        "tool": tool_name,
                        "reasons": reasons,
                        "success_rate": stats.success_rate,
                        "total_calls": stats.total_calls,
                    },
                    ttl=3600,
                )
        else:
            self._flagged.discard(tool_name)

    def _global_avg_latency(self) -> float:
        all_latencies = []
        for stats in self._stats.values():
            all_latencies.extend(stats.latencies)
        if not all_latencies:
            return 0.0
        return sum(all_latencies) / len(all_latencies)

    # ------------------------------------------------------------------
    # Deep diagnostic
    # ------------------------------------------------------------------

    def get_diagnostics(self, tool_name: str) -> dict:
        """Return a deep diagnostic for a flagged tool."""
        stats = self._stats.get(tool_name)
        if not stats:
            return {"tool": tool_name, "status": "no_data"}

        recent = [r for r in self._history[-20:] if r.tool_name == tool_name]

        return {
            "tool": tool_name,
            "stats": {
                "total_calls": stats.total_calls,
                "success_rate": stats.success_rate,
                "avg_latency_ms": stats.avg_latency,
                "p95_latency_ms": stats.p95_latency,
                "consecutive_failures": stats.consecutive_failures,
                "last_called": stats.last_called,
            },
            "flagged": tool_name in self._flagged,
            "recent_history": [
                {"success": r.success, "latency_ms": r.latency_ms,
                 "component": r.component, "detail": r.detail[:80]}
                for r in recent
            ],
            "recommendation": self._recommend(tool_name, stats),
        }

    def _recommend(self, tool_name: str, stats: ToolStats) -> str:
        if stats.success_rate == 0 and stats.total_calls >= 3:
            return f"DISABLE — tool '{tool_name}' has 0% success rate"
        if stats.consecutive_failures >= 5:
            return f"RECOMPILE — tool '{tool_name}' has {stats.consecutive_failures} consecutive failures, consider updating parameters"
        if stats.avg_latency > 30000:
            return f"OPTIMIZE — tool '{tool_name}' avg latency {stats.avg_latency:.0f}ms exceeds 30s"
        return "MONITOR — continuing observation"

    # ------------------------------------------------------------------
    # Report
    # ------------------------------------------------------------------

    def get_report(self) -> dict:
        return {
            "flagged_tools": list(self._flagged),
            "total_tracked": len(self._stats),
            "tool_stats": {
                name: {
                    "total_calls": s.total_calls,
                    "success_rate": s.success_rate,
                    "avg_latency_ms": s.avg_latency,
                    "consecutive_failures": s.consecutive_failures,
                    "flagged": name in self._flagged,
                }
                for name, s in sorted(self._stats.items(), key=lambda x: x[1].total_calls, reverse=True)
                if s.total_calls > 0
            },
        }

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def _persist(self):
        try:
            ANALYTICS_PATH.parent.mkdir(parents=True, exist_ok=True)
            ANALYTICS_PATH.write_text(json.dumps(self.get_report(), indent=2), encoding="utf-8")
        except Exception as e:
            logger.debug("Persist error: %s", e)

    async def run_forever(self, interval: float = 60.0):
        """Background loop that periodically logs analytics summary."""
        logger.info("Performance Analyzer started (interval=%ds, threshold=%.0f%%)",
                    interval, self.rate_threshold * 100)
        while True:
            try:
                report = self.get_report()
                if report["flagged_tools"]:
                    logger.info("Performance: flagged=%s", report["flagged_tools"])
                for name, s in report["tool_stats"].items():
                    if s["total_calls"] > 0:
                        logger.debug("Tool %s: calls=%d rate=%.0f%% avg=%.0fms",
                                     name, s["total_calls"], s["success_rate"] * 100, s["avg_latency_ms"])
            except Exception as e:
                logger.debug("Analytics cycle: %s", e)
            await asyncio.sleep(interval)
