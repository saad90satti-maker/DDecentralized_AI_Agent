"""
Unified structured logging with [INFO], [ERROR], [SUCCESS] prefixes,
console + file dual output, secret sanitization, and correlation IDs.
"""

import json
import logging
import os
import re
import sys
import uuid
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Optional


# ---------------------------------------------------------------------------
# Secret patterns for log sanitization
# ---------------------------------------------------------------------------

_SECRET_PATTERNS = [
    (re.compile(r'ghp_\w+', re.IGNORECASE), 'ghp_***REDACTED***'),
    (re.compile(r'gsk_\w+', re.IGNORECASE), 'gsk_***REDACTED***'),
    (re.compile(r'hf_\w+', re.IGNORECASE), 'hf_***REDACTED***'),
    (re.compile(r'cfut_\w+', re.IGNORECASE), 'cfut_***REDACTED***'),
    (re.compile(r'MTU\w+\.\w+\.\w+'), 'MTU***REDACTED***'),
    (re.compile(r'password["\']?\s*[:=]\s*["\']?([^"\':\s]+)', re.IGNORECASE),
     'password=***REDACTED***'),
    (re.compile(r'token["\']?\s*[:=]\s*["\']?([^"\':\s]+)', re.IGNORECASE),
     'token=***REDACTED***'),
    (re.compile(r'api[_-]?key["\']?\s*[:=]\s*["\']?([^"\':\s]+)', re.IGNORECASE),
     'api_key=***REDACTED***'),
    (re.compile(r'secret["\']?\s*[:=]\s*["\']?([^"\':\s]+)', re.IGNORECASE),
     'secret=***REDACTED***'),
]

_SANITIZE_ENABLED = True


def set_sanitize_enabled(enabled: bool) -> None:
    global _SANITIZE_ENABLED
    _SANITIZE_ENABLED = enabled


def sanitize(text: str) -> str:
    """Redact secrets from log output."""
    if not _SANITIZE_ENABLED or not text:
        return text
    result = text
    for pattern, replacement in _SECRET_PATTERNS:
        result = pattern.sub(replacement, result)
    return result


# ---------------------------------------------------------------------------
# Custom log levels
# ---------------------------------------------------------------------------

SUCCESS_LEVEL = 25
logging.addLevelName(SUCCESS_LEVEL, "SUCCESS")


# ---------------------------------------------------------------------------
# Structured formatter
# ---------------------------------------------------------------------------

class GhostFormatter(logging.Formatter):
    """Formats log records with timestamp, level, module, and correlation ID."""

    LEVEL_ICONS = {
        "DEBUG": "[D]",
        "INFO": "[I]",
        "SUCCESS": "[+]",
        "WARNING": "[!]",
        "ERROR": "[X]",
        "CRITICAL": "[X]",
    }

    def __init__(self, include_correlation_id: bool = True):
        super().__init__()
        self.include_correlation_id = include_correlation_id

    def format(self, record: logging.LogRecord) -> str:
        ts = datetime.now(timezone.utc).strftime("%H:%M:%S.%f")[:-3]
        icon = self.LEVEL_ICONS.get(record.levelname, "[?]")
        level = record.levelname.ljust(7)
        module = record.name.split(".")[-1][:20].ljust(20)
        msg = sanitize(str(record.getMessage()))

        parts = [f"{ts} {icon} {level} | {module} | {msg}"]

        if self.include_correlation_id:
            corr_id = getattr(record, "correlation_id", None)
            if corr_id:
                parts[0] += f" [{corr_id}]"

        if record.exc_info and record.exc_info[0] is not None:
            exc_text = self.formatException(record.exc_info)
            parts.append(f"\n{sanitize(exc_text)}")

        return "".join(parts)


class _ContextFilter(logging.Filter):
    """Injects correlation_id into every log record."""

    def __init__(self):
        super().__init__()
        self.correlation_id: Optional[str] = None

    def filter(self, record: logging.LogRecord) -> bool:
        if self.correlation_id:
            record.correlation_id = self.correlation_id
        else:
            record.correlation_id = ""
        return True


# ---------------------------------------------------------------------------
# Logger registry
# ---------------------------------------------------------------------------

_initialized = False
_context_filter = _ContextFilter()
_log_dir: Optional[Path] = None


def _setup_logging(
    level: str = "INFO",
    log_dir: Optional[str] = None,
    console_output: bool = True,
    file_output: bool = True,
    sanitize_secrets: bool = True,
) -> None:
    global _initialized, _log_dir
    if _initialized:
        return

    set_sanitize_enabled(sanitize_secrets)
    root = logging.getLogger("ghost_media_engine")
    root.setLevel(getattr(logging, level.upper(), logging.INFO))
    root.addFilter(_context_filter)
    root.propagate = False

    formatter = GhostFormatter()

    if console_output:
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setFormatter(formatter)
        root.addHandler(console_handler)

    if file_output:
        _log_dir = Path(log_dir or os.getenv("LOG_DIR", str(Path.cwd() / "agent_logs")))
        _log_dir.mkdir(parents=True, exist_ok=True)
        log_file = _log_dir / f"ghost_{datetime.now().strftime('%Y%m%d')}.log"
        file_handler = logging.FileHandler(log_file, encoding="utf-8")
        file_handler.setFormatter(formatter)
        root.addHandler(file_handler)

    _initialized = True


def get_logger(name: str, correlation_id: Optional[str] = None) -> "GhostLogger":
    """
    Get a named logger with optional correlation ID for request tracing.

    Usage:
        logger = get_logger("BrowserController", correlation_id="abc-123")
        logger.info("Browser started")
        logger.success("Login completed")
        logger.error("Navigation failed")
    """
    if not _initialized:
        _setup_logging()

    base = logging.getLogger(f"ghost_media_engine.{name}")
    return GhostLogger(base, correlation_id)


def set_correlation_id(correlation_id: Optional[str] = None) -> str:
    """Set global correlation ID for all loggers. Returns the ID."""
    cid = correlation_id or str(uuid.uuid4())[:8]
    _context_filter.correlation_id = cid
    return cid


def clear_correlation_id() -> None:
    """Clear the global correlation ID."""
    _context_filter.correlation_id = None


# ---------------------------------------------------------------------------
# GhostLogger wrapper
# ---------------------------------------------------------------------------

class GhostLogger:
    """Logger wrapper with SUCCESS level and correlation ID support."""

    def __init__(self, base_logger: logging.Logger, correlation_id: Optional[str] = None):
        self._logger = base_logger
        self._correlation_id = correlation_id

    def _log(self, level: int, msg: str, *args, **kwargs):
        extra = kwargs.pop("extra", {})
        if self._correlation_id:
            extra["correlation_id"] = self._correlation_id
        self._logger.log(level, msg, *args, extra=extra, **kwargs)

    def debug(self, msg: str, *args, **kwargs):
        self._log(logging.DEBUG, msg, *args, **kwargs)

    def info(self, msg: str, *args, **kwargs):
        self._log(logging.INFO, msg, *args, **kwargs)

    def success(self, msg: str, *args, **kwargs):
        self._log(SUCCESS_LEVEL, msg, *args, **kwargs)

    def warning(self, msg: str, *args, **kwargs):
        self._log(logging.WARNING, msg, *args, **kwargs)

    def error(self, msg: str, *args, **kwargs):
        self._log(logging.ERROR, msg, *args, **kwargs)

    def critical(self, msg: str, *args, **kwargs):
        self._log(logging.CRITICAL, msg, *args, **kwargs)

    def exception(self, msg: str, *args, **kwargs):
        self._log(logging.ERROR, msg, *args, exc_info=True, **kwargs)

    def with_correlation(self, correlation_id: str) -> "GhostLogger":
        """Return a new logger bound to a specific correlation ID."""
        return GhostLogger(self._logger, correlation_id)


# ---------------------------------------------------------------------------
# Convenience initialization
# ---------------------------------------------------------------------------

def init_logging(
    level: str = "INFO",
    log_dir: Optional[str] = None,
    console_output: bool = True,
    file_output: bool = True,
    sanitize_secrets: bool = True,
) -> None:
    """Initialize the logging system. Call once at app startup."""
    _setup_logging(level, log_dir, console_output, file_output, sanitize_secrets)
