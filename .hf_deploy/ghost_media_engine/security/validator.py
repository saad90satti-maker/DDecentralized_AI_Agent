"""
Security validation: input sanitization, command validation, API key verification.
"""

import hmac
import hashlib
import re
from typing import List, Tuple

from ghost_media_engine.config import SecurityConfig
from ghost_media_engine.logging import get_logger

logger = get_logger("Security")

# Secret patterns for log sanitization
SECRET_PATTERNS = [
    re.compile(r'ghp_\w+', re.IGNORECASE),
    re.compile(r'gsk_\w+', re.IGNORECASE),
    re.compile(r'hf_\w+', re.IGNORECASE),
    re.compile(r'cfut_\w+', re.IGNORECASE),
    re.compile(r'MTU\w+\.\w+\.\w+'),
]

# Dangerous command patterns
DANGEROUS_PATTERNS = [
    r';\s*rm\s+',
    r'>\s*/dev/',
    r'&&\s*rm\s+',
    r'\|\s*rm\s+',
    r'`rm\s+',
    r'\$\(rm\s+',
    r';\s*del\s+',
    r'&&\s*del\s+',
]


class SecurityValidator:
    """
    Centralized security validation.

    Usage:
        validator = SecurityValidator(config.security)
        is_valid, msg = validator.validate_command("ls -la")
        sanitized = validator.sanitize_for_logging("api_key=ghp_abc123")
    """

    def __init__(self, config: SecurityConfig):
        self.config = config

    def validate_command(self, command: str) -> Tuple[bool, str]:
        """Validate a command for injection attacks and size limits."""
        if not command:
            return False, "Command cannot be empty"

        if len(command) > self.config.max_command_length:
            return False, f"Command exceeds max length ({self.config.max_command_length})"

        for pattern in DANGEROUS_PATTERNS:
            if re.search(pattern, command, re.IGNORECASE):
                return False, "Command contains dangerous patterns"

        return True, "OK"

    def sanitize_for_logging(self, text: str) -> str:
        """Remove secrets from text before logging."""
        if not text:
            return text

        result = text
        for pattern in SECRET_PATTERNS:
            result = pattern.sub(lambda m: m.group()[:4] + "***REDACTED***", result)

        # Redact password-like assignments
        result = re.sub(
            r'(password|token|api[_-]?key|secret)["\']?\s*[:=]\s*["\']?([^"\':\s]+)',
            lambda m: f"{m.group(1)}=***REDACTED***",
            result,
            flags=re.IGNORECASE,
        )

        return result

    def validate_api_key(self, provided_key: str | None) -> bool:
        """Validate API key using constant-time comparison."""
        if not provided_key:
            return False

        expected_key = self.config.api_key
        if not expected_key:
            return False

        return hmac.compare_digest(provided_key, expected_key)

    def generate_request_signature(self, data: str, secret: str) -> str:
        """Generate HMAC signature for request verification."""
        return hmac.new(
            secret.encode(),
            data.encode(),
            hashlib.sha256,
        ).hexdigest()

    def verify_request_signature(
        self, data: str, signature: str, secret: str,
    ) -> bool:
        """Verify HMAC signature for request."""
        expected = self.generate_request_signature(data, secret)
        return hmac.compare_digest(signature, expected)

    def check_payload_size(self, content_length: int | None) -> Tuple[bool, str]:
        """Check if payload size is acceptable."""
        if content_length is None:
            return True, "OK"

        if content_length > self.config.max_payload_size:
            return False, f"Payload exceeds maximum size ({self.config.max_payload_size})"

        return True, "OK"
