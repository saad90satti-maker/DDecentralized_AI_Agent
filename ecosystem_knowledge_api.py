from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query

from knowledge_system import KnowledgeGraph, KnowledgeSystem, ResearchArchive

logger = logging.getLogger("ecosystem.knowledge_api")

router = APIRouter(prefix="/api/knowledge", tags=["knowledge"])

_system: Optional[KnowledgeSystem] = None


def init_knowledge(db_path: str = "agent_data/knowledge.db"):
    global _system
    _system = KnowledgeSystem(db_path=db_path)
    return _system


def get_system() -> KnowledgeSystem:
    if _system is None:
        raise HTTPException(status_code=503, detail="Knowledge system not initialized")
    return _system


@router.get("/stats")
async def knowledge_stats():
    try:
        system = get_system()
        return system.get_archive_stats()
    except HTTPException:
        return {"status": "not_initialized"}
    except Exception as e:
        logger.error("Knowledge stats error: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/graph/stats")
async def graph_stats():
    try:
        system = get_system()
        return system.graph.get_graph_stats()
    except HTTPException:
        return {"status": "not_initialized"}
    except Exception as e:
        logger.error("Graph stats error: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/graph/concept/{concept_name}")
async def get_concept(concept_name: str, depth: int = Query(2, ge=1, le=5)):
    try:
        system = get_system()
        related = system.graph.get_related_concepts(concept_name, max_depth=depth)
        return {"concept": concept_name, "related": related, "count": len(related)}
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Get concept error: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/archive/search")
async def search_archive(q: str = Query(..., min_length=1), limit: int = Query(20, ge=1, le=100)):
    try:
        system = get_system()
        results = system.archive.search(q, limit=limit)
        return {"results": results, "count": len(results)}
    except Exception as e:
        logger.error("Archive search error: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/archive/timeline")
async def get_timeline(topic: Optional[str] = Query(None)):
    try:
        system = get_system()
        timeline = system.archive.get_timeline(topic=topic)
        return {"timeline": timeline, "count": len(timeline)}
    except Exception as e:
        logger.error("Timeline error: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/archive/discoveries")
async def get_discoveries():
    try:
        system = get_system()
        timeline = system.archive.get_discovery_timeline()
        return {"discoveries": timeline, "count": len(timeline)}
    except Exception as e:
        logger.error("Discoveries error: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/archive/topics")
async def get_topics():
    try:
        system = get_system()
        topics = system.archive.get_topics()
        return {"topics": topics, "count": len(topics)}
    except Exception as e:
        logger.error("Topics error: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/graph/export")
async def export_graph():
    try:
        system = get_system()
        import tempfile, json
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            system.graph.export_graph(f.name)
            data = json.loads(open(f.name, encoding="utf-8").read())
            import os
            os.unlink(f.name)
        return data
    except Exception as e:
        logger.error("Export graph error: %s", e)
        raise HTTPException(status_code=500, detail=str(e))
