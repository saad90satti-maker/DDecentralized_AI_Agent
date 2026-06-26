from __future__ import annotations

import logging
import re
from collections import Counter, defaultdict
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set

from research_engine.models import (
    AnalysisResult, Citation, Concept, Confidence,
    Relationship, ResearchFinding, ResearchReport,
    ResearchSource, ResearchTopic,
)

logger = logging.getLogger("research.analyzer")


class ResearchAnalyzer:
    """Analyzes collected research data for trends, gaps, and quality."""

    def __init__(self):
        pass

    def analyze_topic(
        self,
        topic: ResearchTopic,
        sources: List[ResearchSource],
        findings: List[ResearchFinding],
        concepts: List[Concept],
    ) -> AnalysisResult:
        """Perform comprehensive analysis of a research topic."""
        summary = self._generate_summary(topic, sources, findings, concepts)
        trends = self._detect_trends(sources, concepts)
        gaps = self._identify_gaps(sources, findings, concepts)
        relationships = self._build_relationship_graph(concepts)
        citations = self._extract_citations_from_sources(sources)
        confidence = self._assess_confidence(sources, findings)

        return AnalysisResult(
            topic=topic.name,
            summary=summary,
            findings=findings,
            concepts=concepts,
            relationships=relationships,
            sources=sources,
            citations=citations,
            trends=trends,
            gaps=gaps,
            confidence=confidence,
        )

    def compare_topics(
        self, topics: List[AnalysisResult]
    ) -> Dict[str, Any]:
        """Compare multiple topic analyses to find connections."""
        all_concepts = set()
        topic_concepts = {}
        for t in topics:
            names = frozenset(c.name.lower() for c in t.concepts)
            topic_concepts[t.topic] = names
            all_concepts.update(names)

        shared = {}
        for i, t1 in enumerate(topics):
            for t2 in topics[i + 1:]:
                overlap = topic_concepts[t1.topic] & topic_concepts[t2.topic]
                if overlap:
                    shared[f"{t1.topic} <-> {t2.topic}"] = list(overlap)[:10]

        return {
            "shared_concepts": shared,
            "cross_topic_connections": len(shared),
        }

    def assess_report_quality(self, report: ResearchReport) -> Dict[str, Any]:
        """Assess the quality of a generated research report."""
        wc = report.word_count()
        findings = len(report.findings)
        sources = len(report.sources)
        citations = len(report.citations)
        sections = len(report.sections)

        score = 0.0
        score += min(wc / 500, 1.0) * 25
        score += min(findings / 5, 1.0) * 20
        score += min(sources / 3, 1.0) * 20
        score += min(citations / 3, 1.0) * 20
        score += min(sections / 3, 1.0) * 15

        return {
            "word_count": wc,
            "finding_count": findings,
            "source_count": sources,
            "citation_count": citations,
            "section_count": sections,
            "quality_score": round(score, 1),
            "has_abstract": bool(report.abstract),
            "has_citations": len(report.citations) > 0,
        }

    def rank_sources(self, sources: List[ResearchSource]) -> List[dict]:
        """Rank sources by relevance and credibility."""
        ranked = []
        for src in sources:
            score = 0
            if src.source_type == "arxiv":
                score += 8
            elif src.source_type == "academic":
                score += 7
            elif src.source_type == "patent":
                score += 6
            score += min(len(src.authors), 5) * 2
            if src.doi:
                score += 5
            if src.citation_count > 0:
                score += min(src.citation_count / 10, 5)
            score += min(len(src.keywords), 5)
            ranked.append({"source": src, "relevance_score": score})
        return sorted(ranked, key=lambda x: -x["relevance_score"])

    def _generate_summary(
        self,
        topic: ResearchTopic,
        sources: List[ResearchSource],
        findings: List[ResearchFinding],
        concepts: List[Concept],
    ) -> str:
        """Generate a summary of research findings."""
        parts = [f"Research analysis of '{topic.name}' covering {len(sources)} sources."]
        if findings:
            high_conf = [f for f in findings if f.confidence == Confidence.high]
            if high_conf:
                parts.append(f"Key findings: {len(high_conf)} high-confidence claims identified.")
        if concepts:
            parts.append(f"{len(concepts)} key concepts extracted.")
        return " ".join(parts)

    def _detect_trends(
        self, sources: List[ResearchSource], concepts: List[Concept]
    ) -> List[str]:
        """Detect emerging trends from sources and concepts."""
        trends = []
        concept_names = [c.name.lower() for c in concepts]
        trend_indicators = [
            "transformer", "large language model", "diffusion", "foundation model",
            "reinforcement learning", "multi-agent", "self-supervised",
            "contrastive learning", "neural operator", "equivariant",
            "causal", "world model", "chain-of-thought", "retrieval-augmented",
            "graph neural", "attention", "pretraining", "few-shot",
        ]
        for indicator in trend_indicators:
            if indicator in " ".join(concept_names):
                trends.append(f"Growing interest in {indicator}")

        years = [s.published[:4] for s in sources if s.published and len(s.published) >= 4]
        if years:
            recent = sum(1 for y in years if y >= "2024")
            if recent > len(years) * 0.5:
                trends.append(f"High proportion ({recent}/{len(years)}) recent publications (2024+)")

        if not trends:
            trends.append("Trend analysis limited by available data")

        return trends[:5]

    def _identify_gaps(
        self,
        sources: List[ResearchSource],
        findings: List[ResearchFinding],
        concepts: List[Concept],
    ) -> List[str]:
        """Identify research gaps from available data."""
        gaps = []
        if len(sources) < 3:
            gaps.append("Limited source diversity")
        if len(findings) < 5:
            gaps.append("Few empirical findings extracted")
        if len(concepts) < 3:
            gaps.append("Narrow concept coverage")
        concept_names = [c.name.lower() for c in concepts]
        important_areas = ["ethics", "fairness", "bias", "robustness", "interpretability"]
        for area in important_areas:
            if area not in " ".join(concept_names) and len(concepts) > 5:
                gaps.append(f"Missing consideration of {area}")
        return gaps[:5]

    def _build_relationship_graph(
        self, concepts: List[Concept]
    ) -> List[Relationship]:
        """Build a relationship graph from co-occurring concepts."""
        relationships = []
        for i, c1 in enumerate(concepts):
            for c2 in concepts[i + 1:]:
                shared_sources = set(c1.source_ids) & set(c2.source_ids)
                if shared_sources:
                    rel = Relationship(
                        source_concept_id=c1.id,
                        target_concept_id=c2.id,
                        relation_type="co_occurs_in_source",
                        weight=min(len(shared_sources) / 3, 1.0),
                        evidence=f"Shared across {len(shared_sources)} sources",
                        source_ids=list(shared_sources),
                        confidence=Confidence.medium,
                    )
                    relationships.append(rel)
        return relationships[:30]

    def _extract_citations_from_sources(
        self, sources: List[ResearchSource]
    ) -> List[Citation]:
        """Extract citation metadata from sources."""
        citations = []
        for src in sources:
            if src.authors or src.doi:
                cit = Citation(
                    source_id=src.id,
                    title=src.title,
                    authors=src.authors,
                    year=int(src.published[:4]) if src.published and len(src.published) >= 4 else None,
                    journal=src.publisher,
                    doi=src.doi,
                    url=src.url,
                )
                citations.append(cit)
        return citations

    def _assess_confidence(
        self, sources: List[ResearchSource], findings: List[ResearchFinding]
    ) -> Confidence:
        """Assess overall confidence in analysis based on data quality."""
        if len(sources) >= 5 and len(findings) >= 10:
            return Confidence.high
        if len(sources) >= 2 and len(findings) >= 3:
            return Confidence.medium
        return Confidence.low
