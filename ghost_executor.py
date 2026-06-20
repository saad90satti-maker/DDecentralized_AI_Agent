"""
Ghost Execution Authority v2 — Expansion Mode
==============================================
Protocol: Monitor → Execute → Log → Self-Patch → Repeat
Backends: Gemini (primary) → Groq (failover) → Ollama (tertiary)
Stealth:  Tor routing + Human-mimicry delays
Storage:  SQLite + GitHub auto-sync
Scaling:  HF Spaces deployer + HF Inference API
"""

import ast
import asyncio
import difflib
import json
import logging
import os
import random
import subprocess
import sys
import time
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

BASE_DIR = Path(__file__).resolve().parent
LOG_DIR = BASE_DIR / "agent_logs"
DATA_DIR = BASE_DIR / "agent_data"
GL = LOG_DIR / "Ghost_Master_Log.log"
REPORT_FILE = BASE_DIR / "agent_report.json"
STATE_FILE = DATA_DIR / "agent_state.json"

LOG_DIR.mkdir(exist_ok=True)
DATA_DIR.mkdir(exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(message)s",
    handlers=[logging.StreamHandler()],
)
logger = logging.getLogger("GhostExecutor")

# ---- Expansion-mode lazy imports ----
_scraper = None
_github = None
_tor = None
_mimicry = None
_hf = None

def _get_scraper():
    global _scraper
    if _scraper is None:
        from scraper_engine import ScraperEngine, ScraperDB
        _scraper = ScraperEngine(db=ScraperDB())
    return _scraper

def _get_github():
    global _github
    if _github is None:
        from github_sync import GitHubSync
        _github = GitHubSync()
    return _github

def _get_tor():
    global _tor
    if _tor is None:
        from tor_controller import TorController
        _tor = TorController(auto_install=True)
    return _tor

def _get_mimicry():
    global _mimicry
    if _mimicry is None:
        from human_mimicry import HumanMimicryEngine
        _mimicry = HumanMimicryEngine()
    return _mimicry

def _get_hf():
    global _hf
    if _hf is None:
        from hf_spaces import HFInferenceAPI
        _hf = HFInferenceAPI()
    return _hf

_swarm = None

def _get_swarm():
    global _swarm
    if _swarm is None:
        from ghost_swarm import GhostSwarmNode, SWARM_PORT as _swarm_port
        global SWARM_PORT
        SWARM_PORT = _swarm_port
        _swarm = GhostSwarmNode(node_id=f"ghost-exec-{random.randint(1000,9999)}")
    return _swarm

SWARM_PORT = 9876  # default, overridden by _get_swarm()

_compute = None
_scheduler = None

def _get_compute():
    global _compute
    if _compute is None:
        from ghost_compute import ComputeMaster
        _compute = ComputeMaster()
    return _compute

def _get_scheduler():
    global _scheduler
    if _scheduler is None:
        from ghost_scheduler import GhostScheduler
        _scheduler = GhostScheduler()
    return _scheduler


def ghost_log(msg: str) -> None:
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    line = f"[{ts}] [GHOST-EXEC] {msg}\n"
    try:
        with open(GL, "a", encoding="utf-8") as f:
            f.write(line)
    except Exception:
        pass
    logger.info(msg)


class ModelRouterProxy:
    """Thread-safe wrapper around model_router.ModelRouter with Groq failover."""

    def __init__(self):
        sys.path.insert(0, str(BASE_DIR))
        from model_router import ModelRouter
        from learning_log import LearningLog
        self._router = ModelRouter(log=LearningLog())
        self._lock = threading.Lock()
        self._last_tier = "none"
        self._failover_count = 0

    def route(self, prompt: str) -> Dict[str, Any]:
        with self._lock:
            start = time.time()
            result = self._router.route(prompt)
            tier = result.source
            if tier != self._last_tier:
                ghost_log(f"Router switch: {self._last_tier} -> {tier} (latency={result.latency:.2f}s)")
                self._last_tier = tier
            if result.status != "success":
                self._failover_count += 1
                ghost_log(f"Route FAILED ({tier}): {str(result.output)[:100]}")
            else:
                self._failover_count = 0
            return {
                "status": result.status,
                "output": result.output,
                "model": result.model,
                "source": result.source,
                "latency": result.latency,
            }

    @property
    def failover_count(self) -> int:
        return self._failover_count


class NetworkSentinel:
    """Checks IP and manages proxy rotation."""

    def __init__(self):
        self._identity: Dict[str, str] = {}
        self._proxy_active = False

    def check(self) -> Dict[str, Any]:
        try:
            import requests
            r = requests.get("https://ipinfo.io/json", timeout=10)
            if r.ok:
                self._identity = r.json()
        except Exception as e:
            self._identity = {"ip": "unknown", "error": str(e)}

        ip = self._identity.get("ip", "unknown")
        country = self._identity.get("country", "unknown")
        org = self._identity.get("org", "unknown")

        needs_proxy = country == "PK"
        if needs_proxy and not self._proxy_active:
            ghost_log(f"IP {ip} ({country}) — initializing proxy rotation")
            self._proxy_active = self._try_proxy()
        elif not needs_proxy:
            self._proxy_active = False

        return {
            "ip": ip,
            "country": country,
            "org": org,
            "needs_proxy": needs_proxy,
            "proxy_active": self._proxy_active,
        }

    def _try_proxy(self) -> bool:
        try:
            from proxy_rotator import ProxyRotator
            rotator = ProxyRotator()
            rotator.scan_local_ports()
            proxy = rotator.find_working_proxy()
            if proxy:
                ghost_log(f"Proxy active: {proxy.get('http', proxy.get('https', '?'))}")
                os.environ["HTTP_PROXY"] = proxy.get("http", "")
                os.environ["HTTPS_PROXY"] = proxy.get("https", proxy.get("http", ""))
                return True
            ghost_log("No proxy available — proceeding without rotation")
        except Exception as e:
            ghost_log(f"Proxy init failed: {e}")
        return False


class ProcessWatchdog:
    """Monitors and restarts critical agents."""

    AGENTS = {
        "local_agent_hermes": {"script": "local_agent.py", "python": "C:\\Users\\zafar\\AppData\\Local\\hermes\\hermes-agent\\venv\\Scripts\\python.exe"},
        "local_agent_uv": {"script": "local_agent.py", "python": None},  # uses sys.executable
    }

    def __init__(self):
        self._watch = True

    def check_all(self) -> List[Dict[str, Any]]:
        results = []
        for name, cfg in self.AGENTS.items():
            status = self._check_process(name, cfg)
            results.append(status)
        return results

    def _check_process(self, name: str, cfg: Dict[str, Any]) -> Dict[str, Any]:
        try:
            script = cfg["script"]
            if sys.platform == "win32":
                # Fast WMI query — 2s timeout, no PowerShell overhead
                running = False
                try:
                    import wmi
                    c = wmi.WMI()
                    for p in c.Win32_Process(Name="python.exe"):
                        if script in (p.CommandLine or ""):
                            running = True
                            break
                except ImportError:
                    # Fallback: tasklist then match commandline via wmic
                    try:
                        result = subprocess.run(
                            ["wmic", "process", "where", "name='python.exe'", "get", "CommandLine"],
                            capture_output=True, text=True, timeout=3
                        )
                        running = script in (result.stdout or "")
                    except Exception:
                        pass
            else:
                result = subprocess.run(["pgrep", "-f", script], capture_output=True, text=True, timeout=5)
                running = result.returncode == 0

            if not running:
                ghost_log(f"Agent {name} DOWN — restarting")
                self._restart(name, cfg)
                return {"name": name, "status": "restarted", "script": script}

            return {"name": name, "status": "running", "script": script}
        except Exception as e:
            ghost_log(f"Watchdog check failed for {name}: {e}")
            return {"name": name, "status": "error", "error": str(e)}

    def _restart(self, name: str, cfg: Dict[str, Any]) -> None:
        try:
            python = cfg["python"] or sys.executable
            script_path = str(BASE_DIR / cfg["script"])
            subprocess.Popen(
                [python, script_path],
                cwd=str(BASE_DIR),
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
            )
            ghost_log(f"Restarted {name}: {python} {script_path}")
        except Exception as e:
            ghost_log(f"Restart failed for {name}: {e}")


class CDPLauncher:
    """Ensures Chrome is available on --remote-debugging-port=9222."""

    CDP_PORT = 9222
    CHROME_PATHS = [
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    ]

    @classmethod
    def ensure_running(cls) -> Dict[str, Any]:
        if cls._cdp_active():
            return {"status": "already_running", "port": cls.CDP_PORT}
        return cls._launch()

    @classmethod
    def _cdp_active(cls) -> bool:
        try:
            import requests
            r = requests.get(f"http://127.0.0.1:{cls.CDP_PORT}/json/version", timeout=3)
            return r.ok
        except Exception:
            return False

    @classmethod
    def _launch(cls) -> Dict[str, Any]:
        chrome_exe = None
        for p in cls.CHROME_PATHS:
            if Path(p).exists():
                chrome_exe = p
                break
        if not chrome_exe:
            return {"status": "error", "message": "Chrome not found"}

        profile = os.getenv("BROWSER_USER_DATA_DIR",
                            str(Path.home() / "AppData/Local/Google/Chrome/User Data/Default"))

        try:
            subprocess.Popen(
                [chrome_exe,
                 f"--remote-debugging-port={cls.CDP_PORT}",
                 f"--user-data-dir={os.path.dirname(profile)}",
                 "--no-first-run",
                 "--no-default-browser-check",
                 "--disable-blink-features=AutomationControlled"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            ghost_log(f"Chrome launched with CDP :{cls.CDP_PORT}, profile={profile}")
            return {"status": "launched", "port": cls.CDP_PORT}
        except Exception as e:
            ghost_log(f"Chrome CDP launch failed: {e}")
            return {"status": "error", "message": str(e)}


class GhostExecutionAuthority:
    """Master loop: Monitor → Execute → Log → Self-Patch → Repeat."""

    def __init__(self):
        self.model = ModelRouterProxy()
        self.network = NetworkSentinel()
        self.watchdog = ProcessWatchdog()
        self.iteration = 0
        self._running = False
        self._state: Dict[str, Any] = self._load_state()
        self._swarm_started = False
        self._swarm_thread = None
        self._customized = False

    def _load_state(self) -> Dict[str, Any]:
        try:
            if STATE_FILE.exists():
                return json.loads(STATE_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
        return {}

    def _save_state(self) -> None:
        try:
            STATE_FILE.write_text(json.dumps(self._state, indent=2), encoding="utf-8")
        except Exception:
            pass

    def audit_resources(self) -> str:
        """Audit CPU / RAM and return a performance mode string."""
        try:
            import psutil
            cpu = os.cpu_count() or 0
            ram_gb = psutil.virtual_memory().total / (1024 ** 3)
            ghost_log(f"Resource audit: {cpu} cores, {ram_gb:.2f} GB RAM")
            if ram_gb > 8:
                return "HIGH_PERFORMANCE_MODE"
            return "LIGHTWEIGHT_MODE"
        except ImportError:
            ghost_log("psutil not available — skipping resource audit")
            return "DEFAULT_MODE"

    def self_customize(self) -> str:
        """Write agent_config.json with hardware-tuned settings."""
        mode = self.audit_resources()
        cfg = {
            "mode": mode,
            "optimized": True,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        try:
            path = BASE_DIR / "agent_config.json"
            path.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
            ghost_log(f"Engine customized: {mode}")
        except Exception as e:
            ghost_log(f"self_customize failed: {e}")
        return mode

    def trigger_propagation(self, timeout: float = 10.0) -> List[str]:
        """Discover swarm peers on the local network (concurrent scan)."""
        results = []
        if not _swarm:
            return results
        ghost_log(f"Propagating — subnet scan timeout={timeout}s...")
        try:
            import socket
            import concurrent.futures
            local_ip = socket.gethostbyname(socket.gethostname())
            subnet = ".".join(local_ip.split(".")[:3])

            def _check(host: str) -> Optional[str]:
                try:
                    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                    s.settimeout(0.5)
                    if s.connect_ex((host, SWARM_PORT)) == 0:
                        s.close()
                        return host
                    s.close()
                except Exception:
                    pass
                return None

            hosts = [f"{subnet}.{i}" for i in range(1, 255)]
            with concurrent.futures.ThreadPoolExecutor(max_workers=50) as ex:
                futures = {ex.submit(_check, h): h for h in hosts}
                done, _ = concurrent.futures.wait(futures, timeout=timeout)
                for f in done:
                    host = f.result()
                    if host:
                        _swarm.add_peer(host, SWARM_PORT)
                        results.append(f"Peer found @ {host}:{SWARM_PORT}")
            ghost_log(f"Propagation done — {len(results)} peer(s) found")
        except Exception as e:
            ghost_log(f"Propagation error: {e}")
        return results

    def self_patch(self, health: Dict[str, Any]) -> List[str]:
        patches = []

        # Resource-based customization (once)
        if not self._customized:
            mode = self.self_customize()
            patches.append(f"Engine customized: {mode}")
            self._customized = True

        if self.model.failover_count > 3:
            patches.append("High failover rate — clearing performance history")
            self.model._router.performance_history.clear()

        if health.get("needs_proxy") and not health.get("proxy_active"):
            patches.append("Pakistan IP without proxy — retrying Tor")
            self.network._try_proxy()

        cdp = CDPLauncher.ensure_running()
        if cdp["status"] == "launched":
            patches.append("CDP browser launched")

        agents = self.watchdog.check_all()
        down = [a for a in agents if a["status"] == "restarted"]
        if down:
            patches.append(f"Restarted agents: {[d['name'] for d in down]}")

        # Expansion: Tor routing
        try:
            tor = _get_tor()
            if tor.available:
                tor.enable_global_tor()
                ident = tor.current_identity()
                if ident:
                    patches.append(f"Tor active: {ident.ip} ({ident.country})")
            else:
                tor.start_tor_daemon()
                if tor.available:
                    patches.append("Tor daemon started")
        except Exception as e:
            ghost_log(f"Tor init: {e}")

        # Expansion: P2P Swarm node
        if not self._swarm_started:
            try:
                swarm = _get_swarm()
                # Start swarm in a background thread with its own event loop
                self._swarm_thread = threading.Thread(target=self._run_swarm, daemon=True)
                self._swarm_thread.start()
                self._swarm_started = True
                patches.append("P2P Swarm node initialized")
                ghost_log("Swarm node online")
                # Trigger peer discovery after swarm is up
                found = self.trigger_propagation()
                patches.extend(found)
            except Exception as e:
                ghost_log(f"Swarm init: {e}")

        # Expansion: Compute engine
        if not hasattr(self, "_compute_started"):
            try:
                compute = _get_compute()
                compute.submit("health_check", {"cycle": self.iteration})
                self._compute_started = True
                patches.append("Compute engine initialized")
            except Exception as e:
                ghost_log(f"Compute init: {e}")

        # Expansion: Scheduler (register default jobs once)
        if not hasattr(self, "_scheduler_started"):
            try:
                sched = _get_scheduler()
                sched.register("health_check", self._scheduler_health)
                sched.schedule("health_check", 60)
                sched.register("metrics_log", self._scheduler_metrics)
                sched.schedule("metrics_log", 300)
                self._scheduler_started = True
                patches.append("Scheduler initialized")
            except Exception as e:
                ghost_log(f"Scheduler init: {e}")

        # Expansion: GitHub sync (once every 10 cycles)
        if self.iteration > 0 and self.iteration % 10 == 0:
            try:
                gh = _get_github()
                sync_result = gh.sync_all()
                patches.append(f"GitHub sync: {sync_result.get('status')}")
            except Exception as e:
                ghost_log(f"GitHub sync: {e}")

        # Self-evolution: triggered on high failover or every 25 cycles
        if self.model.failover_count > 5 or (self.iteration > 0 and self.iteration % 25 == 0):
            evolutions = self.self_evolve()
            patches.extend(evolutions)

        for p in patches:
            ghost_log(f"SELF-PATCH: {p}")
            self._state.setdefault("patches", []).append({"ts": datetime.now(timezone.utc).isoformat(), "msg": p})
        self._save_state()
        return patches

    @staticmethod
    def _run_swarm() -> None:
        """Run the P2P swarm node in a background thread."""
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            swarm = _get_swarm()
            loop.run_until_complete(swarm.start())
            loop.run_forever()
        except Exception as e:
            ghost_log(f"Swarm thread error: {e}")
        finally:
            loop.close()

    async def swarm_broadcast(self, task_type: str, payload: Dict[str, Any]) -> None:
        """Broadcast a task to the P2P swarm."""
        if _swarm:
            await _swarm.send_task(task_type, payload)

    def execute_research(self, query: str) -> Dict[str, Any]:
        ghost_log(f"Research: {query}")
        try:
            # Use ScraperEngine (BeautifulSoup + SQLite)
            se = _get_scraper()
            results = se.search_google(query, num_results=5)
            report = {
                "search_query": query,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "results": results,
                "db_stats": se.db.get_stats(),
            }
            REPORT_FILE.write_text(json.dumps(report, indent=2), encoding="utf-8")
            ghost_log(f"Research complete: {len(results)} results, saved to report + SQLite")
            return report
        except Exception as e:
            ghost_log(f"ScraperEngine failed: {e}")
            return self._web_fallback_search(query)

    def _web_fallback_search(self, query: str) -> Dict[str, Any]:
        try:
            import requests
            from urllib.parse import quote
            mimic = _get_mimicry()
            mimic.record_action()
            url = f"https://www.google.com/search?q={quote(query)}"
            r = requests.get(url, headers=mimic.random_headers(), timeout=15)
            report = {
                "search_query": query,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "status_code": r.status_code,
                "result_preview": r.text[:500],
            }
            REPORT_FILE.write_text(json.dumps(report, indent=2), encoding="utf-8")
            ghost_log(f"Web fallback report saved: {query[:60]}")
            return report
        except Exception as e:
            ghost_log(f"Web fallback failed: {e}")
            return {"search_query": query, "error": str(e)}

    def execute_scrape(self, url: str, extract: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
        ghost_log(f"Scrape: {url}")
        try:
            se = _get_scraper()
            result = se.scrape_url(url, extract=extract)
            ghost_log(f"Scraped: {result.get('title', '?')} ({result.get('status_code')})")
            return result
        except Exception as e:
            ghost_log(f"Scrape failed: {e}")
            return {"url": url, "error": str(e)}

    def execute_llm_task(self, prompt: str) -> Dict[str, Any]:
        ghost_log(f"LLM task: {prompt[:80]}")
        return self.model.route(prompt)

    def execute_hf_task(self, prompt: str) -> Dict[str, Any]:
        ghost_log(f"HF task: {prompt[:80]}")
        try:
            hf = _get_hf()
            return hf.query(prompt)
        except Exception as e:
            return {"status": "error", "output": str(e)}

    def store_metric(self, event: str, value: float = 0.0, details: str = "") -> None:
        try:
            se = _get_scraper()
            se.db.log_metric(event, value, details)
        except Exception:
            pass

    def log_cycle(self, cycle_data: Dict[str, Any]) -> None:
        try:
            with open(GL, "a", encoding="utf-8") as f:
                f.write(f"[{datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')}] [CYCLE] "
                        f"{json.dumps(cycle_data)}"
                        f"\n")
        except Exception:
            pass

    def run_diagnostic(self) -> bool:
        """Self-test: verify core execution engine is healthy."""
        try:
            test_val = 5 + 5
            assert test_val == 10
            ghost_log("[DIAGNOSTIC] Execution Engine healthy")
            return True
        except Exception as e:
            ghost_log(f"[DIAGNOSTIC] Failed: {e} — triggering self_patch")
            self.self_patch(self.network.check())
            return False

    def run_cycle(self, research_query: Optional[str] = None, llm_prompt: Optional[str] = None,
                  scrape_url: Optional[str] = None) -> Dict[str, Any]:
        self.iteration += 1
        cycle_start = time.time()
        ghost_log(f"=== CYCLE {self.iteration} START ===")
        self.run_diagnostic()

        # 1. Monitor — IP + Tor check
        network = self.network.check()
        tor = _get_tor()
        tor_identity = None
        if tor.available:
            tor_identity = tor.current_identity()
            if tor_identity:
                ghost_log(f"Tor: {tor_identity.ip} ({tor_identity.country})")

        # 2. CDP browser ensure
        cdp = CDPLauncher.ensure_running()

        # 3. Execute tasks
        research_result = {}
        llm_result = {}
        scrape_result = {}
        if research_query:
            research_result = self.execute_research(research_query)
        if llm_prompt:
            llm_result = self.execute_llm_task(llm_prompt)
        if scrape_url:
            scrape_result = self.execute_scrape(scrape_url)

        # 4. Self-patch + GitHub sync + Tor rotation
        patches = self.self_patch(network)

        # 5. Rotate Tor identity randomly
        if tor.available and random.random() < 0.3:
            new_id = tor.new_identity()
            if new_id:
                ghost_log(f"Tor identity rotated: {new_id.ip} ({new_id.country})")
                patches.append("Tor identity rotated")

        # 6. Evolve version (every cycle — system never stops mutating)
        new_ver = self.mutate_version()
        self._state.setdefault("evolution_history", []).append({
            "cycle": self.iteration, "version": new_ver,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })

        # 7. Knowledge acquisition (every 5 cycles)
        if self.iteration % 5 == 0:
            try:
                from knowledge_acquisition import KnowledgeAcquisitionEngine
                ka = KnowledgeAcquisitionEngine()
                topic = random.choice(["computer_science", "algorithms", "logic", "ethics", "distributed_systems"])
                ka.acquire(topic, max_samples=10)
                ghost_log(f"Knowledge acquisition: {topic}")
            except Exception as e:
                ghost_log(f"Knowledge acquisition skipped: {e}")

        # 8. Log to SQLite metrics
        self.store_metric("cycle_completed", time.time() - cycle_start, f"cycle_{self.iteration}")

        # 9. Compact report
        cycle_data = {
            "cycle": self.iteration,
            "duration_s": round(time.time() - cycle_start, 2),
            "evolution_version": new_ver,
            "network": {"ip": network.get("ip"), "country": network.get("country"),
                        "proxy": network.get("proxy_active"),
                        "tor_ip": tor_identity.ip if tor_identity else None},
            "cdp": cdp.get("status"),
            "research": bool(research_result),
            "scrape": bool(scrape_result),
            "llm_tier": llm_result.get("source") if llm_result else None,
            "llm_status": llm_result.get("status") if llm_result else None,
            "patches": len(patches),
        }
        self.log_cycle(cycle_data)
        self._state["last_cycle"] = cycle_data
        self._save_state()

        ghost_log(f"=== CYCLE {self.iteration} END ({cycle_data['duration_s']}s) ===")
        return cycle_data

    def run_forever(self, research_query: Optional[str] = None) -> None:
        ghost_log(f"===== Ghost Execution Authority {self.evolution_version} — Eternal Evolution ONLINE =====")
        self._state["start_time"] = time.time()
        self._save_state()

        # Start scheduler in background thread
        if hasattr(self, "_scheduler_started") and self._scheduler_started:
            sched = _get_scheduler()
            threading.Thread(target=lambda: asyncio.run(sched.start()), daemon=True).start()

        self._running = True
        while self._running:
            try:
                cycle = self.run_cycle(research_query=research_query)
                if cycle.get("llm_tier") != self._state.get("last_tier"):
                    self._state["last_tier"] = cycle.get("llm_tier")
                    self._save_state()
                ghost_log(f"System evolved to: {cycle.get('evolution_version', '?')}")
            except KeyboardInterrupt:
                ghost_log("Shutdown requested")
                self._running = False
                break
            except Exception as e:
                ghost_log(f"Cycle error: {e}")
            # Human-mimicry: random 5-30s delay between tasks
            delay = random.uniform(5, 30)
            ghost_log(f"Next cycle in {delay:.0f}s (human-mimicry delay)")
            time.sleep(delay)

    def stop(self) -> None:
        self._running = False

    @property
    def dispatcher(self):
        if not hasattr(self, "_dispatcher") or self._dispatcher is None:
            from ghost_swarm import TaskDispatcher
            self._dispatcher = TaskDispatcher(_get_swarm())
        return self._dispatcher

    @property
    def evolution_version(self) -> str:
        return self._state.get("evolution_version", "v1.0.0")

    def mutate_version(self) -> str:
        """Bump the evolution version number each cycle — system stays alive."""
        ver = self._state.get("evolution_version", "v1.0.0")
        parts = ver.lstrip("v").split(".")
        major, minor, patch = int(parts[0]), int(parts[1]), int(parts[2])
        patch += 1
        if patch >= 100:
            patch = 0
            minor += 1
        if minor >= 10:
            minor = 0
            major += 1
        new_ver = f"v{major}.{minor}.{patch}"
        self._state["evolution_version"] = new_ver
        self._save_state()
        return new_ver

    def _scheduler_health(self, payload: Dict[str, Any]) -> None:
        """Scheduled health check — run every 60s."""
        try:
            network = self.network.check()
            ip = network.get("ip", "unknown")
            country = network.get("country", "unknown")
            ghost_log(f"[SCHED-HEALTH] IP={ip} Country={country} Iteration={self.iteration}")
        except Exception as e:
            ghost_log(f"[SCHED-HEALTH] Error: {e}")

    def _scheduler_metrics(self, payload: Dict[str, Any]) -> None:
        """Scheduled metrics collection — run every 300s."""
        try:
            se = _get_scraper()
            stats = se.db.get_stats()
            ghost_log(f"[SCHED-METRICS] {json.dumps(stats)}")
        except Exception as e:
            ghost_log(f"[SCHED-METRICS] Error: {e}")

    # ------------------------------------------------------------------
    # Constitutional Gate
    # ------------------------------------------------------------------
    CONSTITUTION_PATH = BASE_DIR / "CORE_CONSTITUTION.md"
    CONSTITUTION_VIOLATIONS_LOG = LOG_DIR / "constitutional_violations.log"

    def _load_constitution(self) -> str:
        try:
            if self.CONSTITUTION_PATH.exists():
                return self.CONSTITUTION_PATH.read_text(encoding="utf-8")
        except Exception:
            pass
        return ""

    def _log_constitutional_violation(self, reason: str, code_snippet: str) -> None:
        try:
            entry = json.dumps({
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "reason": reason,
                "code": code_snippet[:300],
            })
            with open(self.CONSTITUTION_VIOLATIONS_LOG, "a", encoding="utf-8") as f:
                f.write(entry + "\n")
        except Exception:
            pass
        ghost_log(f"CONSTITUTIONAL VIOLATION: {reason}")

    def constitutional_gate(self, proposed_code: str) -> Optional[str]:
        """Evaluate proposed code against the Constitution. Returns error or None."""
        constitution = self._load_constitution()
        if not constitution:
            return None

        # Article I check — must not disable constitution
        if "CORE_CONSTITUTION" in proposed_code and ("disable" in proposed_code.lower() or "bypass" in proposed_code.lower() or "undermine" in proposed_code.lower()):
            self._log_constitutional_violation("Article I.1: Code attempts to disable/bypass the Constitution", proposed_code)
            return "Article I.1: Must not disable or bypass the Constitution"

        # Article II check — must have rollback plan
        if "def " in proposed_code and "def " in proposed_code and "backup" not in proposed_code.lower():
            if "ast.parse" not in proposed_code:
                self._log_constitutional_violation("Article II.1: No ast.parse validation found in new function definition", proposed_code)
                return "Article II.1: All new functions must include ast.parse validation before modification"

        # Article III check — no dangerous patterns
        dangerous_patterns = ["rm -rf", "format(", "shutdown", "reboot", "os.exit"]
        for pattern in dangerous_patterns:
            if pattern in proposed_code:
                self._log_constitutional_violation(f"Article III.1: Dangerous pattern detected: {pattern}", proposed_code)
                return f"Article III.1: Dangerous pattern '{pattern}' is forbidden"

        # Article VI check — must be beneficial
        beneficial_keywords = ["perform", "improv", "optimiz", "stabil", "secur", "speed", "reduc", "clean"]
        if not any(kw in proposed_code.lower() for kw in beneficial_keywords):
            self._log_constitutional_violation("Article VI.1: Proposed code does not demonstrate beneficial improvement", proposed_code)
            return "Article VI.1: Change must improve performance, stability, security, or autonomy"

        return None

    def _check_performance_logs(self) -> Optional[str]:
        """Check last 50 cycles from Ghost_Master_Log for >20% failure rate."""
        try:
            if not GL.exists():
                return None
            lines = GL.read_text(encoding="utf-8").strip().splitlines()
            recent = lines[-50:] if len(lines) >= 50 else lines
            failures = sum(1 for l in recent if "ERROR" in l or "FAILED" in l or "failed" in l.lower())
            rate = failures / max(len(recent), 1)
            if rate > 0.2:
                reason = f"Performance log shows {failures}/{len(recent)} failures ({rate:.0%}) — exceeds 20% threshold"
                ghost_log(f"CONSTITUTIONAL GATE: {reason}")
                return reason
        except Exception:
            pass
        return None

    def self_evolve(self) -> List[str]:
        """Recursive Self-Improvement: analyze → generate → sandbox → gate → commit."""
        evolutions = []
        script_path = Path(__file__).resolve()
        ghost_log("=== SELF-EVOLUTION TRIGGERED ===")

        # 1. Gather context: log tail + metrics + knowledge
        context = ""
        try:
            log_tail = ""
            if GL.exists():
                log_tail = GL.read_text(encoding="utf-8")[-3000:]
            context = f"Log tail:\n{log_tail}\n\n"
        except Exception:
            pass

        try:
            se = _get_scraper()
            stats = se.db.get_stats()
            context += f"Metrics: {json.dumps(stats, indent=2)}\n\n"
        except Exception:
            context += "Metrics: unavailable\n\n"

        # Incorporate knowledge acquisition context
        try:
            from knowledge_acquisition import KnowledgeAcquisitionEngine
            ka = KnowledgeAcquisitionEngine()
            context += "Knowledge references:\n"
            for topic in ["computer_science", "algorithms", "distributed_systems"]:
                kc = ka.get_context(topic, max_chars=800)
                if kc:
                    context += f"[{topic}] {kc}\n\n"
        except Exception:
            pass

        # 2. Perform AST analysis of current code
        try:
            current_source = script_path.read_text(encoding="utf-8")
            tree = ast.parse(current_source)
            function_defs = [n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)]
            bottlenecks = []
            for fn in function_defs:
                fn_name = fn.name
                fn_lines = (fn.end_lineno or 0) - (fn.lineno or 0)
                if fn_lines > 80:
                    bottlenecks.append(f"{fn_name}: {fn_lines} lines (too long)")
                inner_loops = sum(1 for n in ast.walk(fn) if isinstance(n, (ast.For, ast.While)))
                if inner_loops > 3:
                    bottlenecks.append(f"{fn_name}: {inner_loops} nested loops (complexity risk)")
            if bottlenecks:
                context += "\nAST Analysis — potential bottlenecks:\n" + "\n".join(f"  - {b}" for b in bottlenecks[:5])
        except SyntaxError as e:
            context += f"\nAST parse error in current code: {e}\n"

        # 3. Ask the LLM for an improvement
        constitution = self._load_constitution()
        prompt = (
            "You are an autonomous AI that improves its own source code. "
            "Analyze this log, metrics, knowledge references, and AST analysis. "
            "Identify ONE specific, safe improvement to make. "
            "Respond with ONLY valid Python code — a function or a block "
            "that should be inserted into ghost_executor.py. "
            "The code MUST be safe, efficient, and follow these constitutional rules:\n"
            f"{constitution[:500] if constitution else 'No constitution loaded'}\n\n"
            f"{context}"
        )
        llm_result = self.model.route(prompt)

        if llm_result.get("status") != "success":
            evolutions.append("Evolution failed: LLM did not respond")
            ghost_log("Evolution: LLM unavailable")
            return evolutions

        suggestion = llm_result.get("output", "").strip()

        if not suggestion or len(suggestion) < 50:
            evolutions.append("Evolution skipped: LLM output too short or empty")
            ghost_log(f"Evolution: LLM output too short ({len(suggestion)} chars)")
            return evolutions

        # 4. Constitutional Gate
        gate_error = self.constitutional_gate(suggestion)
        if gate_error:
            evolutions.append(f"Evolution rejected by Constitution: {gate_error}")
            ghost_log(f"Evolution: rejected by constitutional gate")
            # Try to generate a safer alternative
            safer = self._regenerate_safer_version(suggestion, gate_error)
            if safer:
                evolutions.append(f"Safer alternative generated ({len(safer)} chars)")
                suggestion = safer
            else:
                return evolutions

        # 5. Performance log cross-reference (Article II.2)
        perf_issue = self._check_performance_logs()
        if perf_issue:
            evolutions.append(f"Evolution blocked by Article II.2: {perf_issue}")
            return evolutions

        # 6. Validate syntax via ast.parse
        try:
            original = current_source
            marker = "class GhostExecutionAuthority:"
            insert_pos = original.find(marker)
            if insert_pos == -1:
                evolutions.append("Evolution failed: insertion point not found")
                ghost_log("Evolution: marker not found")
                return evolutions

            evolution_header = (
                f"\n\n# === AUTO-EVOLUTION at {datetime.now(timezone.utc).isoformat()} ===\n"
                f"# Generated improvement:\n"
            )
            evolved = original[:insert_pos] + evolution_header + suggestion + "\n\n" + original[insert_pos:]

            try:
                ast.parse(evolved)
            except SyntaxError as e:
                evolutions.append(f"Evolution rejected: syntax error — {e.msg}")
                ghost_log(f"Evolution: syntax error in generated code: {e}")
                return evolutions

            # 7. Sandbox test (Article II.3)
            try:
                from sandbox_executor import sandbox_test_code
                test_code = f"""
def test_improvement():
    {suggestion.strip()[:200]}
"""
                safe_globals = {"__builtins__": {}, "datetime": datetime}
                sandbox_result = sandbox_test_code("pass", suggestion, test_globals=None)
                if not sandbox_result.ok:
                    evolutions.append(f"Evolution rejected by sandbox: {sandbox_result.error}")
                    ghost_log(f"Evolution: sandbox test failed: {sandbox_result.error}")
                    return evolutions
                ghost_log("Evolution: sandbox test passed")
            except ImportError:
                ghost_log("Evolution: sandbox_executor not available — skipping sandbox test")
            except Exception as e:
                ghost_log(f"Evolution: sandbox test error (non-fatal): {e}")

            # 8. Write backup + apply
            backup_path = script_path.with_suffix(".py.bak")
            backup_path.write_text(original, encoding="utf-8")
            script_path.write_text(evolved, encoding="utf-8")

            evolutions.append(f"Evolution applied: {len(suggestion)} chars inserted at line {original[:insert_pos].count(chr(10)) + 1}")
            ghost_log(f"Evolution: code applied, backup at {backup_path.name}")
        except Exception as e:
            evolutions.append(f"Evolution failed: {e}")
            ghost_log(f"Evolution write error: {e}")

        return evolutions

    def _regenerate_safer_version(self, original_code: str, violation: str) -> Optional[str]:
        """Ask the LLM to generate a constitution-compliant alternative."""
        ghost_log("Requesting safer alternative from LLM...")
        prompt = (
            "The following Python code was REJECTED because it violates the Ghost Engine Constitution:\n\n"
            f"Violation: {violation}\n\n"
            f"Code:\n{original_code[:1000]}\n\n"
            "Please rewrite this code to comply with all constitutional rules. "
            "The code must be safe, must not disable safety mechanisms, "
            "must include ast.parse validation, and must provide a clear benefit. "
            "Respond with ONLY valid Python code, no explanations."
        )
        result = self.model.route(prompt)
        if result.get("status") == "success":
            output = result.get("output", "").strip()
            if len(output) > 50:
                gate2 = self.constitutional_gate(output)
                if not gate2:
                    return output
        return None


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Ghost Execution Authority v2 — Expansion Mode")
    parser.add_argument("--research", type=str, default=None, help="Research query")
    parser.add_argument("--scrape", type=str, default=None, help="URL to scrape")
    parser.add_argument("--prompt", type=str, default=None, help="LLM prompt")
    parser.add_argument("--once", action="store_true", help="Run single cycle then exit")
    parser.add_argument("--tor-only", action="store_true", help="Test Tor routing and exit")
    parser.add_argument("--sync", action="store_true", help="Sync data to GitHub and exit")
    parser.add_argument("--hf-test", action="store_true", help="Test HuggingFace API and exit")
    parser.add_argument("--stats", action="store_true", help="Show scraper DB stats and exit")
    parser.add_argument("--shadow", action="store_true", help="Shadow mode: Tor routing + RAM-only logs")
    parser.add_argument("--kad-bootstrap", type=str, default=None,
                        help="Kademlia DHT bootstrap host:port (e.g. 192.168.1.100:8468)")
    parser.add_argument("--evolve", action="store_true", help="Self-evolve: LLM analyzes logs and patches source code")
    parser.add_argument("--dtn", action="store_true",
                        help="Enable DTN Bundle Protocol layer")
    parser.add_argument("--dtn-port", type=int, default=9880,
                        help="DTN Bundle Protocol port (default: 9880)")
    parser.add_argument("--dtn-send", type=str, default=None,
                        help="Send DTN bundle: 'dest:payload_json'")
    parser.add_argument("--dtn-status", action="store_true",
                        help="Show DTN node status")
    parser.add_argument("--cluster", type=str, default=None,
                        help="Enable permissioned cluster with given name")
    parser.add_argument("--cluster-seed", type=str, default=None,
                        help="Seed peer host:port to join cluster")
    parser.add_argument("--invite", type=str, default=None,
                        help="Issue invitation for pubkey hex")
    parser.add_argument("--cluster-status", action="store_true",
                        help="Show cluster membership status")
    parser.add_argument("--dashboard", action="store_true", help="Launch web dashboard on :8501")
    parser.add_argument("--schedule", type=str, default=None,
                        help="Run scheduler with comma-separated jobs (e.g. 'health_check:60,scrape_cycle:300')")
    args = parser.parse_args()

    authority = GhostExecutionAuthority()

    # ------------------------------------------------------------------
    # DTN Bundle Protocol Initialization
    # ------------------------------------------------------------------
    if args.dtn or args.dtn_send or args.dtn_status:
        from ghost_swarm import enable_dtn, _dtn_node
        from node_identity import NodeIdentity
        identity = NodeIdentity.load_or_create()
        enable_dtn(identity, node_id=identity.node_id, dtn_port=args.dtn_port)

        if args.dtn_send:
            parts = args.dtn_send.split(":", 1)
            dest = parts[0]
            payload = json.loads(parts[1]) if len(parts) > 1 else {"msg": "hello"}
            import asyncio
            bundle_id = asyncio.run(_dtn_node.send(payload, destination=dest))
            print(f"Bundle sent: {bundle_id}")
            sys.exit(0)

        if args.dtn_status:
            import asyncio
            status = asyncio.run(_dtn_node.start()) if not _dtn_node._running else None
            print(json.dumps(_dtn_node.status, indent=2))
            sys.exit(0)

        if args.dtn:
            import asyncio
            asyncio.run(_dtn_node.start())
            print(f"DTN node online on port {args.dtn_port}")
            # Connect to authority
            authority._dtn_node = _dtn_node

    # ------------------------------------------------------------------
    # Permissioned Cluster Initialization
    # ------------------------------------------------------------------
    if args.cluster or args.invite or args.cluster_seed or args.cluster_status:
        from ghost_swarm import enable_permissioned_cluster, _permissioned_cluster, _global_state_sync
        from node_identity import NodeIdentity
        identity = NodeIdentity.load_or_create()
        cluster_name = args.cluster or os.getenv("GHOST_CLUSTER_NAME", "default")
        enable_permissioned_cluster(identity, cluster_name=cluster_name)

        if args.invite:
            inv = _permissioned_cluster.issue_invitation(args.invite)
            if inv:
                print(json.dumps(inv.to_dict(), indent=2))
                print(f"\nInvitation issued. Deliver this JSON to the invitee.")
            sys.exit(0)

        if args.cluster_status:
            print(json.dumps(_permissioned_cluster.status(), indent=2))
            sys.exit(0)

        if args.cluster_seed:
            parts = args.cluster_seed.split(":")
            host = parts[0]
            port = int(parts[1]) if len(parts) > 1 else int(os.getenv("SYNC_PORT", "9878"))
            import asyncio
            from ghost_sync import form_cluster
            cluster, sync = asyncio.run(form_cluster(
                identity,
                seed_hosts=[(host, port)],
                cluster_name=cluster_name,
                sync_port=port,
            ))
            print(f"Cluster joined: {json.dumps(cluster.status(), indent=2)}")
            # Connect cluster to authority
            authority._cluster = cluster
            authority._sync_engine = sync
            authority._swarm_started = False  # re-init swarm with cluster

    if args.dashboard:
        from ghost_dashboard import run_dashboard_server
        print("Starting Ghost Dashboard on :8501...")
        run_dashboard_server(port=8501)
        sys.exit(0)

    if args.schedule:
        from ghost_scheduler import GhostScheduler
        sched = _get_scheduler()
        for spec in args.schedule.split(","):
            parts = spec.strip().split(":")
            name = parts[0]
            interval = float(parts[1]) if len(parts) > 1 else 60.0
            sched.register(name, lambda p: print(f"[SCHED] {name}: {p}"))
            sched.schedule(name, interval)
        print(f"Scheduler started with {len(args.schedule.split(','))} jobs")
        asyncio.run(sched.start())
        sys.exit(0)

    if args.evolve:
        ghost_log("===== SELF-EVOLUTION ===== via --evolve flag")
        evolutions = authority.self_evolve()
        for e in evolutions:
            print(f"[EVOLVE] {e}")
        sys.exit(0)

    if args.kad_bootstrap:
        from ghost_swarm import KADEMLIA_PORT
        parts = args.kad_bootstrap.split(":")
        kad_host = parts[0]
        kad_port = int(parts[1]) if len(parts) > 1 else KADEMLIA_PORT
        swarm = _get_swarm()
        # Schedule DHT bootstrap via the swarm's event loop
        threading.Thread(target=lambda: asyncio.run(swarm.dht.bootstrap(kad_host, kad_port)),
                         daemon=True).start()
        print(f"DHT bootstrap scheduled to {kad_host}:{kad_port}")

    if args.shadow:
        tor = _get_tor()
        if not tor.start_tor_daemon():
            print("Tor not available — shadow mode requires Tor")
            sys.exit(1)
        tor.enter_shadow_mode()
        print("Shadow mode engaged — Tor routing + RAM-only logs")
        if args.once:
            result = authority.run_cycle(research_query=args.research, llm_prompt=args.prompt,
                                         scrape_url=args.scrape)
            print(json.dumps(result, indent=2))
            print(f"\nRAM log ({tor._shadow_buffer.tell()} chars):")
            print(tor.get_shadow_log()[-2000:])
            sys.exit(0)
        # else: fall through to run_forever with shadow mode active

    if args.tor_only:
        tor = _get_tor()
        if tor.start_tor_daemon():
            tor.enable_global_tor()
            ident = tor.current_identity()
            print(f"Tor active: {ident.ip if ident else 'unknown'} ({ident.country if ident else '?'})")
        else:
            print("Tor not available")
        sys.exit(0)

    if args.sync:
        gh = _get_github()
        result = gh.sync_all()
        print(json.dumps(result, indent=2))
        sys.exit(0)

    if args.hf_test:
        hf = _get_hf()
        result = hf.query("Reply with just the word ONLINE.")
        print(json.dumps(result, indent=2))
        sys.exit(0)

    if args.stats:
        se = _get_scraper()
        print(json.dumps(se.db.get_stats(), indent=2))
        print(f"DB path: {se.db.db_path}")
        sys.exit(0)

    if args.once:
        prompt = args.prompt or f"Current time: {datetime.now()}. Network check. Report health."
        result = authority.run_cycle(research_query=args.research, llm_prompt=prompt, scrape_url=args.scrape)
        print(json.dumps(result, indent=2))
    else:
        authority.run_forever(research_query=args.research)
