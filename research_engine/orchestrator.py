from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from research_engine.collector import ResearchCollector
from research_engine.extractor import ConceptExtractor
from research_engine.analyzer import ResearchAnalyzer
from research_engine.generator import ReportGenerator
from research_engine.models import (
    AnalysisResult, Concept, ResearchFinding,
    ResearchReport, ResearchSource, ResearchTopic,
)

logger = logging.getLogger("research.orchestrator")


class ResearchOrchestrator:
    """Orchestrates the full research pipeline: collect → extract → analyze → report."""

    def __init__(
        self,
        collector: Optional[ResearchCollector] = None,
        extractor: Optional[ConceptExtractor] = None,
        analyzer: Optional[ResearchAnalyzer] = None,
        generator: Optional[ReportGenerator] = None,
        output_dir: str = "reports",
    ):
        self._collector = collector or ResearchCollector()
        self._extractor = extractor or ConceptExtractor()
        self._analyzer = analyzer or ResearchAnalyzer()
        self._generator = generator or ReportGenerator(output_dir=output_dir)
        self._topics: Dict[str, ResearchTopic] = {}
        self._analyses: Dict[str, AnalysisResult] = {}
        self._reports: Dict[str, ResearchReport] = {}

    async def close(self):
        await self._collector.close()

    async def research_topic(
        self,
        topic_name: str,
        description: str = "",
        keywords: Optional[List[str]] = None,
        max_sources: int = 15,
        generate_report: bool = True,
    ) -> Dict[str, Any]:
        """Run the full research pipeline on a topic."""
        logger.info("Starting research on: %s", topic_name)

        topic = ResearchTopic(
            name=topic_name,
            description=description or f"Research on {topic_name}",
            keywords=keywords or [],
        )
        self._topics[topic.id] = topic

        sources = await self._collector.collect_topic(topic_name, max_per_source=max_sources)
        logger.info("Collected %d sources", len(sources))

        all_findings: List[ResearchFinding] = []
        all_concepts: List[Concept] = []
        concept_map: Dict[str, Concept] = {}

        for src in sources[:5]:
            text = ""
            if src.source_type == "arxiv" and src.abstract:
                text = src.abstract
            else:
                fetched = await self._collector.fetch_url(src.url)
                if fetched:
                    text = fetched[:5000]

            if text:
                concepts = await self._extractor.extract_concepts(text, src)
                for c in concepts:
                    if c.name.lower() not in concept_map:
                        concept_map[c.name.lower()] = c
                        all_concepts.append(c)
                findings = await self._extractor.extract_findings(text, src)
                all_findings.extend(findings)

        logger.info("Extracted %d concepts, %d findings", len(all_concepts), len(all_findings))

        analysis = self._analyzer.analyze_topic(
            topic, sources, all_findings, all_concepts
        )
        self._analyses[analysis.id] = analysis
        logger.info("Analysis complete: confidence=%s", analysis.confidence.value)
        report = None
        if generate_report:
            report = self._generator.generate_report(analysis)
            self._reports[report.id] = report
            quality = self._analyzer.assess_report_quality(report)
            logger.info("Report generated: quality=%.1f", quality["quality_score"])

        return {
            "topic": topic_name,
            "topic_id": topic.id,
            "analysis_id": analysis.id,
            "sources_count": len(sources),
            "findings_count": len(all_findings),
            "concepts_count": len(all_concepts),
            "confidence": analysis.confidence.value,
            "report_id": report.id if report else None,
            "report_path": f"reports/report_{report.id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.md" if report else None,
        }

    async def batch_research(
        self, topics: List[str], max_concurrent: int = 3
    ) -> Dict[str, Any]:
        """Run research pipeline on multiple topics concurrently."""
        sem = asyncio.Semaphore(max_concurrent)

        async def _one(topic: str) -> Dict[str, Any]:
            async with sem:
                return await self.research_topic(topic)

        results = await asyncio.gather(*[_one(t) for t in topics], return_exceptions=True)
        ok = [r for r in results if isinstance(r, dict)]
        errors = [r for r in results if isinstance(r, Exception)]

        report = None
        if len(ok) >= 2:
            analyses = [
                self._analyses[r["analysis_id"]]
                for r in ok
                if r["analysis_id"] in self._analyses
            ]
            if analyses:
                report = self._generator.generate_comparative_report(
                    analyses,
                    title=f"Comparative Analysis: {', '.join(topics)}",
                )

        return {
            "topics_researched": len(ok),
            "errors": len(errors),
            "error_details": [str(e) for e in errors[:3]],
            "results": ok,
            "comparative_report_id": report.id if report else None,
        }

    async def deep_dive(
        self,
        url: str,
        topic_name: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Deep research on a single URL."""
        name = topic_name or url.split("//")[-1].split("/")[0]
        topic = ResearchTopic(name=name, description=f"Deep dive on {url}")
        self._topics[topic.id] = topic

        text = await self._collector.fetch_url(url)
        if not text:
            return {"error": f"Failed to fetch {url}"}

        src = ResearchSource(
            title=name,
            url=url,
            abstract=text[:2000],
        )

        concepts = await self._extractor.extract_concepts(text[:10000], src)
        findings = await self._extractor.extract_findings(text[:10000], src)

        analysis = self._analyzer.analyze_topic(topic, [src], findings, concepts)
        report = self._generator.generate_report(analysis)

        return {
            "topic": name,
            "sources_count": 1,
            "findings_count": len(findings),
            "concepts_count": len(concepts),
            "confidence": analysis.confidence.value,
            "report_id": report.id,
        }

    def get_report(self, report_id: str) -> Optional[ResearchReport]:
        return self._reports.get(report_id)

    def get_analysis(self, analysis_id: str) -> Optional[AnalysisResult]:
        return self._analyses.get(analysis_id)

    def list_reports(self) -> List[Dict[str, Any]]:
        return [
            {
                "id": r.id,
                "title": r.title,
                "topic": r.topic,
                "quality_score": r.quality_score,
                "created_at": r.created_at,
                "word_count": r.word_count(),
            }
            for r in sorted(
                self._reports.values(), key=lambda x: x.created_at, reverse=True
            )
        ]

    def export_knowledge_graph(
        self, analysis_id: str
    ) -> Dict[str, Any]:
        """Export analysis as a knowledge graph JSON (for visualization)."""
        analysis = self._analyses.get(analysis_id)
        if not analysis:
            return {"error": "Analysis not found"}

        nodes = [
            {
                "id": c.id,
                "label": c.name,
                "category": c.category,
                "group": c.category,
                "size": len(c.source_ids) + 1,
            }
            for c in analysis.concepts
        ]
        edges = [
            {
                "id": r.id,
                "source": r.source_concept_id,
                "target": r.target_concept_id,
                "label": r.relation_type,
                "weight": r.weight,
            }
            for r in analysis.relationships
        ]
        return {
            "analysis_id": analysis_id,
            "topic": analysis.topic,
            "nodes": nodes,
            "edges": edges,
            "metadata": {
                "node_count": len(nodes),
                "edge_count": len(edges),
                "confidence": analysis.confidence.value,
            },
        }
