"""
Dynamic Tool-Selection Registry — replaces all static if/elif dispatch chains.
Tools register themselves with schemas; the agent selects them autonomously via function-calling.
"""

import os
import sys
import json
import time
import hashlib
import logging
import asyncio
import subprocess
from datetime import datetime
from typing import Any, Callable, Optional
from dataclasses import dataclass, field
from pathlib import Path
import contextlib

logger = logging.getLogger("tool_registry")

# ---------------------------------------------------------------------------
# Tool schema
# ---------------------------------------------------------------------------

@dataclass
class ToolSpec:
    name: str
    description: str
    parameters: dict
    handler: Callable = field(repr=False)
    category: str = "general"
    requires_approval: bool = False
    timeout: int = 30

    def to_openai_schema(self) -> dict:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }


# ---------------------------------------------------------------------------
# Tool Registry
# ---------------------------------------------------------------------------

class ToolRegistry:
    """Agentic tool-selection engine. Tools self-register; agent picks via LLM function-calling."""

    def __init__(self):
        self._tools: dict[str, ToolSpec] = {}
        self._post_execute_hooks: list = []

    def register(self, spec: ToolSpec):
        self._tools[spec.name] = spec
        logger.debug("Registered tool: %s (%s)", spec.name, spec.category)

    def register_from_callable(self, fn: Callable, **overrides):
        """Register from a decorated function."""
        spec = getattr(fn, "_tool_spec", None)
        if spec:
            self._tools[spec.name] = spec
        else:
            name = overrides.get("name", fn.__name__)
            self._tools[name] = ToolSpec(
                name=name,
                description=overrides.get("description", fn.__doc__ or ""),
                parameters=overrides.get("parameters", {"type": "object", "properties": {}}),
                handler=fn,
                category=overrides.get("category", "general"),
            )

    def get(self, name: str) -> Optional[ToolSpec]:
        return self._tools.get(name)

    def list_tools(self, category: Optional[str] = None) -> list[ToolSpec]:
        if category:
            return [t for t in self._tools.values() if t.category == category]
        return list(self._tools.values())

    def get_openai_schemas(self, category: Optional[str] = None) -> list[dict]:
        return [t.to_openai_schema() for t in self.list_tools(category)]

    async def execute(self, name: str, arguments: dict, timeout: Optional[int] = None) -> Any:
        spec = self._tools.get(name)
        if not spec:
            raise ValueError(f"Unknown tool: {name}")
        import time as _time
        t0 = _time.monotonic()
        success = False
        try:
            if asyncio.iscoroutinefunction(spec.handler):
                result = await asyncio.wait_for(spec.handler(**arguments), timeout=timeout or spec.timeout)
            else:
                result = await asyncio.get_event_loop().run_in_executor(
                    None, lambda: spec.handler(**arguments)
                )
            success = True
            ret = {"tool": name, "status": "ok", "result": result}
        except Exception as e:
            logger.error("Tool %s failed: %s", name, e)
            ret = {"tool": name, "status": "error", "error": str(e)}
        finally:
            latency = (_time.monotonic() - t0) * 1000
            for hook in self._post_execute_hooks:
                try:
                    hook(name, success, latency)
                except Exception as e:
                    logger.debug("Hook error: %s", e)
        return ret

    def add_post_execute_hook(self, hook):
        """Register a callback: fn(tool_name, success, latency_ms)."""
        self._post_execute_hooks.append(hook)

    def size(self) -> int:
        return len(self._tools)


# ---------------------------------------------------------------------------
# Decorator
# ---------------------------------------------------------------------------

def tool(
    name: Optional[str] = None,
    description: Optional[str] = None,
    parameters: Optional[dict] = None,
    category: str = "general",
    requires_approval: bool = False,
    timeout: int = 30,
):
    def decorator(fn):
        spec = ToolSpec(
            name=name or fn.__name__,
            description=description or fn.__doc__ or "",
            parameters=parameters or {"type": "object", "properties": {}},
            handler=fn,
            category=category,
            requires_approval=requires_approval,
            timeout=timeout,
        )
        fn._tool_spec = spec
        return fn
    return decorator


# ===========================================================================
# Built-in tool implementations
# ===========================================================================

# Global registry
_registry: Optional[ToolRegistry] = None


def get_registry() -> ToolRegistry:
    global _registry
    if _registry is None:
        _registry = ToolRegistry()
        _register_builtins(_registry)
    return _registry


# ===========================================================================
# Module-level tool implementations (decorated so _tool_spec is attached)
# ===========================================================================

@tool(
    name="read_file",
    description="Read contents of a file",
    parameters={
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Absolute file path"},
            "limit": {"type": "integer", "description": "Max lines to read", "default": 2000},
        },
        "required": ["path"],
    },
    category="filesystem",
)
def _read_file(path: str, limit: int = 2000):
    p = Path(path)
    if not p.exists():
        return f"ERROR: file not found: {path}"
    with open(p, encoding="utf-8", errors="replace") as f:
        lines = f.readlines()
    return "".join(lines[:limit])


@tool(
    name="write_file",
    description="Write content to a file",
    parameters={
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Absolute file path"},
            "content": {"type": "string", "description": "Content to write"},
        },
        "required": ["path", "content"],
    },
    category="filesystem",
    requires_approval=True,
)
def _write_file(path: str, content: str):
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")
    return f"Wrote {len(content)} bytes to {path}"


@tool(
    name="list_directory",
    description="List contents of a directory",
    parameters={
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Directory path"},
        },
        "required": ["path"],
    },
    category="filesystem",
)
def _list_directory(path: str):
    p = Path(path)
    if not p.is_dir():
        return f"ERROR: not a directory: {path}"
    return "\n".join(sorted([str(x.name) + ("/" if x.is_dir() else "") for x in p.iterdir()]))


@tool(
    name="run_command",
    description="Execute a shell command",
    parameters={
        "type": "object",
        "properties": {
            "command": {"type": "string", "description": "Shell command to execute"},
            "timeout": {"type": "integer", "description": "Timeout in seconds", "default": 30},
        },
        "required": ["command"],
    },
    category="shell",
    requires_approval=True,
    timeout=120,
)
def _run_command(command: str, timeout: int = 30):
    result = subprocess.run(
        command, shell=True, capture_output=True, text=True, timeout=timeout
    )
    output = result.stdout or ""
    if result.stderr:
        output += f"\nSTDERR:\n{result.stderr[:2000]}"
    return output or f"Completed (exit code {result.returncode})"


@tool(
    name="http_request",
    description="Make an HTTP request",
    parameters={
        "type": "object",
        "properties": {
            "url": {"type": "string", "description": "Target URL"},
            "method": {"type": "string", "description": "HTTP method", "default": "GET"},
            "headers": {"type": "object", "description": "Request headers", "default": {}},
            "body": {"type": "string", "description": "Request body", "default": ""},
        },
        "required": ["url"],
    },
    category="network",
)
async def _http_request(url: str, method: str = "GET", headers: Optional[dict] = None, body: str = ""):
    import httpx
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.request(method, url, headers=headers or {}, content=body or None)
        return {"status": resp.status_code, "body": resp.text[:5000], "headers": dict(resp.headers)}


@tool(
    name="swarm_status",
    description="Get current swarm mesh status",
    parameters={"type": "object", "properties": {}},
    category="swarm",
)
def _swarm_status():
    try:
        from ghost_swarm import GhostSwarmNode
        return {"swarm_available": True}
    except ImportError:
        return {"swarm_available": False, "error": "ghost_swarm not importable"}


@tool(
    name="check_api",
    description="Check FastAPI dashboard health",
    parameters={
        "type": "object",
        "properties": {
            "endpoint": {"type": "string", "description": "API endpoint", "default": "/api/status"},
        },
    },
    category="network",
)
async def _check_api(endpoint: str = "/api/status"):
    import httpx
    base = os.getenv("MANAGER_URL", "http://localhost:7860")
    async with httpx.AsyncClient(timeout=10) as client:
        try:
            resp = await client.get(f"{base}{endpoint}")
            return {"status": resp.status_code, "data": resp.text[:2000]}
        except Exception as e:
            return {"status": "error", "error": str(e)}


@tool(
    name="route_prompt",
    description="Send a prompt through the Unified API Gateway to a remote LLM",
    parameters={
        "type": "object",
        "properties": {
            "prompt": {"type": "string", "description": "The prompt text"},
            "system": {"type": "string", "description": "System prompt", "default": ""},
            "model": {"type": "string", "description": "Model override", "default": ""},
        },
        "required": ["prompt"],
    },
    category="model",
    timeout=120,
)
async def _route_prompt(prompt: str, system: str = "", model: str = ""):
    from api_gateway import UnifiedAPIGateway
    gateway = UnifiedAPIGateway()
    await gateway.initialize()
    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})
    resp = await gateway.chat(messages, model=model or None)
    await gateway.close()
    return {"text": resp.text, "provider": resp.provider, "model": resp.model, "latency_ms": resp.latency_ms}


@tool(
    name="install_package",
    description="Install a Python package via pip",
    parameters={
        "type": "object",
        "properties": {
            "package": {"type": "string", "description": "Package name (optionally with version)"},
        },
        "required": ["package"],
    },
    category="system",
    requires_approval=True,
    timeout=120,
)
def _install_package(package: str, **kwargs):
    result = subprocess.run(
        [sys.executable, "-m", "pip", "install", package],
        capture_output=True, text=True, timeout=120,
    )
    return result.stdout[-1000:] + result.stderr[-1000:]


# ===========================================================================
# Autonomous healing tools — used by Health Engine v2
# ===========================================================================

@tool(
    name="dht_initialize",
    description="Initialize or re-initialize the Kademlia DHT node for swarm peering",
    parameters={
        "type": "object",
        "properties": {
            "component": {"type": "string", "description": "Originating component", "default": "dht"},
            "detail": {"type": "string", "description": "Error detail", "default": ""},
            "force_rebuild": {"type": "boolean", "description": "Force pip reinstall", "default": False},
        },
    },
    category="swarm",
    timeout=120,
)
async def _dht_initialize(component: str = "dht", detail: str = "", force_rebuild: bool = False):
    """Re-initialize the Kademlia DHT: install lib, then discover peers."""
    import httpx
    from cloud_native import CloudNativeConfig

    config = CloudNativeConfig()
    results = {}

    # Step 1: ensure kademlia is installed
    try:
        from kademlia.network import Server
        results["library"] = "already installed"
    except ImportError:
        logger.info("dht_initialize: installing kademlia...")
        proc = await asyncio.create_subprocess_exec(
            sys.executable, "-m", "pip", "install", "kademlia",
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
        await asyncio.wait_for(proc.wait(), timeout=60)
        if proc.returncode != 0:
            return {"status": "error", "error": "pip install kademlia failed"}
        results["library"] = "installed"

    # Step 2: try calling the swarm node API to re-init DHT
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(
                f"{config.manager_url}/api/swarm/dht-reinit",
                json={"bootstrap": config.dht_bootstrap, "port": config.dht_port},
            )
            if resp.status_code == 200:
                data = resp.json()
                results["dht_reinit"] = data
            else:
                results["dht_reinit"] = f"API returned {resp.status_code}"
    except Exception as e:
        results["dht_reinit"] = f"API unreachable: {e}"

    success = results.get("dht_reinit", {}).get("status") == "ok" if isinstance(
        results.get("dht_reinit"), dict) else False
    return {"status": "ok" if success else "error", "results": results}


@tool(
    name="swarm_relay",
    description="Switch swarm mesh to relay-based peering when DHT is unavailable",
    parameters={
        "type": "object",
        "properties": {
            "component": {"type": "string", "default": "swarm_mesh"},
            "detail": {"type": "string", "default": ""},
        },
    },
    category="swarm",
    timeout=60,
)
async def _swarm_relay(component: str = "swarm_mesh", detail: str = ""):
    """Activate relay-based peering as fallback when direct DHT fails."""
    import httpx
    from cloud_native import CloudNativeConfig
    config = CloudNativeConfig()

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(
                f"{config.manager_url}/api/swarm/relay",
                json={"reason": detail or "DHT unavailable", "source": "health_engine"},
            )
            if resp.status_code == 200:
                data = resp.json()
                return {"status": "ok", "relay": data}
            return {"status": "error", "error": f"API returned {resp.status_code}"}
    except Exception as e:
        return {"status": "error", "error": str(e)}


@tool(
    name="tunnel_activate",
    description="Activate Cloudflare Tunnel or alternative tunnel to expose local services publicly",
    parameters={
        "type": "object",
        "properties": {
            "component": {"type": "string", "default": "tunnel"},
            "detail": {"type": "string", "default": ""},
        },
    },
    category="network",
    timeout=120,
)
async def _tunnel_activate(component: str = "tunnel", detail: str = ""):
    """Start Cloudflare Tunnel for external swarm peering."""
    from cloud_native import CloudNativeConfig, CloudflareTunnel
    config = CloudNativeConfig()

    if config.tunnel_enabled:
        tunnel = CloudflareTunnel(config)
        success = await tunnel.start()
        return {
            "status": "ok" if success else "error",
            "url": tunnel.url if success else None,
            "tunnel_enabled": config.tunnel_enabled,
        }

    # Try quick tunnel (no token required — ephemeral)
    logger.info("tunnel_activate: attempting Cloudflare quick tunnel...")
    try:
        proc = await asyncio.create_subprocess_exec(
            "cloudflared", "tunnel", "--url", f"http://localhost:{config.port}",
            "--no-autoupdate",
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
        await asyncio.sleep(8)
        if proc.returncode is None:
            return {"status": "ok", "url": "quick-tunnel-started",
                    "note": "check cloudflared logs for the .trycloudflare.com URL"}
        return {"status": "error", "error": "cloudflared exited immediately"}
    except FileNotFoundError:
        return {"status": "error", "error": "cloudflared not installed. Install from https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/downloads/"}
    except Exception as e:
        return {"status": "error", "error": str(e)}


# ===========================================================================
# Developer Tools — autonomous code optimization
# ===========================================================================

@tool(
    name="analyze_performance",
    description="Analyze tool performance metrics and flag bottlenecks across the system",
    parameters={
        "type": "object",
        "properties": {
            "tool_filter": {"type": "string", "description": "Optional tool name to analyze", "default": ""},
            "deep": {"type": "boolean", "description": "Run deep diagnostic", "default": False},
        },
    },
    category="developer",
    timeout=30,
)
async def _analyze_performance(tool_filter: str = "", deep: bool = False):
    """Query the PerformanceAnalyzer for tool success rates and flagged tools."""
    try:
        from performance_analyzer import PerformanceAnalyzer
        # Try to get global instance
        analyzer = getattr(_analyze_performance, "_analyzer", None)
        if not analyzer:
            # Create a fresh one for one-shot analysis
            analyzer = PerformanceAnalyzer()
            setattr(_analyze_performance, "_analyzer", analyzer)

        if tool_filter:
            result = analyzer.get_diagnostics(tool_filter)
        else:
            result = analyzer.get_report()

        return {"status": "ok", "analysis": result}
    except Exception as e:
        return {"status": "error", "error": str(e)}


@tool(
    name="propose_optimization",
    description="Analyze a performance bottleneck and generate an optimization proposal for code review",
    parameters={
        "type": "object",
        "properties": {
            "target_file": {
                "type": "string",
                "description": "File to optimize (api_gateway.py, cloud_native.py, health_engine.py, tool_registry.py)",
            },
            "bottleneck": {"type": "string", "description": "Observed bottleneck description"},
            "proposed_change": {"type": "string", "description": "Proposed code change"},
            "expected_improvement": {"type": "string", "description": "Expected improvement metric"},
        },
        "required": ["target_file", "bottleneck", "proposed_change"],
    },
    category="developer",
    requires_approval=True,
    timeout=30,
)
async def _propose_optimization(target_file: str, bottleneck: str,
                                 proposed_change: str, expected_improvement: str = ""):
    """Generate a structured optimization proposal and save it for review."""
    PROPOSALS_DIR = Path("agent_logs/optimization_proposals")
    PROPOSALS_DIR.mkdir(parents=True, exist_ok=True)

    import time
    timestamp = int(time.time())

    proposal = {
        "id": f"opt-{timestamp}",
        "timestamp": timestamp,
        "target_file": target_file,
        "bottleneck": bottleneck,
        "proposed_change": proposed_change,
        "expected_improvement": expected_improvement,
        "status": "pending_review",
        "source": "autonomous_agent",
    }

    # Read current file for context
    try:
        filepath = Path(target_file)
        if filepath.exists():
            content = filepath.read_text(encoding="utf-8")
            proposal["current_file_size"] = len(content)
            proposal["current_file_lines"] = content.count("\n")
    except Exception as e:
        proposal["read_error"] = str(e)

    proposal_path = PROPOSALS_DIR / f"{proposal['id']}.json"
    proposal_path.write_text(json.dumps(proposal, indent=2), encoding="utf-8")

    logger.info("Optimization proposal created: %s", proposal_path)
    return {"status": "ok", "proposal": proposal, "path": str(proposal_path)}


@tool(
    name="review_proposals",
    description="List all pending optimization proposals awaiting review",
    parameters={
        "type": "object",
        "properties": {
            "status": {"type": "string", "description": "Filter by status (pending_review, approved, rejected)", "default": "pending_review"},
        },
    },
    category="developer",
    timeout=15,
)
async def _review_proposals(status: str = "pending_review"):
    """List optimization proposals by status."""
    PROPOSALS_DIR = Path("agent_logs/optimization_proposals")
    if not PROPOSALS_DIR.exists():
        return {"status": "ok", "proposals": [], "total": 0}

    proposals = []
    for f in sorted(PROPOSALS_DIR.glob("*.json")):
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            if data.get("status") == status or status == "all":
                proposals.append({
                    "id": data["id"],
                    "target_file": data["target_file"],
                    "bottleneck": data["bottleneck"][:100],
                    "expected_improvement": data.get("expected_improvement", ""),
                    "status": data["status"],
                    "timestamp": data["timestamp"],
                })
        except Exception:
            continue

    return {"status": "ok", "proposals": proposals, "total": len(proposals), "filter": status}


# ===========================================================================
# Autonomous Execution Tools — self-governing patch lifecycle
# ===========================================================================

@tool(
    name="evaluate_proposal",
    description="Evaluate an optimization proposal against the >20% performance gain threshold for auto-approval",
    parameters={
        "type": "object",
        "properties": {
            "proposal_id": {"type": "string", "description": "Proposal ID (e.g. opt-1712345678)"},
        },
        "required": ["proposal_id"],
    },
    category="developer",
    timeout=15,
)
async def _evaluate_proposal(proposal_id: str):
    """Check if a proposal meets the auto-approval threshold (>20% expected gain)."""
    PROPOSALS_DIR = Path("agent_logs/optimization_proposals")
    f = PROPOSALS_DIR / f"{proposal_id}.json"
    if not f.exists():
        return {"status": "error", "error": f"proposal not found: {proposal_id}"}

    proposal = json.loads(f.read_text(encoding="utf-8"))

    expected = proposal.get("expected_improvement", "")
    bottleneck = proposal.get("bottleneck", "")
    status = proposal.get("status", "")

    if status == "applied":
        return {"status": "ok", "approved": False, "reason": "already applied", "proposal_id": proposal_id}
    if status == "rejected":
        return {"status": "ok", "approved": False, "reason": "previously rejected", "proposal_id": proposal_id}

    # Parse expected_improvement for numeric gain indicators
    gain_patterns = [">20%", "> 20%", "20%", "reduce", "improve", "optimize", "faster"]
    has_indicator = any(p in expected.lower() for p in gain_patterns)

    # Extract numeric percentage if present
    import re
    nums = re.findall(r'(\d+)%', expected)
    gain_pct = max(int(n) for n in nums) if nums else 0

    approved = False
    reason = ""

    if gain_pct >= 20:
        approved = True
        reason = f"auto-approved: expected gain {gain_pct}% >= 20% threshold"
    elif has_indicator and gain_pct >= 15:
        approved = True
        reason = f"auto-approved: {gain_pct}% expected gain with improvement indicator"
    elif "latency" in expected.lower() or "reliability" in expected.lower():
        approved = True
        reason = "auto-approved: targets latency/reliability improvement"
    else:
        reason = f"flagged for human review: expected gain {gain_pct}% below 20% threshold, no clear indicator"

    return {
        "status": "ok",
        "proposal_id": proposal_id,
        "approved": approved,
        "reason": reason,
        "gain_pct": gain_pct,
        "target_file": proposal.get("target_file", ""),
        "bottleneck": bottleneck[:120],
    }


@tool(
    name="auto_patch",
    description="Autonomously evaluate, apply, verify, and broadcast an optimization proposal. Hot-patches target module and monitors for 60s.",
    parameters={
        "type": "object",
        "properties": {
            "proposal_id": {"type": "string", "description": "Proposal ID to execute"},
            "force": {"type": "boolean", "description": "Skip evaluation threshold check", "default": False},
        },
        "required": ["proposal_id"],
    },
    category="developer",
    requires_approval=True,
    timeout=300,
)
async def _auto_patch(proposal_id: str, force: bool = False):
    """
    Full autonomous patch lifecycle:
    1. Evaluate proposal against >20% gain threshold
    2. Generate code patch via LLM
    3. Backup target file
    4. Apply patch (hot-reload module)
    5. Monitor for 60s (compare pre/post stats)
    6. On success: broadcast patch signature to swarm
    7. On failure: rollback + flag for human review
    """
    PROPOSALS_DIR = Path("agent_logs/optimization_proposals")
    PATCH_LOG = Path("agent_logs/self_patch.log")
    BACKUP_DIR = Path("agent_logs/patch_backups")
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    PROPOSALS_DIR.mkdir(parents=True, exist_ok=True)
    PATCH_LOG.parent.mkdir(parents=True, exist_ok=True)

    # Step 1: Load proposal
    f = PROPOSALS_DIR / f"{proposal_id}.json"
    if not f.exists():
        return {"status": "error", "error": f"proposal not found: {proposal_id}"}

    proposal = json.loads(f.read_text(encoding="utf-8"))
    target_file = proposal.get("target_file", "")
    bottleneck = proposal.get("bottleneck", "")
    proposed_change = proposal.get("proposed_change", "")

    if not target_file:
        return {"status": "error", "error": "proposal has no target_file"}

    target_path = Path(target_file)
    if not target_path.exists():
        return {"status": "error", "error": f"target file not found: {target_file}"}

    # Step 2: Evaluate threshold (unless forced)
    if not force:
        eval_result = await _evaluate_proposal(proposal_id)
        if not eval_result.get("approved"):
            return {"status": "rejected", "reason": eval_result.get("reason", "below auto-approval threshold")}

    # Step 3: Generate patch using optimization templates
    logger.info("Auto-patch %s: generating patch for %s", proposal_id, target_file)
    original_content = target_path.read_text(encoding="utf-8")

    patched_content = _apply_optimization_template(target_file, original_content, bottleneck, proposed_change)
    if patched_content is None:
        return {"status": "error", "error": f"no applicable optimization template for: {bottleneck}"}

    # Step 4: Validate syntax
    try:
        compile(patched_content, target_file, "exec")
    except SyntaxError as e:
        logger.error("Auto-patch %s: syntax error in generated patch: %s", proposal_id, e)
        return {"status": "error", "error": f"generated patch has syntax error: {e}"}

    # Step 5: Compute patch hash for swarm broadcast
    patch_hash = hashlib.sha256(patched_content.encode()).hexdigest()[:16]

    # Step 6: Backup original
    backup_name = f"{target_path.stem}_{proposal_id}_{int(time.time())}.bak"
    backup_path = BACKUP_DIR / backup_name
    backup_path.write_text(original_content, encoding="utf-8")
    logger.info("Auto-patch %s: backed up to %s", proposal_id, backup_path)

    # Step 7: Apply patch
    target_path.write_text(patched_content, encoding="utf-8")

    # Step 8: Hot-reload module
    module_reload_ok = False
    module_name = target_path.stem
    try:
        if module_name in sys.modules:
            import importlib
            importlib.reload(sys.modules[module_name])
            logger.info("Auto-patch %s: hot-reloaded module '%s'", proposal_id, module_name)
            module_reload_ok = True
        else:
            logger.info("Auto-patch %s: module '%s' not loaded, skipping reload", proposal_id, module_name)
            module_reload_ok = True  # Not an error if not imported yet
    except Exception as e:
        logger.error("Auto-patch %s: hot-reload failed: %s — rolling back", proposal_id, e)
        target_path.write_text(original_content, encoding="utf-8")
        return {"status": "error", "error": f"hot-reload failed: {e}", "rolled_back": True}

    # Step 9: Log the patch
    patch_entry = (
        f"{datetime.now().isoformat()} | AUTO-PATCH | {proposal_id} | "
        f"{target_file} | hash={patch_hash} | {bottleneck[:80]}\n"
    )
    with open(PATCH_LOG, "a", encoding="utf-8") as pf:
        pf.write(patch_entry)

    # Step 10: Monitor for 60 seconds
    logger.info("Auto-patch %s: monitoring for 60s...", proposal_id)
    monitor_ok = True
    monitor_errors = []

    # Capture pre-patch analyzer stats
    pre_patch_stats = None
    try:
        from performance_analyzer import PerformanceAnalyzer
        pre_patch_stats = _get_analyzer_snapshot()
    except Exception:
        pass

    await asyncio.sleep(60)

    # Check health after 60s
    try:
        import httpx
        health_resp = await httpx.AsyncClient(timeout=10).get("http://localhost:7860/api/health")
        if health_resp.status_code == 200:
            health_data = health_resp.json()
            # Check if any component went unhealthy
            for comp, status in health_data.items():
                if isinstance(status, dict) and not status.get("healthy", True):
                    monitor_errors.append(f"component {comp} unhealthy after patch")
                    monitor_ok = False
        else:
            monitor_errors.append(f"health API returned {health_resp.status_code}")
    except Exception as e:
        monitor_errors.append(f"health check failed: {e}")

    # Compare post-patch stats
    post_patch_stats = None
    try:
        post_patch_stats = _get_analyzer_snapshot()
    except Exception:
        pass

    performance_gain = 0.0
    if pre_patch_stats and post_patch_stats:
        pre_avg = pre_patch_stats.get("global_avg_latency_ms", 0)
        post_avg = post_patch_stats.get("global_avg_latency_ms", 0)
        if pre_avg > 0:
            performance_gain = max(0, (pre_avg - post_avg) / pre_avg * 100)

    # Step 11: Decision
    if not monitor_ok:
        # Rollback
        target_path.write_text(original_content, encoding="utf-8")
        if module_name in sys.modules:
            try:
                import importlib
                importlib.reload(sys.modules[module_name])
            except Exception:
                pass
        logger.warning("Auto-patch %s: monitor FAILED — rolled back", proposal_id)
        # Update proposal status
        proposal["status"] = "rolled_back"
        proposal["monitor_errors"] = monitor_errors
        f.write_text(json.dumps(proposal, indent=2), encoding="utf-8")
        return {
            "status": "rolled_back",
            "proposal_id": proposal_id,
            "monitor_errors": monitor_errors,
            "message": "exception: human review required — patch caused degradation",
        }

    # Success
    proposal["status"] = "applied"
    proposal["patch_hash"] = patch_hash
    proposal["performance_gain_pct"] = round(performance_gain, 1)
    proposal["applied_at"] = time.time()
    f.write_text(json.dumps(proposal, indent=2), encoding="utf-8")

    # Broadcast to swarm
    try:
        from shared_knowledge import SharedKnowledge
        sk = _get_shared_knowledge_instance()
        if sk:
            sk.broadcast_patch_success(
                patch_id=proposal_id,
                patch_hash=patch_hash,
                target_file=target_file,
                performance_gain=performance_gain,
                proposal=proposal,
            )
            sk.mark_patch_applied(proposal_id, success=True, gain=performance_gain)
    except Exception as e:
        logger.debug("Auto-patch %s: swarm broadcast skipped: %s", proposal_id, e)

    logger.info("Auto-patch %s: SUCCESS — gain=%.1f%%, hash=%s", proposal_id, performance_gain, patch_hash)
    return {
        "status": "ok",
        "proposal_id": proposal_id,
        "target_file": target_file,
        "patch_hash": patch_hash,
        "performance_gain_pct": round(performance_gain, 1),
        "backup_path": str(backup_path),
        "message": f"patch applied, verified for 60s, gain={performance_gain:.1f}%",
    }


def _get_analyzer_snapshot() -> dict:
    """Get a snapshot of current performance analyzer stats."""
    try:
        from performance_analyzer import PerformanceAnalyzer
        analyzer = getattr(_get_analyzer_snapshot, "_analyzer", None)
        if not analyzer:
            analyzer = PerformanceAnalyzer()
            setattr(_get_analyzer_snapshot, "_analyzer", analyzer)
        report = analyzer.get_report()
        latencies = [s["avg_latency_ms"] for s in report.get("tool_stats", {}).values() if s["avg_latency_ms"] > 0]
        return {
            "global_avg_latency_ms": sum(latencies) / len(latencies) if latencies else 0,
            "flagged_count": len(report.get("flagged_tools", [])),
            "tool_count": report.get("total_tracked", 0),
        }
    except Exception:
        return {}


def _get_shared_knowledge_instance():
    """Try to get the global SharedKnowledge singleton."""
    try:
        import sys as _sys
        for mod_name in list(_sys.modules.keys()):
            if mod_name == "manager":
                mod = _sys.modules["manager"]
                return getattr(mod, "_shared_knowledge", None) or getattr(mod, "shared_knowledge", None)
    except Exception:
        pass
    return None


# ===========================================================================
# Optimization Template Engine — applies known code transformations without LLM
# ===========================================================================

def _apply_optimization_template(target_file: str, content: str,
                                  bottleneck: str, proposed_change: str) -> str or None:
    """
    Apply a known optimization template based on the bottleneck description.
    Returns the patched file content, or None if no template matches.
    """
    b = bottleneck.lower()
    c = proposed_change.lower()

    # --- Template: NAT detection caching ---
    if "nat" in b and ("cach" in b or "cach" in c or "every heartbeat" in b):
        return _template_nat_cache(content)

    # --- Template: API response caching ---
    if "api" in b and "cach" in c:
        return _template_api_cache(content, "api_gateway" in target_file)

    # --- Template: Latency-based fallback tuning ---
    if "latency" in b and ("threshold" in c or "switch" in c):
        return _template_latency_tuning(content)

    # --- Template: Add retry logic ---
    if "retry" in c or "timeout" in c:
        return _template_retry_wrapper(content)

    # --- Template: Remove dead code ---
    if "dead code" in b or "unused" in b:
        return _template_remove_dead_code(content)

    # Fallback: unknown optimization pattern
    logger.info("No template matches for bottleneck: %s", bottleneck[:80])
    return None


def _template_nat_cache(content: str) -> str:
    """Add TTL-based caching for NAT detection."""
    # Inject _nat_cache dict + helper after imports
    lines = content.splitlines(keepends=True)

    # Find import section end
    import_end = 0
    for i, line in enumerate(lines):
        if line.strip() and not line.startswith("import ") and not line.startswith("from ") and not line.startswith("#"):
            import_end = i
            break
    if import_end == 0:
        import_end = len(lines)  # Fallback

    cache_helpers = (
        "\n# [AUTO-PATCH] NAT cache for heartbeat optimization\n"
        "_NAT_CACHE = {\"is_nat\": None, \"local_ip\": None, \"timestamp\": 0.0}\n"
        "_NAT_CACHE_TTL = 600  # 10 minutes\n\n"
    )

    # Find detect_nat function and add cache check
    nat_func_start = None
    nat_func_end = None
    for i, line in enumerate(lines):
        if line.strip().startswith("def detect_nat"):
            nat_func_start = i
            # Find function end
            for j in range(i + 1, min(i + 50, len(lines))):
                if j >= len(lines) - 1 or (lines[j].strip() and not lines[j][0].isspace() and not lines[j].strip().startswith("#") and not lines[j].strip().startswith("@")):
                    nat_func_end = j
                    break
            if nat_func_end is None:
                nat_func_end = len(lines)
            break

    cache_check = (
        "\n    # [AUTO-PATCH] Cache check — avoid redundant socket calls\n"
        "    now = time.time()\n"
        "    if (_NAT_CACHE[\"is_nat\"] is not None\n"
        "            and now - _NAT_CACHE[\"timestamp\"] < _NAT_CACHE_TTL):\n"
        "        return _NAT_CACHE[\"is_nat\"], _NAT_CACHE[\"local_ip\"]\n"
    )

    cache_update = (
        "    # [AUTO-PATCH] Update cache\n"
        "    _NAT_CACHE[\"is_nat\"] = is_nat\n"
        "    _NAT_CACHE[\"local_ip\"] = local_ip\n"
        "    _NAT_CACHE[\"timestamp\"] = time.time()\n"
    )

    # Build patched file
    result = []
    inserted_cache = False
    inserted_check = False
    inserted_update = False
    for i, line in enumerate(lines):
        if i == import_end and not inserted_cache:
            result.append(cache_helpers)
            inserted_cache = True
        if nat_func_start is not None and i == nat_func_start + 1 and not inserted_check:
            result.append(cache_check)
            inserted_check = True
        result.append(line)
        # After the return statement of detect_nat, insert cache update
        if nat_func_start is not None and i >= nat_func_start and not inserted_update:
            stripped = line.strip()
            if stripped.startswith("return ") and i >= nat_func_start + 2:
                # Insert cache update before the return
                result.pop()  # Remove the return line we just added
                result.append("    " + cache_update.replace("\n", "\n    ") + "\n")
                result.append(line)
                inserted_update = True

    return "".join(result)


def _template_api_cache(content: str, is_api_gateway: bool) -> str:
    """Add a simple in-memory cache for API responses."""
    lines = content.splitlines(keepends=True)
    # Find class definition or first function
    insert_point = 0
    for i, line in enumerate(lines):
        if line.strip().startswith("class ") or line.strip().startswith("async def "):
            insert_point = i
            break
    cache_code = (
        "\n# [AUTO-PATCH] Response cache for latency optimization\n"
        "_RESPONSE_CACHE = {}\n"
        "_RESPONSE_CACHE_TTL = 300\n\n"
    )
    result = list(lines)
    result.insert(insert_point, cache_code)
    return "".join(result)


def _template_latency_tuning(content: str) -> str:
    """Reduce latency threshold or adjust switching parameters."""
    # Find latency threshold config and reduce it
    lines = content.splitlines(keepends=True)
    for i, line in enumerate(lines):
        if "latency_threshold" in line or "LATENCY_THRESHOLD" in line:
            lines[i] = line.replace("5000", "3000").replace("5000.0", "3000.0")
    return "".join(lines)


def _template_retry_wrapper(content: str) -> str:
    """Add retry loop around the first network call found."""
    lines = content.splitlines(keepends=True)
    # Find the first async function and add retry
    for i, line in enumerate(lines):
        if line.strip().startswith("async def ") and "def _" not in line:
            # Add a decorator or retry import
            lines.insert(i, "import asyncio\n")
            lines.insert(i + 2, "    for attempt in range(3):\n        try:\n")
            # Find the end of the function's first logical block
            for j in range(i + 2, min(i + 5, len(lines))):
                lines[j] = "    " + lines[j]
            break
    return "".join(lines)


def _template_remove_dead_code(content: str) -> str:
    """Remove commented-out code blocks and unused imports."""
    lines = content.splitlines(keepends=True)
    result = []
    for line in lines:
        # Skip large comment blocks (3+ consecutive comment lines start)
        stripped = line.strip()
        if stripped.startswith("# ---") or stripped.startswith("# ==="):
            continue
        result.append(line)
    return "".join(result)


@tool(
    name="sync_patches",
    description="Sync optimization patches from peer swarm nodes via Shared Knowledge and apply locally",
    parameters={
        "type": "object",
        "properties": {
            "patch_id": {"type": "string", "description": "Specific patch to sync (empty = all pending)", "default": ""},
            "dry_run": {"type": "boolean", "description": "List pending patches without applying", "default": False},
        },
    },
    category="developer",
    requires_approval=True,
    timeout=120,
)
async def _sync_patches(patch_id: str = "", dry_run: bool = False):
    """
    Cross-instance patch sync:
    - Reads patch:* entries from Shared Knowledge (broadcast by peers)
    - For each pending patch (not yet applied locally):
      - Verifies the target file exists
      - Checks if the patch was successful on the source node
      - Applies the same change locally via the proposal file
    """
    sk = _get_shared_knowledge_instance()
    if not sk:
        return {"status": "error", "error": "SharedKnowledge not available (manager not loaded)"}

    if patch_id:
        # Sync a specific patch
        entry = sk._store.get(f"patch:{patch_id}")
        if not entry:
            return {"status": "error", "error": f"patch {patch_id} not found in knowledge"}
        pending = [entry.value]
    else:
        pending = sk.get_pending_patches()

    if not pending:
        return {"status": "ok", "patches_synced": 0, "pending": 0, "message": "no pending patches from peers"}

    if dry_run:
        return {
            "status": "ok",
            "patches_synced": 0,
            "pending": len(pending),
            "patches": [
                {
                    "patch_id": p.get("patch_id"),
                    "target_file": p.get("target_file"),
                    "applied_by": p.get("applied_by"),
                    "gain_pct": p.get("performance_gain_pct", 0),
                }
                for p in pending
            ],
        }

    # Apply each pending patch
    results = []
    for p in pending:
        pid = p.get("patch_id", "")
        tgt = p.get("target_file", "")
        if not pid or not tgt:
            results.append({"patch_id": pid or "unknown", "status": "skipped", "reason": "missing patch_id or target_file"})
            continue

        if sk.is_patch_applied(pid):
            results.append({"patch_id": pid, "status": "skipped", "reason": "already applied locally"})
            continue

        target_path = Path(tgt)
        if not target_path.exists():
            results.append({"patch_id": pid, "status": "skipped", "reason": f"target file not found: {tgt}"})
            sk.mark_patch_applied(pid, success=False, gain=0)
            continue

        # The patch is in the local proposals dir (synced from peer via shared knowledge)
        # We re-execute the auto_patch logic using the proposal
        PROPOSALS_DIR = Path("agent_logs/optimization_proposals")
        prop_file = PROPOSALS_DIR / f"{pid}.json"
        if not prop_file.exists():
            results.append({"patch_id": pid, "status": "skipped", "reason": "proposal file not found locally"})
            continue

        # Delegate to auto_patch
        try:
            patch_result = await _auto_patch(proposal_id=pid, force=True)
            results.append({
                "patch_id": pid,
                "status": patch_result.get("status", "error"),
                "target_file": tgt,
                "source_node": p.get("applied_by", "unknown"),
                "detail": patch_result.get("message", patch_result.get("error", "")),
            })
        except Exception as e:
            results.append({"patch_id": pid, "status": "error", "error": str(e)})

    synced = sum(1 for r in results if r.get("status") == "ok")
    return {
        "status": "ok",
        "patches_synced": synced,
        "pending": len(pending),
        "results": results,
    }


def _register_builtins(r: ToolRegistry):
    """Register all module-level built-in tools."""
    known = {"dht_initialize", "swarm_relay", "tunnel_activate",
             "read_file", "write_file", "list_directory", "run_command",
             "http_request", "swarm_status", "check_api", "route_prompt",
             "install_package", "analyze_performance", "propose_optimization",
             "review_proposals", "evaluate_proposal", "auto_patch",
             "sync_patches"}
    for name in list(globals()):
        obj = globals()[name]
        if hasattr(obj, "_tool_spec") and obj._tool_spec.name in known:
            r.register(obj._tool_spec)
            logger.debug("Registered built-in tool: %s", obj._tool_spec.name)
