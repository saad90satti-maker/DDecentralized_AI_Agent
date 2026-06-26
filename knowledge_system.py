from __future__ import annotations

import json
import logging
import sqlite3
import uuid
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

from research_engine.models import AnalysisResult, Concept, Relationship, ResearchReport, ResearchSource

logger = logging.getLogger("knowledge.system")


class KnowledgeGraph:
    """Weighted directed graph of concept relationships with persistent SQLite storage."""

    def __init__(self, db_path: str = "agent_data/knowledge.db"):
        self._db_path = Path(db_path)
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn: Optional[sqlite3.Connection] = None

    def connect(self):
        self._conn = sqlite3.connect(str(self._db_path))
        self._conn.row_factory = sqlite3.Row
        self._init_db()

    def close(self):
        if self._conn:
            self._conn.close()
            self._conn = None

    def _init_db(self):
        self._conn.executescript("""
            PRAGMA journal_mode=WAL;
            PRAGMA synchronous=NORMAL;

            CREATE TABLE IF NOT EXISTS concepts (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                description TEXT DEFAULT '',
                category TEXT DEFAULT 'general',
                confidence TEXT DEFAULT 'medium',
                created_at TEXT NOT NULL,
                aliases TEXT DEFAULT '[]',
                UNIQUE(name, category)
            );

            CREATE TABLE IF NOT EXISTS relationships (
                id TEXT PRIMARY KEY,
                source_concept_id TEXT NOT NULL,
                target_concept_id TEXT NOT NULL,
                relation_type TEXT DEFAULT 'related_to',
                weight REAL DEFAULT 1.0,
                evidence TEXT DEFAULT '',
                confidence TEXT DEFAULT 'medium',
                created_at TEXT NOT NULL,
                FOREIGN KEY(source_concept_id) REFERENCES concepts(id),
                FOREIGN KEY(target_concept_id) REFERENCES concepts(id)
            );

            CREATE INDEX IF NOT EXISTS idx_rel_source ON relationships(source_concept_id);
            CREATE INDEX IF NOT EXISTS idx_rel_target ON relationships(target_concept_id);
            CREATE INDEX IF NOT EXISTS idx_rel_type ON relationships(relation_type);

            CREATE TABLE IF NOT EXISTS discovery_log (
                id TEXT PRIMARY KEY,
                source_type TEXT NOT NULL,
                source_id TEXT,
                topic TEXT NOT NULL,
                summary TEXT NOT NULL,
                findings_count INTEGER DEFAULT 0,
                concepts_found INTEGER DEFAULT 0,
                created_at TEXT NOT NULL,
                metadata TEXT DEFAULT '{}'
            );

            CREATE TABLE IF NOT EXISTS research_archive (
                id TEXT PRIMARY KEY,
                report_id TEXT,
                topic TEXT NOT NULL,
                title TEXT,
                content TEXT NOT NULL,
                content_type TEXT DEFAULT 'report',
                tags TEXT DEFAULT '[]',
                word_count INTEGER DEFAULT 0,
                quality_score REAL DEFAULT 0.0,
                created_at TEXT NOT NULL,
                source_count INTEGER DEFAULT 0
            );

            CREATE INDEX IF NOT EXISTS idx_archive_topic ON research_archive(topic);
            CREATE INDEX IF NOT EXISTS idx_archive_created ON research_archive(created_at);
            CREATE INDEX IF NOT EXISTS idx_discovery_topic ON discovery_log(topic);
        """)
        self._conn.commit()

    def add_concept(self, concept: Concept) -> str:
        self.connect()
        try:
            existing = self._conn.execute(
                "SELECT id FROM concepts WHERE name = ? AND category = ?",
                (concept.name, concept.category),
            ).fetchone()
            if existing:
                return existing["id"]
            self._conn.execute(
                "INSERT INTO concepts (id, name, description, category, confidence, created_at, aliases) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    concept.id, concept.name, concept.description,
                    concept.category, concept.confidence.value, concept.created_at,
                    json.dumps(concept.aliases),
                ),
            )
            self._conn.commit()
            return concept.id
        finally:
            self.close()

    def add_relationship(self, rel: Relationship) -> str:
        self.connect()
        try:
            existing = self._conn.execute(
                "SELECT id FROM relationships WHERE source_concept_id = ? "
                "AND target_concept_id = ? AND relation_type = ?",
                (rel.source_concept_id, rel.target_concept_id, rel.relation_type),
            ).fetchone()
            if existing:
                self._conn.execute(
                    "UPDATE relationships SET weight = weight + ? WHERE id = ?",
                    (rel.weight, existing["id"]),
                )
                return existing["id"]
            rel_id = rel.id
            self._conn.execute(
                "INSERT INTO relationships (id, source_concept_id, target_concept_id, "
                "relation_type, weight, evidence, confidence, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    rel_id, rel.source_concept_id, rel.target_concept_id,
                    rel.relation_type, rel.weight, rel.evidence,
                    rel.confidence.value,
                    datetime.now(timezone.utc).isoformat(),
                ),
            )
            self._conn.commit()
            return rel_id
        finally:
            self.close()

    def bulk_add_from_analysis(self, analysis: AnalysisResult):
        self.connect()
        try:
            concept_map = {}
            for concept in analysis.concepts:
                cid = self.add_concept(concept)
                concept_map[concept.id] = cid

            for rel in analysis.relationships:
                if rel.source_concept_id in concept_map and rel.target_concept_id in concept_map:
                    self.add_relationship(rel)

            self._conn.commit()
            logger.info(
                "Added %d concepts and %d relationships to knowledge graph",
                len(analysis.concepts),
                len(analysis.relationships),
            )
        finally:
            self.close()

    def get_related_concepts(self, concept_name: str, max_depth: int = 2) -> List[Dict[str, Any]]:
        self.connect()
        try:
            concept = self._conn.execute(
                "SELECT id, name, category FROM concepts WHERE name = ? LIMIT 1",
                (concept_name,),
            ).fetchone()
            if not concept:
                return []

            visited: Set[str] = set()
            results: List[Dict[str, Any]] = []
            queue: List[Tuple[str, int]] = [(concept["id"], 0)]

            while queue:
                cid, depth = queue.pop(0)
                if cid in visited or depth > max_depth:
                    continue
                visited.add(cid)

                rows = self._conn.execute(
                    "SELECT c.name, c.category, r.relation_type, r.weight "
                    "FROM relationships r JOIN concepts c ON c.id = "
                    "CASE WHEN r.source_concept_id = ? THEN r.target_concept_id "
                    "ELSE r.source_concept_id END "
                    "WHERE r.source_concept_id = ? OR r.target_concept_id = ?",
                    (cid, cid, cid),
                ).fetchall()

                for row in rows:
                    results.append({
                        "name": row["name"],
                        "category": row["category"],
                        "relation": row["relation_type"],
                        "weight": row["weight"],
                    })
                    target = self._conn.execute(
                        "SELECT id FROM concepts WHERE name = ?", (row["name"],)
                    ).fetchone()
                    if target:
                        queue.append((target["id"], depth + 1))

            return results
        finally:
            self.close()

    def get_graph_stats(self) -> Dict[str, Any]:
        self.connect()
        try:
            concepts = self._conn.execute("SELECT COUNT(*) as c FROM concepts").fetchone()["c"]
            relationships = self._conn.execute("SELECT COUNT(*) as c FROM relationships").fetchone()["c"]
            categories = dict(self._conn.execute(
                "SELECT category, COUNT(*) FROM concepts GROUP BY category"
            ).fetchall())
            relation_types = dict(self._conn.execute(
                "SELECT relation_type, COUNT(*) FROM relationships GROUP BY relation_type"
            ).fetchall())
            return {
                "concept_count": concepts,
                "relationship_count": relationships,
                "categories": categories,
                "relation_types": relation_types,
            }
        finally:
            self.close()

    def export_graph(self, filepath: str):
        self.connect()
        try:
            concepts = [dict(r) for r in self._conn.execute(
                "SELECT id, name, description, category, confidence, aliases FROM concepts"
            ).fetchall()]
            relationships = [dict(r) for r in self._conn.execute(
                "SELECT id, source_concept_id, target_concept_id, relation_type, weight, evidence FROM relationships"
            ).fetchall()]
            data = {"concepts": concepts, "relationships": relationships}
            Path(filepath).write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")
            logger.info("Knowledge graph exported to %s (%d concepts, %d relationships)", filepath, len(concepts), len(relationships))
        finally:
            self.close()


class ResearchArchive:
    """Persistent archive of all research outputs with search and timeline."""

    def __init__(self, db_path: str = "agent_data/knowledge.db"):
        self._db_path = Path(db_path)
        self._kg = KnowledgeGraph(db_path)

    def archive_report(self, report: ResearchReport):
        self._kg.connect()
        conn = self._kg._conn
        try:
            content = report.to_markdown()
            tags = json.dumps(report.tags)
            conn.execute(
                "INSERT OR REPLACE INTO research_archive "
                "(id, report_id, topic, title, content, content_type, tags, word_count, quality_score, created_at, source_count) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    f"arch-{uuid.uuid4().hex[:8]}",
                    report.id,
                    report.topic,
                    report.title,
                    content,
                    "report",
                    tags,
                    report.word_count(),
                    report.quality_score,
                    report.created_at,
                    len(report.sources),
                ),
            )
            conn.commit()
            logger.info("Archived report '%s' (topic: %s)", report.title, report.topic)
        finally:
            self._kg.close()

    def archive_analysis(self, analysis: AnalysisResult):
        self._kg.connect()
        conn = self._kg._conn
        try:
            conn.execute(
                "INSERT INTO discovery_log "
                "(id, source_type, source_id, topic, summary, findings_count, concepts_found, created_at, metadata) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    f"disc-{uuid.uuid4().hex[:8]}",
                    "analysis",
                    analysis.id,
                    analysis.topic,
                    analysis.summary,
                    len(analysis.findings),
                    len(analysis.concepts),
                    analysis.generated_at,
                    json.dumps({
                        "trends": analysis.trends,
                        "gaps": analysis.gaps,
                        "sources": len(analysis.sources),
                        "confidence": analysis.confidence.value,
                    }),
                ),
            )
            conn.commit()
            logger.info("Archived analysis for topic '%s'", analysis.topic)
        finally:
            self._kg.close()

    def search(self, query: str, limit: int = 20) -> List[Dict[str, Any]]:
        self._kg.connect()
        conn = self._kg._conn
        try:
            like = f"%{query}%"
            rows = conn.execute(
                "SELECT id, topic, title, content_type, word_count, quality_score, "
                "created_at, tags, source_count FROM research_archive "
                "WHERE topic LIKE ? OR title LIKE ? OR content LIKE ? OR tags LIKE ? "
                "ORDER BY quality_score DESC, created_at DESC LIMIT ?",
                (like, like, like, like, limit),
            ).fetchall()
            return [dict(r) for r in rows]
        finally:
            self._kg.close()

    def get_timeline(self, topic: Optional[str] = None) -> List[Dict[str, Any]]:
        self._kg.connect()
        conn = self._kg._conn
        try:
            if topic:
                rows = conn.execute(
                    "SELECT id, report_id, topic, title, content_type, word_count, "
                    "quality_score, created_at FROM research_archive "
                    "WHERE topic = ? ORDER BY created_at ASC",
                    (topic,),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT id, report_id, topic, title, content_type, word_count, "
                    "quality_score, created_at FROM research_archive "
                    "ORDER BY created_at ASC"
                ).fetchall()
            return [dict(r) for r in rows]
        finally:
            self._kg.close()

    def get_discovery_timeline(self) -> List[Dict[str, Any]]:
        self._kg.connect()
        conn = self._kg._conn
        try:
            rows = conn.execute(
                "SELECT id, topic, summary, findings_count, concepts_found, created_at "
                "FROM discovery_log ORDER BY created_at ASC"
            ).fetchall()
            return [dict(r) for r in rows]
        finally:
            self._kg.close()

    def get_topics(self) -> List[Dict[str, Any]]:
        self._kg.connect()
        conn = self._kg._conn
        try:
            rows = conn.execute(
                "SELECT topic, COUNT(*) as report_count, "
                "MAX(quality_score) as max_quality, "
                "SUM(word_count) as total_words, "
                "AVG(source_count) as avg_sources, "
                "MIN(created_at) as first_seen, "
                "MAX(created_at) as last_updated "
                "FROM research_archive GROUP BY topic ORDER BY last_updated DESC"
            ).fetchall()
            return [dict(r) for r in rows]
        finally:
            self._kg.close()

    def get_archive_stats(self) -> Dict[str, Any]:
        self._kg.connect()
        conn = self._kg._conn
        try:
            archives = dict(conn.execute(
                "SELECT COUNT(*) as total, "
                "SUM(word_count) as total_words, "
                "AVG(quality_score) as avg_quality, "
                "COUNT(DISTINCT topic) as unique_topics, "
                "MAX(created_at) as latest "
                "FROM research_archive"
            ).fetchone())
            discoveries = dict(conn.execute(
                "SELECT COUNT(*) as total, SUM(findings_count) as total_findings, "
                "SUM(concepts_found) as total_concepts "
                "FROM discovery_log"
            ).fetchone())
            kg_stats = self._kg.get_graph_stats()
            return {
                **archives,
                "discoveries": discoveries,
                "knowledge_graph": kg_stats,
            }
        finally:
            self._kg.close()


class KnowledgeSystem:
    """Unified knowledge system combining graph, archive, timeline, and discovery."""

    def __init__(self, db_path: str = "agent_data/knowledge.db"):
        self.graph = KnowledgeGraph(db_path)
        self.archive = ResearchArchive(db_path)

    def ingest_analysis(self, analysis: AnalysisResult):
        self.archive.archive_analysis(analysis)
        self.graph.bulk_add_from_analysis(analysis)

    def ingest_report(self, report: ResearchReport):
        self.archive.archive_report(report)

    def ingest_full(self, analysis: AnalysisResult, report: ResearchReport):
        self.ingest_analysis(analysis)
        self.ingest_report(report)

    def export_full_state(self, filepath: str):
        self.graph.export_graph(filepath.replace(".json", "_graph.json"))
        stats = self.archive.get_archive_stats()
        timeline = {
            "research": self.archive.get_timeline(),
            "discoveries": self.archive.get_discovery_timeline(),
        }
        output = {"stats": stats, "timeline": timeline}
        Path(filepath).write_text(json.dumps(output, indent=2, default=str), encoding="utf-8")
        logger.info("Full knowledge state exported to %s", filepath)

    def get_archive_stats(self) -> Dict[str, Any]:
        return self.archive.get_archive_stats()
