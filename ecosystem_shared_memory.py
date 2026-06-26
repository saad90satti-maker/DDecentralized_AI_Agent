"""
Ecosystem Shared Memory v1.0 — Unified Knowledge Layer

Bridges ALL memory systems in the ecosystem into one unified interface:
  - DAIOS SharedMemory (in-memory agent knowledge)
  - Ghost SharedKnowledge (swarm-wide distributed knowledge)
  - Agent Metrics DB (SQLite)
  - Learning Log (JSON)
  - Scraper Data (SQLite)
  - Knowledge DB (SQLite)

Every agent reads/writes through this single interface.
Knowledge persists across sessions.
"""

import json
import os
import sqlite3
import time
import uuid
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from loguru import logger as loguru_logger
from cachetools import TTLCache
import structlog

structlog.configure(
    processors=[
        structlog.stdlib.filter_by_level,
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.JSONRenderer(),
    ],
    wrapper_class=structlog.stdlib.BoundLogger,
    context_class=dict,
    logger_factory=structlog.PrintLoggerFactory(),
    cache_logger_on_first_use=True,
)
logger = structlog.get_logger("ecosystem.memory")

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "agent_data"
SESSION_DIR = BASE_DIR / "session_data"
DATA_DIR.mkdir(exist_ok=True)
SESSION_DIR.mkdir(exist_ok=True)

ECOSYSTEM_DB = DATA_DIR / "ecosystem_memory.db"
KNOWLEDGE_FILE = DATA_DIR / "ecosystem_knowledge.json"


class EcosystemMemory:
    """Unified shared memory for the entire ecosystem."""

    def __init__(self):
        self._db_path = str(ECOSYSTEM_DB)
        self._knowledge: Dict[str, Dict[str, Any]] = {}
        self._observations: List[Dict[str, Any]] = []
        self._learning: List[Dict[str, Any]] = []
        self._max_observations = 5000
        self._max_learning = 2000
        self._search_cache = TTLCache(maxsize=256, ttl=60)
        self._get_cache = TTLCache(maxsize=512, ttl=120)
        self._load_knowledge()
        self._init_db()

    def _init_db(self) -> None:
        try:
            conn = sqlite3.connect(self._db_path)
            c = conn.cursor()
            c.execute("""
                CREATE TABLE IF NOT EXISTS knowledge (
                    key TEXT PRIMARY KEY,
                    value TEXT,
                    source TEXT,
                    agent_type TEXT,
                    confidence REAL DEFAULT 1.0,
                    tags TEXT DEFAULT '[]',
                    created_at REAL,
                    updated_at REAL
                )
            """)
            c.execute("""
                CREATE TABLE IF NOT EXISTS observations (
                    id TEXT PRIMARY KEY,
                    agent_id TEXT,
                    observation TEXT,
                    tick INTEGER,
                    created_at REAL
                )
            """)
            c.execute("""
                CREATE TABLE IF NOT EXISTS learning (
                    id TEXT PRIMARY KEY,
                    agent_id TEXT,
                    pattern TEXT,
                    confidence REAL DEFAULT 0.5,
                    verification_count INTEGER DEFAULT 0,
                    created_at REAL
                )
            """)
            c.execute("""
                CREATE TABLE IF NOT EXISTS agent_memory (
                    agent_id TEXT,
                    key TEXT,
                    value TEXT,
                    created_at REAL,
                    updated_at REAL,
                    PRIMARY KEY (agent_id, key)
                )
            """)
            c.execute("""
                CREATE TABLE IF NOT EXISTS ecosystem_metrics (
                    tick INTEGER,
                    metric_name TEXT,
                    metric_value REAL,
                    created_at REAL
                )
            """)
            c.execute("""
                CREATE INDEX IF NOT EXISTS idx_obs_agent ON observations(agent_id)
            """)
            c.execute("""
                CREATE INDEX IF NOT EXISTS idx_learn_agent ON learning(agent_id)
            """)
            conn.commit()
            conn.close()
        except Exception as e:
            loguru_logger.warning("DB init error: {}", e)

    def _load_knowledge(self) -> None:
        try:
            if KNOWLEDGE_FILE.exists():
                self._knowledge = json.loads(KNOWLEDGE_FILE.read_text())
        except Exception as e:
            loguru_logger.debug("No saved knowledge: {}", e)

    def _save_knowledge(self) -> None:
        try:
            KNOWLEDGE_FILE.write_text(json.dumps(self._knowledge, indent=2, default=str))
        except Exception as e:
            loguru_logger.warning("Failed to save knowledge: {}", e)

    # ─── Knowledge Store ──────────────────────────────────────────

    def store_knowledge(self, key: str, value: Any, source: str = "ecosystem",
                        agent_type: str = "agent", confidence: float = 1.0,
                        tags: Optional[List[str]] = None) -> None:
        now = time.time()
        entry = {
            "key": key,
            "value": value,
            "source": source,
            "agent_type": agent_type,
            "confidence": confidence,
            "tags": tags or [],
            "created_at": now,
            "updated_at": now,
        }
        self._knowledge[key] = entry
        try:
            conn = sqlite3.connect(self._db_path)
            c = conn.cursor()
            c.execute("""
                INSERT OR REPLACE INTO knowledge (key, value, source, agent_type,
                    confidence, tags, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (key, json.dumps(value, default=str), source, agent_type,
                  confidence, json.dumps(tags or []), now, now))
            conn.commit()
            conn.close()
        except Exception as e:
            loguru_logger.warning("DB store error: {}", e)
        self._save_knowledge()

    def get_knowledge(self, key: str) -> Optional[Any]:
        cache_key = f"get:{key}"
        if cache_key in self._get_cache:
            return self._get_cache[cache_key]
        entry = self._knowledge.get(key)
        if entry:
            self._get_cache[cache_key] = entry["value"]
            return entry["value"]
        try:
            conn = sqlite3.connect(self._db_path)
            c = conn.cursor()
            c.execute("SELECT value FROM knowledge WHERE key = ?", (key,))
            row = c.fetchone()
            conn.close()
            if row:
                val = json.loads(row[0])
                self._get_cache[cache_key] = val
                return val
        except Exception:
            pass
        self._get_cache[cache_key] = None
        return None

    def search_knowledge(self, query: str, min_confidence: float = 0.0,
                         top_n: int = 20) -> List[Dict[str, Any]]:
        cache_key = f"search:{query}:{min_confidence}:{top_n}"
        if cache_key in self._search_cache:
            return self._search_cache[cache_key]
        q = query.lower()
        results = []
        for key, entry in self._knowledge.items():
            if entry["confidence"] < min_confidence:
                continue
            if q in key.lower():
                results.append(entry)
            else:
                val_str = str(entry.get("value", ""))
                if q in val_str.lower():
                    results.append(entry)
                elif any(q in t.lower() for t in entry.get("tags", [])):
                    results.append(entry)
        results.sort(key=lambda x: x["confidence"], reverse=True)
        results = results[:top_n]
        self._search_cache[cache_key] = results
        return results

    def all_knowledge(self) -> Dict[str, Dict[str, Any]]:
        return dict(self._knowledge)

    def knowledge_stats(self) -> Dict[str, Any]:
        return {
            "total_entries": len(self._knowledge),
            "sources": list(set(e["source"] for e in self._knowledge.values())),
            "avg_confidence": round(
                sum(e["confidence"] for e in self._knowledge.values()) / max(len(self._knowledge), 1), 2
            ),
        }

    # ─── Observations ─────────────────────────────────────────────

    def add_observation(self, agent_id: str, observation: Dict[str, Any],
                        tick: int = 0) -> str:
        obs_id = f"obs-{agent_id}-{uuid.uuid4().hex[:8]}"
        entry = {
            "id": obs_id,
            "agent_id": agent_id,
            "observation": observation,
            "tick": tick,
            "created_at": time.time(),
        }
        self._observations.append(entry)
        if len(self._observations) > self._max_observations:
            self._observations = self._observations[-self._max_observations:]
        try:
            conn = sqlite3.connect(self._db_path)
            c = conn.cursor()
            c.execute("""
                INSERT INTO observations (id, agent_id, observation, tick, created_at)
                VALUES (?, ?, ?, ?, ?)
            """, (obs_id, agent_id, json.dumps(observation, default=str), tick, time.time()))
            conn.commit()
            conn.close()
        except Exception as e:
            loguru_logger.warning("DB observe error: {}", e)
        return obs_id

    def get_observations(self, agent_id: Optional[str] = None,
                         last_n: int = 50) -> List[Dict[str, Any]]:
        if agent_id:
            filtered = [o for o in self._observations if o["agent_id"] == agent_id]
        else:
            filtered = list(self._observations)
        return filtered[-last_n:]

    # ─── Learning ─────────────────────────────────────────────────

    def add_learning(self, agent_id: str, pattern: Dict[str, Any],
                     confidence: float = 0.5) -> str:
        learn_id = f"learn-{agent_id}-{uuid.uuid4().hex[:8]}"
        entry = {
            "id": learn_id,
            "agent_id": agent_id,
            "pattern": pattern,
            "confidence": confidence,
            "verification_count": 0,
            "created_at": time.time(),
        }
        self._learning.append(entry)
        if len(self._learning) > self._max_learning:
            self._learning = self._learning[-self._max_learning:]
        try:
            conn = sqlite3.connect(self._db_path)
            c = conn.cursor()
            c.execute("""
                INSERT INTO learning (id, agent_id, pattern, confidence, created_at)
                VALUES (?, ?, ?, ?, ?)
            """, (learn_id, agent_id, json.dumps(pattern, default=str), confidence, time.time()))
            conn.commit()
            conn.close()
        except Exception as e:
            loguru_logger.warning("DB learn error: {}", e)
        return learn_id

    def verify_learning(self, learn_id: str) -> None:
        for entry in self._learning:
            if entry["id"] == learn_id:
                entry["verification_count"] += 1
                entry["confidence"] = min(1.0, entry["confidence"] + 0.1)
                break
        try:
            conn = sqlite3.connect(self._db_path)
            c = conn.cursor()
            c.execute("""
                UPDATE learning SET verification_count = verification_count + 1,
                    confidence = MIN(1.0, confidence + 0.1)
                WHERE id = ?
            """, (learn_id,))
            conn.commit()
            conn.close()
        except Exception as e:
            loguru_logger.warning("DB verify error: {}", e)

    def get_learning(self, min_confidence: float = 0.0) -> List[Dict[str, Any]]:
        return [l for l in self._learning if l["confidence"] >= min_confidence]

    def get_high_confidence_patterns(self, threshold: float = 0.7) -> List[Dict[str, Any]]:
        return [l for l in self._learning if l["confidence"] >= threshold]

    def learning_stats(self) -> Dict[str, Any]:
        return {
            "total_patterns": len(self._learning),
            "high_confidence": len(self.get_high_confidence_patterns()),
            "avg_confidence": round(
                sum(l["confidence"] for l in self._learning) / max(len(self._learning), 1), 2
            ),
        }

    # ─── Agent-Specific Memory ────────────────────────────────────

    def set_agent_memory(self, agent_id: str, key: str, value: Any) -> None:
        now = time.time()
        try:
            conn = sqlite3.connect(self._db_path)
            c = conn.cursor()
            c.execute("""
                INSERT OR REPLACE INTO agent_memory (agent_id, key, value, created_at, updated_at)
                VALUES (?, ?, ?, COALESCE((SELECT created_at FROM agent_memory
                    WHERE agent_id = ? AND key = ?), ?), ?)
            """, (agent_id, key, json.dumps(value, default=str),
                  agent_id, key, now, now))
            conn.commit()
            conn.close()
        except Exception as e:
            loguru_logger.warning("DB agent memory error: {}", e)

    def get_agent_memory(self, agent_id: str, key: str) -> Optional[Any]:
        try:
            conn = sqlite3.connect(self._db_path)
            c = conn.cursor()
            c.execute("SELECT value FROM agent_memory WHERE agent_id = ? AND key = ?",
                      (agent_id, key))
            row = c.fetchone()
            conn.close()
            if row:
                return json.loads(row[0])
        except Exception:
            pass
        return None

    def get_all_agent_memory(self, agent_id: str) -> Dict[str, Any]:
        result = {}
        try:
            conn = sqlite3.connect(self._db_path)
            c = conn.cursor()
            c.execute("SELECT key, value FROM agent_memory WHERE agent_id = ?", (agent_id,))
            for key, val in c.fetchall():
                try:
                    result[key] = json.loads(val)
                except Exception:
                    result[key] = val
            conn.close()
        except Exception:
            pass
        return result

    def delete_agent_memory(self, agent_id: str, key: str) -> None:
        try:
            conn = sqlite3.connect(self._db_path)
            c = conn.cursor()
            c.execute("DELETE FROM agent_memory WHERE agent_id = ? AND key = ?",
                      (agent_id, key))
            conn.commit()
            conn.close()
        except Exception as e:
            loguru_logger.warning("DB delete error: {}", e)

    # ─── Cross-Memory Bridge ──────────────────────────────────────

    def bridge_from_daios(self, shared_memory) -> int:
        """Import knowledge from a DAIOS SharedMemory instance."""
        imported = 0
        try:
            for key, entry in shared_memory.all_knowledge().items():
                self.store_knowledge(key, entry.value, source="daios",
                                     agent_type="memory", confidence=entry.confidence,
                                     tags=entry.tags)
                imported += 1
        except Exception as e:
            loguru_logger.warning("DAIOS bridge error: {}", e)
        return imported

    def bridge_from_ghost(self, ghost_shared_knowledge) -> int:
        """Import knowledge from Ghost SharedKnowledge."""
        imported = 0
        try:
            for key, entry in ghost_shared_knowledge.__dict__.get("_store", {}).items():
                self.store_knowledge(key, entry, source="ghost_swarm",
                                     agent_type="swarm", confidence=1.0)
                imported += 1
        except Exception as e:
            loguru_logger.warning("Ghost bridge error: {}", e)
        return imported

    # ─── Snapshot ─────────────────────────────────────────────────

    def snapshot(self) -> Dict[str, Any]:
        return {
            "knowledge": self.knowledge_stats(),
            "observations": {
                "total": len(self._observations),
            },
            "learning": self.learning_stats(),
            "agent_memory_count": self._count_agent_memory(),
        }

    def _count_agent_memory(self) -> int:
        try:
            conn = sqlite3.connect(self._db_path)
            c = conn.cursor()
            c.execute("SELECT COUNT(*) FROM agent_memory")
            count = c.fetchone()[0]
            conn.close()
            return count
        except Exception:
            return 0

    def close(self) -> None:
        self._save_knowledge()
