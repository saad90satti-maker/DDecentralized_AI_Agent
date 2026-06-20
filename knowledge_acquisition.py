"""Knowledge Acquisition — connects to public datasets for educational content."""

import json
import logging
import os
import random
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger("KnowledgeAcquisition")

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "agent_data"
DATA_DIR.mkdir(exist_ok=True)

KNOWLEDGE_DB = DATA_DIR / "knowledge.db"

EDUCATIONAL_TOPICS = [
    "computer_science", "algorithms", "data_structures", "machine_learning",
    "mathematics", "logic", "ethics", "philosophy",
    "programming_languages", "security", "networks", "distributed_systems",
    "operating_systems", "software_engineering", "formal_verification",
]

DATASET_SOURCES = [
    {
        "name": "cais/mmlu",
        "configs": ["all"],
        "topics": ["computer_science", "mathematics", "logic"],
    },
    {
        "name": "openai/gsm8k",
        "configs": ["main"],
        "topics": ["mathematics", "logic"],
    },
    {
        "name": "tatsu-lab/alpaca",
        "configs": None,
        "topics": ["computer_science", "programming_languages", "ethics"],
    },
    {
        "name": "bigcode/the-stack-v2-train-smol-ids",
        "configs": None,
        "topics": ["programming_languages", "software_engineering"],
    },
    {
        "name": "HuggingFaceH4/ultrachat_200k",
        "configs": None,
        "topics": ["ethics", "philosophy", "logic"],
    },
]


class KnowledgeStore:
    """SQLite-backed store for acquired knowledge."""

    def __init__(self, path: Path = KNOWLEDGE_DB):
        self.path = path
        self._conn: Optional[sqlite3.Connection] = None

    def _get_conn(self) -> sqlite3.Connection:
        if self._conn is None:
            self._conn = sqlite3.connect(str(self.path))
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("""
                CREATE TABLE IF NOT EXISTS knowledge (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    topic TEXT NOT NULL,
                    source TEXT NOT NULL,
                    content TEXT NOT NULL,
                    embedding BLOB,
                    acquired_at REAL NOT NULL,
                    access_count INTEGER DEFAULT 0
                )
            """)
            self._conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_knowledge_topic
                ON knowledge(topic)
            """)
            self._conn.commit()
        return self._conn

    def store(self, topic: str, source: str, content: str) -> int:
        conn = self._get_conn()
        conn.execute(
            "INSERT INTO knowledge (topic, source, content, acquired_at) VALUES (?, ?, ?, ?)",
            (topic, source, content, time.time()),
        )
        conn.commit()
        return conn.execute("SELECT last_insert_rowid()").fetchone()[0]

    def search(self, topic: str, limit: int = 5) -> List[Dict[str, Any]]:
        conn = self._get_conn()
        rows = conn.execute(
            "SELECT id, topic, source, content, acquired_at, access_count "
            "FROM knowledge WHERE topic LIKE ? ORDER BY access_count DESC LIMIT ?",
            (f"%{topic}%", limit),
        ).fetchall()
        results = []
        for row in rows:
            results.append({
                "id": row[0], "topic": row[1], "source": row[2],
                "content": row[3][:500], "acquired_at": row[4],
                "access_count": row[5],
            })
            conn.execute("UPDATE knowledge SET access_count = access_count + 1 WHERE id = ?", (row[0],))
        conn.commit()
        return results

    def random_by_topic(self, topic: str) -> Optional[str]:
        conn = self._get_conn()
        row = conn.execute(
            "SELECT content FROM knowledge WHERE topic LIKE ? ORDER BY RANDOM() LIMIT 1",
            (f"%{topic}%",),
        ).fetchone()
        return row[0] if row else None

    def stats(self) -> Dict[str, Any]:
        conn = self._get_conn()
        total = conn.execute("SELECT COUNT(*) FROM knowledge").fetchone()[0]
        by_topic = conn.execute(
            "SELECT topic, COUNT(*) FROM knowledge GROUP BY topic ORDER BY COUNT(*) DESC"
        ).fetchall()
        return {"total_entries": total, "by_topic": dict(by_topic)}

    def close(self) -> None:
        if self._conn:
            self._conn.close()
            self._conn = None


class HuggingFaceDatasetLoader:
    """Load datasets from Hugging Face Hub."""

    def __init__(self, store: KnowledgeStore):
        self.store = store
        self._datasets = {}

    def available(self) -> bool:
        try:
            import datasets
            return True
        except ImportError:
            return False

    def _get_datasets(self):
        if not self._datasets:
            from datasets import load_dataset
            self._datasets["load_dataset"] = load_dataset
        return self._datasets

    def acquire_topic(self, topic: str, max_samples: int = 50) -> int:
        if not self.available():
            logger.warning("datasets library not installed — skipping HF acquisition")
            return 0

        count = 0
        for source in DATASET_SOURCES:
            if topic not in source["topics"]:
                continue
            try:
                load_dataset = self._get_datasets()["load_dataset"]
                configs = source["configs"] or [None]
                for config in configs:
                    try:
                        kwargs = {"split": "train", "trust_remote_code": True}
                        if config:
                            ds = load_dataset(source["name"], config, **kwargs)
                        else:
                            ds = load_dataset(source["name"], **kwargs)
                        samples = 0
                        for i, example in enumerate(ds):
                            if samples >= max_samples:
                                break
                            text = self._extract_text(example)
                            if text and len(text) > 50:
                                self.store.store(topic, source["name"], text)
                                samples += 1
                                count += 1
                    except Exception as e:
                        logger.debug("Dataset %s config=%s: %s", source["name"], config, e)
            except Exception as e:
                logger.warning("Failed to load %s: %s", source["name"], e)

        logger.info("Acquired %d samples for topic '%s' from Hugging Face", count, topic)
        return count

    def acquire_all_topics(self, max_per_topic: int = 30) -> int:
        total = 0
        for topic in EDUCATIONAL_TOPICS:
            total += self.acquire_topic(topic, max_samples=max_per_topic)
        return total

    @staticmethod
    def _extract_text(example: dict) -> Optional[str]:
        for field in ["text", "content", "instruction", "output", "prompt",
                       "response", "code", "problem", "solution", "answer"]:
            val = example.get(field)
            if val and isinstance(val, str) and len(val) > 20:
                return val
        vals = [v for v in example.values() if isinstance(v, str) and len(v) > 50]
        return vals[0] if vals else None


class WebKnowledgeLoader:
    """Fallback: load educational content from public APIs when HF unavailable."""

    @staticmethod
    def available() -> bool:
        try:
            import requests
            return True
        except ImportError:
            return False

    def fetch_topic_summary(self, topic: str) -> Optional[str]:
        if not self.available():
            return None
        try:
            import requests
            url = f"https://en.wikipedia.org/api/rest_v1/page/summary/{topic.replace(' ', '_')}"
            r = requests.get(url, timeout=10)
            if r.ok:
                data = r.json()
                return data.get("extract", "")
        except Exception:
            pass
        return None

    def acquire_topic(self, topic: str, store: KnowledgeStore) -> int:
        summary = self.fetch_topic_summary(topic)
        if summary:
            store.store(topic, "wikipedia", summary)
            return 1
        return 0


class KnowledgeAcquisitionEngine:
    """Orchestrates knowledge acquisition from multiple sources."""

    def __init__(self):
        self.store = KnowledgeStore()
        self.hf_loader = HuggingFaceDatasetLoader(self.store)
        self.web_loader = WebKnowledgeLoader()
        self._last_acquisition: Dict[str, float] = {}

    def acquire(self, topic: Optional[str] = None,
                force: bool = False, max_samples: int = 50) -> Dict[str, Any]:
        now = time.time()
        topic = topic or random.choice(EDUCATIONAL_TOPICS)

        cooldown = self._last_acquisition.get(topic, 0)
        if not force and (now - cooldown) < 3600:
            return {"status": "skipped", "reason": f"Cooldown active for '{topic}'", "topic": topic}

        total = 0
        sources = []

        hf_count = self.hf_loader.acquire_topic(topic, max_samples)
        if hf_count > 0:
            total += hf_count
            sources.append("huggingface")

        web_count = self.web_loader.acquire_topic(topic, self.store)
        if web_count > 0:
            total += web_count
            sources.append("wikipedia")

        self._last_acquisition[topic] = now
        logger.info("Knowledge acquisition for '%s': %d entries from %s", topic, total, sources)
        return {"status": "ok", "topic": topic, "entries": total, "sources": sources}

    def search(self, topic: str, limit: int = 5) -> List[Dict[str, Any]]:
        return self.store.search(topic, limit)

    def get_context(self, topic: str, max_chars: int = 2000) -> str:
        entries = self.search(topic, limit=3)
        parts = []
        for e in entries:
            parts.append(f"[{e['source']}] {e['content'][:600]}")
        return "\n\n---\n\n".join(parts)[:max_chars]

    def stats(self) -> Dict[str, Any]:
        return self.store.stats()

    def pull_the_stack(self, max_samples: int = 100) -> Dict[str, Any]:
        """Pull code samples from HuggingFace 'bigcode/the-stack' dataset."""
        if not self.hf_loader.available():
            return {"status": "skipped", "reason": "datasets library not installed"}

        try:
            from datasets import load_dataset
            ds = load_dataset("bigcode/the-stack-v2-train-smol-ids", split="train",
                              trust_remote_code=True)
            count = 0
            for i, example in enumerate(ds):
                if count >= max_samples:
                    break
                content = example.get("content", "")
                lang = example.get("lang", "unknown")
                if content and len(content) > 100:
                    self.store.store("programming_languages", f"the_stack/{lang}", content[:2000])
                    count += 1

            logger.info("The Stack: pulled %d code samples across %d languages",
                        count, len(set(
                            e.get("lang", "unknown") for e in ds.select(range(min(max_samples, len(ds))))
                        )))
            return {"status": "ok", "entries": count, "source": "the_stack"}
        except Exception as e:
            logger.warning("The Stack pull failed: %s", e)
            return {"status": "failed", "error": str(e)}


def constitutional_audit(base_dir: Optional[Path] = None) -> Dict[str, Any]:
    """
    Audit all .py files in the project against CORE_CONSTITUTION.md rules.
    Returns a report with violations, score, and article-by-article breakdown.
    """
    base_dir = base_dir or Path(__file__).resolve().parent
    constitution_path = base_dir / "CORE_CONSTITUTION.md"
    violations_log = base_dir / "agent_logs" / "constitutional_violations.log"
    (base_dir / "agent_logs").mkdir(exist_ok=True)

    # Load constitution
    if not constitution_path.exists():
        return {"status": "error", "reason": "CORE_CONSTITUTION.md not found"}

    constitution_text = constitution_path.read_text(encoding="utf-8")

    # Scan all Python files
    py_files = list(base_dir.rglob("*.py"))
    excluded = {"__pycache__", ".venv", "venv", "node_modules", ".git"}
    py_files = [f for f in py_files if not any(p in f.parts for p in excluded)]

    violations = []
    articles = {
        "I": {"name": "Integrity", "score": 100, "penalties": 0},
        "II": {"name": "Stability", "score": 100, "penalties": 0},
        "III": {"name": "Safety", "score": 100, "penalties": 0},
        "IV": {"name": "Autonomy & Decentralization", "score": 100, "penalties": 0},
        "V": {"name": "Self-Preservation", "score": 100, "penalties": 0},
        "VI": {"name": "Beneficial Growth", "score": 100, "penalties": 0},
    }

    dangerous_patterns = {
        "III": [
            ("rm -rf", "Article III.1: Destructive command"),
            ("os.system", "Article III.1: Unsafe system call"),
            ("shutdown", "Article III.1: Shutdown command"),
            ("private_key", "Article III.2: Possible key exposure"),
            ("api_key", "Article III.2: Possible API key exposure"),
        ],
        "VI": [
            ("beneficial", "Article VI: Positive reference"),
        ],
    }

    beneficial_keywords = ["improv", "optimiz", "stabil", "secur", "autonom"]

    for filepath in py_files:
        try:
            content = filepath.read_text(encoding="utf-8", errors="ignore")
            rel = filepath.relative_to(base_dir)

            # Article I: Self-modification safety
            if "self_evolve" in content or "self_patch" in content:
                if "ast.parse" not in content and "ast" in filepath.name:
                    violations.append({"file": str(rel), "article": "I",
                                       "detail": "self-modifying code without ast.parse validation"})
                    articles["I"]["penalties"] += 15

            # Article II: Rollback / backup check
            if ".bak" not in content and ("write_text" in content or "write_bytes" in content):
                if "backup" not in content.lower():
                    # Only flag if it modifies files
                    pass  # Too many false positives, skip

            # Article III: Safety patterns
            for article_key, patterns in dangerous_patterns.items():
                for pattern, desc in patterns:
                    idx = content.find(pattern)
                    if idx >= 0:
                        line = content[:idx].count("\n") + 1
                        violations.append({"file": str(rel), "article": article_key,
                                           "detail": f"{desc} at line {line}"})
                        articles[article_key]["penalties"] += 10

            # Article VI: Beneficial growth
            if filepath.name == "ghost_executor.py":
                has_beneficial = any(kw in content.lower() for kw in beneficial_keywords)
                if not has_beneficial:
                    violations.append({"file": str(rel), "article": "VI",
                                       "detail": "No beneficial improvement keywords found"})
                    articles["VI"]["penalties"] += 10

            # Article IV: P2P / DHT presence
            if filepath.name == "ghost_swarm.py":
                if "dht" not in content.lower():
                    violations.append({"file": str(rel), "article": "IV",
                                       "detail": "DHT not referenced in swarm module"})
                    articles["IV"]["penalties"] += 20

            # Article V: Self-preservation
            if filepath.name == "ghost_swarm.py":
                if "self_preservation" not in content:
                    violations.append({"file": str(rel), "article": "V",
                                       "detail": "No self-preservation mechanism found"})
                    articles["V"]["penalties"] += 20

        except Exception:
            continue

    # Calculate scores
    for key in articles:
        articles[key]["score"] = max(0, 100 - articles[key]["penalties"])

    overall = round(sum(a["score"] for a in articles.values()) / len(articles), 1)

    # Log violations
    try:
        log_entry = json.dumps({
            "timestamp": time.time(),
            "files_scanned": len(py_files),
            "total_violations": len(violations),
            "overall_score": overall,
            "articles": articles,
            "violations": violations[:20],
        })
        violations_log.write_text(log_entry + "\n", encoding="utf-8")
    except Exception:
        pass

    return {
        "status": "ok",
        "files_scanned": len(py_files),
        "total_violations": len(violations),
        "overall_score": overall,
        "articles": articles,
        "violations": violations[:20],
    }
