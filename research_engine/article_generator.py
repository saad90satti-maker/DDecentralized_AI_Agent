from __future__ import annotations

import json
import logging
import os
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional
from enum import Enum

from pydantic import BaseModel, Field

from research_engine.models import (
    AnalysisResult, Citation, ResearchFinding,
    ResearchSource, ResearchReport,
)

logger = logging.getLogger("research.article")


class ArticleFormat(str, Enum):
    ieee = "ieee"
    acm = "acm"
    apa = "apa"
    nature = "nature"
    markdown = "markdown"


class ScientificArticle(BaseModel):
    id: str = Field(default_factory=lambda: f"article-{uuid.uuid4().hex[:8]}")
    title: str
    authors: List[str]
    abstract: str
    keywords: List[str] = []
    sections: List[Dict[str, Any]] = []
    citations: List[Citation] = []
    figures: List[Dict[str, Any]] = []
    tables: List[Dict[str, Any]] = []
    acknowledgments: str = ""
    conflict_of_interest: str = "The authors declare no competing interests."
    doi: Optional[str] = None
    format: ArticleFormat = ArticleFormat.markdown
    word_count: int = 0
    created_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    source_report_id: Optional[str] = None

    def to_latex(self, template: str = "ieee") -> str:
        if template == "ieee":
            return self._latex_ieee()
        elif template == "acm":
            return self._latex_acm()
        elif template == "nature":
            return self._latex_nature()
        return self._latex_generic()

    def to_markdown(self) -> str:
        lines = [
            f"# {self.title}",
            "",
            f"**Authors:** {', '.join(self.authors)}",
            f"**DOI:** {self.doi or 'N/A'}",
            f"**Keywords:** {', '.join(self.keywords)}",
            "",
            "---",
            "",
            "## Abstract",
            "",
            self.abstract,
            "",
        ]
        for section in self.sections:
            heading = section.get("heading", "")
            content = section.get("content", "")
            lines.append(f"## {heading}")
            lines.append("")
            lines.append(content)
            lines.append("")
        if self.figures:
            lines.append("---")
            lines.append("")
            for fig in self.figures:
                caption = fig.get("caption", "")
                lines.append(f"![{caption}]({fig.get('url', '')})")
                lines.append(f"*{caption}*")
                lines.append("")
        if self.tables:
            for table in self.tables:
                lines.append(self._format_table_markdown(table))
                lines.append("")
        if self.citations:
            lines.append("## References")
            lines.append("")
            for i, cit in enumerate(self.citations, 1):
                lines.append(f"[{i}] {cit.format_apa()}")
                lines.append("")
        if self.acknowledgments:
            lines.append("## Acknowledgments")
            lines.append("")
            lines.append(self.acknowledgments)
            lines.append("")
        return "\n".join(lines)

    def to_html(self) -> str:
        md = self.to_markdown()
        import markdown
        return markdown.markdown(
            md, extensions=["extra", "codehilite", "toc"]
        )

    def _latex_ieee(self) -> str:
        lines = [
            r"\documentclass[10pt,conference]{IEEEtran}",
            r"\usepackage{cite}",
            r"\usepackage{amsmath,amssymb}",
            r"\usepackage{graphicx}",
            r"\usepackage{hyperref}",
            r"\usepackage{booktabs}",
            "",
            r"\title{" + self._escape_latex(self.title) + "}",
            "",
            r"\author{"
            + r" \and ".join(
                self._escape_latex(a) for a in self.authors
            )
            + "}",
            "",
            r"\begin{document}",
            r"\maketitle",
            "",
            r"\begin{abstract}",
            self._escape_latex(self.abstract),
            r"\end{abstract}",
            "",
            r"\IEEEkeywords{"
            + ", ".join(self._escape_latex(k) for k in self.keywords)
            + "}",
            "",
        ]
        for section in self.sections:
            heading = section.get("heading", "")
            content = section.get("content", "")
            lines.append(
                r"\section{" + self._escape_latex(heading) + "}"
            )
            lines.append("")
            lines.append(self._escape_latex(content))
            lines.append("")
        if self.citations:
            lines.append(r"\bibliographystyle{IEEEtran}")
            lines.append(r"\bibliography{references}")
        lines.append(r"\end{document}")
        return "\n".join(lines)

    def _latex_acm(self) -> str:
        lines = [
            r"\documentclass[manuscript,screen]{acmart}",
            r"\usepackage{graphicx}",
            r"\usepackage{booktabs}",
            r"\usepackage{hyperref}",
            "",
            r"\title{" + self._escape_latex(self.title) + "}",
            "",
            r"\author{"
            + r" \and ".join(
                self._escape_latex(a) for a in self.authors
            )
            + "}",
            "",
            r"\begin{document}",
            r"\maketitle",
            "",
            r"\begin{abstract}",
            self._escape_latex(self.abstract),
            r"\end{abstract}",
            "",
            r"\keywords{"
            + ", ".join(self._escape_latex(k) for k in self.keywords)
            + "}",
            "",
        ]
        for section in self.sections:
            heading = section.get("heading", "")
            content = section.get("content", "")
            lines.append(
                r"\section{" + self._escape_latex(heading) + "}"
            )
            lines.append("")
            lines.append(self._escape_latex(content))
            lines.append("")
        lines.append(r"\end{document}")
        return "\n".join(lines)

    def _latex_nature(self) -> str:
        lines = [
            r"\documentclass[11pt]{article}",
            r"\usepackage{natbib}",
            r"\usepackage{amsmath}",
            r"\usepackage{geometry}",
            r"\geometry{margin=1in}",
            "",
            r"\title{" + self._escape_latex(self.title) + "}",
            "",
            r"\author{"
            + r" \and ".join(
                self._escape_latex(a) for a in self.authors
            )
            + r"\\"
            + r"\textit{Decentralized AI Agent Research Group}}",
            "",
            r"\begin{document}",
            r"\maketitle",
            "",
            r"\begin{abstract}",
            self._escape_latex(self.abstract),
            r"\end{abstract}",
            "",
        ]
        for section in self.sections:
            heading = section.get("heading", "")
            content = section.get("content", "")
            lines.append(
                r"\section*{" + self._escape_latex(heading) + "}"
            )
            lines.append("")
            lines.append(self._escape_latex(content))
            lines.append("")
        if self.citations:
            lines.append(
                r"\bibliographystyle{plainnat}"
            )
            lines.append(r"\bibliography{references}")
        lines.append(r"\end{document}")
        return "\n".join(lines)

    def _latex_generic(self) -> str:
        return self._latex_ieee()

    def _escape_latex(self, text: str) -> str:
        replacements = {
            "&": r"\&", "%": r"\%", "$": r"\$",
            "#": r"\#", "_": r"\_", "{": r"\{",
            "}": r"\}", "~": r"\textasciitilde{}",
            "^": r"\^{}",
        }
        for char, escaped in replacements.items():
            text = text.replace(char, escaped)
        return text

    def _format_table_markdown(self, table: Dict) -> str:
        headers = table.get("headers", [])
        rows = table.get("rows", [])
        caption = table.get("caption", "")
        lines = [f"**{caption}**", ""]
        if headers:
            lines.append("| " + " | ".join(headers) + " |")
            lines.append("| " + " | ".join("---" for _ in headers) + " |")
        for row in rows:
            lines.append("| " + " | ".join(str(c) for c in row) + " |")
        return "\n".join(lines)


class ArticleGenerator:
    """Generates publishable scientific articles from research analyses."""

    def __init__(self, output_dir: str = "articles"):
        self._output_dir = Path(output_dir)
        self._output_dir.mkdir(parents=True, exist_ok=True)
        self._articles: Dict[str, ScientificArticle] = {}

    def from_analysis(
        self,
        analysis: AnalysisResult,
        title: Optional[str] = None,
        authors: Optional[List[str]] = None,
        format: ArticleFormat = ArticleFormat.ieee,
        generate_doi: bool = True,
    ) -> ScientificArticle:
        """Generate a scientific article from a research analysis."""
        article_title = title or f"A Comprehensive Analysis of {analysis.topic}"

        _stop = {"general", "this", "that", "the", "a", "an", "in", "of", "to", "and"}
        keywords = list(set(
            [analysis.topic.lower()]
            + [c.name.lower() for c in analysis.concepts[:8]]
            + [f.tags[0] for f in analysis.findings[:3] if f.tags]
        ))
        keywords = [k for k in keywords if k not in _stop and len(k) > 2][:10]

        sections = self._build_sections(analysis)
        article = ScientificArticle(
            title=article_title,
            authors=authors or ["Decentralized AI Agent Research Group"],
            abstract=self._generate_abstract(analysis),
            keywords=keywords,
            sections=sections,
            citations=analysis.citations,
            figures=self._build_figures(analysis),
            tables=self._build_tables(analysis),
            format=format,
            source_report_id=analysis.id,
        )
        if generate_doi:
            article.doi = self._mint_doi(article)

        article.word_count = len(article.abstract.split()) + sum(
            len(s.get("content", "").split()) for s in sections
        )

        self._articles[article.id] = article
        self._save_article(article)
        return article

    def from_report(
        self,
        report: ResearchReport,
        title: Optional[str] = None,
        authors: Optional[List[str]] = None,
        format: ArticleFormat = ArticleFormat.markdown,
    ) -> ScientificArticle:
        """Generate a scientific article from an existing research report."""
        article_title = title or report.title
        sections = [
            {"heading": "Introduction",
             "content": report.abstract or f"This article presents research on {report.topic}."},
        ]
        sections.extend(report.sections)
        sections.append({
            "heading": "Conclusion",
            "content": (
                f"This study analyzed {len(report.sources)} sources "
                f"and identified {len(report.findings)} key findings. "
                f"The results demonstrate significant progress in {report.topic} "
                f"while highlighting areas requiring further investigation."
            ),
        })

        article = ScientificArticle(
            title=article_title,
            authors=authors or ["Decentralized AI Agent Research Group"],
            abstract=report.abstract or f"Research report on {report.topic}.",
            keywords=[report.topic.lower().replace(" ", "-")],
            sections=sections,
            citations=report.citations,
            figures=report.figures,
            format=format,
            source_report_id=report.id,
        )
        article.doi = self._mint_doi(article)
        article.word_count = report.word_count()
        self._articles[article.id] = article
        self._save_article(article)
        return article

    def get_article(self, article_id: str) -> Optional[ScientificArticle]:
        return self._articles.get(article_id)

    def list_articles(self) -> List[Dict[str, Any]]:
        return [
            {
                "id": a.id,
                "title": a.title,
                "authors": a.authors,
                "format": a.format.value,
                "doi": a.doi,
                "word_count": a.word_count,
                "created_at": a.created_at,
            }
            for a in sorted(
                self._articles.values(), key=lambda x: x.created_at, reverse=True
            )
        ]

    def export_bibtex(self, article_id: str) -> str:
        article = self._articles.get(article_id)
        if not article:
            return ""
        key = f"{article.authors[0].split()[-1].lower() if article.authors else 'unknown'}{datetime.now().year}"
        lines = [
            f"@article{{{key},",
            f"  title = {{{article.title}}},",
            f"  author = {{{' and '.join(article.authors)}}},",
            f"  journal = {{Decentralized AI Agent Research}},",
            f"  year = {{{datetime.now().year}}},",
            f"  doi = {{{article.doi or ''}}},",
            f"  keywords = {{{', '.join(article.keywords)}}},",
            "}",
        ]
        return "\n".join(lines)

    def _build_sections(self, analysis: AnalysisResult) -> List[Dict[str, Any]]:
        sections = []

        intro = (
            f"The field of {analysis.topic} has seen significant advances in recent years. "
            f"This article presents a comprehensive analysis based on "
            f"{len(analysis.sources)} sources from the academic literature. "
        )
        if analysis.trends:
            intro += " " + " ".join(analysis.trends[:2])
        sections.append({"heading": "Introduction", "content": intro})

        sections.append({
            "heading": "Methodology",
            "content": (
                f"We conducted a systematic search of academic databases, "
                f"collecting {len(analysis.sources)} relevant publications. "
                f"Each source was analyzed for key concepts, findings, and relationships. "
                f"Concept extraction identified {len(analysis.concepts)} distinct concepts, "
                f"and relationship analysis revealed {len(analysis.relationships)} connections "
                f"between them. The overall confidence in our analysis is "
                f"'{analysis.confidence.value}'."
            ),
        })

        if analysis.findings:
            findings_text = "\n\n".join(
                f"**{f.claim}**  \n*Evidence:* {f.evidence[:200]}..."
                for f in analysis.findings[:8]
            )
            sections.append({
                "heading": "Results",
                "content": (
                    f"We identified {len(analysis.findings)} key findings from the literature:\n\n"
                    f"{findings_text}"
                ),
            })

        if analysis.concepts:
            concepts_by_cat = {}
            for c in analysis.concepts:
                concepts_by_cat.setdefault(c.category, []).append(c.name)
            cat_text = "\n".join(
                f"- **{cat}**: {', '.join(names[:5])}"
                for cat, names in concepts_by_cat.items()
            )
            sections.append({
                "heading": "Discussion",
                "content": (
                    f"The analysis revealed {len(analysis.concepts)} key concepts "
                    f"across multiple categories:\n\n{cat_text}\n\n"
                    f"{' '.join(analysis.gaps[:3]) if analysis.gaps else ''}"
                ),
            })

        sections.append({
            "heading": "Conclusion",
            "content": (
                f"This study presented a comprehensive analysis of {analysis.topic}, "
                f"drawing on {len(analysis.sources)} academic sources. "
                f"We identified {len(analysis.findings)} findings and "
                f"{len(analysis.concepts)} concepts with {analysis.confidence.value} confidence. "
                f"Future work should address the identified research gaps "
                f"and expand the scope of analysis."
            ),
        })

        return sections

    def _generate_abstract(self, analysis: AnalysisResult) -> str:
        return (
            f"This article presents a comprehensive analysis of '{analysis.topic}' "
            f"based on a systematic review of {len(analysis.sources)} academic sources. "
            f"Through concept extraction and relationship analysis, we identified "
            f"{len(analysis.concepts)} key concepts and {len(analysis.findings)} significant findings. "
            f"The analysis reveals {len(analysis.relationships)} meaningful relationships "
            f"between concepts, with an overall confidence level of "
            f"'{analysis.confidence.value}'. "
            f"Our findings highlight {len(analysis.trends)} emerging trends "
            f"and identify {len(analysis.gaps)} critical research gaps "
            f"that warrant further investigation. This work provides a structured "
            f"foundation for future research in {analysis.topic}."
        )

    def _build_figures(self, analysis: AnalysisResult) -> List[Dict[str, Any]]:
        figures = []
        if analysis.concepts:
            figures.append({
                "id": f"fig-{uuid.uuid4().hex[:8]}",
                "type": "concept_distribution",
                "caption": f"Distribution of {len(analysis.concepts)} extracted concepts "
                           f"across categories in {analysis.topic}",
                "data": {
                    "labels": [c.name[:25] for c in analysis.concepts[:10]],
                    "values": [len(c.source_ids) + 1 for c in analysis.concepts[:10]],
                },
            })
        if analysis.relationships:
            figures.append({
                "id": f"fig-{uuid.uuid4().hex[:8]}",
                "type": "relationship_graph",
                "caption": f"Concept relationship graph showing {len(analysis.relationships)} "
                           f"connections between {len(set(r.source_concept_id for r in analysis.relationships) | set(r.target_concept_id for r in analysis.relationships))} concepts",
                "data": {
                    "nodes": len(set(
                        r.source_concept_id for r in analysis.relationships
                    ) | set(r.target_concept_id for r in analysis.relationships)),
                    "edges": len(analysis.relationships),
                },
            })
        return figures

    def _build_tables(self, analysis: AnalysisResult) -> List[Dict[str, Any]]:
        tables = []
        if analysis.sources:
            headers = ["Title", "Authors", "Year", "Type"]
            rows = []
            for s in sorted(analysis.sources, key=lambda x: x.published or "", reverse=True)[:10]:
                year = s.published[:4] if s.published else "N/A"
                authors = s.authors[0] if s.authors else "N/A"
                rows.append([s.title[:50], authors, year, s.source_type.value])
            tables.append({
                "caption": f"Summary of {len(analysis.sources)} sources analyzed",
                "headers": headers,
                "rows": rows,
            })
        if analysis.findings:
            headers = ["Finding", "Confidence", "Tags"]
            rows = []
            for f in analysis.findings[:10]:
                rows.append([f.claim[:60], f.confidence.value, ", ".join(f.tags[:3])])
            tables.append({
                "caption": f"Key findings ({len(analysis.findings)} total)",
                "headers": headers,
                "rows": rows,
            })
        return tables

    def _mint_doi(self, article: ScientificArticle) -> str:
        ts = datetime.now().strftime("%Y%m%d%H%M%S")
        return f"10.5281/zenodo.{article.id.split('-')[-1]}.{ts}"

    def _save_article(self, article: ScientificArticle) -> None:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        base = self._output_dir / f"article_{article.id}_{ts}"

        for fmt, ext, content_fn in [
            ("markdown", ".md", article.to_markdown),
            (article.format.value, ".tex", lambda: article.to_latex()),
            ("json", ".json", lambda: article.model_dump_json(indent=2)),
            ("bibtex", ".bib", lambda: self.export_bibtex(article.id)),
        ]:
            path = base.with_suffix(ext)
            path.write_text(content_fn(), encoding="utf-8")
            logger.info("Saved article: %s", path.name)
