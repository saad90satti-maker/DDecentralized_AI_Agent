from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class SourceType(str, Enum):
    arxiv = "arxiv"
    web = "web"
    academic = "academic"
    patent = "patent"
    news = "news"
    github = "github"
    rss = "rss"
    user_submitted = "user_submitted"


class Confidence(str, Enum):
    high = "high"
    medium = "medium"
    low = "low"
    unverified = "unverified"


class ResearchSource(BaseModel):
    id: str = Field(default_factory=lambda: f"src-{uuid.uuid4().hex[:8]}")
    title: str
    url: str
    source_type: SourceType = SourceType.web
    authors: List[str] = []
    published: Optional[str] = None
    publisher: Optional[str] = None
    doi: Optional[str] = None
    abstract: Optional[str] = None
    pdf_url: Optional[str] = None
    citation_count: int = 0
    keywords: List[str] = []
    collected_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )


class Citation(BaseModel):
    id: str = Field(default_factory=lambda: f"cit-{uuid.uuid4().hex[:8]}")
    source_id: str
    title: str
    authors: List[str] = []
    year: Optional[int] = None
    journal: Optional[str] = None
    doi: Optional[str] = None
    url: Optional[str] = None
    formatted: Optional[str] = None

    def format_apa(self) -> str:
        author_str = ", ".join(self.authors) if self.authors else "Unknown"
        year_str = f"({self.year})" if self.year else "(n.d.)"
        title_str = self.title
        journal_str = f"*{self.journal}*." if self.journal else ""
        doi_str = f"https://doi.org/{self.doi}" if self.doi else ""
        parts = [a for a in [author_str, year_str, title_str, journal_str, doi_str] if a]
        return " ".join(parts)

    def format_bibtex(self) -> str:
        key = f"{self.authors[0].split()[-1].lower() if self.authors else 'unknown'}{self.year or 'nd'}"
        lines = [f"@article{{{key},", f"  title = {{{self.title}}},"]
        if self.authors:
            lines.append(f"  author = {{{' and '.join(self.authors)}}},")
        if self.year:
            lines.append(f"  year = {{{self.year}}},")
        if self.journal:
            lines.append(f"  journal = {{{self.journal}}},")
        if self.doi:
            lines.append(f"  doi = {{{self.doi}}},")
        lines.append("}")
        return "\n".join(lines)


class ResearchFinding(BaseModel):
    id: str = Field(default_factory=lambda: f"find-{uuid.uuid4().hex[:8]}")
    claim: str
    evidence: str
    source_ids: List[str] = []
    confidence: Confidence = Confidence.medium
    tags: List[str] = []
    extracted_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )


class Concept(BaseModel):
    id: str = Field(default_factory=lambda: f"concept-{uuid.uuid4().hex[:8]}")
    name: str
    description: str = ""
    aliases: List[str] = []
    category: str = "general"
    source_ids: List[str] = []
    confidence: Confidence = Confidence.medium
    created_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )


class Relationship(BaseModel):
    id: str = Field(default_factory=lambda: f"rel-{uuid.uuid4().hex[:8]}")
    source_concept_id: str
    target_concept_id: str
    relation_type: str = "related_to"
    weight: float = 1.0
    evidence: str = ""
    source_ids: List[str] = []
    confidence: Confidence = Confidence.medium


class ResearchTopic(BaseModel):
    id: str = Field(default_factory=lambda: f"topic-{uuid.uuid4().hex[:8]}")
    name: str
    description: str = ""
    keywords: List[str] = []
    parent_topic_id: Optional[str] = None
    sub_topics: List[str] = []
    source_ids: List[str] = []
    created_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )


class AnalysisResult(BaseModel):
    id: str = Field(default_factory=lambda: f"analysis-{uuid.uuid4().hex[:8]}")
    topic: str
    summary: str
    findings: List[ResearchFinding] = []
    concepts: List[Concept] = []
    relationships: List[Relationship] = []
    sources: List[ResearchSource] = []
    citations: List[Citation] = []
    trends: List[str] = []
    gaps: List[str] = []
    confidence: Confidence = Confidence.medium
    generated_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )


class ResearchReport(BaseModel):
    id: str = Field(default_factory=lambda: f"report-{uuid.uuid4().hex[:8]}")
    title: str
    topic: str
    abstract: str = ""
    sections: List[Dict[str, Any]] = []
    findings: List[ResearchFinding] = []
    concepts: List[Concept] = []
    relationships: List[Relationship] = []
    sources: List[ResearchSource] = []
    citations: List[Citation] = []
    figures: List[Dict[str, Any]] = []
    tags: List[str] = []
    quality_score: float = 0.0
    created_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    def word_count(self) -> int:
        text = self.abstract + " " + " ".join(
            s.get("content", "") for s in self.sections
        )
        return len(text.split())

    def to_markdown(self, include_citations: bool = True) -> str:
        lines = [f"# {self.title}", "", self.abstract, ""]
        for section in self.sections:
            lines.append(f"## {section.get('heading', '')}")
            lines.append("")
            lines.append(section.get("content", ""))
            lines.append("")
        if include_citations and self.citations:
            lines.append("## References")
            lines.append("")
            for i, cit in enumerate(self.citations, 1):
                lines.append(f"[{i}] {cit.format_apa()}")
                lines.append("")
        return "\n".join(lines)

    def to_latex(self) -> str:
        lines = [
            r"\documentclass[11pt,a4paper]{article}",
            r"\usepackage[utf8]{inputenc}",
            r"\usepackage{amsmath,amssymb}",
            r"\usepackage{hyperref}",
            r"\usepackage{geometry}",
            r"\geometry{margin=1in}",
            "",
            r"\title{" + self.title.replace("&", r"\&") + "}",
            r"\date{" + self.created_at[:10] + "}",
            r"\begin{document}",
            r"\maketitle",
            "",
            self.abstract,
            "",
        ]
        for section in self.sections:
            heading = section.get("heading", "")
            content = section.get("content", "")
            lines.append(r"\section{" + heading.replace("&", r"\&") + "}")
            lines.append("")
            lines.append(self._latex_escape(content))
            lines.append("")
        if self.citations:
            lines.append(r"\begin{thebibliography}{99}")
            for i, cit in enumerate(self.citations, 1):
                lines.append(r"\bibitem{" + cit.id + "} " + cit.format_apa())
            lines.append(r"\end{thebibliography}")
        lines.append(r"\end{document}")
        return "\n".join(lines)

    def _latex_escape(self, text: str) -> str:
        return (text.replace("&", r"\&").replace("%", r"\%")
                    .replace("$", r"\$").replace("#", r"\#")
                    .replace("_", r"\_").replace("{", r"\{")
                    .replace("}", r"\}"))
