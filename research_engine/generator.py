from __future__ import annotations

import json
import logging
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from research_engine.models import (
    AnalysisResult, Citation, Concept, Confidence,
    ResearchFinding, ResearchReport, ResearchSource,
)

logger = logging.getLogger("research.generator")


class ReportGenerator:
    """Generates structured research reports in multiple formats."""

    def __init__(self, output_dir: str = "reports"):
        self._output_dir = Path(output_dir)
        self._output_dir.mkdir(parents=True, exist_ok=True)

    def generate_report(
        self,
        analysis: AnalysisResult,
        title: Optional[str] = None,
        include_latex: bool = False,
    ) -> ResearchReport:
        """Generate a complete research report from analysis results."""
        report_title = title or f"Research Report: {analysis.topic}"

        sections = self._build_sections(analysis)
        figures = self._build_figures(analysis)

        report = ResearchReport(
            title=report_title,
            topic=analysis.topic,
            abstract=self._generate_abstract(analysis),
            sections=sections,
            findings=analysis.findings,
            concepts=analysis.concepts,
            relationships=analysis.relationships,
            sources=analysis.sources,
            citations=analysis.citations,
            figures=figures,
            tags=self._generate_tags(analysis),
            quality_score=self._calculate_quality(analysis),
        )

        self._save_report(report)
        if include_latex:
            self._save_latex(report)

        return report

    def generate_comparative_report(
        self, analyses: List[AnalysisResult], title: str
    ) -> ResearchReport:
        """Generate a report comparing multiple research topics."""
        sections = [
            {
                "heading": "Comparative Analysis",
                "content": f"Comparing {len(analyses)} research topics.",
            }
        ]
        for analysis in analyses:
            sections.append({
                "heading": analysis.topic,
                "content": (
                    f"Sources: {len(analysis.sources)} | "
                    f"Findings: {len(analysis.findings)} | "
                    f"Concepts: {len(analysis.concepts)}\n\n"
                    f"{analysis.summary}"
                ),
            })
        all_sources = []
        seen_ids = set()
        for a in analyses:
            for s in a.sources:
                if s.id not in seen_ids:
                    seen_ids.add(s.id)
                    all_sources.append(s)
        all_findings = []
        for a in analyses:
            all_findings.extend(a.findings)

        report = ResearchReport(
            title=title,
            topic="comparative",
            abstract=f"Comparative analysis of {len(analyses)} research topics.",
            sections=sections,
            findings=all_findings[:50],
            sources=all_sources,
            citations=[c for a in analyses for c in a.citations],
            quality_score=75.0,
        )
        self._save_report(report)
        return report

    def report_to_json(self, report: ResearchReport) -> str:
        """Serialize report to JSON."""
        return report.model_dump_json(indent=2)

    def report_to_markdown(self, report: ResearchReport) -> str:
        """Convert report to formatted Markdown."""
        return report.to_markdown()

    def report_to_latex(self, report: ResearchReport) -> str:
        """Convert report to LaTeX."""
        return report.to_latex()

    def _build_sections(self, analysis: AnalysisResult) -> List[Dict[str, Any]]:
        """Build report sections from analysis data."""
        sections = []

        if analysis.summary:
            sections.append({"heading": "Executive Summary", "content": analysis.summary})

        if analysis.findings:
            findings_content = "\n\n".join(
                f"- **{f.claim}**\n  *Confidence: {f.confidence.value}*"
                for f in analysis.findings[:10]
            )
            sections.append({"heading": "Key Findings", "content": findings_content})

        if analysis.concepts:
            concepts_by_cat = {}
            for c in analysis.concepts:
                concepts_by_cat.setdefault(c.category, []).append(c.name)
            cat_lines = []
            for cat, names in concepts_by_cat.items():
                cat_lines.append(f"**{cat.capitalize()}**: {', '.join(names[:8])}")
            sections.append({
                "heading": "Key Concepts",
                "content": "\n\n".join(cat_lines) if cat_lines else "No concepts extracted.",
            })

        if analysis.relationships:
            rel_lines = []
            rel_map = {}
            for r in analysis.relationships[:15]:
                rel_map.setdefault(r.relation_type.replace("_", " ").title(), []).append(
                    f"{r.source_concept_id[:8]} → {r.target_concept_id[:8]}"
                )
            for rtype, pairs in rel_map.items():
                rel_lines.append(f"**{rtype}**: " + ", ".join(pairs[:5]))
            sections.append({
                "heading": "Relationship Network",
                "content": "\n\n".join(rel_lines) if rel_lines else "No relationships identified.",
            })

        if analysis.trends:
            sections.append({
                "heading": "Trends",
                "content": "\n".join(f"- {t}" for t in analysis.trends),
            })

        if analysis.gaps:
            sections.append({
                "heading": "Research Gaps",
                "content": "\n".join(f"- {g}" for g in analysis.gaps),
            })

        if analysis.sources:
            src_list = "\n".join(
                f"- [{s.title[:80]}]({s.url}) ({s.source_type.value})"
                for s in sorted(analysis.sources, key=lambda x: x.title)[:20]
            )
            sections.append({"heading": "Sources", "content": src_list})

        sections.append({
            "heading": "Conclusion",
            "content": (
                f"This analysis covered {len(analysis.sources)} sources, "
                f"identified {len(analysis.findings)} findings across "
                f"{len(analysis.concepts)} concepts. "
                f"Confidence level: {analysis.confidence.value}."
            ),
        })

        return sections

    def _build_figures(self, analysis: AnalysisResult) -> List[Dict[str, Any]]:
        """Build figure metadata for the report."""
        figures = []
        if analysis.concepts:
            figure_data = {
                "id": f"fig-{uuid.uuid4().hex[:8]}",
                "type": "concept_distribution",
                "caption": f"Concept distribution across {len(analysis.concepts)} extracted concepts",
                "data": {
                    "labels": [c.name[:20] for c in analysis.concepts[:10]],
                    "categories": [c.category for c in analysis.concepts[:10]],
                },
            }
            figures.append(figure_data)
        if analysis.relationships:
            figures.append({
                "id": f"fig-{uuid.uuid4().hex[:8]}",
                "type": "relationship_graph",
                "caption": f"Relationship graph with {len(analysis.relationships)} connections",
                "data": {
                    "node_count": len(set(
                        r.source_concept_id for r in analysis.relationships
                    ) | set(r.target_concept_id for r in analysis.relationships)),
                    "edge_count": len(analysis.relationships),
                },
            })
        return figures

    def _generate_abstract(self, analysis: AnalysisResult) -> str:
        """Generate an abstract from analysis data."""
        return (
            f"This report presents a comprehensive analysis of '{analysis.topic}' "
            f"based on {len(analysis.sources)} sources. "
            f"We identified {len(analysis.findings)} key findings and "
            f"{len(analysis.concepts)} distinct concepts, revealing "
            f"{len(analysis.relationships)} meaningful relationships. "
            f"Analysis confidence: {analysis.confidence.value}."
        )

    def _generate_tags(self, analysis: AnalysisResult) -> List[str]:
        """Generate tags from analysis data."""
        tags = set()
        tags.add(analysis.topic.lower().replace(" ", "-"))
        tags.add(analysis.confidence.value)
        for c in analysis.concepts:
            tags.add(c.category)
            if len(tags) >= 10:
                break
        for f in analysis.findings:
            tags.update(f.tags)
            if len(tags) >= 15:
                break
        return list(tags)[:15]

    def _calculate_quality(self, analysis: AnalysisResult) -> float:
        score = 0.0
        score += min(len(analysis.sources) / 10, 1.0) * 25
        score += min(len(analysis.findings) / 15, 1.0) * 25
        score += min(len(analysis.concepts) / 10, 1.0) * 20
        score += min(len(analysis.relationships) / 10, 1.0) * 15
        score += (1.0 if analysis.trends else 0.0) * 7.5
        score += (1.0 if analysis.gaps else 0.0) * 7.5
        return round(score, 1)

    def _save_report(self, report: ResearchReport) -> None:
        """Save report to disk."""
        fname = f"report_{report.id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        md_path = self._output_dir / f"{fname}.md"
        md_path.write_text(report.to_markdown(), encoding="utf-8")
        json_path = self._output_dir / f"{fname}.json"
        json_path.write_text(report.model_dump_json(indent=2), encoding="utf-8")
        logger.info("Report saved: %s (.md / .json)", fname)

    def _save_latex(self, report: ResearchReport) -> None:
        """Save LaTeX version of report."""
        fname = f"report_{report.id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        tex_path = self._output_dir / f"{fname}.tex"
        tex_path.write_text(report.to_latex(), encoding="utf-8")
        logger.info("LaTeX saved: %s.tex", fname)
