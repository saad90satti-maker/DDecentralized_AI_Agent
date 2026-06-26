"""Discovery System — encourages exploration, ranks discoveries, shares findings across agents."""

import random
import logging
from typing import Dict, Any, List, Optional
from dataclasses import dataclass, field

logger = logging.getLogger("daios.discovery")


@dataclass
class Discovery:
    id: str
    agent_id: str
    title: str
    field: str
    description: str
    confidence: float
    impact_score: float = 0.0
    novelty: float = 0.5
    verification_count: int = 0
    shared: bool = False
    tags: List[str] = field(default_factory=list)


class DiscoverySystem:
    def __init__(self):
        self._discoveries: List[Discovery] = []
        self._max_discoveries: int = 200

    def submit(self, agent_id: str, title: str, field: str, description: str,
               confidence: float, tags: Optional[List[str]] = None) -> str:
        did = f"disc-{agent_id}-{len(self._discoveries)+1}"
        discovery = Discovery(
            id=did, agent_id=agent_id, title=title, field=field,
            description=description, confidence=confidence,
            impact_score=self._calculate_impact(field, confidence),
            novelty=random.uniform(0.2, 1.0),
            tags=tags or [field],
        )
        self._discoveries.append(discovery)
        if len(self._discoveries) > self._max_discoveries:
            self._discoveries = self._discoveries[-self._max_discoveries:]
        return did

    def verify(self, discovery_id: str) -> bool:
        for d in self._discoveries:
            if d.id == discovery_id:
                d.verification_count += 1
                d.confidence = min(1.0, d.confidence + 0.1)
                return True
        return False

    def share(self, discovery_id: str) -> bool:
        for d in self._discoveries:
            if d.id == discovery_id:
                d.shared = True
                return True
        return False

    def get_ranked(self, top_n: int = 20) -> List[Dict[str, Any]]:
        scored = []
        for d in self._discoveries:
            score = (
                d.confidence * 0.3 +
                d.novelty * 0.25 +
                d.impact_score * 0.25 +
                min(d.verification_count / 5, 1.0) * 0.2
            )
            scored.append({
                "id": d.id, "title": d.title, "field": d.field,
                "score": round(score, 2), "confidence": round(d.confidence, 2),
                "novelty": round(d.novelty, 2), "impact": round(d.impact_score, 2),
                "verified": d.verification_count,
                "shared": d.shared, "agent_id": d.agent_id,
            })
        return sorted(scored, key=lambda x: x["score"], reverse=True)[:top_n]

    def get_unshared(self) -> List[Discovery]:
        return [d for d in self._discoveries if not d.shared]

    def get_by_field(self, field: str) -> List[Discovery]:
        return [d for d in self._discoveries if d.field == field]

    def _calculate_impact(self, field: str, confidence: float) -> float:
        base_impact = {"physics": 0.6, "biology": 0.5, "economics": 0.4,
                       "computing": 0.7, "social": 0.3}
        return base_impact.get(field, 0.5) * confidence

    def summary(self) -> Dict[str, Any]:
        total = len(self._discoveries)
        shared = sum(1 for d in self._discoveries if d.shared)
        verified_high = sum(1 for d in self._discoveries if d.verification_count >= 3)
        fields: Dict[str, int] = {}
        for d in self._discoveries:
            fields[d.field] = fields.get(d.field, 0) + 1
        top = self.get_ranked(5)
        return {
            "total": total,
            "shared": shared,
            "verified_high_confidence": verified_high,
            "fields": fields,
            "top_discoveries": top,
        }
