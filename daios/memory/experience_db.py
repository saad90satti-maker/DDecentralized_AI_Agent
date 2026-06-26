"""Experience Database — records successes, failures, and lessons learned for continuous improvement."""

import json
import time
from pathlib import Path
from typing import Dict, Any, List, Optional
from dataclasses import dataclass, field, asdict


@dataclass
class ExperienceEntry:
    id: str
    agent_id: str
    outcome: str
    summary: str
    details: Dict[str, Any]
    tick: int
    lesson: str = ""
    tags: List[str] = field(default_factory=list)
    timestamp: float = field(default_factory=time.time)


class ExperienceDatabase:
    def __init__(self, data_dir: str):
        self.data_dir = Path(data_dir)
        self._entries: List[ExperienceEntry] = []
        self._max_entries: int = 500

    def record_success(self, agent_id: str, summary: str, details: Dict[str, Any],
                       tick: int, lesson: str = "", tags: Optional[List[str]] = None) -> str:
        return self._add_entry(agent_id, "success", summary, details, tick, lesson, tags)

    def record_failure(self, agent_id: str, summary: str, details: Dict[str, Any],
                       tick: int, lesson: str = "", tags: Optional[List[str]] = None) -> str:
        return self._add_entry(agent_id, "failure", summary, details, tick, lesson, tags)

    def record_lesson(self, agent_id: str, summary: str, lesson: str,
                      tick: int, tags: Optional[List[str]] = None) -> str:
        return self._add_entry(agent_id, "lesson", summary, {}, tick, lesson, tags)

    def _add_entry(self, agent_id: str, outcome: str, summary: str,
                   details: Dict[str, Any], tick: int, lesson: str = "",
                   tags: Optional[List[str]] = None) -> str:
        eid = f"exp-{agent_id}-{int(time.time()*1000)}"
        entry = ExperienceEntry(
            id=eid, agent_id=agent_id, outcome=outcome,
            summary=summary, details=details, tick=tick,
            lesson=lesson, tags=tags or [outcome],
        )
        self._entries.append(entry)
        if len(self._entries) > self._max_entries:
            self._entries = self._entries[-self._max_entries:]
        return eid

    def get_by_outcome(self, outcome: str) -> List[ExperienceEntry]:
        return [e for e in self._entries if e.outcome == outcome]

    def get_recent(self, n: int = 20) -> List[ExperienceEntry]:
        return self._entries[-n:]

    def get_lessons(self, min_entries: int = 1) -> List[Dict[str, Any]]:
        lessons_by_tag: Dict[str, List[str]] = {}
        for e in self._entries:
            if e.lesson:
                for tag in e.tags:
                    lessons_by_tag.setdefault(tag, []).append(e.lesson)
        return [{"tag": tag, "lessons": lessons, "count": len(lessons)}
                for tag, lessons in lessons_by_tag.items()
                if len(lessons) >= min_entries]

    def get_success_rate(self, agent_id: Optional[str] = None) -> float:
        entries = self._entries
        if agent_id:
            entries = [e for e in entries if e.agent_id == agent_id]
        if not entries:
            return 0.0
        successes = sum(1 for e in entries if e.outcome == "success")
        return successes / len(entries)

    def summary(self) -> Dict[str, Any]:
        total = len(self._entries)
        successes = len(self.get_by_outcome("success"))
        failures = len(self.get_by_outcome("failure"))
        lessons = len(self.get_by_outcome("lesson"))
        return {
            "total_entries": total,
            "successes": successes,
            "failures": failures,
            "lessons": lessons,
            "success_rate": round(successes / total, 2) if total > 0 else 0,
            "agents_with_data": len(set(e.agent_id for e in self._entries)),
        }

    def save(self, path: Optional[str] = None) -> str:
        path = path or str(self.data_dir / "experience_db.json")
        Path(path).write_text(json.dumps(
            {"entries": [asdict(e) for e in self._entries]}, indent=2))
        return path

    def load(self, path: str) -> None:
        data = json.loads(Path(path).read_text())
        self._entries = [ExperienceEntry(**e) for e in data.get("entries", [])]
