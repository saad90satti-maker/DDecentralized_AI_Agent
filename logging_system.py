"""
Unified Logging System — Enterprise-grade dual-output logging.
Writes to both console (stdout) and a rotating file with levels.
Secrets are automatically redacted from all log output.
"""

import logging
import logging.handlers
import sys
import re
from pathlib import Path
from typing import Optional


_LOG_INITIALIZED = False

# Common secret patterns to redact from all log output
_SECRET_PATTERNS = [
    (re.compile(r'(ghp_|gho_|ghu_|ghs_|ghr_)[0-9a-zA-Z]{36}'), r'\1***REDACTED***'),
    (re.compile(r'gsk_[0-9a-zA-Z]{32}'), 'gsk_***REDACTED***'),
    (re.compile(r'hf_[0-9a-zA-Z]{32,}'), 'hf_***REDACTED***'),
    (re.compile(r'cfut_[0-9a-zA-Z]{32,}'), 'cfut_***REDACTED***'),
    (re.compile(r'(sk-[0-9a-zA-Z]{20,}|sk-[0-9a-zA-Z]{40,})'), 'sk-***REDACTED***'),
    (re.compile(r'MT[0-9a-zA-Z_\-]+\.[0-9a-zA-Z_\-]+\.[0-9a-zA-Z_\-]+'), 'MT***REDACTED***'),
    (re.compile(r'AKIA[0-9A-Z]{16}'), 'AKIA***REDACTED***'),
    (re.compile(r'(?:^|[^a-zA-Z0-9])(AQ\.[0-9a-zA-Z_\-]{30,})(?:$|[^a-zA-Z0-9])'), ' AQ.***REDACTED*** '),
    (re.compile(r'(?i)(token|secret|password|api_key)\s*[:=]\s*["\'][^"\']+["\']'), lambda m: m.group(0)[:m.group(0).rfind('"')-8] + '"***REDACTED***"' if '"' in m.group(0) else m.group(0)[:20] + '***REDACTED***'),
    (re.compile(r'-----BEGIN (RSA|EC|OPENSSH|PGP|PRIVATE) PRIVATE KEY-----'), '-----BEGIN PRIVATE KEY-----***REDACTED***'),
]


class SanitizingFormatter(logging.Formatter):
    """Formatter that redacts secrets from all log messages."""

    def format(self, record):
        msg = super().format(record)
        for pattern, replacement in _SECRET_PATTERNS:
            msg = pattern.sub(replacement, msg)
        return msg


def get_config() -> dict:
    try:
        import json
        path = Path(__file__).resolve().parent / "config.json"
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8")).get("logging", {})
    except Exception:
        pass
    return {}


def setup_logging(level: Optional[str] = None,
                  log_file: Optional[str] = None,
                  max_bytes: int = 10_485_760,
                  backup_count: int = 5) -> logging.Logger:
    global _LOG_INITIALIZED

    cfg = get_config()
    log_level = (level or cfg.get("level", "INFO")).upper()
    log_path = Path(__file__).resolve().parent / (log_file or cfg.get("file", "system_log.txt"))

    root = logging.getLogger()
    if _LOG_INITIALIZED and root.handlers:
        return logging.getLogger("Agent")

    root.setLevel(getattr(logging, log_level, logging.INFO))

    fmt = SanitizingFormatter(
        "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    console = logging.StreamHandler(sys.stdout)
    console.setLevel(logging.DEBUG)
    console.setFormatter(fmt)
    root.addHandler(console)

    try:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        file_handler = logging.handlers.RotatingFileHandler(
            str(log_path),
            maxBytes=max_bytes or cfg.get("max_bytes", 10_485_760),
            backupCount=backup_count or cfg.get("backup_count", 5),
            encoding="utf-8",
        )
        file_handler.setLevel(logging.DEBUG)
        file_handler.setFormatter(fmt)
        root.addHandler(file_handler)
    except Exception:
        root.warning("Could not create log file handler — console only")

    _LOG_INITIALIZED = True
    return logging.getLogger("Agent")


def get_logger(name: str) -> logging.Logger:
    if not _LOG_INITIALIZED:
        setup_logging()
    return logging.getLogger(name)
