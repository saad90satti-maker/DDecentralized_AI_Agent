"""
Ecosystem Hardening v1.0 — Reliability, Observability, Recovery
================================================================
Integrates all newly installed libraries:
  - diskcache   → persistent knowledge cache, cross-session
  - loguru      → structured console + file logging with rotation
  - structlog   → JSON-format machine-parseable agent logs
  - cachetools  → TTL caches in memory and shared memory layers
  - apscheduler → cron-based scheduled tasks
  - schedule    → lightweight periodic health checks
  - pandera     → data validation for knowledge entries
  - huey        → optional distributed task queue backend
"""

import asyncio
import json
import shutil
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from loguru import logger
import diskcache as dc
from apscheduler.schedulers.asyncio import AsyncIOScheduler

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "agent_data"
LOG_DIR = BASE_DIR / "agent_logs"
BACKUP_DIR = DATA_DIR / "backups"
HEALTH_DIR = DATA_DIR / "health_reports"

for d in [DATA_DIR, LOG_DIR, BACKUP_DIR, HEALTH_DIR]:
    d.mkdir(exist_ok=True)


class EcosystemHardening:
    """System hardening layer: backups, health reports, dependency checks, scheduler."""

    def __init__(self, kernel=None, memory=None):
        self._kernel = kernel
        self._memory = memory
        self._disk_cache = dc.Cache(str(DATA_DIR / "diskcache"))
        self._scheduler = AsyncIOScheduler()
        self._start_time = time.time()

    # ─── Backup System ─────────────────────────────────────────────

    def backup_configs(self) -> Dict[str, Any]:
        """Backup all ecosystem configuration files with rotation."""
        now = datetime.now().strftime("%Y%m%d_%H%M%S")
        results = {"backup_id": now, "files": [], "errors": []}

        patterns = [
            ("agent_data/ecosystem_*.json", DATA_DIR),
            ("agent_data/ghost_*.json", DATA_DIR),
            ("agent_data/*.db", DATA_DIR),
            (".env", BASE_DIR),
            ("agent_config.json", BASE_DIR),
        ]

        backup_subdir = BACKUP_DIR / now
        backup_subdir.mkdir(parents=True, exist_ok=True)

        for pattern, search_dir in patterns:
            for f in search_dir.glob(pattern):
                if f.is_file():
                    try:
                        dest = backup_subdir / f.name
                        shutil.copy2(str(f), str(dest))
                        results["files"].append(str(f.relative_to(BASE_DIR)))
                    except Exception as e:
                        results["errors"].append(f"{f.name}: {e}")

        self._rotate_backups(max_backups=7)
        logger.info("backup_complete", files=len(results["files"]), backup_id=now)
        return results

    def _rotate_backups(self, max_backups: int = 7) -> None:
        """Keep only the N most recent backups."""
        backups = sorted(BACKUP_DIR.iterdir()) if BACKUP_DIR.exists() else []
        while len(backups) > max_backups:
            oldest = backups.pop(0)
            shutil.rmtree(str(oldest), ignore_errors=True)
            logger.info("backup_rotated", removed=str(oldest.name))

    # ─── Health Reports ────────────────────────────────────────────

    def generate_health_report(self) -> Dict[str, Any]:
        """Generate a structured health report with trend tracking."""
        report = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "uptime_s": round(time.time() - self._start_time, 1),
            "disk_cache": {
                "size": self._disk_cache.volume(),
                "entries": len(self._disk_cache),
            },
            "hardening": {
                "backups_available": len(list(BACKUP_DIR.iterdir())) if BACKUP_DIR.exists() else 0,
            },
        }

        if self._kernel:
            status = self._kernel.get_status()
            report["kernel"] = {
                "node_id": status.get("ecosystem", {}).get("node_id"),
                "tick": status.get("ecosystem", {}).get("tick"),
                "agents_alive": status.get("agents", {}).get("alive", 0),
                "agents_total": status.get("agents", {}).get("total", 0),
                "tasks_done": status.get("tasks", {}).get("done", 0),
                "tasks_failed": status.get("tasks", {}).get("failed", 0),
                "messages": status.get("stats", {}).get("total_messages", 0),
                "errors": status.get("stats", {}).get("total_errors", 0),
                "cpu_percent": status.get("cpu_percent"),
                "memory_percent": status.get("memory_percent"),
                "memory_available_gb": status.get("memory_available_gb"),
            }

        if self._memory:
            mem_stats = self._memory.snapshot()
            report["memory"] = mem_stats

        # Save report
        report_path = HEALTH_DIR / f"health_{datetime.now():%Y%m%d_%H%M%S}.json"
        report_path.write_text(json.dumps(report, indent=2, default=str))
        logger.info("health_report_generated", path=str(report_path))
        return report

    # ─── Dependency Check ─────────────────────────────────────────

    def check_dependencies(self) -> Dict[str, Any]:
        """Check that all required packages are installed."""
        required = {
            "loguru": "0.7.3",
            "cachetools": "7.1.4",
            "diskcache": "5.6.3",
            "apscheduler": "3.11.2",
            "structlog": "26.1.0",
        }
        results = {}
        all_ok = True
        for pkg, ver in required.items():
            try:
                mod = __import__(pkg)
                installed = getattr(mod, "__version__", "?")
                results[pkg] = {"status": "ok", "installed": installed, "required": ver}
            except ImportError:
                results[pkg] = {"status": "missing", "required": ver}
                all_ok = False
        results["all_ok"] = all_ok
        logger.info("dependency_check", all_ok=all_ok)
        return results

    # ─── Scheduler ────────────────────────────────────────────────

    async def start_scheduler(self) -> None:
        """Start APScheduler with ecosystem health tasks."""
        self._scheduler.add_job(
            self.generate_health_report,
            "interval",
            minutes=5,
            id="health_report",
            replace_existing=True,
        )
        self._scheduler.add_job(
            self.backup_configs,
            "interval",
            hours=1,
            id="config_backup",
            replace_existing=True,
        )
        self._scheduler.start()
        logger.info("hardening_scheduler_started", jobs=len(self._scheduler.get_jobs()))

    async def stop_scheduler(self) -> None:
        if self._scheduler.running:
            self._scheduler.shutdown(wait=False)

    # ─── Disk Cache Helpers ───────────────────────────────────────

    def cache_get(self, key: str) -> Optional[Any]:
        try:
            return self._disk_cache.get(key)
        except Exception:
            return None

    def cache_set(self, key: str, value: Any, expire: int = 3600) -> None:
        try:
            self._disk_cache.set(key, value, expire=expire)
        except Exception:
            pass

    # ─── Lifecycle ────────────────────────────────────────────────

    async def start(self) -> None:
        logger.info("ecosystem_hardening_started")
        self._start_time = time.time()
        await self.start_scheduler()
        self.backup_configs()

    async def stop(self) -> None:
        await self.stop_scheduler()
        self._disk_cache.close()
        logger.info("ecosystem_hardening_stopped")
