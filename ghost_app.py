"""
ghost_app.py - Ghost-Core FastAPI Application.

Decentralised DSP orchestration server with:

  - Background DSP cycle (adaptive FFT targeting 21.17 dB SNR)
  - REST endpoints: /telemetry, /introspect, /reflect, /swarm/status
  - WebSocket: /ws/swarm for P2P node communication
  - Graceful shutdown with resource release()

Run:
    uvicorn ghost_app:app --host 0.0.0.0 --port 7861 --reload
"""

import os
import sys
import json
import time
import asyncio
import logging
from pathlib import Path
from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse
import uvicorn

from ghost_core import GhostCore

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("ghost.app")

# ---------------------------------------------------------------------------
# Global GhostCore instance
# ---------------------------------------------------------------------------

core: GhostCore = None
_background_task: asyncio.Task = None
_ws_connections: list[WebSocket] = []


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Async startup/shutdown with graceful resource release."""
    global core, _background_task

    logger.info("Ghost-Core initialising...")
    core = GhostCore(interval=3.0, target_snr=21.17)

    # Run initial introspection
    try:
        core.introspect()
        logger.info("Library map built: %d packages, %d modules",
                     core.library_map.get("total_packages", 0),
                     core.library_map.get("inspected_modules", 0))
    except Exception as e:
        logger.warning("Introspection failed: %s", e)

    # Start background DSP cycle
    _background_task = asyncio.create_task(_dsp_loop())
    logger.info("Ghost-Core online - DSP cycle running every %.1fs", core.interval)

    yield

    # Shutdown
    logger.info("Ghost-Core shutting down...")
    if _background_task:
        _background_task.cancel()
        try:
            await _background_task
        except asyncio.CancelledError:
            pass
    await core.close()
    logger.info("Ghost-Core terminated")


app = FastAPI(
    title="Ghost-Core DSP Orchestrator",
    version="1.0.0",
    lifespan=lifespan,
)

# Store latest cycle output for quick access
_latest_telemetry: dict = {}
_latest_reflection: dict = {}


# ---------------------------------------------------------------------------
# Background DSP loop
# ---------------------------------------------------------------------------

async def _dsp_loop():
    """Run the DSP analysis cycle at the configured interval."""
    global _latest_telemetry, _latest_reflection

    while True:
        try:
            output = await core.run_dsp_cycle()
            _latest_telemetry = output.get("telemetry", {})
            _latest_reflection = output.get("reflective_analysis", {})

            # Broadcast to all connected WebSocket peers
            dead_connections = []
            for ws in _ws_connections:
                try:
                    await ws.send_json(output)
                except Exception:
                    dead_connections.append(ws)
            for ws in dead_connections:
                _ws_connections.remove(ws)

        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.error("DSP cycle error: %s", e, exc_info=True)

        await asyncio.sleep(core.interval if core else 3.0)


# ---------------------------------------------------------------------------
# REST endpoints
# ---------------------------------------------------------------------------


@app.get("/")
async def root():
    """Root endpoint - Ghost-Core identity."""
    return {
        "service": "Ghost-Core DSP Orchestrator",
        "version": "1.0.0",
        "status": "autonomous",
        "endpoints": {
            "/telemetry": "Live DSP telemetry (buffer, processes, FFT)",
            "/introspect": "Virtual library map and capabilities",
            "/reflect": "Meta-cognitive reflective analysis",
            "/tune": "POST - accept heuristic weight overrides from GNP supervisor",
            "/swarm/status": "Swarm peer connections",
            "/ws/swarm": "WebSocket for real-time P2P telemetry",
        },
    }


@app.get("/telemetry")
async def get_telemetry():
    """Live DSP telemetry: buffer I/O, process profiles, FFT metrics."""
    global _latest_telemetry
    return JSONResponse({
        "status": "active",
        "node_id": core.swarm.node_id if core else "initialising",
        "cycle": core.cycle_count if core else 0,
        "telemetry": _latest_telemetry,
        "swarm_peers": len(core.swarm.peers) if core else 0,
    })


@app.get("/introspect")
async def get_introspect():
    """Virtual library map - scanned Python environment."""
    if core is None:
        return JSONResponse({"status": "initialising"})
    return JSONResponse({
        "virtual_library_map": core.library_map,
        "capability_summary": core.capability_summary,
        "node_id": core.swarm.node_id,
    })


@app.get("/reflect")
async def get_reflection():
    """Meta-cognitive reflective analysis - current heuristic state."""
    global _latest_reflection
    return JSONResponse({
        "reflective_analysis": _latest_reflection,
        "heuristic_weights": dict(core.meta.heuristic_weights) if core else {},
        "snr_history": core.meta.snr_history[-20:] if core else [],
        "error_history": core.meta.error_history[-20:] if core else [],
        "total_insights": len(core.meta._insights) if core else 0,
    })


@app.get("/swarm/status")
async def get_swarm_status():
    """Swarm peer connections and global memory state."""
    if core is None:
        return JSONResponse({"status": "initialising"})
    return JSONResponse(core.swarm.get_swarm_status())


@app.post("/swarm/peer/register")
async def register_peer(peer_id: str, ws_url: str):
    """Manually register a peer node in the swarm."""
    if core is None:
        return JSONResponse({"status": "error", "message": "Core not ready"})
    core.swarm.register_peer(peer_id, ws_url)
    return JSONResponse({
        "status": "registered",
        "peer_id": peer_id,
        "total_peers": len(core.swarm.peers),
    })


@app.post("/tune")
async def tune_heuristics(params: dict):
    """Accept external heuristic weight overrides from Ghost-Node-Prime supervisor."""
    global core
    if core is None:
        return JSONResponse({"status": "error", "message": "Core not ready"})
    weights = core.meta.heuristic_weights
    applied = {}
    for key in ("gate_aggressiveness", "exploration_rate", "learning_rate", "window_adapt_speed"):
        if key in params:
            old = weights.get(key)
            weights[key] = float(params[key])
            applied[key] = {"from": old, "to": weights[key]}
    # Also allow direct gate/window overrides for the signal processor
    if "gate_threshold_db" in params:
        core.signal_processor.gate_threshold_db = float(params["gate_threshold_db"])
        applied["gate_threshold_db"] = params["gate_threshold_db"]
    if "window_exponent" in params:
        core.signal_processor.window_exponent = float(params["window_exponent"])
        applied["window_exponent"] = params["window_exponent"]
    # Allow overriding the target SNR (both MetaController and AdaptiveFeedbackController)
    if "target_snr_db" in params:
        val = float(params["target_snr_db"])
        core.meta.target_snr_db = val
        core.signal_processor.controller.target_snr_db = val
        applied["target_snr_db"] = val
        logger.info("Tune: target_snr_db set to %.2f dB (both controllers)", val)
    # Allow overriding PI controller gains
    for gain_key in ("kp", "ki", "dt"):
        if gain_key in params:
            setattr(core.signal_processor.controller, gain_key, float(params[gain_key]))
            applied[gain_key] = params[gain_key]
    logger.info("Tune applied: %s", applied)
    return JSONResponse({"status": "applied", "changes": applied})


@app.get("/health")
async def health():
    """Liveness check."""
    return JSONResponse({
        "status": "healthy",
        "cycle_count": core.cycle_count if core else 0,
        "peers": len(core.swarm.peers) if core else 0,
        "memory_mb": 0.0,
    })


@app.post("/research")
async def research_topic(topic: str):
    """Trigger a browser research session (async)."""
    if core is None:
        return JSONResponse({"status": "error", "message": "Core not ready"})
    result = await core.browser.research_topic(topic)
    return JSONResponse(result)


# ---------------------------------------------------------------------------
# WebSocket - real-time peer swarm communication
# ---------------------------------------------------------------------------


@app.websocket("/ws/swarm")
async def websocket_swarm(ws: WebSocket):
    """WebSocket endpoint for P2P node communication.

    Each connected peer receives JSON telemetry broadcasts every cycle
    and can send messages to sync global memory state.
    """
    await ws.accept()
    _ws_connections.append(ws)
    peer_id = f"ws-{len(_ws_connections)}"
    logger.info("WebSocket peer connected: %s", peer_id)

    try:
        while True:
            data = await ws.receive_json()
            # Handle peer sync requests
            if isinstance(data, dict):
                cmd = data.get("command", "")
                if cmd == "sync_memory":
                    payload = data.get("global_memory", {})
                    merged = core.swarm.sync_global_memory({"global_memory": payload})
                    await ws.send_json({
                        "type": "memory_synced",
                        "merged_keys": list(merged.keys()),
                    })
                elif cmd == "ping":
                    await ws.send_json({"type": "pong", "timestamp": time.time()})
                elif cmd == "register":
                    core.swarm.register_peer(
                        data.get("peer_id", peer_id),
                        data.get("url", "unknown"),
                    )
                    await ws.send_json({"type": "registered", "peer_id": peer_id})

    except WebSocketDisconnect:
        logger.info("WebSocket peer disconnected: %s", peer_id)
    except Exception as e:
        logger.warning("WebSocket error (%s): %s", peer_id, e)
    finally:
        if ws in _ws_connections:
            _ws_connections.remove(ws)


# ---------------------------------------------------------------------------
# CLI entry
# ---------------------------------------------------------------------------

def main():
    port = int(os.getenv("GHOST_CORE_PORT", "7861"))
    logger.info("Starting Ghost-Core on http://0.0.0.0:%d", port)
    uvicorn.run(
        "ghost_app:app",
        host="0.0.0.0",
        port=port,
        reload=False,
        log_level="info",
    )


if __name__ == "__main__":
    main()
