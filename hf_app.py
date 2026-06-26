"""
Ghost-Orbital HF — Hugging Face Spaces FastAPI backend.

Serves:
  - Telemetry proxy (from ghost-core on :7861)
  - Handshake log viewer
  - Fleet command relay
  - DSP tuning controls
  - LLM Chat (Hermes/Ollama bridge)
  - Static SPA dashboard
"""
import os
import json
import time
import httpx
from pathlib import Path
from fastapi import FastAPI, Query
from fastapi.responses import JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles

BASE = Path(__file__).parent.resolve()
STATIC = BASE / "hf_static"
LOG_DIR = BASE / "agent_logs"

GHOST_CORE_URL = os.environ.get("GHOST_CORE_URL", "http://localhost:7861")
FLASK_UPGRADE_URL = os.environ.get("FLASK_UPGRADE_URL", "http://localhost:8080")
SWARM_SECRET = os.environ.get("SWARM_SECRET", "ghost-default-secret")

app = FastAPI(title="Ghost-Orbital HF", version="1.0.0")
http = httpx.Client(timeout=5.0)


# ── Static SPA ────────────────────────────────────────────────────────

if STATIC.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC)), name="static")

    @app.get("/")
    async def root():
        return FileResponse(str(STATIC / "index.html"))
else:
    @app.get("/")
    async def root():
        return {"status": "ok", "message": "Ghost-Orbital HF running"}


# ── Telemetry proxy ───────────────────────────────────────────────────

@app.get("/api/telemetry")
async def api_telemetry():
    """Proxy live telemetry from ghost-core DSP engine."""
    try:
        r = http.get(f"{GHOST_CORE_URL}/telemetry", timeout=4)
        if r.status_code == 200:
            return r.json()
    except Exception:
        pass
    return {"error": "ghost-core unreachable", "cycle": 0, "telemetry": {"fft": {}}}


# ── Handshake log viewer ──────────────────────────────────────────────

@app.get("/api/handshake/log")
async def api_handshake_log(lines: int = Query(50, ge=1, le=500)):
    """Return last N lines of handshake triggers log."""
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
    """Push DSP tuning params to ghost-core /tune endpoint."""
    params = {"target_snr_db": target_snr, "gate_threshold_db": gate, "window_exp": window}
    try:
        r = http.post(f"{GHOST_CORE_URL}/tune", json=params, timeout=4)
        if r.status_code == 200:
            return {"tuned": True, **params}
    except Exception:
        pass
    # Fallback: return anyway
    return {"tuned": False, "error": "ghost-core unreachable", **params}


# ── Fleet command ─────────────────────────────────────────────────────

@app.post("/api/fleet/command")
async def api_fleet_command(data: dict):
    """Relay a signed command to the global fleet via upgrade agent."""
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


# ── LLM Chat (Hermes/Ollama bridge) ───────────────────────────────────

HERMES_URL = os.environ.get("HERMES_URL", "http://localhost:11434")
HERMES_MODEL = os.environ.get("HERMES_MODEL", "QyrouNnet/summarizer:400m")


@app.post("/api/chat")
async def api_chat(data: dict):
    """Chat with Hermes/Ollama LLM. Falls back to echo if unreachable."""
    prompt = data.get("prompt", "")
    if not prompt:
        return JSONResponse({"error": "no prompt"}, status_code=400)

    system = (
        "You are Ghost-Orbital AI, an autonomous decentralized agent. "
        "Answer concisely about DSP, satellite communications, mesh networks, and swarm AI."
    )

    # Try Ollama API
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

    # Try Hermes HTTP bridge
    try:
        bridge_url = f"{GHOST_CORE_URL.replace(':7861', ':11434')}"
        r = http.post(
            f"{bridge_url}/api/generate",
            json={"model": "hermes", "prompt": prompt, "system": system, "stream": False},
            timeout=30,
        )
        if r.status_code == 200:
            return {"reply": r.json().get("response", ""), "model": "hermes", "provider": "bridge"}
    except Exception:
        pass

    # Fallback: echo with analysis hint
    return {
        "reply": f"[Hermes offline] Received: '{prompt[:200]}'. Start Ollama with `ollama serve` and pull hermes model to enable AI chat.",
        "model": "offline",
        "provider": "fallback",
    }


# ── Unified status ────────────────────────────────────────────────────

@app.get("/api/status")
async def api_status():
    """Aggregate status from all subsystems."""
    t = await api_telemetry()
    fft = t.get("telemetry", {}).get("fft", {})
    return {
        "snr_db": fft.get("snr_after_db", 0),
        "cycle": t.get("cycle", 0),
        "gate_db": fft.get("gate_threshold_db", 0),
        "window_exp": fft.get("window_exp", 0),
        "node": t.get("node_id", "unknown"),
        "timestamp": time.time(),
    }


if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", "7860"))
    uvicorn.run(app, host="0.0.0.0", port=port)
