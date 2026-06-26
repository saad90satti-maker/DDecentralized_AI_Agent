"""
Ghost-Orbital HF — Hugging Face Spaces FastAPI backend.
Self-contained: serves dashboard, publication/knowledge APIs, telemetry, chat.
"""
import os
import time
import json
import logging
import httpx
from pathlib import Path
from fastapi import FastAPI, Query
from fastapi.responses import JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(message)s")
logger = logging.getLogger("hf_app")

BASE = Path(__file__).parent.resolve()
STATIC = BASE / "static"
LOG_DIR = BASE / "agent_logs"
LOG_DIR.mkdir(exist_ok=True)

app = FastAPI(title="Decentralized AI Agent", version="1.0.0")
http = httpx.Client(timeout=5.0)

# Try to include publication & knowledge APIs
try:
    from ecosystem_publication_api import router as pub_router
    app.include_router(pub_router)
    logger.info("Publication API router loaded")
except Exception as e:
    logger.warning("Publication API not available: %s", e)

try:
    from ecosystem_knowledge_api import router as know_router
    app.include_router(know_router)
    logger.info("Knowledge API router loaded")
except Exception as e:
    logger.warning("Knowledge API not available: %s", e)

try:
    from ecosystem_publication_api import init_pipeline
    init_pipeline()
    logger.info("Publication pipeline initialized")
except Exception as e:
    logger.warning("Publication pipeline init: %s", e)

try:
    from ecosystem_knowledge_api import init_knowledge
    init_knowledge()
    logger.info("Knowledge system initialized")
except Exception as e:
    logger.warning("Knowledge system init: %s", e)

# ── Static Dashboard ──────────────────────────────────────────────────

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

# ── Health ────────────────────────────────────────────────────────────

@app.get("/api/health")
async def api_health():
    return {"status": "healthy", "service": "decentralized-ai-agent", "version": "1.0.0"}

# ── Telemetry proxy ───────────────────────────────────────────────────

GHOST_CORE_URL = os.environ.get("GHOST_CORE_URL", "http://localhost:7861")

@app.get("/api/telemetry")
async def api_telemetry():
    try:
        r = http.get(f"{GHOST_CORE_URL}/telemetry", timeout=4)
        if r.status_code == 200:
            return r.json()
    except Exception:
        pass
    return {"error": "ghost-core unreachable", "cycle": 0, "telemetry": {"fft": {}}}

# ── Handshake log viewer ──────────────────────────────────────────────

LOG_DIR.mkdir(exist_ok=True)

@app.get("/api/handshake/log")
async def api_handshake_log(lines: int = Query(50, ge=1, le=500)):
    log_path = LOG_DIR / "handshake_triggers.log"
    if not log_path.exists():
        return {"entries": []}
    try:
        with open(log_path) as f:
            all_lines = f.readlines()
        tail = all_lines[-lines:]
        return {"entries": [l.strip() for l in tail], "total": len(all_lines)}
    except Exception as e:
        return {"error": str(e), "entries": []}

# ── DSP tuning ────────────────────────────────────────────────────────

@app.get("/api/dsp/tune")
async def api_dsp_tune(
    target_snr: float = Query(38.0, ge=0, le=100),
    gate: float = Query(13.0, ge=0, le=30),
    window: float = Query(0.9, ge=0.5, le=2.0),
):
    params = {"target_snr_db": target_snr, "gate_threshold_db": gate, "window_exp": window}
    try:
        r = http.post(f"{GHOST_CORE_URL}/tune", json=params, timeout=4)
        if r.status_code == 200:
            return {"tuned": True, **params}
    except Exception:
        pass
    return {"tuned": False, "error": "ghost-core unreachable", **params}

# ── Fleet command ─────────────────────────────────────────────────────

FLASK_UPGRADE_URL = os.environ.get("FLASK_UPGRADE_URL", "http://localhost:8080")

@app.post("/api/fleet/command")
async def api_fleet_command(data: dict):
    cmd = data.get("command", "")
    if not cmd:
        return JSONResponse({"error": "no command"}, status_code=400)
    try:
        r = http.post(f"{FLASK_UPGRADE_URL}/fleet/command", json={"command": cmd}, timeout=5)
        if r.status_code == 200:
            return r.json()
    except Exception:
        pass
    return {"orchestrated": False, "command": cmd, "error": "upgrade agent unreachable"}

# ── LLM Chat ──────────────────────────────────────────────────────────

HERMES_URL = os.environ.get("HERMES_URL", "http://localhost:11434")
HERMES_MODEL = os.environ.get("HERMES_MODEL", "QyrouNnet/summarizer:400m")

@app.post("/api/chat")
async def api_chat(data: dict):
    prompt = data.get("prompt", "")
    if not prompt:
        return JSONResponse({"error": "no prompt"}, status_code=400)
    system = (
        "You are an autonomous decentralized AI agent. "
        "Answer concisely about swarm AI, mesh networks, and decentralized systems."
    )
    try:
        r = http.post(
            f"{HERMES_URL}/api/generate",
            json={"model": HERMES_MODEL, "prompt": prompt, "system": system, "stream": False},
            timeout=30,
        )
        if r.status_code == 200:
            return {"reply": r.json().get("response", ""), "model": HERMES_MODEL, "provider": "ollama"}
    except Exception:
        pass
    return {"reply": f"[AI offline] Received: '{prompt[:200]}'", "model": "offline", "provider": "fallback"}

# ── Status ────────────────────────────────────────────────────────────

@app.get("/api/status")
async def api_status():
    t = await api_telemetry()
    fft = t.get("telemetry", {}).get("fft", {})
    return {
        "snr_db": fft.get("snr_after_db", 0),
        "cycle": t.get("cycle", 0),
        "gate_db": fft.get("gate_threshold_db", 0),
        "window_exp": fft.get("window_exp", 0),
        "node": t.get("node_id", "unknown"),
        "timestamp": time.time(),
        "version": "1.0.0",
    }


if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", "7860"))
    uvicorn.run(app, host="0.0.0.0", port=port)
