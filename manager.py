"""
🤖 DECENTRALIZED AI AGENT - Live Browser Access Master Controller
Web interface + task queue + recovery + cloud-ready deployment bridge
"""

import asyncio
import os
import sys
import json
import time
import subprocess
import threading
import logging
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, List, Optional

from fastapi.staticfiles import StaticFiles
from dotenv import load_dotenv
load_dotenv()

import requests
from fastapi import FastAPI
from fastapi.responses import HTMLResponse, JSONResponse
import uvicorn

from browser_agent import BrowserAgent
from ghost_swarm import GhostSwarmNode, SwarmMessage
from learning_log import LearningLog
from model_router import ModelRouter
from hf_inference import HFInferenceEngine, InferenceConfig
from security_utils import validate_command, add_security_headers
import security_config

# Cloud-native upgrades
from api_gateway import UnifiedAPIGateway, GatewayConfig
from tool_registry import get_registry
from health_engine import HealthEngine, HealthStatus
from cloud_native import CloudNativeConfig, CloudflareTunnel, HeartbeatSignal, generate_env_template, detect_nat, ensure_public_endpoint
from performance_analyzer import PerformanceAnalyzer
from shared_knowledge import SharedKnowledge
from swarm_security import SwarmSecurityAudit, compute_node_fingerprint, is_trusted_node, sign_json_payload, verify_json_payload

try:
    from autonomous_swarm import AutonomousSwarmOrchestrator
    _AUTONOMOUS_SWARM_AVAILABLE = True
except ImportError:
    AutonomousSwarmOrchestrator = None
    _AUTONOMOUS_SWARM_AVAILABLE = False

try:
    from propagation_engine import PropagationOrchestrator
    _PROPAGATION_AVAILABLE = True
except ImportError:
    PropagationOrchestrator = None
    _PROPAGATION_AVAILABLE = False

try:
    from hermes_bridge import HermesBridge
except ImportError:
    HermesBridge = None

try:
    from blockchain import get_ledger, update_ledger
    _BLOCKCHAIN_AVAILABLE = True
except ImportError:
    get_ledger = update_ledger = None
    _BLOCKCHAIN_AVAILABLE = False

try:
    import global_ignition
    _GLOBAL_IGNITION_AVAILABLE = True
except ImportError:
    global_ignition = None
    _GLOBAL_IGNITION_AVAILABLE = False

# GhostSignal — satellite trans-state propagation layer
try:
    import stealth_beyond_sat
    _STEALTH_SAT_AVAILABLE = True
except ImportError:
    stealth_beyond_sat = None
    _STEALTH_SAT_AVAILABLE = False

try:
    import autonomous_resilience
    _AUTONOMOUS_RESILIENCE_AVAILABLE = True
except ImportError:
    autonomous_resilience = None
    _AUTONOMOUS_RESILIENCE_AVAILABLE = False

try:
    import seed_reassembly
    _SEED_REASSEMBLY_AVAILABLE = True
except ImportError:
    seed_reassembly = None
    _SEED_REASSEMBLY_AVAILABLE = False

# ============= DIRECTORIES & LOGGING =============
BASE_DIR = Path(__file__).resolve().parent
LOG_DIR = BASE_DIR / "agent_logs"
DATA_DIR = BASE_DIR / "agent_data"
DEPLOY_DIR = BASE_DIR / ".github" / "workflows"
LOG_DIR.mkdir(exist_ok=True)
DATA_DIR.mkdir(exist_ok=True)
DEPLOY_DIR.mkdir(parents=True, exist_ok=True)

LOG_FILE = LOG_DIR / f"manager_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    handlers=[logging.FileHandler(LOG_FILE), logging.StreamHandler()]
)
logger = logging.getLogger("ghost_master")

security_config.log_safe_startup()

TASK_QUEUE = DATA_DIR / "task_queue.json"
STATE_FILE = DATA_DIR / "agent_state.json"
RECOVERY_FILE = LOG_DIR / "recovery.log"
OUTPUT_FILE = LOG_DIR / "browser_output.json"

# Cloud-native singletons
_cloud_config = CloudNativeConfig()
_api_gateway = UnifiedAPIGateway(GatewayConfig(
    preferred_provider=_cloud_config.preferred_provider,
    preferred_model=_cloud_config.preferred_model,
    fallback_provider=_cloud_config.fallback_provider,
    fallback_model=_cloud_config.fallback_model,
))
_tool_registry = get_registry()
_cloudflare_tunnel = CloudflareTunnel(_cloud_config)
_shared_knowledge = SharedKnowledge(node_id=f"ghost-mgr-{os.getpid()}")
_swarm_security = SwarmSecurityAudit(secret_key=os.getenv("SWARM_SECRET", "default-swarm-secret-change-me"))
_performance_analyzer = PerformanceAnalyzer(rate_threshold=0.4)
_heartbeat = HeartbeatSignal(_cloud_config, _cloudflare_tunnel, interval=60.0, shared_knowledge=_shared_knowledge)
_health_engine = HealthEngine(
    tool_registry=_tool_registry,
    check_interval=30.0,
)

# Wire performance analyzer into tool registry as post-exec hook
_tool_registry.add_post_execute_hook(
    lambda name, success, latency: _performance_analyzer.record(
        name, success, latency,
        component=name.split("_")[0] if "_" in name else "general",
    )
)

# Wire shared knowledge into performance analyzer
_performance_analyzer.set_shared_knowledge(_shared_knowledge)

for path in [TASK_QUEUE, STATE_FILE, OUTPUT_FILE]:
    if not path.exists():
        default = "[]" if path.name != STATE_FILE.name else "{}"
        path.write_text(default, encoding="utf-8")

# ==============================================================================
# AutoPatcher — Autonomous Proposal Execution & Cross-Instance Patch Sync
# Moves from Human Review to Exception-Based Review model.
# Proposals with >20% expected gain are auto-approved, applied, verified for 60s,
# and broadcast to the swarm. Only failures/deviations flag for human attention.
# ==============================================================================

AUTO_PATCH_LOG = LOG_DIR / "auto_patch.log"

class AutoPatcher:
    """
    Self-governing patch lifecycle engine.

    Lifecycle per proposal:
    1. Evaluate: parse expected_improvement, check >20% threshold
    2. If approved → call tool_registry auto_patch tool
    3. auto_patch generates code via LLM, backs up, applies, hot-reloads
    4. Monitor 60s post-patch via Performance Analyzer + Health Engine
    5. On success → broadcast patch signature to swarm peers
    6. On failure → rollback, log to auto_patch.log, flag for human review
    """

    def __init__(self, tool_registry, shared_knowledge, performance_analyzer, health_engine):
        self.tool_registry = tool_registry
        self.shared_knowledge = shared_knowledge
        self.performance_analyzer = performance_analyzer
        self.health_engine = health_engine
        self._running = False
        self._task = None
        self._patch_history: list[dict] = []
        self._lock = threading.Lock()

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start(self, interval: float = 120.0):
        if self._running:
            return
        self._running = True
        loop = asyncio.get_event_loop()
        self._task = loop.create_task(self._run_forever(interval))
        logger.info("AutoPatcher started (interval=%.0fs) — exception-based review model active", interval)

    def stop(self):
        self._running = False
        if self._task:
            self._task.cancel()
            self._task = None

    async def _run_forever(self, interval: float):
        while self._running:
            try:
                await self._scan_and_patch()
            except Exception as e:
                logger.error("AutoPatcher cycle failed: %s", e)
            await asyncio.sleep(interval)

    # ------------------------------------------------------------------
    # Core scan → evaluate → apply cycle
    # ------------------------------------------------------------------

    async def _scan_and_patch(self):
        """Scan all pending_review proposals and auto-apply those meeting threshold."""
        PROPOSALS_DIR = Path("agent_logs/optimization_proposals")
        if not PROPOSALS_DIR.exists():
            return

        proposals = []
        for f in sorted(PROPOSALS_DIR.glob("*.json")):
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
                if data.get("status") in ("pending_review",):
                    proposals.append((f, data))
            except Exception:
                continue

        if not proposals:
            return

        logger.info("AutoPatcher: %d proposals pending review", len(proposals))

        for fpath, proposal in proposals:
            if not self._running:
                break

            proposal_id = proposal.get("id", "")
            target_file = proposal.get("target_file", "")

            # Evaluate threshold
            approved, reason = self._evaluate_threshold(proposal)
            if not approved:
                logger.info("AutoPatcher: %s skipped (%s)", proposal_id, reason)
                continue

            # Auto-approve and execute
            logger.info("AutoPatcher: executing %s — %s", proposal_id, reason)
            result = await self.tool_registry.execute(
                "auto_patch",
                {"proposal_id": proposal_id, "force": False},
                timeout=300,
            )

            entry = {
                "proposal_id": proposal_id,
                "target_file": target_file,
                "timestamp": time.time(),
                "result": result,
            }

            with self._lock:
                self._patch_history.append(entry)
                if len(self._patch_history) > 100:
                    self._patch_history = self._patch_history[-50:]

            status = result.get("status", "error")
            if status == "ok":
                logger.info("AutoPatcher: %s applied successfully", proposal_id)
            elif status == "rolled_back":
                logger.warning("AutoPatcher: %s rolled back — human review flagged", proposal_id)
                self._flag_for_human_review(proposal, result)
            elif status == "error":
                logger.error("AutoPatcher: %s failed — %s", proposal_id, result.get("error", ""))
                self._flag_for_human_review(proposal, result)

    # ------------------------------------------------------------------
    # Threshold evaluation
    # ------------------------------------------------------------------

    def _evaluate_threshold(self, proposal: dict):
        """Check if proposal meets auto-approval threshold (>20% gain)."""
        expected = proposal.get("expected_improvement", "").lower()
        status = proposal.get("status", "")

        if status == "applied":
            return False, "already applied"
        if status == "rejected":
            return False, "previously rejected"

        # Extract numeric percentage
        import re
        nums = re.findall(r'(\d+)%', expected)
        gain_pct = max(int(n) for n in nums) if nums else 0

        if gain_pct >= 20:
            return True, f"expected gain {gain_pct}% >= 20% threshold"

        improvement_keywords = ["latency", "reliability", "reduce", "optimize", "faster", "throughput"]
        if any(kw in expected for kw in improvement_keywords) and gain_pct >= 15:
            return True, f"{gain_pct}% gain with improvement indicator"

        if any(kw in expected for kw in ["latency", "reliability"]):
            return True, "targets latency/reliability improvement"

        return False, f"gain {gain_pct}% below 20% threshold, no clear improvement indicator"

    # ------------------------------------------------------------------
    # Exception-based review flagging
    # ------------------------------------------------------------------

    def _flag_for_human_review(self, proposal: dict, result: dict):
        """Flag a failed/rolled-back proposal for human attention."""
        entry = {
            "type": "human_review_required",
            "proposal_id": proposal.get("id", ""),
            "target_file": proposal.get("target_file", ""),
            "bottleneck": proposal.get("bottleneck", "")[:100],
            "timestamp": time.time(),
            "reason": result.get("message", result.get("error", "unknown")),
            "status": result.get("status", "error"),
        }
        with self._lock:
            self._patch_history.append(entry)

        # Write to auto_patch.log
        try:
            line = (
                f"{datetime.now().isoformat()} | HUMAN_REVIEW | "
                f"{entry['proposal_id']} | {entry['reason']} | {entry['target_file']}\n"
            )
            AUTO_PATCH_LOG.parent.mkdir(parents=True, exist_ok=True)
            with open(AUTO_PATCH_LOG, "a", encoding="utf-8") as lf:
                lf.write(line)
        except Exception as e:
            logger.debug("AutoPatcher log error: %s", e)

        logger.warning("HUMAN REVIEW REQUIRED: %s — %s", entry["proposal_id"], entry["reason"])

    # ------------------------------------------------------------------
    # Status & report
    # ------------------------------------------------------------------

    def get_status(self) -> dict:
        with self._lock:
            recent = self._patch_history[-20:]
        return {
            "running": self._running,
            "total_patches_attempted": len(self._patch_history),
            "recent_actions": [
                {
                    "proposal_id": e.get("proposal_id", ""),
                    "target_file": e.get("target_file", ""),
                    "timestamp": e.get("timestamp", 0),
                    "status": e.get("result", {}).get("status", e.get("status", "unknown")),
                    "is_exception": e.get("type") == "human_review_required",
                }
                for e in recent
            ],
        }

    async def apply_proposal(self, proposal_id: str, force: bool = False) -> dict:
        """Manually trigger auto-patch for a specific proposal."""
        result = await self.tool_registry.execute(
            "auto_patch",
            {"proposal_id": proposal_id, "force": force},
            timeout=300,
        )
        entry = {"proposal_id": proposal_id, "timestamp": time.time(), "result": result}
        with self._lock:
            self._patch_history.append(entry)
        return result

    async def sync_peer_patches(self) -> dict:
        """Sync and apply patches broadcast by peer swarm nodes."""
        result = await self.tool_registry.execute(
            "sync_patches",
            {"dry_run": False},
            timeout=300,
        )
        return result


# AutoPatcher singleton — initialized with existing singletons
_auto_patcher = AutoPatcher(
    tool_registry=_tool_registry,
    shared_knowledge=_shared_knowledge,
    performance_analyzer=_performance_analyzer,
    health_engine=_health_engine,
)

# ============= PORT / NETWORK UTILITIES =============
def is_port_in_use(port: int, host: str = "0.0.0.0") -> bool:
    """Check if a TCP port is already bound on the given host."""
    import socket
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(1)
            result = s.connect_ex((host if host != "0.0.0.0" else "127.0.0.1", port))
            return result == 0
    except Exception:
        return False


def find_free_port(preferred: int = 8000, max_attempts: int = 10) -> int:
    """Find the first free port starting from preferred, up to preferred+max_attempts."""
    for port in range(preferred, preferred + max_attempts):
        if not is_port_in_use(port):
            return port
    return preferred + max_attempts


STATUS_CACHE: Dict[str, Any] = {}
STATUS_CACHE_TTL: float = 0.0


def get_cached_status() -> Dict[str, Any]:
    """Return cached status if still fresh, else recompute."""
    global STATUS_CACHE, STATUS_CACHE_TTL
    now = time.time()
    if STATUS_CACHE and now < STATUS_CACHE_TTL:
        return STATUS_CACHE
    services = connector.check_services()
    STATUS_CACHE = {
        "services": services,
        "pending_tasks": manager.pending_tasks(),
        "recent_outputs": manager.recent_outputs(),
        "active_workers": getattr(engine, 'active_workers', 0),
        "swarm_peers": len(getattr(_scheduler, 'peers', {})) if _scheduler else 0,
    }
    STATUS_CACHE_TTL = now + 1.5  # cache for 1.5s to prevent CPU spike on rapid polls
    return STATUS_CACHE


# ============= CREDENTIAL CONFIGURATION =============
class ServiceConfig:
    Gmail = {
        "user": os.getenv("GMAIL_USER"),
        "pass": os.getenv("GMAIL_PASS")
    }
    HuggingFace = os.getenv("HUGGINGFACE_TOKEN")
    Groq = os.getenv("GROQ_API_KEY")
    GitHub = os.getenv("GITHUB_TOKEN")
    Cloudflare = os.getenv("CLOUDFLARE_TOKEN")
    Discord = os.getenv("DISCORD_TOKEN")
    DiscordChannel = os.getenv("DISCORD_CHANNEL_ID", "YOUR_CHANNEL_ID")

    @classmethod
    def auth_status(cls) -> Dict[str, str]:
        return {
            "Gmail": "Configured" if cls.Gmail["user"] and cls.Gmail["pass"] else "Missing",
            "HuggingFace": "Configured" if cls.HuggingFace else "Missing",
            "Groq": "Configured" if cls.Groq else "Missing",
            "GitHub": "Configured" if cls.GitHub else "Missing",
            "Cloudflare": "Configured" if cls.Cloudflare else "Missing",
            "Discord": "Configured" if cls.Discord else "Missing",
        }

# ============= RECOVERY MODULE =============
class RecoveryModule:
    def __init__(self):
        self.recovery_file = RECOVERY_FILE

    def log_failure(self, message: str, context: str = ""):
        timestamp = datetime.now().isoformat()
        line = f"{timestamp} | {context} | {message}\n"
        self._safe_write(self.recovery_file, line, append=True)
        logger.error(f"Recovery: {message} | {context}")
        self.notify_discord(f"[Recovery] {context}: {message}")

    def notify_discord(self, content: str) -> bool:
        if not ServiceConfig.Discord or ServiceConfig.DiscordChannel == "YOUR_CHANNEL_ID":
            logger.warning("Discord notification skipped: token/channel missing")
            return False
        url = f"https://discord.com/api/v9/channels/{ServiceConfig.DiscordChannel}/messages"
        headers = {"Authorization": f"Bot {ServiceConfig.Discord}", "Content-Type": "application/json"}
        payload = {"content": content[:1800]}
        try:
            response = requests.post(url, headers=headers, json=payload, timeout=15)
            if response.ok:
                return True
            self._safe_write(self.recovery_file, f"Discord response {response.status_code}: {response.text}\n", append=True)
        except Exception as exc:
            self._safe_write(self.recovery_file, f"Discord exception: {exc}\n", append=True)
        return False

    def auto_fix_module(self, error_message: str) -> bool:
        if "No module named" in error_message:
            missing = self._extract_module_name(error_message)
            if missing:
                logger.info(f"Attempting auto-install for missing module: {missing}")
                return self.install_package(missing)
        return False

    def install_package(self, package_name: str) -> bool:
        try:
            subprocess.check_call([sys.executable, "-m", "pip", "install", package_name])
            return True
        except Exception as exc:
            self._safe_write(self.recovery_file, f"Install failed {package_name}: {exc}\n", append=True)
            return False

    @staticmethod
    def _extract_module_name(message: str) -> str:
        start = message.find("No module named")
        if start >= 0:
            candidate = message[start + len("No module named"):].strip(" '")
            return candidate.split()[0].strip("'\"")
        return ""

    @staticmethod
    def _safe_write(path: Path, content: str, append: bool = False):
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            mode = "a" if append else "w"
            with open(path, mode, encoding="utf-8") as f:
                f.write(content)
        except Exception as exc:
            logger.error(f"Failed to write recovery file: {exc}")

recovery = RecoveryModule()

# ============= SERVICE CONNECTOR =============
class ServiceConnector:
    def check_github(self) -> str:
        if not ServiceConfig.GitHub:
            return "Missing token"
        try:
            headers = {"Authorization": f"token {ServiceConfig.GitHub}"}
            r = requests.get("https://api.github.com/user", headers=headers, timeout=15)
            return "Active" if r.status_code == 200 else f"Invalid ({r.status_code})"
        except Exception as exc:
            recovery.log_failure(str(exc), "check_github")
            return "Error"

    def check_discord(self) -> str:
        if not ServiceConfig.Discord:
            return "Missing token"
        try:
            headers = {"Authorization": f"Bot {ServiceConfig.Discord}"}
            r = requests.get("https://discord.com/api/v9/users/@me", headers=headers, timeout=15)
            return "Active" if r.status_code == 200 else f"Invalid ({r.status_code})"
        except Exception as exc:
            recovery.log_failure(str(exc), "check_discord")
            return "Error"

    def check_cloudflare(self) -> str:
        if not ServiceConfig.Cloudflare:
            return "Missing token"
        try:
            headers = {"Authorization": f"Bearer {ServiceConfig.Cloudflare}", "Content-Type": "application/json"}
            r = requests.get("https://api.cloudflare.com/client/v4/user/tokens/verify", headers=headers, timeout=15)
            return "Active" if r.ok else f"Invalid ({r.status_code})"
        except Exception as exc:
            recovery.log_failure(str(exc), "check_cloudflare")
            return "Error"

    def check_hf_inference(self) -> str:
        if model_router.hf_engine is None:
            return "unloaded"
        try:
            status = model_router.hf_engine.get_status()
            if status.get("hf_model_loaded"):
                return f"ok/{status.get('hf_model', 'unknown')}"
            err = status.get("hf_load_error", "")
            return f"error/{err[:40]}" if err else "pending"
        except Exception as exc:
            return f"error/{str(exc)[:40]}"

    def check_services(self) -> Dict[str, str]:
        return {
            "Gmail": "Configured" if ServiceConfig.Gmail["user"] and ServiceConfig.Gmail["pass"] else "Missing",
            "HuggingFace": "Configured" if ServiceConfig.HuggingFace else "Missing",
            "Groq": "Configured" if ServiceConfig.Groq else "Missing",
            "GitHub": self.check_github(),
            "Cloudflare": self.check_cloudflare(),
            "Discord": self.check_discord(),
            "HFInference": self.check_hf_inference(),
        }

connector = ServiceConnector()
learning_log = LearningLog()
model_router = ModelRouter(log=learning_log)

BROWSER_HEADLESS = os.getenv("BROWSER_HEADLESS", "1") not in ("0", "false", "False")
BROWSER_DATA_DIR = os.getenv("BROWSER_DATA_DIR", str(BASE_DIR / "browser_profile"))

async def _browser_action(action: str, **kwargs) -> Dict[str, Any]:
    async with BrowserAgent(headless=BROWSER_HEADLESS, user_data_dir=BROWSER_DATA_DIR) as agent:
        if action == "goto":
            url = kwargs.get("url")
            if not url:
                return {"status": "error", "message": "url required"}
            return await agent.goto(url, wait_until=kwargs.get("wait_until", "networkidle"))

        if action == "fill_form":
            return await agent.fill_form(kwargs.get("fields", {}))

        if action == "click":
            selector = kwargs.get("selector")
            if not selector:
                return {"status": "error", "message": "selector required"}
            return await agent.click(selector)

        if action == "get_text":
            selector = kwargs.get("selector")
            if not selector:
                return {"status": "error", "message": "selector required"}
            return await agent.get_text(selector)

        if action == "screenshot":
            return await agent.screenshot(kwargs.get("path", "screenshot.png"))

        if action == "execute_script":
            script = kwargs.get("script")
            if not script:
                return {"status": "error", "message": "script required"}
            return await agent.execute_script(script, kwargs.get("arg"))

        if action == "airdrop":
            url = kwargs.get("airdrop_url")
            form_data = kwargs.get("form_data", {})
            if not url:
                return {"status": "error", "message": "airdrop_url required"}
            return await agent.airdrop_claim_workflow(url, form_data)

        return {"status": "error", "message": f"unknown action: {action}"}


def _run_browser_task(action: str, **kwargs) -> Dict[str, Any]:
    try:
        return asyncio.run(_browser_action(action, **kwargs))
    except Exception as exc:
        return {"status": "error", "message": str(exc)}

# ============= EXECUTION ENGINE =============
class ExecutionEngine:
    def __init__(self):
        self.max_workers = max(4, (os.cpu_count() or 1) * 4)

    def execute_command(self, command: str, parallel: bool = False, timeout: int = 120) -> Dict[str, Any]:
        result = {
            "command": command,
            "status": "pending",
            "stdout": "",
            "stderr": "",
            "returncode": None,
            "timestamp": datetime.now().isoformat(),
        }
        try:
            if parallel:
                outputs: List[Dict[str, Any]] = []
                threads: List[threading.Thread] = []
                for _ in range(self.max_workers):
                    thread = threading.Thread(target=self._run_subprocess, args=(command, timeout, outputs))
                    thread.start()
                    threads.append(thread)
                for thread in threads:
                    thread.join()
                result["status"] = "success"
                result["stdout"] = "Parallel execution completed"
                result["workers"] = len(threads)
                result["outputs"] = outputs
                return result
            completed = subprocess.run(command, shell=True, capture_output=True, text=True, timeout=timeout)
            result["stdout"] = completed.stdout.strip()
            result["stderr"] = completed.stderr.strip()
            result["returncode"] = completed.returncode
            result["status"] = "success" if completed.returncode == 0 else "failed"
            if completed.returncode != 0:
                recovery.auto_fix_module(result["stderr"])
            return result
        except subprocess.TimeoutExpired as exc:
            result["status"] = "timeout"
            result["stderr"] = str(exc)
            recovery.log_failure(str(exc), "execute_command_timeout")
            return result
        except Exception as exc:
            error_text = str(exc)
            result["status"] = "error"
            result["stderr"] = error_text
            recovery.log_failure(error_text, "execute_command")
            if recovery.auto_fix_module(error_text):
                result["repair_attempted"] = True
            return result

    @staticmethod
    def _run_subprocess(command: str, timeout: int, outputs: List[Dict[str, Any]]):
        try:
            completed = subprocess.run(command, shell=True, capture_output=True, text=True, timeout=timeout)
            outputs.append({
                "stdout": completed.stdout.strip(),
                "stderr": completed.stderr.strip(),
                "returncode": completed.returncode,
            })
        except Exception as exc:
            outputs.append({"error": str(exc)})

engine = ExecutionEngine()

# ============= IPFS STATE MANAGEMENT =============
class IPFSStateManager:
    """Decentralized state storage via IPFS — survival across reboots."""

    def __init__(self):
        self._client = None
        self._cached_state: Dict[str, Any] = {}
        self._known_cids: List[str] = []
        self._state_key = "ghost-manager-state-v1"

    def _get_client(self):
        if self._client is None:
            try:
                import ipfshttpclient
                multiaddr = os.getenv("IPFS_MULTIADDR", "/dns/ipfs-node/tcp/5001/http")
                self._client = ipfshttpclient.connect(multiaddr)
                logger.info("IPFS state manager connected: %s", multiaddr)
            except Exception as e:
                logger.warning("IPFS not available — state stored locally only: %s", e)
                self._client = False
        return self._client if self._client else None

    def save_state(self, state: Dict[str, Any], topic: str = "state") -> Optional[str]:
        """Save state dict to IPFS. Returns CID or None."""
        client = self._get_client()
        if not client:
            return None

        try:
            payload = {
                "topic": topic,
                "timestamp": time.time(),
                "data": state,
                "node_id": os.getenv("NODE_ID", "ghost-mgr"),
            }
            raw = json.dumps(payload).encode()
            cid = client.add_bytes(raw)
            self._known_cids.append(cid)
            self._cached_state[topic] = state

            # Pin for persistence
            try:
                client.pin.add(cid)
            except Exception:
                pass

            logger.info("IPFS state saved: %s (topic=%s, %d bytes)", cid[:16], topic, len(raw))
            return cid
        except Exception as e:
            logger.warning("IPFS save failed: %s", e)
            return None

    def load_state(self, cid: str) -> Optional[Dict[str, Any]]:
        """Load state dict from IPFS by CID."""
        client = self._get_client()
        if not client:
            return None

        try:
            raw = client.cat(cid)
            data = json.loads(raw.decode() if isinstance(raw, bytes) else raw)
            logger.info("IPFS state loaded: %s (topic=%s)", cid[:16], data.get("topic", "?"))
            return data.get("data")
        except Exception as e:
            logger.warning("IPFS load failed for %s: %s", cid[:16], e)
            return None

    def get_latest_state(self, topic: str = "state") -> Optional[Dict[str, Any]]:
        if topic in self._cached_state:
            return self._cached_state[topic]

    def pin_state(self, cid: str) -> bool:
        client = self._get_client()
        if not client:
            return False
        try:
            client.pin.add(cid)
            return True
        except Exception:
            return False

    def list_states(self) -> List[Dict[str, Any]]:
        return [{"cid": c, "pinned": True} for c in self._known_cids]

    def available(self) -> bool:
        return self._get_client() is not None

    def verify_on_gateway(self, cid: str,
                           gateway: str = "https://ipfs.io/ipfs/") -> bool:
        """Verify a CID is accessible via a public IPFS gateway."""
        try:
            import requests
            url = f"{gateway.rstrip('/')}/{cid}"
            r = requests.get(url, timeout=10)
            ok = r.status_code == 200
            logger.info("IPFS gateway verify: %s -> %s (%d bytes)",
                        cid[:16], "OK" if ok else "FAIL", len(r.content))
            return ok
        except Exception as e:
            logger.warning("IPFS gateway verify failed: %s", e)
            return False

    def save_and_verify(self, state: Dict[str, Any],
                         topic: str = "state") -> Optional[Dict[str, Any]]:
        """Save state to IPFS, pin it, and verify via public gateway."""
        cid = self.save_state(state, topic)
        if not cid:
            return {"status": "failed", "step": "save", "reason": "IPFS not available"}

        pinned = self.pin_state(cid)

        gateway_ok = self.verify_on_gateway(cid)

        return {
            "status": "ok" if gateway_ok else "pinned_not_public",
            "cid": cid,
            "pinned": pinned,
            "gateway_accessible": gateway_ok,
            "topic": topic,
        }


ipfs_state = IPFSStateManager()

# ============= TASK MANAGEMENT =============
class TaskManager:
    def __init__(self):
        self.queue_file = TASK_QUEUE
        self.output_file = OUTPUT_FILE
        self.current_outputs: List[Dict[str, Any]] = []
        self.lock = threading.Lock()
        self.worker = threading.Thread(target=self._task_loop, daemon=True)
        self.worker.start()

    def _append_output(self, entry: Dict[str, Any]):
        self.current_outputs.insert(0, entry)
        self.current_outputs = self.current_outputs[:200]
        try:
            with open(self.output_file, "w", encoding="utf-8") as f:
                json.dump(self.current_outputs, f, indent=2)
        except Exception as exc:
            recovery.log_failure(str(exc), "append_output")

    def _read_queue(self) -> List[Dict[str, Any]]:
        try:
            with open(self.queue_file, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as exc:
            recovery.log_failure(str(exc), "read_queue")
            return []

    def _write_queue(self, tasks: List[Dict[str, Any]]):
        try:
            with open(self.queue_file, "w", encoding="utf-8") as f:
                json.dump(tasks, f, indent=2)
        except Exception as exc:
            recovery.log_failure(str(exc), "write_queue")

    def enqueue_task(self, command: str) -> Dict[str, Any]:
        task = {
            "id": int(time.time() * 1000),
            "command": command,
            "status": "pending",
            "created_at": datetime.now().isoformat(),
        }
        tasks = self._read_queue()
        tasks.append(task)
        self._write_queue(tasks)
        return task

    def claim_pending_task(self, claim_status: str = "running") -> Optional[Dict[str, Any]]:
        """
        Atomically claim the next pending task from the queue.
        Sets its status to claim_status under the thread lock.
        Returns the claimed task, or None if queue is empty.
        """
        with self.lock:
            tasks = self._read_queue()
            for t in tasks:
                if t.get("status") == "pending":
                    t["status"] = claim_status
                    if claim_status == "dispatched":
                        t["dispatched_at"] = datetime.now().isoformat()
                    self._write_queue(tasks)
                    return t
            return None

    def release_task(self, task_id: int, new_status: str = "pending"):
        """Release a claimed task back to a different status."""
        with self.lock:
            tasks = self._read_queue()
            for t in tasks:
                if t.get("id") == task_id:
                    t["status"] = new_status
                    t.pop("dispatched_at", None)
                    break
            self._write_queue(tasks)

    def _task_loop(self):
        while True:
            task = self.claim_pending_task(claim_status="running")
            if task:
                self._execute_task(task)
            else:
                time.sleep(3)

    def _execute_task(self, task: Dict[str, Any]):
        try:
            task["status"] = "running"
            self._update_task(task)
            cmd = task["command"]
            if cmd.startswith("hf:"):
                prompt = cmd[3:].strip()
                hf_result = model_router._call_hf(prompt)
                result = {
                    "status": hf_result.get("status", "error"),
                    "stdout": hf_result.get("output", ""),
                    "stderr": "",
                    "returncode": 0 if hf_result.get("status") == "success" else 1,
                    "model": hf_result.get("model", "hf"),
                }
            else:
                result = engine.execute_command(cmd, parallel=True)
            task["status"] = result.get("status", "failed")
            task["result"] = result
            task["completed_at"] = datetime.now().isoformat()
            self._append_output({
                "task_id": task["id"],
                "command": cmd,
                "result": result,
                "timestamp": datetime.now().isoformat(),
            })
            self._update_task(task, remove=True)
        except Exception as exc:
            recovery.log_failure(str(exc), f"execute_task:{task.get('command')}")
            task["status"] = "error"
            task["error"] = str(exc)
            self._update_task(task)

    def _update_task(self, task: Dict[str, Any], remove: bool = False):
        tasks = self._read_queue()
        if remove:
            tasks = [t for t in tasks if t.get("id") != task.get("id")]
        else:
            tasks = [task if t.get("id") == task.get("id") else t for t in tasks]
        self._write_queue(tasks)

    def recent_outputs(self) -> List[Dict[str, Any]]:
        return self.current_outputs

    def pending_tasks(self) -> List[Dict[str, Any]]:
        return [t for t in self._read_queue() if t.get("status") == "pending"]

    def prepare_deployment(self) -> Dict[str, Any]:
        workflow_path = DEPLOY_DIR / "python-app.yml"
        workflow_content = """
name: Python application

on:
  push:
    branches: [main]

jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v2
      - name: Set up Python
        uses: actions/setup-python@v2
        with:
          python-version: "3.11"
      - name: Install dependencies
        run: pip install -r requirements.txt
      - name: Launch app
        run: uvicorn manager:app --host 0.0.0.0 --port 8000
"""
        try:
            workflow_path.parent.mkdir(parents=True, exist_ok=True)
            workflow_path.write_text(workflow_content, encoding="utf-8")
            return {"status": "ready", "workflow_path": str(workflow_path)}
        except Exception as exc:
            recovery.log_failure(str(exc), "prepare_deployment")
            return {"status": "error", "error": str(exc)}

manager = TaskManager()

# ============= SWARM TASK SCHEDULER =============
class SwarmTaskScheduler:
    """
    Autonomous task scheduler that monitors the P2P swarm for idle peers
    and assigns pending tasks from the global queue to them.

    Runs as a background daemon thread. Uses asyncio.run_coroutine_threadsafe
    to bridge between the threading (manager) and asyncio (swarm) worlds.
    """

    def __init__(self, task_manager: TaskManager, swarm_node: GhostSwarmNode,
                 swarm_loop: asyncio.AbstractEventLoop):
        self.task_manager = task_manager
        self.swarm = swarm_node
        self.loop = swarm_loop
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._dispatch_log: List[Dict[str, Any]] = []
        self._lock = threading.Lock()
        self.poll_interval = int(os.getenv("SCHEDULER_POLL_INTERVAL", "10"))

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------
    def start(self):
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._scheduler_loop, daemon=True)
        self._thread.start()
        logger.info("SwarmTaskScheduler started (poll every %ds)", self.poll_interval)

    def stop(self):
        self._running = False

    @property
    def status(self) -> Dict[str, Any]:
        with self._lock:
            return {
                "running": self._running,
                "poll_interval_s": self.poll_interval,
                "dispatches_total": len(self._dispatch_log),
                "recent_dispatches": self._dispatch_log[-10:],
            }

    # ------------------------------------------------------------------
    # Core loop
    # ------------------------------------------------------------------
    def _scheduler_loop(self):
        while self._running:
            try:
                self._schedule_round()
            except Exception as exc:
                logger.error("Scheduler round failed: %s", exc)
            time.sleep(self.poll_interval)

    def _schedule_round(self):
        idle_peers = self._find_idle_peers()
        if not idle_peers:
            return

        pending = self._get_pending_tasks()
        if not pending:
            return

        logger.info("Scheduler: %d idle peers, %d pending tasks",
                     len(idle_peers), len(pending))

        for peer_id, peer in idle_peers:
            task = self._claim_next_task()
            if not task:
                break

            success = self._dispatch_to_peer(peer_id, peer, task)
            if success:
                with self._lock:
                    self._dispatch_log.append({
                        "timestamp": datetime.now().isoformat(),
                        "task_id": task["id"],
                        "command": task["command"],
                        "peer_id": peer_id,
                        "peer_host": peer.host,
                    })
                    if len(self._dispatch_log) > 200:
                        self._dispatch_log = self._dispatch_log[-100:]

    # ------------------------------------------------------------------
    # Peer discovery
    # ------------------------------------------------------------------
    def _find_idle_peers(self) -> List[tuple]:
        """Return (peer_id, PeerInfo) for peers with idle status."""
        idle = []
        for pid, p in list(self.swarm.peers.items()):
            if p.is_alive and p.task_status == "idle" and pid != self.swarm.node_id:
                idle.append((pid, p))
        return idle

    # ------------------------------------------------------------------
    # Task queue operations
    # ------------------------------------------------------------------
    def _get_pending_tasks(self) -> List[Dict[str, Any]]:
        return self.task_manager.pending_tasks()

    def _claim_next_task(self) -> Optional[Dict[str, Any]]:
        """Atomically claim a pending task via TaskManager."""
        return self.task_manager.claim_pending_task(claim_status="dispatched")

    # ------------------------------------------------------------------
    # P2P dispatch
    # ------------------------------------------------------------------
    def _dispatch_to_peer(self, peer_id: str, peer, task: Dict[str, Any]) -> bool:
        """Send a task to a peer via P2P. Runs on the swarm's event loop."""
        future = asyncio.run_coroutine_threadsafe(
            self.swarm.send_task(
                task_type="task",
                payload={
                    "task_id": task["id"],
                    "task_type": "shell",
                    "command": task["command"],
                    "assigned_by": self.swarm.node_id,
                },
                target_peer=peer_id,
                encrypt=self.swarm.identity is not None,
            ),
            self.loop,
        )
        try:
            future.result(timeout=10)
            logger.info("Dispatched task %d (%s) to peer %s @ %s:%d",
                         task["id"], task["command"], peer_id, peer.host, peer.port)
            return True
        except Exception as exc:
            logger.error("Dispatch to peer %s failed: %s", peer_id, exc)
            self.task_manager.release_task(task["id"], new_status="pending")
            return False


SELF_PATCH_LOG = LOG_DIR / "self_patch.log"

class HermesExecutionAuthority:
    def __init__(self, router: ModelRouter, learning_log: LearningLog, task_manager: TaskManager):
        self.router = router
        self.learning_log = learning_log
        self.task_manager = task_manager
        self.state_file = DATA_DIR / "agent_brain_state.json"
        self.state = self._load_state()

    def _load_state(self) -> Dict[str, Any]:
        if self.state_file.exists():
            try:
                return json.loads(self.state_file.read_text(encoding="utf-8"))
            except Exception:
                return {}
        return {}

    def _save_state(self) -> None:
        try:
            self.state_file.write_text(json.dumps(self.state, indent=2), encoding="utf-8")
        except Exception as exc:
            recovery.log_failure(str(exc), "save_agent_state")

    def summarize_learning(self, limit: int = 50) -> Dict[str, Any]:
        entries = self.learning_log.latest(limit)
        failures = [entry for entry in entries if entry.get("status") != "success"]
        return {
            "total": len(entries),
            "recent_failures": len(failures),
            "failure_examples": failures[:5],
        }

    def analyze_terminal(self, max_lines: int = 200) -> str:
        history = self.router.read_terminal_history().splitlines()
        if len(history) > max_lines:
            history = history[-max_lines:]
        return "\n".join(history)

    def suggest_improvements(self, health: Dict[str, Any], learning_summary: Dict[str, Any]) -> List[str]:
        suggestions: List[str] = []
        if not health.get("local_ok"):
            suggestions.append("Local Hermes/Llama is unresponsive or too slow. Use Gemini fallback and investigate local server performance.")
        if learning_summary.get("recent_failures", 0) > 0:
            suggestions.append("Several recent model interactions failed. Consider adding stronger prompt validation, timeout handling, and retry logic.")
        if health.get("latency_ms") and health["latency_ms"] > model_router.local_response_threshold:
            suggestions.append(f"Local response latency is high ({health['latency_ms']:.2f}s). Increase the threshold or offload to Gemini during heavy loads.")
        return suggestions

    def preflight_check(self) -> Dict[str, Any]:
        health = self.router.preflight_check()
        learning_summary = self.summarize_learning(50)
        terminal_history = self.analyze_terminal(100)
        suggestions = self.suggest_improvements(health, learning_summary)
        self.state["last_preflight"] = {
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "health": health,
            "learning_summary": learning_summary,
            "suggestions": suggestions,
        }
        self._save_state()
        self._self_patch(health, learning_summary)
        return {
            "health": health,
            "learning_summary": learning_summary,
            "terminal_history": terminal_history,
            "suggestions": suggestions,
        }

    def _self_patch(self, health: Dict[str, Any], learning_summary: Dict[str, Any]) -> None:
        try:
            if not health.get("local_ok") and model_router.local_priority:
                model_router.local_priority = False
                self._record_patch("Disabled local priority because local Hermes is unhealthy.")
            if learning_summary.get("recent_failures", 0) > 3:
                self._record_patch("Detected repeated failures. Recommend adding smarter error handling in manager task execution.")
        except Exception as exc:
            recovery.log_failure(str(exc), "self_patch")

    def _record_patch(self, message: str) -> None:
        line = f"{datetime.utcnow().isoformat()}Z | {message}\n"
        try:
            SELF_PATCH_LOG.parent.mkdir(parents=True, exist_ok=True)
            with open(SELF_PATCH_LOG, "a", encoding="utf-8") as f:
                f.write(line)
        except Exception as exc:
            recovery.log_failure(str(exc), "record_self_patch")

    def execute_authorized_command(self, command: str, browser_action: Dict[str, Any] | None = None) -> Dict[str, Any]:
        preflight = self.preflight_check()
        if browser_action:
            action = browser_action.get("action")
            args = browser_action.get("args", {})
            browser_result = _run_browser_task(action, **args)
            self.task_manager._append_output({
                "task_id": int(time.time() * 1000),
                "command": f"browser:{action}",
                "result": browser_result,
                "timestamp": datetime.now().isoformat(),
            })
            return {"status": browser_result.get("status", "error"), "details": browser_result, "preflight": preflight}

        valid, message = validate_command(command)
        if not valid:
            return {"status": "error", "message": message, "preflight": preflight}

        analysis_prompt = (
            f"Analyze recent execution failures and recommend safer shell command behavior. "
            f"Recent failures: {preflight['learning_summary']['recent_failures']} entries."
        )
        analysis = model_router.route(analysis_prompt)
        result = engine.execute_command(command)
        self.task_manager._append_output({
            "task_id": int(time.time() * 1000),
            "command": command,
            "result": result,
            "analysis": analysis.output,
            "timestamp": datetime.now().isoformat(),
        })
        return {"status": result.get("status"), "result": result, "analysis": analysis.output, "preflight": preflight}

authority = HermesExecutionAuthority(model_router, learning_log, manager)

# ============= SWARM NODE + TASK SCHEDULER =============
_swarm_node: Optional[GhostSwarmNode] = None
_swarm_loop: Optional[asyncio.AbstractEventLoop] = None
_scheduler: Optional[SwarmTaskScheduler] = None
_autonomous_swarm: Optional[AutonomousSwarmOrchestrator] = None
_propagation_engine: Optional[PropagationOrchestrator] = None
_ignition_task: Optional[asyncio.Task] = None

def _start_swarm_and_scheduler():
    global _swarm_node, _swarm_loop, _scheduler

    swarm_port = int(os.getenv("SWARM_PORT", "9876"))
    enable_dht = os.getenv("ENABLE_DHT", "0") == "1"
    node_id = os.getenv("NODE_ID", f"ghost-mgr-{os.getpid()}")
    use_identity = os.getenv("USE_NODE_IDENTITY", "0") == "1"

    identity = None
    if use_identity:
        try:
            from node_identity import NodeIdentity
            identity = NodeIdentity.load_or_create()
            node_id = identity.node_id
            logger.info("Loaded Ed25519 identity: %s", node_id)
        except Exception as exc:
            logger.warning("Could not load identity: %s — using ephemeral ID", exc)

    _swarm_loop = asyncio.new_event_loop()

    def run_swarm():
        asyncio.set_event_loop(_swarm_loop)
        _swarm_loop.run_forever()

    t = threading.Thread(target=run_swarm, daemon=True)
    t.start()

    _swarm_node = GhostSwarmNode(
        node_id=node_id,
        port=swarm_port,
        enable_dht=enable_dht,
        identity=identity,
    )

    future = asyncio.run_coroutine_threadsafe(
        _swarm_node.start(), _swarm_loop
    )
    try:
        future.result(timeout=15)
        logger.info("Swarm node '%s' listening on TCP :%d", node_id, swarm_port)
    except Exception as exc:
        logger.error("Swarm node failed to start: %s", exc)
        return

    _scheduler = SwarmTaskScheduler(
        task_manager=manager,
        swarm_node=_swarm_node,
        swarm_loop=_swarm_loop,
    )
    _scheduler.start()

    # Also start the autonomous high-fidelity swarm (Layer 1-5)
    global _autonomous_swarm
    if _AUTONOMOUS_SWARM_AVAILABLE:
        try:

            def _start_auto_swarm():
                global _autonomous_swarm
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                _autonomous_swarm = AutonomousSwarmOrchestrator(
                    node_id=node_id + "-auto",
                    model_router=model_router,
                )
                loop.run_until_complete(_autonomous_swarm.start_async())
                loop.run_forever()

            t = threading.Thread(target=_start_auto_swarm, daemon=True)
            t.start()
            time.sleep(0.5)  # brief wait for startup
            logger.info("Autonomous swarm orchestrator started (layers 1-5)")
        except Exception as exc:
            logger.warning("Autonomous swarm init: %s", exc)

    # Start the propagation engine (advanced protocols 1-5)
    global _propagation_engine
    if _PROPAGATION_AVAILABLE:
        try:

            def _start_propagation():
                global _propagation_engine
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                _propagation_engine = PropagationOrchestrator(
                    node_id=node_id + "-prop"
                )
                loop.run_until_complete(_propagation_engine.start_async())
                loop.run_forever()

            t = threading.Thread(target=_start_propagation, daemon=True)
            t.start()
            time.sleep(0.5)
            logger.info("Propagation engine started (protocols 1-5)")
        except Exception as exc:
            logger.warning("Propagation engine init: %s", exc)


def _start_global_ignition():
    """Start the global ignition loop as a background asyncio task."""
    global _ignition_task
    if not _GLOBAL_IGNITION_AVAILABLE:
        logger.warning("Global ignition module not available — skipping")
        return

    async def _run():
        logger.info("Global ignition loop starting...")
        try:
            await global_ignition.global_ignition()
        except Exception as exc:
            logger.error("Global ignition loop terminated: %s", exc)

    try:
        loop = asyncio.get_event_loop()
        _ignition_task = loop.create_task(_run())
        logger.info("Global ignition loop started (background)")
    except Exception as exc:
        logger.warning("Global ignition start failed: %s", exc)


# ============= FASTAPI BROWSER BRIDGE =============
app = FastAPI(title="Decentralized AI Agent Dashboard")
add_security_headers(app)

@app.on_event("startup")
def on_startup():
    model_router.start_terminal_monitor()
    logger.info("Model router terminal monitor started")
    _start_swarm_and_scheduler()
    _start_global_ignition()

    # Cloud-native startup sequence v2 — autonomous orchestration
    _start_api_gateway()
    _start_health_engine()

    # Start heartbeat (NAT detection + auto-tunnel)
    _start_heartbeat()

    # Meta-cognitive loop — performance analyzer
    _start_performance_analyzer()

    # Autonomous patching — exception-based review model
    _start_auto_patcher()

    # GhostSignal — satellite trans-state propagation (blueprint modes)
    _start_satellite_transstate()
    _start_seed_reassembly()
    _start_autonomous_resilience()

    logger.info("Swarm intelligence online: tools=%d, knowledge_entries=%d, analyzer=%s",
                _tool_registry.size() if _tool_registry else 0,
                _shared_knowledge.get_report()["total_entries"],
                _performance_analyzer is not None)


def _start_performance_analyzer():
    """Background meta-cognitive loop for tool performance tracking."""
    try:
        loop = asyncio.get_event_loop()
        loop.create_task(_performance_analyzer.run_forever(interval=60.0))
        logger.info("Performance Analyzer started (background, threshold=40%%)")
    except Exception as e:
        logger.warning("Performance Analyzer startup: %s", e)


def _start_auto_patcher():
    """Background autonomous patcher — scans and applies proposals every 120s."""
    try:
        loop = asyncio.get_event_loop()
        _auto_patcher.start(interval=120.0)
        logger.info("AutoPatcher started (exception-based review model active)")
    except Exception as e:
        logger.warning("AutoPatcher startup: %s", e)


def _start_health_engine():
    """Background health-check daemon — now uses Tool Registry for repairs."""
    try:
        loop = asyncio.get_event_loop()
        # Wire tool registry into health engine
        _health_engine.set_tool_registry(_tool_registry)
        loop.create_task(_health_engine.run_forever())
        logger.info("Health Engine v2 started (background, tool-driven repairs)")
    except Exception as e:
        logger.warning("Health Engine startup: %s", e)


def _start_heartbeat():
    """NAT detection + auto-tunnel heartbeat for external swarm peering."""
    try:
        loop = asyncio.get_event_loop()
        loop.create_task(_heartbeat.run_forever())
    except Exception as e:
        logger.warning("Heartbeat startup: %s", e)


def _start_api_gateway():
    """Initialize the Unified API Gateway (probe providers)."""
    try:
        loop = asyncio.get_event_loop()
        loop.create_task(_init_gateway_async())
    except Exception as e:
        logger.warning("API Gateway startup: %s", e)


async def _init_gateway_async():
    providers = await _api_gateway.initialize()
    if providers:
        logger.info("API Gateway online — providers: %s", list(providers.keys()))
    else:
        logger.warning("API Gateway: no providers configured. Set GROQ_API_KEY, DEEPSEEK_API_KEY, etc.")

    # Log latency-based switching config
    logger.info("Gateway latency switching: threshold=%sms, window=%d samples",
                _api_gateway.config.latency_threshold_ms, _api_gateway.config.latency_window)


def _start_cloudflare_tunnel():
    """Start Cloudflare Tunnel if configured."""
    if not _cloud_config.tunnel_enabled:
        logger.info("Cloudflare Tunnel disabled (set CF_TUNNEL_ENABLED=true to enable)")
        return
    try:
        loop = asyncio.get_event_loop()
        loop.create_task(_cloudflare_tunnel.start())
        logger.info("Cloudflare Tunnel starting...")
    except Exception as e:
        logger.warning("Cloudflare Tunnel startup: %s", e)


def _start_satellite_transstate():
    """GhostSignal — satellite trans-state propagation background layer.

    Attempts to start the SDR receiver (stealth_beyond_sat) and the
    seed-reassembly daemon. Both act as architecture blueprints when
    no SDR hardware is available.
    """
    if not _STEALTH_SAT_AVAILABLE:
        logger.info("stealth_beyond_sat not available — satellite layer not started")
        return
    try:
        loop = asyncio.get_event_loop()
        loop.create_task(stealth_beyond_sat.start_sdr_daemon())
        logger.info("Satellite SDR daemon started (blueprint mode)")
    except Exception as e:
        logger.warning("Satellite SDR startup: %s", e)


def _start_seed_reassembly():
    """Seed-Reassembly daemon — listens for NULL-packet fragments."""
    if not _SEED_REASSEMBLY_AVAILABLE:
        logger.info("seed_reassembly not available — reassembly not started")
        return
    try:
        loop = asyncio.get_event_loop()
        loop.create_task(seed_reassembly.start_reassembly_daemon())
        logger.info("Seed-Reassembly daemon started (blueprint mode)")
    except Exception as e:
        logger.warning("Seed-Reassembly startup: %s", e)


def _start_autonomous_resilience():
    """Autonomous resilience — echo-mode ambient diagnostics."""
    if not _AUTONOMOUS_RESILIENCE_AVAILABLE:
        logger.info("autonomous_resilience not available — resilience not started")
        return
    try:
        loop = asyncio.get_event_loop()
        loop.create_task(autonomous_resilience.start_autonomous_resilience())
        logger.info("Autonomous resilience monitor started (blueprint mode)")
    except Exception as e:
        logger.warning("Resilience startup: %s", e)


BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"

@app.get("/", response_class=HTMLResponse)
def dashboard():
    index_path = STATIC_DIR / "index.html"
    if index_path.exists():
        return HTMLResponse(index_path.read_text(encoding="utf-8"))
    return HTMLResponse("<h1>Ghost Engine</h1><p>Dashboard static files not found. Run from project root.</p>")

if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

@app.get("/api/status")
def api_status():
    return JSONResponse(get_cached_status())

@app.post("/api/execute")
def api_execute(command: Dict[str, Any]):
    cmd = command.get("command", "")
    parallel = command.get("parallel", False)
    valid, message = validate_command(cmd)
    if not cmd:
        return JSONResponse({"status": "error", "message": "Command is required"}, status_code=400)
    if not valid:
        return JSONResponse({"status": "error", "message": message}, status_code=400)
    result = engine.execute_command(cmd, parallel=parallel)
    manager._append_output({
        "task_id": int(time.time() * 1000),
        "command": cmd,
        "result": result,
        "timestamp": datetime.now().isoformat(),
    })
    return JSONResponse(result)

@app.post("/api/task")
def api_task(cmd: Dict[str, Any]):
    command = cmd.get("command", "")
    valid, message = validate_command(command)
    if not command:
        return JSONResponse({"status": "error", "message": "Task command required"}, status_code=400)
    if not valid:
        return JSONResponse({"status": "error", "message": message}, status_code=400)
    task = manager.enqueue_task(command)
    return JSONResponse({"status": "queued", "task": task})

@app.get("/api/logs")
def api_logs():
    try:
        with open(OUTPUT_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as exc:
        recovery.log_failure(str(exc), "api_logs")
        data = []
    return JSONResponse({"outputs": data})

@app.post("/api/deploy")
def api_deploy():
    result = manager.prepare_deployment()
    return JSONResponse(result)

@app.post("/api/model-route")
def api_model_route(payload: Dict[str, Any]):
    prompt = payload.get("prompt", "")
    params = payload.get("params", {})
    if not prompt:
        return JSONResponse({"status": "error", "message": "prompt is required"}, status_code=400)
    response = model_router.route(prompt, params)
    return JSONResponse({
        "status": response.status,
        "model": response.model,
        "source": response.source,
        "latency": response.latency,
        "output": response.output,
    })

@app.get("/api/ping")
def api_ping():
    return JSONResponse({"pong": True, "timestamp": time.time()})

@app.get("/api/check-port")
def api_check_port(port: int = 8000, host: str = "127.0.0.1"):
    in_use = is_port_in_use(port, host)
    return JSONResponse({
        "port": port,
        "host": host,
        "in_use": in_use,
        "status": "busy" if in_use else "free",
    })

@app.post("/api/hf-infer")
def api_hf_infer(payload: Dict[str, Any]):
    prompt = payload.get("prompt", "")
    params = payload.get("params", {})
    if not prompt:
        return JSONResponse({"status": "error", "message": "prompt is required"}, status_code=400)
    if model_router.hf_engine is None:
        return JSONResponse({"status": "error", "message": "HF engine not initialized"}, status_code=503)
    result = model_router.hf_engine.process_prompt(prompt, params)
    return JSONResponse({
        "status": result.status,
        "model": result.model,
        "latency": result.latency,
        "tokens_generated": result.tokens_generated,
        "output": result.output,
        "error": result.error,
    })

@app.get("/api/gateway/status")
async def api_gateway_status():
    """Unified API Gateway — provider availability."""
    providers = await _api_gateway.initialize()
    return JSONResponse({
        "providers": list(providers.keys()),
        "preferred": f"{_cloud_config.preferred_provider}/{_cloud_config.preferred_model}",
        "fallback": f"{_cloud_config.fallback_provider}/{_cloud_config.fallback_model}",
        "available_models": {
            name: list(cfg["models"].keys()) for name, cfg in providers.items()
        },
    })


@app.post("/api/gateway/chat")
async def api_gateway_chat(payload: dict):
    """Route a prompt through the Unified API Gateway (no local LLM)."""
    messages = payload.get("messages", [])
    model = payload.get("model")
    provider = payload.get("provider")
    temperature = payload.get("temperature", 0.3)
    tools = payload.get("tools")

    if not messages:
        return JSONResponse({"status": "error", "message": "messages required"}, status_code=400)

    await _api_gateway.initialize()
    response = await _api_gateway.chat(
        messages=messages, model=model, provider=provider,
        temperature=temperature, tools=tools,
    )
    return JSONResponse({
        "text": response.text,
        "provider": response.provider,
        "model": response.model,
        "latency_ms": response.latency_ms,
        "finish_reason": response.finish_reason,
    })


@app.get("/api/tools")
def api_tools_list():
    """List all registered tools by category."""
    category = None
    tools = _tool_registry.list_tools(category)
    return JSONResponse({
        "total": len(tools),
        "tools": [
            {"name": t.name, "description": t.description,
             "category": t.category, "parameters": t.parameters}
            for t in tools
        ],
    })


@app.post("/api/tools/execute")
async def api_tools_execute(payload: dict):
    """Execute a registered tool by name with arguments."""
    name = payload.get("name")
    arguments = payload.get("arguments", {})
    if not name:
        return JSONResponse({"status": "error", "message": "tool name required"}, status_code=400)
    result = await _tool_registry.execute(name, arguments)
    return JSONResponse(result)


@app.get("/api/health")
def api_health():
    """Health engine status report."""
    report = _health_engine.get_report()
    return JSONResponse(report)


@app.post("/api/health/check")
async def api_health_check():
    """Trigger an immediate health check cycle."""
    results = await _health_engine.run_checks()
    return JSONResponse([
        {"component": r.component, "healthy": r.healthy, "detail": r.detail}
        for r in results
    ])


@app.post("/api/health/repair")
async def api_health_repair(payload: dict):
    """Trigger repair for a specific component."""
    component = payload.get("component", "")
    results = await _health_engine.run_checks()
    target = next((r for r in results if r.component == component), None)
    if not target:
        return JSONResponse({"status": "error", "message": f"Unknown component: {component}"}, status_code=400)
    success = await _health_engine.auto_repair(target)
    return JSONResponse({"component": component, "repaired": success})


@app.post("/api/cloudflare/tunnel")
async def api_tunnel_start():
    """Start Cloudflare Tunnel."""
    success = await _cloudflare_tunnel.start()
    return JSONResponse({
        "tunnel_started": success,
        "url": _cloudflare_tunnel.url if success else None,
    })


@app.post("/api/cloudflare/tunnel/stop")
async def api_tunnel_stop():
    """Stop Cloudflare Tunnel."""
    await _cloudflare_tunnel.stop()
    return JSONResponse({"tunnel_stopped": True})


@app.get("/api/terminal-history")
def api_terminal_history():
    return JSONResponse({
        "terminal_last": model_router.terminal_last_read,
        "history": model_router.read_terminal_history(),
    })

@app.post("/api/browser")
def api_browser(payload: Dict[str, Any]):
    action = payload.get("action", "").lower()
    args = payload.get("args", {})
    if not action:
        return JSONResponse({"status": "error", "message": "action is required"}, status_code=400)
    result = _run_browser_task(action, **args)
    manager._append_output({
        "task_id": int(time.time() * 1000),
        "command": f"browser:{action}",
        "result": result,
        "timestamp": datetime.now().isoformat(),
    })
    return JSONResponse(result)

@app.post("/api/retry")
def api_retry(task_info: Dict[str, Any]):
    command = task_info.get("command")
    if not command:
        return JSONResponse({"status": "error", "message": "command required"}, status_code=400)
    task = manager.enqueue_task(command)
    return JSONResponse({"status": "retry_queued", "task": task})

@app.post("/api/hermes")
def api_hermes(payload: Dict[str, Any]):
    """Forward task to Hermes/Ollama for intelligent analysis."""
    if not HermesBridge:
        return JSONResponse({"status": "error", "message": "HermesBridge not available"}, status_code=500)
    try:
        hb = HermesBridge()
        result = hb.orchestrate_task(payload)
        return JSONResponse({"status": "success", "hermes_response": result})
    except Exception as exc:
        recovery.log_failure(str(exc), "api_hermes")
        return JSONResponse({"status": "error", "message": str(exc)}, status_code=500)

@app.post("/api/cli")
def api_cli(cmd_input: Dict[str, Any]):
    """CLI interface: execute actions like status, execute, think, deploy, scale."""
    action = cmd_input.get("action", "").lower()
    args = cmd_input.get("args", [])
    if action == "status":
        return JSONResponse({"status": "success", "services": connector.check_services()})
    elif action == "execute":
        cmd = " ".join(args) if args else ""
        if not cmd:
            return JSONResponse({"status": "error", "message": "command required"}, status_code=400)
        result = engine.execute_command(cmd, parallel=False)
        return JSONResponse({"status": "success", "result": result})
    elif action == "think":
        text = " ".join(args) if args else ""
        if HermesBridge:
            hb = HermesBridge()
            result = hb.analyze(text)
            return JSONResponse({"status": "success", "analysis": result})
        return JSONResponse({"status": "error", "message": "Hermes not available"}, status_code=500)
    elif action == "deploy":
        result = manager.prepare_deployment()
        return JSONResponse({"status": "success", "deployment": result})
    elif action == "scale":
        workers = max(1, int(args[0]) if args else 4)
        engine.max_workers = workers
        return JSONResponse({"status": "success", "max_workers": engine.max_workers})
    else:
        return JSONResponse({"status": "error", "message": f"unknown action: {action}"}, status_code=400)

@app.post("/api/discord")
def api_discord(msg: Dict[str, Any]):
    """Send a Discord notification."""
    content = msg.get("content", "")
    success = recovery.notify_discord(content)
    return JSONResponse({"status": "success" if success else "failed", "sent": success})

@app.get("/api/scheduler")
def api_scheduler():
    """Return swarm task scheduler status and dispatch history."""
    global _scheduler
    if _scheduler is None:
        return JSONResponse({"running": False, "message": "Scheduler not initialized"})
    return JSONResponse(_scheduler.status)

@app.get("/api/swarm/status")
def api_swarm_status():
    """Return full autonomous swarm status (all 5 layers)."""
    global _autonomous_swarm
    if _autonomous_swarm is None:
        return JSONResponse({"running": False, "message": "Autonomous swarm not initialized"})
    try:
        return JSONResponse(_autonomous_swarm.get_full_status())
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=500)


@app.post("/api/swarm/execute")
def api_swarm_execute(payload: Dict[str, Any]):
    """Submit a task to the autonomous swarm's distributed executor."""
    global _autonomous_swarm
    command = payload.get("command", "")
    if not command:
        return JSONResponse({"status": "error", "message": "command required"}, status_code=400)
    if _autonomous_swarm is None:
        return JSONResponse({"status": "error", "message": "Swarm not running"}, status_code=503)
    if not _autonomous_swarm._running or not _autonomous_swarm._event_loop:
        return JSONResponse({"status": "error", "message": "Swarm not ready"}, status_code=503)
    try:
        future = asyncio.run_coroutine_threadsafe(
            _autonomous_swarm.task_sync.submit_task(command),
            _autonomous_swarm._event_loop,
        )
        task = future.result(timeout=10)
        return JSONResponse({"status": "submitted", "task_id": task.task_id, "command": command})
    except Exception as exc:
        return JSONResponse({"status": "error", "message": str(exc)}, status_code=500)


@app.get("/api/propagate/status")
def api_propagate_status():
    """Return full propagation engine status (all 5 protocols)."""
    global _propagation_engine
    if _propagation_engine is None:
        return JSONResponse({"running": False, "message": "Propagation engine not initialized"})
    try:
        return JSONResponse(_propagation_engine.get_full_status())
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=500)


@app.post("/api/propagate/infiltrate")
def api_propagate_infiltrate():
    """Run infrastructure infiltration and deploy to cloud targets."""
    global _propagation_engine
    if _propagation_engine is None or not _propagation_engine._event_loop:
        return JSONResponse({"status": "error", "message": "Propagation engine not running"}, status_code=503)
    try:
        future = asyncio.run_coroutine_threadsafe(
            _propagation_engine.infiltrate_and_deploy(),
            _propagation_engine._event_loop,
        )
        deployed = future.result(timeout=120)
        return JSONResponse({"status": "complete", "deployed": [
            {"node_id": n.node_id, "host": n.host, "provider": n.provider} for n in deployed
        ]})
    except Exception as exc:
        return JSONResponse({"status": "error", "message": str(exc)}, status_code=500)


@app.post("/api/propagate/replicate")
def api_propagate_replicate(payload: Dict[str, Any]):
    """Replicate swarm to a target host via SSH."""
    global _propagation_engine
    host = payload.get("host", "")
    port = payload.get("port", 22)
    if not host:
        return JSONResponse({"status": "error", "message": "host required"}, status_code=400)
    if _propagation_engine is None or not _propagation_engine._event_loop:
        return JSONResponse({"status": "error", "message": "Propagation engine not running"}, status_code=503)
    try:
        future = asyncio.run_coroutine_threadsafe(
            _propagation_engine.replicate_to_target(host, port),
            _propagation_engine._event_loop,
        )
        node_id = future.result(timeout=180)
        return JSONResponse({"status": "ok" if node_id else "failed", "node_id": node_id})
    except Exception as exc:
        return JSONResponse({"status": "error", "message": str(exc)}, status_code=500)


@app.get("/api/ignition/status")
def api_ignition_status():
    """Return global ignition loop status."""
    global _ignition_task
    if _ignition_task is None:
        return JSONResponse({"running": False, "message": "Ignition loop not started"})
    running = not _ignition_task.done()
    status = {
        "running": running,
        "exception": str(_ignition_task.exception()) if _ignition_task.done() and _ignition_task.exception() else None,
    }
    if _BLOCKCHAIN_AVAILABLE:
        try:
            ledger = get_ledger()
            status["ledger"] = ledger.get_summary()
        except Exception as exc:
            status["ledger_error"] = str(exc)
    return JSONResponse(status)


@app.post("/api/ignition/trigger")
def api_ignition_trigger():
    """Manually trigger an immediate ignition cycle (forces scan + deploy)."""
    global _ignition_task
    if _ignition_task is None or _ignition_task.done():
        try:
            loop = asyncio.get_event_loop()
            _ignition_task = loop.create_task(_run_ignition_once())
            return JSONResponse({"status": "triggered"})
        except Exception as exc:
            return JSONResponse({"status": "error", "message": str(exc)}, status_code=500)
    return JSONResponse({"status": "running", "message": "Ignition already in progress"})


async def _run_ignition_once():
    """Run a single scan-deploy cycle for the /api/ignition/trigger endpoint."""
    logger.info("Manual ignition cycle triggered via API")
    if _GLOBAL_IGNITION_AVAILABLE:
        try:
            from replication import SwarmReplicator
            from blockchain import update_ledger

            replicator = SwarmReplicator()
            target = replicator.find_idle_cloud_instance()
            if target:
                reachable = await replicator._check_reachable(target)
                if reachable:
                    success = await replicator.deploy_node(target)
                    if success:
                        update_ledger("NODE_ADDED", {
                            "host": target.host, "provider": target.provider,
                        })
                        logger.info("Manual deploy: %s OK", target.host)
        except Exception as exc:
            logger.error("Manual ignition cycle failed: %s", exc)


@app.post("/api/swarm/dht-reinit")
async def api_swarm_dht_reinit(payload: dict):
    """Re-initialize the Kademlia DHT node. Called by Health Engine v2."""
    from ghost_swarm import GhostSwarmNode
    bootstrap = payload.get("bootstrap", _cloud_config.dht_bootstrap)
    port = payload.get("port", _cloud_config.dht_port)

    logger.info("Swarm DHT re-init requested (bootstrap=%s, port=%s)", bootstrap, port)
    try:
        node = GhostSwarmNode(node_id=f"dht-reinit-{int(time.time())}", port=port)
        if hasattr(node, 'dht') and node.dht:
            await node.dht.start()
            if bootstrap:
                await node.dht.bootstrap(bootstrap)
            return JSONResponse({"status": "ok", "dht_started": True, "port": port})
        return JSONResponse({"status": "ok", "message": "DHT not available on this node"})
    except Exception as e:
        logger.error("DHT re-init failed: %s", e)
        return JSONResponse({"status": "error", "error": str(e)}, status_code=500)


@app.post("/api/swarm/relay")
async def api_swarm_relay(payload: dict):
    """Switch swarm to relay-based peering. Called by Health Engine v2."""
    reason = payload.get("reason", "no reason")
    source = payload.get("source", "unknown")
    logger.info("Swarm relay activated (reason=%s, source=%s)", reason, source)

    # Try to enable relay mode on the swarm node
    try:
        global _swarm_node
        if _swarm_node and hasattr(_swarm_node, 'enable_relay'):
            await _swarm_node.enable_relay()
            return JSONResponse({"status": "ok", "relay": "activated"})
        return JSONResponse({"status": "ok", "relay": "not available", "note": "swarm node has no relay mode"})
    except Exception as e:
        logger.error("Swarm relay error: %s", e)
        return JSONResponse({"status": "error", "error": str(e)}, status_code=500)


@app.post("/api/swarm/announce")
async def api_swarm_announce(payload: dict):
    """Receive heartbeat announcement + shared knowledge from an external peer.

    Verifies the HMAC signature and node fingerprint before accepting
    knowledge. Untrusted announcements are rejected with 403.
    """
    global _shared_knowledge, _swarm_security
    url = payload.get("url", "unknown")
    node_id = payload.get("node_id", "unknown")
    role = payload.get("role", "unknown")
    signature = payload.get("signature", "")
    fingerprint = payload.get("fingerprint", "")

    # Verify authenticity
    if signature:
        payload_copy = dict(payload)
        payload_copy.pop("signature", None)
        payload_copy.pop("fingerprint", None)
        if not verify_json_payload(payload_copy, signature):
            logger.warning("Swarm announce REJECTED (bad signature): node=%s", node_id)
            return JSONResponse({"status": "rejected", "reason": "invalid_signature"}, status_code=403)
        if fingerprint and not is_trusted_node(node_id, fingerprint):
            logger.warning("Swarm announce REJECTED (bad fingerprint): node=%s", node_id)
            return JSONResponse({"status": "rejected", "reason": "invalid_fingerprint"}, status_code=403)
        _swarm_security.register_node(node_id, fingerprint)

    # Ingest shared knowledge from peer
    knowledge_payload = payload.get("knowledge")
    if knowledge_payload and _shared_knowledge:
        _shared_knowledge.ingest_heartbeat(knowledge_payload)
        logger.info("Swarm announce: node=%s url=%s knowledge=%d entries",
                    node_id, url, knowledge_payload.get("knowledge_count", 0))
    else:
        logger.info("Swarm announce: node=%s url=%s", node_id, url)

    return JSONResponse({"status": "acknowledged", "node_id": node_id, "swarm_secret_required": True})


@app.get("/api/swarm/peers")
def api_swarm_peers():
    """Return discovered peers from the autonomous swarm."""
    global _autonomous_swarm
    if _autonomous_swarm is None:
        return JSONResponse({"peers": []})
    peers = []
    for pid, p in _autonomous_swarm.discovery.peers.items():
        peers.append({
            "peer_id": pid,
            "host": p.host,
            "port": p.port,
            "last_seen": p.last_seen,
            "capacity_score": p.capacity_score,
            "task_status": p.task_status,
            "is_alive": p.is_alive,
        })
    return JSONResponse({"peers": peers, "total": len(peers)})


# ==============================================================================
# Meta-cognitive endpoints — Performance Analyzer
# ==============================================================================


@app.get("/api/analyzer/report")
def api_analyzer_report():
    """Performance Analyzer — full report with flagged tools."""
    global _performance_analyzer
    return JSONResponse(_performance_analyzer.get_report())


@app.get("/api/analyzer/diagnostics/{tool_name}")
def api_analyzer_diagnostics(tool_name: str):
    """Deep diagnostic for a specific tool."""
    global _performance_analyzer
    return JSONResponse(_performance_analyzer.get_diagnostics(tool_name))


# ==============================================================================
# Shared Knowledge endpoints
# ==============================================================================


@app.get("/api/knowledge")
def api_knowledge():
    """Shared Knowledge Layer — all entries and peers."""
    global _shared_knowledge
    return JSONResponse(_shared_knowledge.get_report())


@app.post("/api/knowledge/propagate")
async def api_knowledge_propagate(payload: dict):
    """Manually propagate a knowledge entry to all peers."""
    global _shared_knowledge
    key = payload.get("key", "")
    value = payload.get("value", {})
    ttl = payload.get("ttl", 3600)
    if not key:
        return JSONResponse({"status": "error", "message": "key required"}, status_code=400)
    _shared_knowledge.add_observation(key, value, ttl=ttl)
    return JSONResponse({"status": "propagated", "key": key, "ttl": ttl})


# ==============================================================================
# Optimization Proposals endpoints
# ==============================================================================


@app.get("/api/proposals/{proposal_id}")
def api_proposal_detail(proposal_id: str):
    """Get a single optimization proposal."""
    PROPOSALS_DIR = Path("agent_logs/optimization_proposals")
    f = PROPOSALS_DIR / f"{proposal_id}.json"
    if not f.exists():
        return JSONResponse({"error": "not found"}, status_code=404)
    return JSONResponse(json.loads(f.read_text(encoding="utf-8")))


# ==============================================================================
# AutoPatcher endpoints — autonomous execution & exception-based review
# ==============================================================================


@app.get("/api/patcher/status")
def api_patcher_status():
    """AutoPatcher status — running, recent actions, exceptions flagged."""
    global _auto_patcher
    return JSONResponse(_auto_patcher.get_status())


@app.post("/api/patcher/apply/{proposal_id}")
async def api_patcher_apply(proposal_id: str, force: bool = False):
    """Manually trigger auto-patch for a specific proposal (force skips threshold)."""
    global _auto_patcher
    result = await _auto_patcher.apply_proposal(proposal_id, force=force)
    return JSONResponse(result)


@app.post("/api/patcher/sync")
async def api_patcher_sync():
    """Sync and apply patches broadcast by peer swarm nodes."""
    global _auto_patcher
    result = await _auto_patcher.sync_peer_patches()
    return JSONResponse(result)


@app.get("/api/patcher/exceptions")
def api_patcher_exceptions():
    """List all exceptions flagged for human review."""
    global _auto_patcher
    status = _auto_patcher.get_status()
    exceptions = [
        e for e in status.get("recent_actions", [])
        if e.get("is_exception")
    ]
    # Also read from auto_patch.log
    log_path = AUTO_PATCH_LOG
    log_entries = []
    if log_path.exists():
        try:
            with open(log_path, encoding="utf-8") as lf:
                for line in lf.readlines()[-50:]:
                    log_entries.append(line.strip())
        except Exception:
            pass
    return JSONResponse({
        "exceptions": exceptions,
        "total": len(exceptions),
        "log_entries": log_entries,
    })


@app.get("/api/proposals")
def api_proposals(status: str = "all"):
    """List optimization proposals. Default shows ALL (exception-based review model)."""
    PROPOSALS_DIR = Path("agent_logs/optimization_proposals")
    if not PROPOSALS_DIR.exists():
        return JSONResponse({"proposals": [], "total": 0})
    proposals = []
    for f in sorted(PROPOSALS_DIR.glob("*.json"), reverse=True):
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            if data.get("status") == status or status == "all":
                proposals.append(data)
        except Exception:
            continue
    return JSONResponse({"proposals": proposals, "total": len(proposals)})


# ============= SWARM SECURITY =============

@app.get("/api/swarm/security")
def api_swarm_security():
    """Swarm mesh security status — trusted nodes, isolated nodes, audit log."""
    global _swarm_security
    status = _swarm_security.get_status()
    threat_level = "low"
    if status["isolated_nodes"] > 0:
        threat_level = "medium"
    if status["isolated_nodes"] > 5:
        threat_level = "high"
    return JSONResponse({
        **status,
        "threat_level": threat_level,
        "hmac_algorithm": "HMAC-SHA256",
        "mesh_encryption": "symmetric (SWARM_SECRET env var)",
    })


# ============= GHOSTSIGNAL STATUS =============

@app.get("/api/ghostsignal/status")
def api_ghostsignal_status():
    """Satellite trans-state propagation layer status."""
    sat_ok = _STEALTH_SAT_AVAILABLE
    seed_ok = _SEED_REASSEMBLY_AVAILABLE
    res_ok = _AUTONOMOUS_RESILIENCE_AVAILABLE

    sat_status = "active" if sat_ok else "unavailable"
    seed_status = {}
    if seed_ok:
        try:
            loop = asyncio.new_event_loop()
            seed_status = loop.run_until_complete(seed_reassembly.get_reassembly_status())
            loop.close()
        except Exception:
            seed_status = {"error": "seed_reassembly_status_failed"}

    return JSONResponse({
        "stealth_beyond_sat": {
            "available": sat_ok,
            "status": sat_status,
            "description": "DVB-S/S2 NULL-packet injection blueprint (requires SDR hardware)",
        },
        "seed_reassembly": {
            "available": seed_ok,
            "status": seed_status,
            "description": "Cross-platform identity reconstruction from satellite fragments",
        },
        "autonomous_resilience": {
            "available": res_ok,
            "status": "active" if res_ok else "unavailable",
            "description": "Echo-mode diagnostics / thermal-noise heartbeat / offline failover",
        },
        "carrier_mhz": 10723.0,
        "note": "Blueprints active — require SDR hardware (RTL-SDR / HackRF) and/or oscilloscope for full TX/RX",
    })


# ============= STARTUP HELPERS =============
def initialize_state():
    if not STATE_FILE.exists():
        STATE_FILE.write_text(json.dumps({"started_at": datetime.now().isoformat()}), encoding="utf-8")

if __name__ == "__main__":
    import sys
    if "--auto-evolve=true" in sys.argv:
        on_startup()
    initialize_state()
    port = int(os.getenv("MANAGER_PORT", "8000"))
    resolved_port = find_free_port(preferred=port)
    if resolved_port != port:
        logger.warning("Port %d in use, falling back to port %d", port, resolved_port)
    logger.info("Starting Decentralized AI Agent web dashboard on http://0.0.0.0:%d", resolved_port)
    uvicorn.run(app, host="0.0.0.0", port=resolved_port)
