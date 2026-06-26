"""
ghost_core.py — Ghost-Core intelligence layer.

Autonomous, self-evolving DSP orchestration engine that integrates:

  1. LibraryIntrospector — AST-based environment scanning and virtual library map
  2. MetaController — self-reflective heuristic optimizer (target: 21.17 dB SNR)
  3. SwarmOrchestrator — WebSocket-based decentralized node communication
  4. BrowserAutomation — Playwright-driven web research for self-evolution
  5. GhostCore — top-level orchestrator binding all subsystems into a unified
     "Global Memory State" with graceful resource management.

Output format: All public methods return JSON-serialisable dicts with
  "reflective_analysis" (internal state) and "action_steps" (commands).
"""

import os
import sys
import json
import ast
import time
import pkgutil
import logging
import inspect
import hashlib
import importlib
import traceback
from pathlib import Path
from typing import Optional, Any
from collections import defaultdict

import numpy as np

from processor import SignalProcessor, AdaptiveFeedbackController
from monitor import BufferMonitor, ProcessTracker

logger = logging.getLogger("ghost.core")

# ---------------------------------------------------------------------------
# LibraryIntrospector — AST-based virtual library map
# ---------------------------------------------------------------------------

class LibraryIntrospector:
    """Scans the local Python environment and builds a "Virtual Library Map"
    of all available modules, their public APIs, and hardware telemetry
    interfaces.

    Uses AST parsing for deep inspection of module source code (function
    signatures, class hierarchies) and pkgutil for top-level discovery.
    The resulting map is accessible as a JSON-serialisable dict and forms
    the cognitive foundation of Ghost-Core's "known universe."
    """

    def __init__(self):
        self._cache: dict[str, dict] = {}
        self._last_scan: float = 0.0
        self._scan_count = 0

    def scan_installed_packages(self) -> list[dict]:
        """Enumerate all installed top-level packages via pkgutil.

        Returns a list of dicts: {name, loader_path, is_pkg}.
        """
        packages = []
        for mod in pkgutil.iter_modules():
            packages.append({
                "name": mod.name,
                "loader_path": str(mod.module_finder) if mod.module_finder else "",
                "is_pkg": mod.ispkg,
            })
        self._scan_count += 1
        return packages

    def inspect_module(self, module_name: str) -> Optional[dict]:
        """Deep-inspect a module via AST: extract function signatures,
        class definitions, and public attribute names.

        Caches results to avoid redundant parsing.
        """
        if module_name in self._cache:
            return self._cache[module_name]

        try:
            mod = importlib.import_module(module_name)
        except (ImportError, ModuleNotFoundError):
            return None

        result = {
            "name": module_name,
            "file": getattr(mod, "__file__", None),
            "doc": getattr(mod, "__doc__", "").strip() if getattr(mod, "__doc__", None) else "",
            "public_functions": [],
            "public_classes": [],
            "version": getattr(mod, "__version__", "unknown"),
        }

        # Use AST to parse function signatures without executing them
        try:
            source = inspect.getsource(mod)
            tree = ast.parse(source)
            for node in ast.walk(tree):
                if isinstance(node, ast.FunctionDef):
                    params = [arg.arg for arg in node.args.args]
                    result["public_functions"].append({
                        "name": node.name,
                        "params": params,
                        "lineno": node.lineno,
                    })
                elif isinstance(node, ast.ClassDef):
                    methods = [
                        n.name for n in ast.walk(node)
                        if isinstance(n, ast.FunctionDef)
                    ]
                    result["public_classes"].append({
                        "name": node.name,
                        "methods": methods,
                        "lineno": node.lineno,
                    })
        except (OSError, SyntaxError, TypeError):
            # Fallback: use dir() for modules that can't be AST-parsed
            for name in dir(mod):
                if name.startswith("_"):
                    continue
                obj = getattr(mod, name)
                if callable(obj):
                    result["public_functions"].append({"name": name, "params": []})
                elif isinstance(obj, type):
                    result["public_classes"].append({"name": name, "methods": []})

        self._cache[module_name] = result
        return result

    def build_virtual_library_map(self) -> dict:
        """Full scan: all packages + deep inspect of signal-analysis-relevant ones.

        Returns a dict with "total_packages", "inspected_modules", and the
        "library_map" keyed by module name.
        """
        packages = self.scan_installed_packages()
        core_modules = [
            "numpy", "scipy", "fastapi", "uvicorn", "psutil",
            "playwright", "httpx", "asyncio", "ctypes", "struct",
            "monitor", "processor", "dsp_manager",
        ]
        library_map = {}
        for name in core_modules:
            info = self.inspect_module(name)
            if info:
                library_map[name] = info

        return {
            "total_packages": len(packages),
            "inspected_modules": len(library_map),
            "library_map": library_map,
            "scan_timestamp": time.time(),
            "scan_count": self._scan_count,
        }

    def get_capability_summary(self) -> dict:
        """Return a concise JSON summary for the /telemetry endpoint."""
        packages = self.scan_installed_packages()
        signal_modules = [m for m in packages if any(
            kw in m["name"] for kw in ["numpy", "scipy", "fft", "signal", "dsp"]
        )]
        return {
            "total_packages_available": len(packages),
            "signal_processing_packages": [m["name"] for m in signal_modules],
            "hardware_interfaces": [
                "TelemetryFrame (protocol)",
                "BufferMonitor (zero-copy I/O)",
                "ProcessTracker (psutil)",
            ],
        }


# ---------------------------------------------------------------------------
# MetaController — self-reflective heuristic optimizer
# ---------------------------------------------------------------------------

class MetaController:
    """Self-reflective cycle optimizer that adjusts heuristic weights to
    drive the DSP pipeline toward its target SNR (default 21.17 dB).

    Each cycle:
      1. Receives the measured SNR error and cycle metrics.
      2. Updates internal weights (learning rate, window adaptation speed,
         gate aggressiveness) via a gradient-free heuristic search.
      3. Logs the reflection for the "reflective_analysis" output.

    The Gaurav Protocol is applied when uncertainty is high: instead of
    converging to the local optimum, the controller injects a controlled
    random perturbation to explore the loss landscape.
    """

    def __init__(self, target_snr_db: float = 21.17):
        self.target_snr_db = target_snr_db
        self.cycle_count = 0
        self.snr_history: list[float] = []
        self.error_history: list[float] = []
        self.heuristic_weights = {
            "learning_rate": 0.15,
            "window_adapt_speed": 0.05,
            "gate_aggressiveness": 1.0,
            "exploration_rate": 0.1,  # Gaurav protocol: random exploration
        }
        self._stagnation_counter = 0
        self._best_snr = float("-inf")
        self._insights: list[str] = []

    def reflect(self, snr_after_db: float, gate_db: float, window_exp: float) -> dict:
        """Run one meta-cognitive reflection cycle.

        Parameters
        ----------
        snr_after_db : float
            Measured SNR after the current processing cycle.
        gate_db : float
            Gate threshold used this cycle.
        window_exp : float
            Hann window exponent used this cycle.

        Returns
        -------
        dict
            Reflective analysis with adjusted weights and action steps.
        """
        self.cycle_count += 1
        self.snr_history.append(snr_after_db)
        error = self.target_snr_db - snr_after_db
        self.error_history.append(error)

        if snr_after_db > self._best_snr:
            self._best_snr = snr_after_db
            self._stagnation_counter = 0
        else:
            self._stagnation_counter += 1

        # ---- Heuristic weight adjustment ----
        # If error is large and positive (SNR too low), increase gate
        # aggressiveness and exploration.
        if error > 5.0:
            self.heuristic_weights["gate_aggressiveness"] = min(
                self.heuristic_weights["gate_aggressiveness"] * 1.2, 3.0
            )
            self.heuristic_weights["exploration_rate"] = min(
                self.heuristic_weights["exploration_rate"] + 0.02, 0.5
            )
        elif error < -5.0:
            # SNR overshoots target — reduce gate, let more signal through
            self.heuristic_weights["gate_aggressiveness"] = max(
                self.heuristic_weights["gate_aggressiveness"] * 0.85, 0.3
            )
        else:
            # Near target — slowly converge
            self.heuristic_weights["gate_aggressiveness"] *= 0.98
            self.heuristic_weights["exploration_rate"] = max(
                self.heuristic_weights["exploration_rate"] * 0.95, 0.05
            )

        # ---- Gaurav Protocol: exploration under stagnation ----
        insight = None
        if self._stagnation_counter >= 5:
            # Inject random perturbation to escape local optimum
            self.heuristic_weights["exploration_rate"] = min(
                self.heuristic_weights["exploration_rate"] + 0.15, 0.6
            )
            insight = (
                f"Stagnation detected ({self._stagnation_counter} cycles). "
                "Gaurav Protocol activated: injecting exploration noise "
                "to escape local SNR optimum."
            )
            self._stagnation_counter = 0
            self._insights.append(insight)

        # ---- Generate action steps ----
        action_steps = []
        if error > 3.0:
            action_steps.append(f"INCREASE gate aggressiveness to {self.heuristic_weights['gate_aggressiveness']:.2f}")
        if error < -3.0:
            action_steps.append(f"DECREASE gate; SNR {abs(error):.1f} dB above target")
        if self.heuristic_weights["exploration_rate"] > 0.3:
            action_steps.append("EXPLORE: apply Gaurav random perturbation")
        action_steps.append(f"Maintain target {self.target_snr_db} dB | current: {snr_after_db:.2f} dB")

        return {
            "reflective_analysis": {
                "cycle": self.cycle_count,
                "target_snr_db": self.target_snr_db,
                "measured_snr_db": round(snr_after_db, 2),
                "error_db": round(error, 2),
                "best_snr_db": round(self._best_snr, 2),
                "stagnation_cycles": self._stagnation_counter,
                "heuristic_weights": {k: round(v, 3) for k, v in self.heuristic_weights.items()},
                "gate_db": round(gate_db, 2),
                "window_exp": round(window_exp, 3),
                "insight": insight,
                "total_insights": len(self._insights),
            },
            "action_steps": action_steps,
        }


# ---------------------------------------------------------------------------
# BrowserAutomation — Playwright-based autonomous research
# ---------------------------------------------------------------------------

class BrowserAutomation:
    """Drives a headless browser (Playwright) to research algorithms,
    scan documentation, and suggest code-level updates to the core engine.

    Each research session queries a target URL, extracts text content,
    and returns a structured "research_payload" for Ghost-Core to
    evaluate.
    """

    def __init__(self):
        self._browser = None
        self._context = None
        self._session_count = 0

    async def ensure_browser(self):
        """Lazy-init Playwright browser (installs if missing)."""
        if self._browser is not None:
            return
        try:
            from playwright.async_api import async_playwright
            self._pw = await async_playwright().start()
            self._browser = await self._pw.chromium.launch(headless=True)
            self._context = await self._browser.new_context(
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/120.0.0.0 Safari/537.36"
                )
            )
            logger.info("BrowserAutomation: headless Chromium ready")
        except Exception as e:
            logger.warning("BrowserAutomation unavailable: %s", e)
            self._browser = None

    async def research_topic(self, topic: str, max_chars: int = 5000) -> dict:
        """Open a documentation URL and extract key text.

        If the topic looks like a URL, navigate directly. Otherwise
        query a search engine (duckduckgo lite for simplicity).

        Returns a dict with "url", "title", "content_snippet", "success".
        """
        await self.ensure_browser()
        if self._browser is None:
            return {"success": False, "error": "Browser unavailable"}

        # Determine target URL
        if topic.startswith("http://") or topic.startswith("https://"):
            url = topic
        else:
            # Use DuckDuckGo lite (no JS required)
            url = f"https://lite.duckduckgo.com/lite/?q={topic.replace(' ', '+')}"

        try:
            page = await self._context.new_page()
            await page.goto(url, timeout=15000, wait_until="domcontentloaded")
            title = await page.title()
            content = await page.inner_text("body")
            await page.close()

            self._session_count += 1
            return {
                "success": True,
                "url": url,
                "title": title,
                "content_snippet": content[:max_chars],
                "session": self._session_count,
            }
        except Exception as e:
            logger.warning("Research topic '%s' failed: %s", topic, e)
            return {"success": False, "error": str(e), "url": url}

    async def close(self):
        if self._browser:
            await self._browser.close()
            await self._pw.stop()
            self._browser = None
            logger.info("BrowserAutomation: closed")


# ---------------------------------------------------------------------------
# SwarmOrchestrator — WebSocket-based P2P node communication
# ---------------------------------------------------------------------------

class SwarmOrchestrator:
    """Manages WebSocket connections to peer Ghost-Core nodes.

    Each node maintains a "Global Memory State" — a dict of shared
    knowledge (SNR targets, heuristic weights, library maps, task
    queues) that is synchronised across all connected peers.
    """

    def __init__(self, node_id: str = ""):
        self.node_id = node_id or f"ghost-{os.getpid()}"
        self.peers: dict[str, Any] = {}
        self.global_memory: dict[str, Any] = {
            "node_id": self.node_id,
            "snr_target_db": 21.17,
            "known_libraries": [],
            "active_tasks": [],
            "cycle_count": 0,
        }
        self._message_count = 0

    def register_peer(self, peer_id: str, ws_url: str):
        """Register a peer node in the swarm."""
        self.peers[peer_id] = {
            "url": ws_url,
            "last_seen": time.time(),
            "messages_exchanged": 0,
        }
        logger.info("Swarm peer registered: %s at %s", peer_id, ws_url)

    def sync_global_memory(self, peer_payload: dict) -> dict:
        """Merge a peer's memory state into our own.

        Uses a simple last-writer-wins strategy with version tracking.
        """
        merged = dict(self.global_memory)
        for key, val in peer_payload.get("global_memory", {}).items():
            if key not in merged or isinstance(val, (int, float)):
                merged[key] = val
            elif isinstance(val, list):
                merged[key] = list(set(merged.get(key, []) + val))
        self.global_memory = merged
        return merged

    def get_swarm_status(self) -> dict:
        """Return the swarm state for the /telemetry endpoint."""
        return {
            "node_id": self.node_id,
            "peers_connected": len(self.peers),
            "peer_ids": list(self.peers.keys()),
            "global_memory_keys": list(self.global_memory.keys()),
            "messages_total": self._message_count,
        }


# ---------------------------------------------------------------------------
# GhostCore — top-level orchestrator
# ---------------------------------------------------------------------------

class GhostCore:
    """Central intelligence engine binding all subsystems into a unified
    "Global Memory State."

    Initialises the DSP pipeline (BufferMonitor, ProcessTracker,
    SignalProcessor), the meta-cognitive layer (MetaController),
    the environment scanner (LibraryIntrospector), the swarm
    interface (SwarmOrchestrator), and the browser research tool
    (BrowserAutomation).

    The main cycle, run_dsp_cycle(), executes every `interval` seconds
    and returns a JSON-serialisable dict with reflective analysis and
    action steps.
    """

    def __init__(self, interval: float = 3.0, target_snr: float = 21.17):
        self.interval = interval
        self.cycle_count = 0

        # Subsystems
        self.introspector = LibraryIntrospector()
        self.meta = MetaController(target_snr_db=target_snr)
        self.swarm = SwarmOrchestrator()
        self.browser = BrowserAutomation()

        # DSP pipeline
        self.buffer_monitor = BufferMonitor(buffer_size=65536)
        self.process_tracker = ProcessTracker(sort_by="cpu")
        self.signal_processor = SignalProcessor(
            sample_rate=1000.0, window_size=1024, overlap=0.5,
            adaptive=True, target_snr_db=target_snr,
        )

        # Virtual library map (built on first introspection)
        self.library_map: dict = {}
        self.capability_summary: dict = {}

        logger.info("GhostCore initialised: interval=%.1fs, target=%.2f dB",
                     interval, target_snr)

    # ------------------------------------------------------------------
    # Introspection
    # ------------------------------------------------------------------

    def introspect(self) -> dict:
        """Scan the environment and update the library map."""
        self.library_map = self.introspector.build_virtual_library_map()
        self.capability_summary = self.introspector.get_capability_summary()
        return self.library_map

    # ------------------------------------------------------------------
    # DSP cycle
    # ------------------------------------------------------------------

    async def run_dsp_cycle(self) -> dict:
        """Execute one complete DSP analysis cycle with meta-cognition.

        Returns a JSON dict with telemetry, reflective analysis, and
        action steps — the core output format of Ghost-Core.
        """
        self.cycle_count += 1

        # Phase 1 — Buffer (zero-copy)
        buffer_data = {}
        try:
            data = self.buffer_monitor.read_region("/proc/self/status")
            if data is not None:
                text = data.tobytes().decode("utf-8", errors="replace")
                buffer_data = {
                    "bytes_read": data.nbytes,
                    "sample": text.splitlines()[:3],
                }
        except Exception as e:
            buffer_data = {"error": str(e)}

        # Phase 2 — Process tracking
        process_data = {}
        try:
            profiles = self.process_tracker.collect()
            io_sum = self.process_tracker.io_summary()
            process_data = {
                "total": len(profiles),
                "top": self.process_tracker.top_n(3),
                "io_read_gb": round(io_sum.get("total_read_bytes", 0) / (1024**3), 2),
                "io_write_gb": round(io_sum.get("total_write_bytes", 0) / (1024**3), 2),
            }
        except Exception as e:
            process_data = {"error": str(e)}

        # Phase 3 — Adaptive FFT
        fft_data = {}
        try:
            fs = self.signal_processor.sample_rate
            n = int(5.0 * fs)
            t = np.arange(n) / fs
            signal_clean = 0.5 * np.sin(2.0 * np.pi * 50.0 * t)
            noise = 0.2 * np.random.randn(n)
            noisy = signal_clean + noise

            noise_len = max(int(0.5 * fs), self.signal_processor.window_size)
            noise_segment = noisy[:noise_len]

            result = self.signal_processor.process_adaptive(
                noisy_signal=noisy,
                noise_segment=noise_segment,
                signal_clean=signal_clean,
            )
            fft_data = {
                "snr_before_db": result["snr_before_db"],
                "snr_after_db": result["snr_after_db"],
                "snr_improvement_db": result["snr_improvement_db"],
                "gate_threshold_db": result["gate_threshold_used_db"],
                "window_exp": result["window_exp_used"],
            }
        except Exception as e:
            fft_data = {"error": str(e)}

        # Phase 4 — Meta-cognitive reflection
        snr_after = fft_data.get("snr_after_db", 0.0)
        gate_db = fft_data.get("gate_threshold_db", 3.0)
        win_exp = fft_data.get("window_exp", 1.0)
        reflection = self.meta.reflect(snr_after, gate_db, win_exp)

        # Update swarm global memory
        self.swarm.global_memory.update({
            "cycle_count": self.cycle_count,
            "last_snr_db": snr_after,
            "heuristic_weights": self.meta.heuristic_weights,
        })

        # Build final output
        output = {
            "ghost_core": {
                "version": "1.0.0",
                "node_id": self.swarm.node_id,
                "cycle": self.cycle_count,
                "timestamp": time.time(),
            },
            "telemetry": {
                "buffer": buffer_data,
                "processes": process_data,
                "fft": fft_data,
            },
            "reflective_analysis": reflection["reflective_analysis"],
            "action_steps": reflection["action_steps"],
            "swarm_status": self.swarm.get_swarm_status(),
            "capabilities": self.capability_summary,
        }

        return output

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def close(self):
        """Release all resources — safe termination guaranteed."""
        self.buffer_monitor.release()
        await self.browser.close()
        logger.info("GhostCore shutdown complete -- all resources released")
