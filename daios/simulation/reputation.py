"""Virtual Reputation System — tracks agent effectiveness and rewards useful contributions."""

import json
import time
from pathlib import Path
from typing import Dict, Any, List, Optional
from dataclasses import dataclass, field


@dataclass
class ReputationRecord:
    agent_id: str
    agent_type: str
    score: float = 50.0
    contributions: int = 0
    successful_tasks: int = 0
    failed_tasks: int = 0
    discoveries_made: int = 0
    lessons_shared: int = 0
    rank: str = "contributor"


RANK_THRESHOLDS = [
    ("novice", 0),
    ("contributor", 30),
    ("specialist", 60),
    ("expert", 80),
    ("master", 95),
]


class ReputationSystem:
    def __init__(self):
        self._records: Dict[str, ReputationRecord] = {}

    def register_agent(self, agent_id: str, agent_type: str) -> None:
        if agent_id not in self._records:
            self._records[agent_id] = ReputationRecord(
                agent_id=agent_id, agent_type=agent_type,
            )

    def record_success(self, agent_id: str, value: float = 2.0) -> None:
        rec = self._records.get(agent_id)
        if rec:
            rec.score = min(100, rec.score + value)
            rec.successful_tasks += 1
            rec.contributions += 1
            self._update_rank(rec)

    def record_failure(self, agent_id: str, penalty: float = 1.0) -> None:
        rec = self._records.get(agent_id)
        if rec:
            rec.score = max(0, rec.score - penalty)
            rec.failed_tasks += 1
            self._update_rank(rec)

    def record_discovery(self, agent_id: str) -> None:
        rec = self._records.get(agent_id)
        if rec:
            rec.score = min(100, rec.score + 3.0)
            rec.discoveries_made += 1
            rec.contributions += 1
            self._update_rank(rec)

    def record_lesson(self, agent_id: str) -> None:
        rec = self._records.get(agent_id)
        if rec:
            rec.score = min(100, rec.score + 1.5)
            rec.lessons_shared += 1
            self._update_rank(rec)

    def get_score(self, agent_id: str) -> float:
        rec = self._records.get(agent_id)
        return rec.score if rec else 0.0

    def get_rank(self, agent_id: str) -> str:
        rec = self._records.get(agent_id)
        return rec.rank if rec else "unranked"

    def get_leaderboard(self, top_n: int = 10) -> List[Dict[str, Any]]:
        sorted_recs = sorted(
            self._records.values(),
            key=lambda r: r.score, reverse=True
        )[:top_n]
        return [
            {"agent_id": r.agent_id, "type": r.agent_type, "score": round(r.score, 1),
             "rank": r.rank, "contributions": r.contributions,
             "discoveries": r.discoveries_made}
            for r in sorted_recs
        ]

    def _update_rank(self, rec: ReputationRecord) -> None:
        for rank, threshold in reversed(RANK_THRESHOLDS):
            if rec.score >= threshold:
                rec.rank = rank
                break

    def summary(self) -> Dict[str, Any]:
        if not self._records:
            return {"agents_tracked": 0}
        scores = [r.score for r in self._records.values()]
        return {
            "agents_tracked": len(self._records),
            "avg_score": round(sum(scores) / len(scores), 1),
            "highest_score": round(max(scores), 1),
            "lowest_score": round(min(scores), 1),
            "leaderboard": self.get_leaderboard(5),
            "rank_distribution": {
                rank: sum(1 for r in self._records.values() if r.rank == rank)
                for rank, _ in RANK_THRESHOLDS
            },
        }

    def save(self, path: str) -> None:
        Path(path).write_text(json.dumps({
            aid: {"agent_id": r.agent_id, "agent_type": r.agent_type, "score": r.score,
                  "contributions": r.contributions, "rank": r.rank}
            for aid, r in self._records.items()
        }, indent=2))

    def load(self, path: str) -> None:
        data = json.loads(Path(path).read_text())
        for aid, d in data.items():
            self._records[aid] = ReputationRecord(**d)
