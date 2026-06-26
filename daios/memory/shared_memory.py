"""Shared Memory Layer — centralized knowledge, observation, and learning store."""

import json
import time
from pathlib import Path
from typing import Dict, Any, List, Optional
from dataclasses import dataclass, field, asdict


@dataclass
class KnowledgeEntry:
    key: str
    value: Any
    source: str
    tick: int
    confidence: float = 1.0
    tags: List[str] = field(default_factory=list)
    timestamp: float = field(default_factory=time.time)


@dataclass
class ObservationEntry:
    agent_id: str
    observation: Dict[str, Any]
    tick: int
    id: str = ""
    timestamp: float = field(default_factory=time.time)


@dataclass
class LearningEntry:
    agent_id: str
    pattern: Dict[str, Any]
    tick: int
    confidence: float = 0.5
    verification_count: int = 0
    id: str = ""
    timestamp: float = field(default_factory=time.time)


class SharedMemory:
    def __init__(self, data_dir: str):
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self._knowledge: Dict[str, KnowledgeEntry] = {}
        self._observations: List[ObservationEntry] = []
        self._learning: List[LearningEntry] = []
        self._max_observations: int = 1000
        self._max_learning: int = 500

    def store_knowledge(self, key: str, value: Any, source: str, tick: int,
                        confidence: float = 1.0, tags: Optional[List[str]] = None) -> None:
        self._knowledge[key] = KnowledgeEntry(
            key=key, value=value, source=source, tick=tick,
            confidence=confidence, tags=tags or [],
        )

    def get_knowledge(self, key: str) -> Optional[Any]:
        entry = self._knowledge.get(key)
        return entry.value if entry else None

    def search_knowledge(self, query: str) -> List[KnowledgeEntry]:
        q = query.lower()
        results = []
        for entry in self._knowledge.values():
            if q in entry.key.lower() or any(q in t.lower() for t in entry.tags):
                results.append(entry)
        return sorted(results, key=lambda x: x.confidence, reverse=True)

    def all_knowledge(self) -> Dict[str, KnowledgeEntry]:
        return dict(self._knowledge)

    def add_observation(self, agent_id: str, observation: Dict[str, Any], tick: int) -> str:
        obs_id = f"obs-{agent_id}-{int(time.time()*1000)}"
        self._observations.append(ObservationEntry(
            id=obs_id, agent_id=agent_id, observation=observation, tick=tick,
        ))
        if len(self._observations) > self._max_observations:
            self._observations = self._observations[-self._max_observations:]
        return obs_id

    def get_observations(self, agent_id: Optional[str] = None, last_n: int = 50) -> List[ObservationEntry]:
        if agent_id:
            filtered = [o for o in self._observations if o.agent_id == agent_id]
        else:
            filtered = list(self._observations)
        return filtered[-last_n:]

    def add_learning(self, agent_id: str, pattern: Dict[str, Any], tick: int,
                     confidence: float = 0.5) -> str:
        learn_id = f"learn-{agent_id}-{int(time.time()*1000)}"
        self._learning.append(LearningEntry(
            id=learn_id, agent_id=agent_id, pattern=pattern, tick=tick,
            confidence=confidence,
        ))
        if len(self._learning) > self._max_learning:
            self._learning = self._learning[-self._max_learning:]
        return learn_id

    def verify_learning(self, learn_id: str) -> None:
        for entry in self._learning:
            if entry.id == learn_id:
                entry.verification_count += 1
                entry.confidence = min(1.0, entry.confidence + 0.1)
                break

    def get_learning(self, min_confidence: float = 0.0) -> List[LearningEntry]:
        return [l for l in self._learning if l.confidence >= min_confidence]

    def get_high_confidence_patterns(self, threshold: float = 0.7) -> List[LearningEntry]:
        return [l for l in self._learning if l.confidence >= threshold]

    def snapshot(self) -> Dict[str, Any]:
        return {
            "knowledge_count": len(self._knowledge),
            "observation_count": len(self._observations),
            "learning_count": len(self._learning),
            "high_confidence_patterns": len(self.get_high_confidence_patterns()),
        }

    def save(self, path: Optional[str] = None) -> str:
        path = path or str(self.data_dir / "memory_snapshot.json")
        data = {
            "knowledge": {k: asdict(v) for k, v in self._knowledge.items()},
            "observations": [asdict(o) for o in self._observations[-200:]],
            "learning": [asdict(l) for l in self._learning],
        }
        Path(path).write_text(json.dumps(data, indent=2))
        return path

    def load(self, path: str) -> None:
        data = json.loads(Path(path).read_text())
        self._knowledge = {k: KnowledgeEntry(**v) for k, v in data.get("knowledge", {}).items()}
        self._observations = [ObservationEntry(**o) for o in data.get("observations", [])]
        self._learning = [LearningEntry(**l) for l in data.get("learning", [])]
