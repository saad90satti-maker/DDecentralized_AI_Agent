from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query

from research_engine.models import ResearchReport
from publication_pipeline import ArticleFormat, PublicationPipeline, PublicationStatus

logger = logging.getLogger("ecosystem.publication_api")

router = APIRouter(prefix="/api/publication", tags=["publication"])

_pipeline: Optional[PublicationPipeline] = None


def init_pipeline(output_dir: str = "publications", archive_dir: str = "archive"):
    global _pipeline
    _pipeline = PublicationPipeline(output_dir=output_dir, archive_dir=archive_dir)
    return _pipeline


def get_pipeline() -> PublicationPipeline:
    if _pipeline is None:
        raise HTTPException(status_code=503, detail="Publication pipeline not initialized")
    return _pipeline


@router.get("/status")
async def publication_status():
    try:
        pipeline = get_pipeline()
        return pipeline.generate_site_data()
    except HTTPException:
        return {"status": "not_initialized", "total_publications": 0}
    except Exception as e:
        logger.error("Publication status error: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/list")
async def list_publications(
    status: Optional[str] = Query(None, description="Filter by status"),
    topic: Optional[str] = Query(None, description="Filter by topic"),
    limit: int = Query(50, ge=1, le=200),
):
    try:
        pipeline = get_pipeline()
        status_enum = PublicationStatus(status) if status else None
        return {"publications": pipeline.list_publications(status=status_enum, topic=topic, limit=limit)}
    except Exception as e:
        logger.error("List publications error: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/search")
async def search_publications(q: str = Query(..., min_length=1)):
    try:
        pipeline = get_pipeline()
        return {"results": pipeline.search_publications(q)}
    except Exception as e:
        logger.error("Search publications error: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{pub_id}")
async def get_publication(pub_id: str):
    try:
        pipeline = get_pipeline()
        pub = pipeline.get_publication(pub_id)
        if not pub:
            raise HTTPException(status_code=404, detail="Publication not found")
        return pub
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Get publication error: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/{pub_id}/publish")
async def publish_publication(pub_id: str):
    try:
        pipeline = get_pipeline()
        success = pipeline.publish_publication(pub_id)
        if not success:
            raise HTTPException(status_code=404, detail="Publication not found")
        return {"status": "published", "publication_id": pub_id, "published_at": pipeline.get_publication(pub_id).get("published_at")}
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Publish publication error: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/{pub_id}/archive")
async def archive_publication(pub_id: str):
    try:
        pipeline = get_pipeline()
        success = pipeline.archive_publication(pub_id)
        if not success:
            raise HTTPException(status_code=404, detail="Publication not found")
        return {"status": "archived", "publication_id": pub_id}
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Archive publication error: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{pub_id}/versions")
async def get_versions(pub_id: str):
    try:
        pipeline = get_pipeline()
        pub = pipeline.get_publication(pub_id)
        if not pub:
            raise HTTPException(status_code=404, detail="Publication not found")
        topic = pub.get("source_topic", "")
        versions = pipeline.get_version_history(topic)
        return {"versions": versions}
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Get versions error: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/stats/site")
async def site_stats():
    try:
        pipeline = get_pipeline()
        return pipeline.generate_site_data()
    except Exception:
        return {"total_publications": 0, "status": "unavailable"}
