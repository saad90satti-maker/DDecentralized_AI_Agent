import asyncio
import json
import logging
import os
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

import aiohttp

logger = logging.getLogger("DashboardInstrumentation")


class MetricsStore:
    def __init__(self, sqlite_path: Optional[str] = None, json_path: Optional[str] = None):
        self.sqlite_path = Path(sqlite_path or Path("agent_metrics.db"))
        self.json_path = Path(json_path or Path("dashboard_metrics.json"))
        self.webhook_url = os.getenv("PUBLIC_WEBHOOK_URL")
        self._ensure_database()
        self.state: Dict[str, Any] = {"last_updated": None, "events": [], "counters": {}}

    def _ensure_database(self) -> None:
        self.sqlite_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.sqlite_path)
        try:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS metrics (timestamp TEXT, category TEXT, name TEXT, payload TEXT)"
            )
            conn.commit()
        finally:
            conn.close()

    def record_task_event(self, status: str, task: Any, latency: float = 0.0) -> None:
        payload = {
            "task_id": task.id,
            "type": task.type,
            "status": status,
            "attempts": task.attempts,
            "duration": round(latency, 3),
        }
        self._record("task", status, payload)

    def record_email_event(self, action: str, data: Dict[str, Any]) -> None:
        self._record("email", action, data)

    def record_browser_event(self, step: str, url: str, duration: float) -> None:
        self._record("browser", step, {"url": url, "duration": round(duration, 3)})

    def record_system_event(self, event_name: str, data: Dict[str, Any]) -> None:
        self._record("system", event_name, data)

    def _record(self, category: str, name: str, payload: Dict[str, Any]) -> None:
        timestamp = datetime.utcnow().isoformat() + "Z"
        event = {"timestamp": timestamp, "category": category, "name": name, "payload": payload}
        self.state["last_updated"] = timestamp
        self.state["events"].append(event)
        self.state["counters"][name] = self.state["counters"].get(name, 0) + 1
        self._persist_json()
        self._persist_sql(category, name, payload)

    def _persist_json(self) -> None:
        try:
            self.json_path.write_text(json.dumps(self.state, indent=2), encoding="utf-8")
        except Exception as exc:
            logger.warning("Failed to write metrics JSON: %s", exc)

    def _persist_sql(self, category: str, name: str, payload: Dict[str, Any]) -> None:
        try:
            conn = sqlite3.connect(self.sqlite_path)
            conn.execute(
                "INSERT INTO metrics (timestamp, category, name, payload) VALUES (?, ?, ?, ?)",
                (datetime.utcnow().isoformat(), category, name, json.dumps(payload, ensure_ascii=False)),
            )
            conn.commit()
        except Exception as exc:
            logger.warning("Failed to persist metrics to SQLite: %s", exc)
        finally:
            conn.close()

    async def publish_state(self, payload: Dict[str, Any]) -> None:
        self._record(payload.get("type", "state"), "state_publish", payload)

    async def publish_webhook(self, payload: Dict[str, Any]) -> None:
        if not self.webhook_url:
            return
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(self.webhook_url, json=payload, timeout=10) as response:
                    if response.status >= 400:
                        logger.warning("Webhook publish failed %s: %s", response.status, await response.text())
        except Exception as exc:
            logger.warning("Webhook publish error: %s", exc)

    def get_current_state(self) -> Dict[str, Any]:
        return self.state


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    store = MetricsStore()
    store.record_system_event("test_event", {"value": 42})
    print(store.get_current_state())
