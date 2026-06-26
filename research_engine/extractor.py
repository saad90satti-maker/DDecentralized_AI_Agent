from __future__ import annotations

import json
import logging
import re
from typing import Any, Dict, List, Optional
from collections import Counter

from research_engine.models import (
    Concept, ResearchFinding, Citation, Confidence,
    Relationship, ResearchSource,
)

logger = logging.getLogger("research.extractor")


class ConceptExtractor:
    """Extracts concepts, findings, and relationships from research text."""

    def __init__(self, llm_client=None):
        self._llm = llm_client
        self._stopwords = set(
            "the a an in of to and is for on that with this from as at by be are was were has have had not but what which who whom whose when where why how all each its their his her our your its".split()
        )

    async def extract_concepts(self, text: str, source: ResearchSource) -> List[Concept]:
        """Extract key concepts from text."""
        concepts = []
        seen = set()

        candidates = self._find_candidate_phrases(text)
        for phrase, count in candidates:
            if phrase.lower() in seen:
                continue
            seen.add(phrase.lower())
            concept = Concept(
                name=phrase,
                description=f"Extracted concept found {count} times in '{source.title[:50]}...'",
                category=self._categorize(phrase),
                source_ids=[source.id],
            )
            concepts.append(concept)

        return concepts

    async def extract_findings(self, text: str, source: ResearchSource) -> List[ResearchFinding]:
        """Extract research findings/claims from text."""
        findings = []
        sentences = re.split(r"(?<=[.!?])\s+", text)

        for sent in sentences:
            if len(sent) < 40 or len(sent) > 800:
                continue
            if self._is_claim_sentence(sent):
                finding = ResearchFinding(
                    claim=sent[:200],
                    evidence=sent,
                    source_ids=[source.id],
                    confidence=Confidence.medium,
                    tags=self._extract_tags(sent),
                )
                findings.append(finding)

        return findings[:20]

    async def extract_citations(self, text: str) -> List[Citation]:
        """Extract citations from text (APA-like patterns)."""
        citations = []
        patterns = [
            r"\(([A-Z][a-z]+(?:\s(?:et\sal\.?|&\s)?[A-Z][a-z]+)?),\s*(\d{4})\)",
            r"([A-Z][a-z]+(?:\s(?:et\sal\.?|&\s)?[A-Z][a-z]+)?)\s*\((\d{4})\)",
            r"(https?://doi\.org/10\.\d{4,}/[\w.\-/:;()]+)",
        ]
        for pattern in patterns:
            for match in re.finditer(pattern, text):
                doi = None
                if match.group(0).startswith("http"):
                    doi = match.group(1)
                    title = f"Unknown ({doi})"
                else:
                    title = match.group(0)
                cit = Citation(
                    source_id="text",
                    title=title,
                    year=int(match.group(2)) if len(match.groups()) >= 2 and match.group(2).isdigit() else None,
                    doi=doi,
                )
                citations.append(cit)
        return citations

    async def extract_relationships(
        self, concepts: List[Concept], text: str
    ) -> List[Relationship]:
        """Discover relationships between extracted concepts."""
        relationships = []
        concept_names = {c.name.lower(): c for c in concepts}

        for c1 in concepts:
            for c2 in concepts:
                if c1.id >= c2.id:
                    continue
                name1, name2 = c1.name.lower(), c2.name.lower()
                if name1 == name2:
                    continue
                co_count = text.lower().count(name1) + text.lower().count(name2)
                if co_count > 2:
                    rel = Relationship(
                        source_concept_id=c1.id,
                        target_concept_id=c2.id,
                        relation_type="co_occurs_with",
                        weight=min(co_count / 10, 1.0),
                        evidence=f"Co-occurrence count: {co_count}",
                        source_ids=list(set(c1.source_ids + c2.source_ids)),
                        confidence=Confidence.medium,
                    )
                    relationships.append(rel)

        return relationships[:50]

    async def summarize_text(self, text: str, max_length: int = 500) -> str:
        """Summarize text by extracting key sentences."""
        sentences = re.split(r"(?<=[.!?])\s+", text)
        if len(sentences) <= 3:
            return text[:max_length]

        scores = []
        for sent in sentences:
            score = 0
            words = sent.lower().split()
            score += sum(1 for w in words if w not in self._stopwords and len(w) > 4)
            score += sum(
                1 for w in words
                if w in ("key", "important", "significant", "novel", "propose", "demonstrate", "show", "result", "finding", "conclude", "therefore", "hence")
            )
            sent_len = len(words)
            if 10 <= sent_len <= 35:
                score += 5
            scores.append(score)

        ranked = sorted(zip(sentences, scores), key=lambda x: -x[1])
        selected = []
        current_len = 0
        for sent, _ in ranked:
            if current_len + len(sent) <= max_length:
                selected.append(sent)
                current_len += len(sent)
            else:
                break

        return " ".join(sorted(selected, key=lambda s: sentences.index(s))) if selected else text[:max_length]

    def _find_candidate_phrases(self, text: str) -> List[tuple]:
        """Find frequent meaningful phrases using simple frequency approach."""
        words = re.findall(r"\b[A-Z][a-z]+(?:\s[A-Z][a-z]+)*\b", text)
        if not words:
            return []
        counter = Counter(words)
        bigrams = Counter()
        for i in range(len(words) - 1):
            bigrams[f"{words[i]} {words[i+1]}"] += 1
        merged = counter + bigrams
        return [(phrase, count) for phrase, count in merged.most_common(30) if count >= 2 and phrase.lower() not in self._stopwords]

    def _categorize(self, phrase: str) -> str:
        lphrase = phrase.lower()
        tech = ("network", "algorithm", "model", "system", "neural", "learning", "data", "optimization", "computation", "quantum", "blockchain", "protocol", "distributed", "autonomous", "agent", "intelligence")
        science = ("theory", "analysis", "method", "study", "experiment", "research", "hypothesis", "mechanism", "dynamics", "equation")
        if any(t in lphrase for t in tech):
            return "technology"
        if any(s in lphrase for s in science):
            return "science"
        return "general"

    def _is_claim_sentence(self, sent: str) -> bool:
        indicators = [
            "show", "demonstrate", "propose", "find", "suggest", "indicate",
            "reveal", "conclude", "identify", "develop", "introduce",
            "achieve", "improve", "enable", "result in", "lead to",
            "significantly", "novel", "state-of-the-art", "first",
            "we present", "we introduce", "our approach", "experimental results",
        ]
        lsent = sent.lower()
        return any(ind in lsent for ind in indicators)

    def _extract_tags(self, sent: str) -> List[str]:
        words = re.findall(r"\b[A-Z][a-z]{3,}\b", sent)
        return list(set(w.lower() for w in words[:5])) if words else ["general"]
