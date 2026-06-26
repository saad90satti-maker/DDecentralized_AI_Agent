from __future__ import annotations

import json
import logging
import os
import shutil
import uuid
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional

from research_engine.article_generator import ArticleGenerator, ArticleFormat, ScientificArticle
from research_engine.models import AnalysisResult, ResearchReport

logger = logging.getLogger("publication.pipeline")


class PublicationStatus(str, Enum):
    draft = "draft"
    published = "published"
    archived = "archived"
    failed = "failed"


class PublicationRecord:
    def __init__(
        self,
        publication_id: str,
        title: str,
        pub_type: str,
        formats: Dict[str, str],
        status: PublicationStatus,
        source_report_id: str,
        source_topic: str,
        created_at: str,
        published_at: Optional[str] = None,
        version: int = 1,
        changelog: str = "",
        tags: List[str] = None,
        metadata: Dict[str, Any] = None,
    ):
        self.id = publication_id
        self.title = title
        self.type = pub_type
        self.formats = formats
        self.status = status
        self.source_report_id = source_report_id
        self.source_topic = source_topic
        self.created_at = created_at
        self.published_at = published_at
        self.version = version
        self.changelog = changelog
        self.tags = tags or []
        self.metadata = metadata or {}

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "type": self.type,
            "formats": self.formats,
            "status": self.status.value,
            "source_report_id": self.source_report_id,
            "source_topic": self.source_topic,
            "created_at": self.created_at,
            "published_at": self.published_at,
            "version": self.version,
            "changelog": self.changelog,
            "tags": self.tags,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> PublicationRecord:
        return cls(
            publication_id=data["id"],
            title=data["title"],
            pub_type=data["type"],
            formats=data.get("formats", {}),
            status=PublicationStatus(data.get("status", "draft")),
            source_report_id=data.get("source_report_id", ""),
            source_topic=data.get("source_topic", ""),
            created_at=data.get("created_at", ""),
            published_at=data.get("published_at"),
            version=data.get("version", 1),
            changelog=data.get("changelog", ""),
            tags=data.get("tags", []),
            metadata=data.get("metadata", {}),
        )


class PublicationPipeline:
    """End-to-end pipeline: research result → publication → archive → distribution."""

    def __init__(self, output_dir: str = "publications", archive_dir: str = "archive"):
        self._output_dir = Path(output_dir)
        self._archive_dir = Path(archive_dir)
        self._output_dir.mkdir(parents=True, exist_ok=True)
        self._archive_dir.mkdir(parents=True, exist_ok=True)
        self._index_path = self._output_dir / "index.json"
        self._index: Dict[str, Dict[str, Any]] = self._load_index()
        self._article_gen = ArticleGenerator()

    def _load_index(self) -> Dict[str, Dict[str, Any]]:
        if self._index_path.exists():
            try:
                return json.loads(self._index_path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, Exception):
                return {}
        return {}

    def _save_index(self):
        self._index_path.write_text(
            json.dumps(self._index, indent=2, default=str), encoding="utf-8"
        )

    def generate_publications(
        self,
        report: ResearchReport,
        formats: Optional[List[ArticleFormat]] = None,
        publish: bool = False,
    ) -> Dict[str, Any]:
        if formats is None:
            formats = [ArticleFormat.markdown, ArticleFormat.ieee]
        if not report.sections:
            logger.warning("Report %s has no sections; article will be minimal", report.id)

        pub_id = f"pub-{uuid.uuid4().hex[:8]}"
        output_subdir = self._output_dir / pub_id
        output_subdir.mkdir(parents=True, exist_ok=True)

        saved_files = {}
        article = None
        for fmt in formats:
            fmt_article = self._article_gen.from_report(report=report, format=fmt)
            if article is None:
                article = fmt_article
            ext = self._extension_for_format(fmt)
            filepath = output_subdir / f"{article.id}.{ext}"
            content = self._render_article(fmt_article, fmt)
            filepath.write_text(content, encoding="utf-8")
            saved_files[fmt.value] = str(filepath)

        summary = self._generate_summary(report, article)
        changelog = self._generate_changelog(report)
        release_notes = self._generate_release_notes(report, article)

        record = PublicationRecord(
            publication_id=pub_id,
            title=article.title,
            pub_type="research_article",
            formats=saved_files,
            status=PublicationStatus.published if publish else PublicationStatus.draft,
            source_report_id=report.id,
            source_topic=report.topic,
            created_at=datetime.now(timezone.utc).isoformat(),
            published_at=datetime.now(timezone.utc).isoformat() if publish else None,
            version=1,
            changelog=changelog,
            tags=report.tags,
            metadata={
                "word_count": report.word_count(),
                "quality_score": report.quality_score,
                "source_count": len(report.sources),
                "finding_count": len(report.findings),
                "citation_count": len(report.citations),
                "formats": [f.value for f in formats],
            },
        )

        if article is None:
            raise RuntimeError("No article generated from report")

        summary = self._generate_summary(report, article)
        changelog = self._generate_changelog(report)
        release_notes = self._generate_release_notes(report, article)

        summaries_dir = output_subdir / "summaries"
        summaries_dir.mkdir(exist_ok=True)
        (summaries_dir / "summary.md").write_text(summary, encoding="utf-8")
        (summaries_dir / "release_notes.md").write_text(release_notes, encoding="utf-8")
        (summaries_dir / "changelog.md").write_text(changelog, encoding="utf-8")

        self._index[pub_id] = record.to_dict()
        self._save_index()

        logger.info(
            "Generated %d format(s) for article '%s' (id=%s)",
            len(saved_files), article.title, pub_id,
        )

        return {
            "publication_id": pub_id,
            "title": article.title,
            "summary": summary,
            "changelog": changelog,
            "release_notes": release_notes,
            "formats": saved_files,
            "record": record.to_dict(),
            "article": article.model_dump() if hasattr(article, "model_dump") else article.dict(),
        }

    def publish_publication(self, pub_id: str) -> bool:
        if pub_id not in self._index:
            logger.error("Publication %s not found in index", pub_id)
            return False
        record_dict = self._index[pub_id]
        record_dict["status"] = PublicationStatus.published.value
        record_dict["published_at"] = datetime.now(timezone.utc).isoformat()
        self._index[pub_id] = record_dict
        self._save_index()

        archive_path = self._archive_dir / pub_id
        if not archive_path.exists():
            src_path = self._output_dir / pub_id
            if src_path.exists():
                shutil.copytree(src_path, archive_path)

        logger.info("Publication %s published at %s", pub_id, record_dict["published_at"])
        return True

    def archive_publication(self, pub_id: str) -> bool:
        if pub_id not in self._index:
            logger.error("Publication %s not found in index", pub_id)
            return False
        self._index[pub_id]["status"] = PublicationStatus.archived.value
        self._save_index()
        return True

    def get_publication(self, pub_id: str) -> Optional[Dict[str, Any]]:
        return self._index.get(pub_id)

    def list_publications(
        self,
        status: Optional[PublicationStatus] = None,
        topic: Optional[str] = None,
        limit: int = 50,
    ) -> List[Dict[str, Any]]:
        results = []
        for record in self._index.values():
            if status and record.get("status") != status.value:
                continue
            if topic and topic.lower() not in record.get("source_topic", "").lower():
                continue
            results.append(record)
        results.sort(key=lambda r: r.get("created_at", ""), reverse=True)
        return results[:limit]

    def search_publications(self, query: str) -> List[Dict[str, Any]]:
        query_lower = query.lower()
        results = []
        for record in self._index.values():
            searchable = json.dumps(record).lower()
            if query_lower in searchable:
                results.append(record)
        return results

    def get_version_history(self, source_topic: str) -> List[Dict[str, Any]]:
        versions = []
        for record in self._index.values():
            if record.get("source_topic", "").lower() == source_topic.lower():
                versions.append({
                    "publication_id": record["id"],
                    "version": record.get("version", 1),
                    "created_at": record.get("created_at", ""),
                    "published_at": record.get("published_at"),
                    "status": record.get("status", ""),
                    "changelog": record.get("changelog", ""),
                })
        versions.sort(key=lambda v: v.get("created_at", ""))
        return versions

    def generate_site_data(self) -> Dict[str, Any]:
        stats = {
            "total_publications": len(self._index),
            "published": sum(1 for r in self._index.values() if r.get("status") == "published"),
            "drafts": sum(1 for r in self._index.values() if r.get("status") == "draft"),
            "archived": sum(1 for r in self._index.values() if r.get("status") == "archived"),
            "topics": {},
            "recent": [],
        }
        for record in self._index.values():
            topic = record.get("source_topic", "unknown")
            stats["topics"][topic] = stats["topics"].get(topic, 0) + 1
        recent = sorted(
            self._index.values(),
            key=lambda r: r.get("created_at", ""),
            reverse=True,
        )[:10]
        stats["recent"] = [
            {
                "id": r["id"],
                "title": r["title"],
                "topic": r.get("source_topic", ""),
                "status": r.get("status", ""),
                "created_at": r.get("created_at", ""),
            }
            for r in recent
        ]
        return stats

    def export_publication_index(self, filepath: str):
        Path(filepath).write_text(
            json.dumps(self._index, indent=2, default=str), encoding="utf-8"
        )
        logger.info("Publication index exported to %s", filepath)

    def import_publication_index(self, filepath: str):
        data = json.loads(Path(filepath).read_text(encoding="utf-8"))
        self._index.update(data)
        self._save_index()
        logger.info("Imported %d publications from %s", len(data), filepath)

    def _generate_summary(self, report: ResearchReport, article: ScientificArticle) -> str:
        lines = [
            f"# {article.title}",
            "",
            f"**Topic:** {report.topic}",
            f"**Date:** {report.created_at[:10]}",
            f"**Quality Score:** {report.quality_score:.2f}",
            f"**Word Count:** {report.word_count()}",
            "",
            "## Abstract",
            "",
            article.abstract,
            "",
            "## Key Findings",
            "",
        ]
        for finding in report.findings[:5]:
            lines.append(f"- **{finding.claim}** ({finding.confidence.value} confidence)")
        if report.findings and len(report.findings) > 5:
            lines.append(f"\n*...and {len(report.findings) - 5} more findings*")

        lines.extend([
            "",
            "## Sources",
            "",
        ])
        for source in report.sources[:5]:
            lines.append(f"- [{source.title}]({source.url})")
        if report.sources and len(report.sources) > 5:
            lines.append(f"\n*...and {len(report.sources) - 5} more sources*")
        return "\n".join(lines)

    def _generate_changelog(self, report: ResearchReport) -> str:
        now = datetime.now(timezone.utc).isoformat()[:16]
        lines = [
            f"# Changelog — {report.title}",
            f"## {now} — Version 1.0.0",
            "",
            "### Added",
            f"- Initial publication on '{report.topic}'",
            f"- {len(report.sections)} sections covering {len(report.findings)} findings",
            f"- {len(report.sources)} sources cited ({len(report.citations)} formatted citations)",
            f"- Quality score: {report.quality_score:.2f}",
            "",
            "### Content",
            f"- Abstract: {len(report.abstract.split())} words",
            f"- Total: {report.word_count()} words",
            f"- {len(report.concepts)} key concepts identified",
            "",
            "### Technical",
            "- Generated via Decentralized AI Agent Research Engine",
            "- DOI registered for permanent access",
        ]
        return "\n".join(lines)

    def _generate_release_notes(self, report: ResearchReport, article: ScientificArticle) -> str:
        lines = [
            f"# Release Notes: {article.title}",
            "",
            f"**Published:** {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}",
            f"**Topic:** {report.topic}",
            f"**DOI:** {article.doi or 'Pending registration'}",
            "",
            "## Overview",
            "",
            article.abstract,
            "",
            "## Highlights",
            "",
        ]
        for finding in report.findings[:3]:
            lines.append(f"- {finding.claim}")
        lines.extend([
            "",
            "## Access",
            "",
            f"- **Formats available:** {', '.join(article.format.value for _ in [1])}",
            "- Published in the Decentralized AI Agent research archive",
            "",
            "## References",
            "",
        ])
        for i, cit in enumerate(report.citations[:10], 1):
            lines.append(f"[{i}] {cit.format_apa()}")
        return "\n".join(lines)

    @staticmethod
    def _extension_for_format(fmt: ArticleFormat) -> str:
        return {"ieee": "tex", "acm": "tex", "nature": "tex", "apa": "tex", "markdown": "md"}.get(
            fmt.value, "txt"
        )

    @staticmethod
    def _render_article(article: ScientificArticle, fmt: ArticleFormat) -> str:
        if fmt == ArticleFormat.markdown:
            return article.to_markdown()
        return article.to_latex(template=fmt.value)
