"""
Security Configuration Loader — Centralized env-var validation and access.

Loaded at startup by manager.py and main.py to validate required credentials
without exposing secret values in logs or error messages.

Usage:
    import security_config
    config = security_config.load_with_validation()
    gemini_key = config.get("GEMINI_API_KEY")  # returns str or None
    status = config.validation_report()  # returns human-readable status
"""

import os
import logging
from typing import Dict, Optional, List

logger = logging.getLogger("SecurityConfig")

REQUIRED_VARS = {
    "GEMINI_API_KEY": "Gemini LLM backend",
}

OPTIONAL_VARS = {
    "GROQ_API_KEY": "Groq LLM fallback",
    "GITHUB_TOKEN": "GitHub API access",
    "HUGGINGFACE_TOKEN": "HuggingFace model access",
    "CLOUDFLARE_TOKEN": "Cloudflare tunnel",
    "DISCORD_TOKEN": "Discord bot",
    "GMAIL_USER": "Gmail automation",
    "GMAIL_PASS": "Gmail app password",
    "SWARM_SECRET": "P2P swarm encryption",
    "OPENROUTER_KEY": "OpenRouter LLM fallback",
    "DIGITALOCEAN_TOKEN": "DigitalOcean API (replication)",
    "HF_TOKEN": "HuggingFace Spaces token",
    "TOR_PASSWORD": "Tor controller password",
}

SENSITIVE_SUFFIXES = [
    "TOKEN", "KEY", "SECRET", "PASS", "PASSWORD", "PRIVATE",
]


def _is_sensitive(var_name: str) -> bool:
    return any(var_name.endswith(s) or "_".join(var_name.split("_")[-2:]).endswith(s) for s in SENSITIVE_SUFFIXES)


def load_with_validation() -> Dict[str, Optional[str]]:
    """Load all known config vars, return dict (values never logged)."""
    config = {}
    for var in list(REQUIRED_VARS.keys()) + list(OPTIONAL_VARS.keys()):
        config[var] = os.getenv(var)
    return config


def validate_required(config: Optional[Dict[str, Optional[str]]] = None) -> List[str]:
    """Return list of missing required variables (names only, no values)."""
    if config is None:
        config = load_with_validation()
    missing = [var for var in REQUIRED_VARS if not config.get(var)]
    return missing


def validation_report(config: Optional[Dict[str, Optional[str]]] = None) -> Dict[str, str]:
    """Return status report suitable for /api/status endpoint."""
    if config is None:
        config = load_with_validation()

    report = {}
    for var, description in {**REQUIRED_VARS, **OPTIONAL_VARS}.items():
        present = bool(config.get(var))
        status = "Configured" if present else "Missing"
        report[description] = status
    return report


def get_safe_env(key: str, default: Optional[str] = None) -> Optional[str]:
    """Get env var without logging the value. Safe for logging contexts."""
    value = os.getenv(key)
    if not value:
        return default
    return value


def log_safe_startup(config: Optional[Dict[str, Optional[str]]] = None) -> None:
    """Log startup credential status without exposing values."""
    if config is None:
        config = load_with_validation()

    missing_required = validate_required(config)
    missing_optional = [
        var for var in OPTIONAL_VARS
        if not config.get(var)
    ]

    if missing_required:
        logger.warning(
            "Missing required credentials: %s. Some features will be unavailable.",
            ", ".join(missing_required),
        )

    if missing_optional:
        logger.info(
            "Optional credentials not configured: %s. Related features disabled.",
            ", ".join(missing_optional),
        )

    configured_count = sum(1 for v in config.values() if v)
    total_count = len(config)
    logger.info(
        "Credential status: %d/%d configured (%d required, %d optional)",
        configured_count, total_count,
        len(REQUIRED_VARS), len(OPTIONAL_VARS),
    )


def sanitize_value(value: str, max_prefix_len: int = 4) -> str:
    """Redact a sensitive value for safe logging. Shows first 4 chars only."""
    if not value:
        return "<empty>"
    if len(value) <= max_prefix_len + 4:
        return value[:max_prefix_len] + "***"
    return value[:max_prefix_len] + "..." + value[-4:]


if __name__ == "__main__":
    config = load_with_validation()
    print("=== Security Config Validation ===\n")

    print("Required Variables:")
    for var in REQUIRED_VARS:
        val = config.get(var)
        status = "✓ Configured" if val else "✗ MISSING"
        print(f"  {var:30s} [{status}]")

    print("\nOptional Variables:")
    for var in OPTIONAL_VARS:
        val = config.get(var)
        status = "✓ Configured" if val else "○ Not set"
        print(f"  {var:30s} [{status}]")

    print(f"\nCredentials configured: {sum(1 for v in config.values() if v)}/{len(config)}")
