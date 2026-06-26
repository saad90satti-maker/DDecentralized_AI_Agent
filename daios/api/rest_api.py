"""DAIOS REST API — FastAPI-based interface for human control and monitoring."""

import json
import logging
from typing import Dict, Any, Optional
from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel

logger = logging.getLogger("daios.api")

app = FastAPI(title="DAIOS API", version="0.1.0",
              description="Decentralized AI Operating System — Simulation Control Interface")

_kernel_ref = None


def init(kernel) -> None:
    global _kernel_ref
    _kernel_ref = kernel


class CommandRequest(BaseModel):
    command: str
    params: Dict[str, Any] = {}


class AgentProposal(BaseModel):
    agent_type: str
    reason: str


@app.get("/api/status")
def get_status():
    if not _kernel_ref:
        return JSONResponse({"status": "error", "message": "Kernel not initialized"})
    return JSONResponse(_kernel_ref.get_status())


@app.get("/api/world")
def get_world():
    if not _kernel_ref:
        return JSONResponse({"status": "error", "message": "Kernel not initialized"})
    world = getattr(_kernel_ref, "_world", None)
    if not world:
        return JSONResponse({"status": "error", "message": "World not initialized"})
    return JSONResponse(world.get_status())


@app.get("/api/agents")
def list_agents():
    if not _kernel_ref:
        return JSONResponse({"status": "error", "message": "Kernel not initialized"})
    agents = _kernel_ref.get_all_agents()
    return JSONResponse({
        aid: a.get_status() if hasattr(a, "get_status") else {"id": aid}
        for aid, a in agents.items()
    })


@app.get("/api/agents/{agent_id}")
def get_agent(agent_id: str):
    if not _kernel_ref:
        return JSONResponse({"status": "error", "message": "Kernel not initialized"})
    agent = _kernel_ref.get_agent(agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail=f"Agent {agent_id} not found")
    status = agent.get_status() if hasattr(agent, "get_status") else {"id": agent_id}
    return JSONResponse(status)


@app.get("/api/memory")
def get_memory():
    k = _kernel_ref
    if not k:
        return JSONResponse({"status": "error", "message": "Kernel not initialized"})
    memory_agents = [a for aid, a in k.get_all_agents().items() if getattr(a, "agent_type", "") == "memory"]
    if memory_agents:
        mem = memory_agents[0]
        mem_status = mem.get_status() if hasattr(mem, "get_status") else {}
        return JSONResponse(mem_status)
    return JSONResponse({"status": "no_memory_agent"})


@app.get("/api/hypotheses")
def get_hypotheses():
    k = _kernel_ref
    if not k or not hasattr(k, "_hypothesis_engine"):
        return JSONResponse({"status": "unavailable"})
    return JSONResponse(k._hypothesis_engine.summary())


@app.get("/api/metrics")
def get_metrics():
    k = _kernel_ref
    if not k:
        return JSONResponse({"status": "error", "message": "Kernel not initialized"})
    return JSONResponse(k.resource_tracker.summary())


@app.post("/api/command")
async def run_command(cmd: CommandRequest):
    k = _kernel_ref
    if not k:
        return JSONResponse({"status": "error", "message": "Kernel not initialized"})

    command = cmd.command
    params = cmd.params

    if command == "pause":
        return JSONResponse({"status": "paused"})
    elif command == "resume":
        return JSONResponse({"status": "resumed"})
    elif command == "shutdown":
        import asyncio
        asyncio.create_task(k.stop())
        return JSONResponse({"status": "shutting_down"})
    elif command == "propose_agent":
        factory = getattr(k, "_agent_factory", None)
        if factory:
            proposal_id = factory.propose_new_agent(
                params.get("agent_type", "research"),
                params.get("reason", "Manual request"),
                "human_operator"
            )
            return JSONResponse({"proposal_id": proposal_id, "status": "pending_approval"})
        return JSONResponse({"status": "error", "message": "Agent factory not available"})
    elif command == "approve_agent":
        factory = getattr(k, "_agent_factory", None)
        if factory:
            agent_id = factory.approve_creation(params.get("proposal_id", ""))
            if agent_id:
                return JSONResponse({"agent_id": agent_id, "status": "created"})
            return JSONResponse({"status": "error", "message": "Proposal not found"})
    elif command == "checkpoint":
        path = k.state_mgr.save_checkpoint()
        return JSONResponse({"checkpoint": path})
    else:
        return JSONResponse({"status": "error", "message": f"Unknown command: {command}"})


@app.get("/api/exploration")
def get_exploration():
    k = _kernel_ref
    if not k or not hasattr(k, "_hypothesis_engine"):
        return JSONResponse({"status": "unavailable"})
    return JSONResponse(k._hypothesis_engine.rank_by_usefulness()[:20])


def start_api(host: str = "0.0.0.0", port: int = 8471):
    import uvicorn
    uvicorn.run(app, host=host, port=port)
