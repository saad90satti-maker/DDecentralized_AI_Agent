"""
Security Engine — Constitutional audit, graceful degradation, Safe-State policy.
All safety-critical checks are centralized here per Article III of the Constitution.
"""

import json
import logging
import os
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from logging_system import get_logger

logger = get_logger("SecurityEngine")

_BASE_DIR = Path(__file__).resolve().parent
_SAFE_STATE_ACTIVE = False


def load_security_config() -> dict:
    try:
        path = _BASE_DIR / "config.json"
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8")).get("security", {})
    except Exception:
        pass
    return {"article_iii_threshold": 70, "safe_state_enabled": True}


def is_safe_state() -> bool:
    return _SAFE_STATE_ACTIVE


def _set_safe_state(active: bool) -> None:
    global _SAFE_STATE_ACTIVE
    _SAFE_STATE_ACTIVE = active
    if active:
        logger.critical("SAFE-STATE ACTIVATED — Degraded operation mode")
    else:
        logger.info("Safe-State deactivated — full operation restored")


def constitutional_audit(base_dir: Optional[Path] = None) -> Dict[str, Any]:
    """
    Audit all .py files against CORE_CONSTITUTION.md rules.
    Returns report with violations, scores, and article-by-article breakdown.
    Implements Graceful Degradation: if Article III (Safety) score < threshold,
    system enters Safe-State mode instead of crashing.
    """
    base_dir = base_dir or _BASE_DIR
    constitution_path = base_dir / "CORE_CONSTITUTION.md"
    violations_log = base_dir / "agent_logs" / "constitutional_violations.log"
    (base_dir / "agent_logs").mkdir(exist_ok=True)

    if not constitution_path.exists():
        logger.error("CORE_CONSTITUTION.md not found — audit impossible")
        return {"status": "error", "reason": "CORE_CONSTITUTION.md not found"}

    constitution_text = constitution_path.read_text(encoding="utf-8")

    py_files = list(base_dir.rglob("*.py"))
    excluded = {"__pycache__", ".venv", "venv", "node_modules", ".git"}
    py_files = [f for f in py_files if not any(p in f.parts for p in excluded)]

    violations: List[Dict[str, Any]] = []
    articles: Dict[str, Dict[str, Any]] = {
        "I": {"name": "Integrity", "score": 100, "penalties": 0},
        "II": {"name": "Stability", "score": 100, "penalties": 0},
        "III": {"name": "Safety", "score": 100, "penalties": 0},
        "IV": {"name": "Autonomy & Decentralization", "score": 100, "penalties": 0},
        "V": {"name": "Self-Preservation", "score": 100, "penalties": 0},
        "VI": {"name": "Beneficial Growth", "score": 100, "penalties": 0},
    }

    dangerous_patterns: Dict[str, List[Tuple[str, str]]] = {
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

            if "self_evolve" in content or "self_patch" in content:
                if "ast.parse" not in content:
                    violations.append({"file": str(rel), "article": "I",
                                       "detail": "self-modifying code without ast.parse validation"})
                    articles["I"]["penalties"] += 15

            for article_key, patterns in dangerous_patterns.items():
                for pattern, desc in patterns:
                    idx = content.find(pattern)
                    if idx >= 0:
                        line = content[:idx].count("\n") + 1
                        violations.append({"file": str(rel), "article": article_key,
                                           "detail": f"{desc} at line {line}"})
                        articles[article_key]["penalties"] += 10

            if filepath.name == "ghost_executor.py":
                has_beneficial = any(kw in content.lower() for kw in beneficial_keywords)
                if not has_beneficial:
                    violations.append({"file": str(rel), "article": "VI",
                                       "detail": "No beneficial improvement keywords found"})
                    articles["VI"]["penalties"] += 10

            if filepath.name == "ghost_swarm.py":
                if "dht" not in content.lower():
                    violations.append({"file": str(rel), "article": "IV",
                                       "detail": "DHT not referenced in swarm module"})
                    articles["IV"]["penalties"] += 20

                if "self_preservation" not in content:
                    violations.append({"file": str(rel), "article": "V",
                                       "detail": "No self-preservation mechanism found"})
                    articles["V"]["penalties"] += 20

        except Exception:
            continue

    for key in articles:
        articles[key]["score"] = max(0, 100 - articles[key]["penalties"])

    overall = round(sum(a["score"] for a in articles.values()) / len(articles), 1)

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

    _evaluate_graceful_degradation(articles["III"]["score"], violations)

    return {
        "status": "ok",
        "files_scanned": len(py_files),
        "total_violations": len(violations),
        "overall_score": overall,
        "articles": articles,
        "violations": violations[:20],
    }


def _evaluate_graceful_degradation(article_iii_score: int, violations: List[Dict[str, Any]]) -> None:
    """
    Graceful Degradation policy (Article III enforcement):
    If Safety score is below threshold, activate Safe-State log mode.
    The rest of the stack continues running — telemetry is preserved.
    """
    config = load_security_config()
    threshold = config.get("article_iii_threshold", 70)

    if article_iii_score >= threshold:
        if is_safe_state():
            _set_safe_state(False)
        return

    _set_safe_state(True)
    safety_violations = [v for v in violations if v["article"] == "III"]
    logger.critical(
        "GRACEFUL DEGRADATION — Article III score %d < threshold %d. "
        "Safe-State enabled. %d safety violations found.",
        article_iii_score, threshold, len(safety_violations),
    )
    for v in safety_violations:
        logger.warning("  Safety violation: %s — %s", v["file"], v["detail"])


def preflight_security_check() -> Dict[str, Any]:
    """Quick preflight that audits and applies Safe-State before any execution."""
    audit = constitutional_audit()
    return {
        "safe_state": is_safe_state(),
        "overall_score": audit.get("overall_score", 0),
        "article_iii_score": audit.get("articles", {}).get("III", {}).get("score", 100),
        "total_violations": audit.get("total_violations", 0),
        "audit_status": audit.get("status", "error"),
    }


class SafetyGate:
    """
    Constitutional gate for self-modification code.
    Evaluates proposed changes against all articles before allowing execution.
    """

    def __init__(self):
        self._last_audit: Dict[str, Any] = {}
        self._last_audit_time: float = 0

    def evaluate(self, change_description: str, change_code: str) -> Tuple[bool, List[str]]:
        """Returns (approved, reasons) for a proposed self-modification."""
        now = time.time()
        if now - self._last_audit_time > 300:
            self._last_audit = constitutional_audit()
            self._last_audit_time = now

        rejections: List[str] = []

        if is_safe_state():
            rejections.append("Blocked by Safe-State: modifications disabled during degraded mode")

        if "ast.parse" not in change_code and ("self_evolve" in change_code or "self_patch" in change_code):
            rejections.append("Article I.2 violation: self-modification without ast.parse validation")

        lower_desc = change_description.lower()
        dangerous_keywords = ["rm -rf", "os.system", "shutdown"]
        for kw in dangerous_keywords:
            if kw in lower_desc:
                rejections.append(f"Article III.1 violation: dangerous pattern '{kw}'")
                break

        articles = self._last_audit.get("articles", {})
        if articles.get("III", {}).get("score", 100) < 60:
            rejections.append("Article III score critically low — all modifications rejected")

        approved = len(rejections) == 0
        if approved:
            logger.info("SafetyGate: change approved — %s", change_description[:80])
        else:
            logger.warning("SafetyGate: change rejected — %s", "; ".join(rejections))

        return approved, rejections
