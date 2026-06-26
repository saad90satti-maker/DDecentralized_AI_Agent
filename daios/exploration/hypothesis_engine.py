"""Hypothesis Engine — generates and evaluates hypotheses from agent discoveries."""

import random
import logging
from typing import Dict, Any, List, Optional
from dataclasses import dataclass, field
from daios.exploration.data_sources import APPROVED_SOURCES

logger = logging.getLogger("daios.exploration")


@dataclass
class Hypothesis:
    id: str
    title: str
    description: str
    confidence: float
    evidence_count: int
    source_ids: List[str]
    verified: bool = False
    verification_count: int = 0


class HypothesisEngine:
    def __init__(self):
        self._hypotheses: Dict[str, Hypothesis] = {}
        self._max_hypotheses: int = 50

    def generate(self, discovery: Dict[str, Any], agent_id: str) -> Optional[Hypothesis]:
        if not discovery:
            return None
        h_id = f"hyp-{agent_id}-{random.randint(1000,9999)}"
        title = f"Hypothesis: {discovery.get('title', 'unknown pattern')}"
        hypothesis = Hypothesis(
            id=h_id,
            title=title,
            description=f"Generated from {agent_id}'s discovery in {discovery.get('field', 'unknown')}",
            confidence=discovery.get("confidence", 0.5),
            evidence_count=1,
            source_ids=[random.choice(APPROVED_SOURCES).id],
        )
        self._hypotheses[h_id] = hypothesis
        if len(self._hypotheses) > self._max_hypotheses:
            oldest = min(self._hypotheses.keys(), key=lambda k: self._hypotheses[k].confidence)
            del self._hypotheses[oldest]
        return hypothesis

    def add_evidence(self, hypothesis_id: str, source_id: str) -> bool:
        hyp = self._hypotheses.get(hypothesis_id)
        if not hyp:
            return False
        hyp.evidence_count += 1
        hyp.confidence = min(1.0, hyp.confidence + 0.05)
        if source_id not in hyp.source_ids:
            hyp.source_ids.append(source_id)
        if hyp.evidence_count >= 3 and hyp.confidence >= 0.7:
            hyp.verified = True
        return True

    def get_unverified(self) -> List[Hypothesis]:
        return [h for h in self._hypotheses.values() if not h.verified]

    def get_verified(self) -> List[Hypothesis]:
        return [h for h in self._hypotheses.values() if h.verified]

    def get_high_value(self, threshold: float = 0.6) -> List[Hypothesis]:
        return [h for h in self._hypotheses.values()
                if h.confidence >= threshold and not h.verified]

    def rank_by_usefulness(self) -> List[Dict[str, Any]]:
        scored = []
        for h in self._hypotheses.values():
            score = h.confidence * 0.4 + min(h.evidence_count / 10, 1.0) * 0.3
            score += (0.3 if h.verified else 0)
            scored.append({"id": h.id, "title": h.title, "score": round(score, 2),
                           "confidence": round(h.confidence, 2), "verified": h.verified})
        return sorted(scored, key=lambda x: x["score"], reverse=True)

    def summary(self) -> Dict[str, Any]:
        total = len(self._hypotheses)
        verified = len(self.get_verified())
        return {
            "total": total,
            "verified": verified,
            "unverified": total - verified,
            "high_value": len(self.get_high_value()),
            "top_hypotheses": self.rank_by_usefulness()[:5],
        }
