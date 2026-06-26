"""
Decentralized AI Agent — Hugging Face Spaces FastAPI backend.
Self-contained: static dashboard, publication/knowledge APIs, telemetry, chat.
"""
import os, time, json, logging, uuid, sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional
from enum import Enum

import httpx
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(message)s")
logger = logging.getLogger("hf_app")

BASE = Path(__file__).parent.resolve()
STATIC = BASE / "static"
LOG_DIR = BASE / "agent_logs"
DATA_DIR = BASE / "agent_data"
DATA_DIR.mkdir(parents=True, exist_ok=True)
LOG_DIR.mkdir(parents=True, exist_ok=True)

app = FastAPI(title="Decentralized AI Agent", version="1.0.0")
http = httpx.Client(timeout=5.0)

# ─── Static Dashboard ─────────────────────────────────────────────────

if STATIC.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC)), name="static")
    @app.get("/")
    async def root():
        index = STATIC / "index.html"
        if index.exists():
            return FileResponse(str(index))
        return {"status": "ok", "message": "Decentralized AI Agent running"}
else:
    @app.get("/")
    async def root():
        return {"status": "ok", "message": "Decentralized AI Agent running"}

# ─── Health & Status ─────────────────────────────────────────────────

@app.get("/api/health")
async def health():
    return {"status": "healthy", "service": "decentralized-ai-agent", "version": "1.0.0", "uptime": time.time()}

# ─── Publication Pipeline ────────────────────────────────────────────

PUBLICATIONS_DIR = BASE / "publications"
PUBLICATIONS_DIR.mkdir(exist_ok=True)
INDEX_PATH = PUBLICATIONS_DIR / "index.json"

def _load_index() -> Dict[str, Any]:
    if INDEX_PATH.exists():
        try: return json.loads(INDEX_PATH.read_text(encoding="utf-8"))
        except: return {}
    return {}

def _save_index(idx: Dict[str, Any]):
    INDEX_PATH.write_text(json.dumps(idx, indent=2, default=str), encoding="utf-8")

@app.get("/api/publication/status")
async def pub_status():
    idx = _load_index()
    return {
        "total_publications": len(idx),
        "published": sum(1 for r in idx.values() if r.get("status") == "published"),
        "drafts": sum(1 for r in idx.values() if r.get("status") == "draft"),
    }

@app.get("/api/publication/list")
async def pub_list(status: Optional[str] = None, topic: Optional[str] = None, limit: int = 50):
    idx = _load_index()
    results = []
    for r in idx.values():
        if status and r.get("status") != status: continue
        if topic and topic.lower() not in r.get("source_topic", "").lower(): continue
        results.append(r)
    results.sort(key=lambda r: r.get("created_at", ""), reverse=True)
    return {"publications": results[:limit]}

@app.get("/api/publication/search")
async def pub_search(q: str = Query(..., min_length=1)):
    idx = _load_index()
    ql = q.lower()
    results = [r for r in idx.values() if ql in json.dumps(r).lower()]
    return {"results": results}

@app.get("/api/publication/{pub_id}")
async def pub_get(pub_id: str):
    idx = _load_index()
    pub = idx.get(pub_id)
    if not pub: raise HTTPException(404, "Publication not found")
    return pub

@app.post("/api/publication/{pub_id}/publish")
async def pub_publish(pub_id: str):
    idx = _load_index()
    if pub_id not in idx: raise HTTPException(404, "Publication not found")
    idx[pub_id]["status"] = "published"
    idx[pub_id]["published_at"] = datetime.now(timezone.utc).isoformat()
    _save_index(idx)
    return {"status": "published", "publication_id": pub_id}

@app.post("/api/publication/{pub_id}/archive")
async def pub_archive(pub_id: str):
    idx = _load_index()
    if pub_id not in idx: raise HTTPException(404, "Publication not found")
    idx[pub_id]["status"] = "archived"
    _save_index(idx)
    return {"status": "archived", "publication_id": pub_id}

@app.get("/api/publication/stats/site")
async def pub_site_stats():
    idx = _load_index()
    topics = {}
    for r in idx.values():
        t = r.get("source_topic", "unknown")
        topics[t] = topics.get(t, 0) + 1
    recent = sorted(idx.values(), key=lambda r: r.get("created_at", ""), reverse=True)[:10]
    return {
        "total_publications": len(idx),
        "published": sum(1 for r in idx.values() if r.get("status") == "published"),
        "drafts": sum(1 for r in idx.values() if r.get("status") == "draft"),
        "topics": topics,
        "recent": [{"id": r["id"], "title": r.get("title",""), "topic": r.get("source_topic",""), "status": r.get("status",""), "created_at": r.get("created_at","")} for r in recent],
    }

# ─── Knowledge System ────────────────────────────────────────────────

DB_PATH = str(DATA_DIR / "knowledge.db")

def _get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS concepts (
            id TEXT PRIMARY KEY, name TEXT NOT NULL, description TEXT DEFAULT '',
            category TEXT DEFAULT 'general', confidence TEXT DEFAULT 'medium',
            created_at TEXT NOT NULL, aliases TEXT DEFAULT '[]',
            UNIQUE(name, category)
        );
        CREATE TABLE IF NOT EXISTS relationships (
            id TEXT PRIMARY KEY, source_concept_id TEXT NOT NULL,
            target_concept_id TEXT NOT NULL, relation_type TEXT DEFAULT 'related_to',
            weight REAL DEFAULT 1.0, evidence TEXT DEFAULT '',
            confidence TEXT DEFAULT 'medium', created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS research_archive (
            id TEXT PRIMARY KEY, report_id TEXT, topic TEXT NOT NULL,
            title TEXT, content TEXT NOT NULL, content_type TEXT DEFAULT 'report',
            tags TEXT DEFAULT '[]', word_count INTEGER DEFAULT 0,
            quality_score REAL DEFAULT 0.0, created_at TEXT NOT NULL,
            source_count INTEGER DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS discovery_log (
            id TEXT PRIMARY KEY, source_type TEXT NOT NULL, source_id TEXT,
            topic TEXT NOT NULL, summary TEXT NOT NULL,
            findings_count INTEGER DEFAULT 0, concepts_found INTEGER DEFAULT 0,
            created_at TEXT NOT NULL, metadata TEXT DEFAULT '{}'
        );
    """)
    conn.commit()
    return conn

@app.get("/api/knowledge/stats")
async def know_stats():
    conn = _get_db()
    try:
        arch = dict(conn.execute("SELECT COUNT(*) as total, SUM(word_count) as total_words, AVG(quality_score) as avg_quality, COUNT(DISTINCT topic) as unique_topics FROM research_archive").fetchone())
        discoveries = dict(conn.execute("SELECT COUNT(*) as total, SUM(findings_count) as total_findings, SUM(concepts_found) as total_concepts FROM discovery_log").fetchone())
        concepts = conn.execute("SELECT COUNT(*) as c FROM concepts").fetchone()["c"]
        relationships = conn.execute("SELECT COUNT(*) as c FROM relationships").fetchone()["c"]
        return {**arch, "discoveries": discoveries, "knowledge_graph": {"concept_count": concepts, "relationship_count": relationships}}
    finally: conn.close()

@app.get("/api/knowledge/graph/stats")
async def know_graph_stats():
    conn = _get_db()
    try:
        concepts = conn.execute("SELECT COUNT(*) as c FROM concepts").fetchone()["c"]
        relationships = conn.execute("SELECT COUNT(*) as c FROM relationships").fetchone()["c"]
        cats = dict(conn.execute("SELECT category, COUNT(*) FROM concepts GROUP BY category").fetchall())
        return {"concept_count": concepts, "relationship_count": relationships, "categories": cats}
    finally: conn.close()

@app.get("/api/knowledge/graph/concept/{concept_name}")
async def know_concept(concept_name: str, depth: int = 2):
    conn = _get_db()
    try:
        c = conn.execute("SELECT id FROM concepts WHERE name = ?", (concept_name,)).fetchone()
        if not c: return {"concept": concept_name, "related": [], "count": 0}
        rows = conn.execute("""
            SELECT c.name, c.category, r.relation_type, r.weight
            FROM relationships r JOIN concepts c ON c.id =
                CASE WHEN r.source_concept_id = ? THEN r.target_concept_id ELSE r.source_concept_id END
            WHERE r.source_concept_id = ? OR r.target_concept_id = ?
        """, (c["id"], c["id"], c["id"])).fetchall()
        return {"concept": concept_name, "related": [dict(r) for r in rows], "count": len(rows)}
    finally: conn.close()

@app.get("/api/knowledge/archive/search")
async def know_search(q: str = Query(..., min_length=1), limit: int = 20):
    conn = _get_db()
    try:
        like = f"%{q}%"
        rows = conn.execute("SELECT id, topic, title, content_type, word_count, quality_score, created_at, tags FROM research_archive WHERE topic LIKE ? OR title LIKE ? OR tags LIKE ? ORDER BY quality_score DESC, created_at DESC LIMIT ?", (like, like, like, limit)).fetchall()
        return {"results": [dict(r) for r in rows], "count": len(rows)}
    finally: conn.close()

@app.get("/api/knowledge/archive/timeline")
async def know_timeline(topic: Optional[str] = None):
    conn = _get_db()
    try:
        if topic: rows = conn.execute("SELECT id, report_id, topic, title, word_count, quality_score, created_at FROM research_archive WHERE topic = ? ORDER BY created_at ASC", (topic,)).fetchall()
        else: rows = conn.execute("SELECT id, report_id, topic, title, word_count, quality_score, created_at FROM research_archive ORDER BY created_at ASC").fetchall()
        return {"timeline": [dict(r) for r in rows], "count": len(rows)}
    finally: conn.close()

@app.get("/api/knowledge/archive/discoveries")
async def know_discoveries():
    conn = _get_db()
    try:
        rows = conn.execute("SELECT id, topic, summary, findings_count, concepts_found, created_at FROM discovery_log ORDER BY created_at ASC").fetchall()
        return {"discoveries": [dict(r) for r in rows], "count": len(rows)}
    finally: conn.close()

@app.get("/api/knowledge/archive/topics")
async def know_topics():
    conn = _get_db()
    try:
        rows = conn.execute("SELECT topic, COUNT(*) as report_count, MAX(quality_score) as max_quality, SUM(word_count) as total_words, MIN(created_at) as first_seen, MAX(created_at) as last_updated FROM research_archive GROUP BY topic ORDER BY last_updated DESC").fetchall()
        return {"topics": [dict(r) for r in rows], "count": len(rows)}
    finally: conn.close()

@app.get("/api/knowledge/graph/export")
async def know_export():
    conn = _get_db()
    try:
        concepts = [dict(r) for r in conn.execute("SELECT id, name, description, category, confidence FROM concepts").fetchall()]
        relationships = [dict(r) for r in conn.execute("SELECT id, source_concept_id, target_concept_id, relation_type, weight FROM relationships").fetchall()]
        return {"concepts": concepts, "relationships": relationships}
    finally: conn.close()

# ─── Legacy HF Endpoints ─────────────────────────────────────────────

@app.get("/api/status")
async def api_status():
    return {"snr_db": 0, "cycle": 0, "gate_db": 0, "window_exp": 0, "node": "hf-space", "timestamp": time.time(), "version": "1.0.0"}

@app.get("/api/telemetry")
async def api_telemetry():
    return {"cycle": 0, "telemetry": {"fft": {}}, "node_id": "hf-space"}

@app.get("/api/handshake/log")
async def api_handshake_log(lines: int = Query(50, ge=1, le=500)):
    log_path = LOG_DIR / "handshake_triggers.log"
    if not log_path.exists(): return {"entries": []}
    try:
        with open(log_path) as f: all_lines = f.readlines()
        return {"entries": [l.strip() for l in all_lines[-lines:]], "total": len(all_lines)}
    except Exception as e: return {"error": str(e), "entries": []}

HERMES_URL = os.environ.get("HERMES_URL", "http://localhost:11434")
HERMES_MODEL = os.environ.get("HERMES_MODEL", "QyrouNnet/summarizer:400m")

@app.post("/api/chat")
async def api_chat(data: dict):
    prompt = data.get("prompt", "")
    if not prompt: raise HTTPException(400, "no prompt")
    try:
        r = http.post(f"{HERMES_URL}/api/generate", json={"model": HERMES_MODEL, "prompt": prompt, "stream": False}, timeout=10)
        if r.status_code == 200: return {"reply": r.json().get("response", ""), "model": HERMES_MODEL, "provider": "ollama"}
    except: pass
    return {"reply": f"[AI offline] Received: '{prompt[:200]}'", "model": "offline", "provider": "fallback"}


if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", "7860"))
    uvicorn.run(app, host="0.0.0.0", port=port)
