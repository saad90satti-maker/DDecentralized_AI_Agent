"""
GitHub Sync Engine — Auto-syncs SQLite databases and agent data to GitHub.
Ensures data persistence even after local system restart.
"""

import json
import logging
import os
import sqlite3
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests

logger = logging.getLogger("GitHubSync")

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "agent_data"
DB_PATH = DATA_DIR / "scraper_data.db"
SYNC_STATE_FILE = DATA_DIR / "github_sync_state.json"


def get_token() -> str:
    return os.getenv("GITHUB_TOKEN", "")


class GitHubSync:
    """Push/pull agent data to a GitHub repository."""

    def __init__(self, repo: str = "DDecentralized_AI_Agent", branch: str = "main"):
        self.token = get_token()
        self.repo = repo
        self.branch = branch
        self.api_base = f"https://api.github.com/repos/{repo}" if "/" in repo else None
        self._headers = {"Authorization": f"token {self.token}", "Accept": "application/vnd.github.v3+json"} if self.token else {}
        self._state = self._load_state()

    def _load_state(self) -> Dict[str, Any]:
        try:
            if SYNC_STATE_FILE.exists():
                return json.loads(SYNC_STATE_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
        return {"last_sync": None, "sync_count": 0}

    def _save_state(self) -> None:
        try:
            SYNC_STATE_FILE.write_text(json.dumps(self._state, indent=2), encoding="utf-8")
        except Exception:
            pass

    def verify_token(self) -> bool:
        if not self.token:
            logger.warning("GITHUB_TOKEN not set")
            return False
        try:
            r = requests.get("https://api.github.com/user", headers=self._headers, timeout=10)
            if r.ok:
                user = r.json().get("login", "?")
                logger.info("GitHub token valid for: %s", user)
                return True
            logger.warning("GitHub token invalid: %s", r.status_code)
            return False
        except Exception as e:
            logger.warning("GitHub verify: %s", e)
            return False

    def push_file(self, local_path: Path, remote_path: str, message: str = "") -> bool:
        if not self.verify_token():
            return False
        if not local_path.exists():
            logger.warning("File not found: %s", local_path)
            return False

        content = local_path.read_bytes()
        import base64
        encoded = base64.b64encode(content).decode()

        # Check if file exists to get SHA
        sha = None
        url = f"{self.api_base}/contents/{remote_path}"
        try:
            r = requests.get(url, headers=self._headers, timeout=10)
            if r.ok:
                sha = r.json().get("sha")
        except Exception:
            pass

        data = {
            "message": message or f"Auto-sync: {local_path.name} ({datetime.now().isoformat()})",
            "content": encoded,
            "branch": self.branch,
        }
        if sha:
            data["sha"] = sha

        try:
            r = requests.put(url, headers=self._headers, json=data, timeout=15)
            if r.ok:
                logger.info("Pushed %s -> %s", local_path.name, remote_path)
                return True
            logger.warning("Push failed %s: %s", local_path.name, r.status_code)
            return False
        except Exception as e:
            logger.warning("Push error %s: %s", local_path.name, e)
            return False

    def export_db_to_json(self) -> List[Dict[str, Any]]:
        """Export SQLite scraper data to JSON for GitHub-friendly format."""
        if not DB_PATH.exists():
            return []
        try:
            with sqlite3.connect(str(DB_PATH)) as conn:
                conn.row_factory = sqlite3.Row
                data = []
                for table in ["scraped_pages", "search_results", "extracted_data", "metrics_log"]:
                    try:
                        rows = conn.execute(f"SELECT * FROM {table} ORDER BY id DESC LIMIT 200").fetchall()
                        data.append({"table": table, "rows": [dict(r) for r in rows]})
                    except Exception:
                        data.append({"table": table, "rows": []})
                return data
        except Exception as e:
            logger.warning("DB export: %s", e)
            return []

    def sync_all(self) -> Dict[str, Any]:
        """Push all agent data to GitHub."""
        if not self.verify_token():
            return {"status": "error", "message": "GitHub token invalid"}

        results = []

        # 1. Push SQLite database snapshot as JSON
        db_json = self.export_db_to_json()
        json_path = DATA_DIR / "scraper_data_export.json"
        try:
            json_path.write_text(json.dumps(db_json, indent=2), encoding="utf-8")
            ok = self.push_file(json_path, "agent_data/scraper_data_export.json",
                                f"Auto-sync scraper data ({datetime.now().isoformat()})")
            results.append({"file": "scraper_data_export.json", "pushed": ok})
        except Exception as e:
            logger.warning("JSON export push failed: %s", e)
            results.append({"file": "scraper_data_export.json", "error": str(e)})

        # 2. Push agent state
        state_file = DATA_DIR / "agent_state.json"
        if state_file.exists():
            ok = self.push_file(state_file, "agent_data/agent_state.json", "Auto-sync agent state")
            results.append({"file": "agent_state.json", "pushed": ok})

        # 3. Push agent report
        report_file = BASE_DIR / "agent_report.json"
        if report_file.exists():
            ok = self.push_file(report_file, "agent_report.json", "Auto-sync agent report")
            results.append({"file": "agent_report.json", "pushed": ok})

        # 4. Push Ghost Master Log
        log_file = BASE_DIR / "agent_logs" / "Ghost_Master_Log.log"
        if log_file.exists():
            ok = self.push_file(log_file, "agent_logs/Ghost_Master_Log.log", "Auto-sync master log")
            results.append({"file": "Ghost_Master_Log.log", "pushed": ok})

        self._state["last_sync"] = datetime.now(timezone.utc).isoformat()
        self._state["sync_count"] += 1
        self._state["last_results"] = results
        self._save_state()

        all_pushed = all(r.get("pushed") for r in results)
        return {
            "status": "success" if all_pushed else "partial",
            "sync_count": self._state["sync_count"],
            "timestamp": self._state["last_sync"],
            "files": results,
        }

    def git_commit_push(self) -> Dict[str, Any]:
        """Alternative: use git CLI to commit and push."""
        try:
            result = subprocess.run(
                ["git", "add", "-A"],
                cwd=str(BASE_DIR), capture_output=True, text=True, timeout=30
            )
            result = subprocess.run(
                ["git", "commit", "-m", f"Auto-sync: {datetime.now().isoformat()}"],
                cwd=str(BASE_DIR), capture_output=True, text=True, timeout=30
            )
            result = subprocess.run(
                ["git", "push"],
                cwd=str(BASE_DIR), capture_output=True, text=True, timeout=60
            )
            if result.returncode == 0:
                logger.info("Git commit+push successful")
                return {"status": "success", "output": result.stdout[:500]}
            logger.warning("Git push: %s", result.stderr[:200])
            return {"status": "warning", "output": result.stderr[:500]}
        except Exception as e:
            logger.warning("Git CLI sync: %s", e)
            return {"status": "error", "message": str(e)}
