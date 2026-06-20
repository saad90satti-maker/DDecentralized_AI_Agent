"""
Security utilities for Ghost Engine

- Input validation
- Log sanitization
- Command parsing
- Rate limiting helpers
- File permission management
"""

import os
import re
import hashlib
import hmac
from pathlib import Path
from typing import List
from enum import Enum

# ============= CONSTANTS =============
SENSITIVE_PATTERNS = [
    r'password["\']?\s*[:=]\s*["\']?([^"\':\s]+)["\']?',
    r'token["\']?\s*[:=]\s*["\']?([^"\':\s]+)["\']?',
    r'api[_-]?key["\']?\s*[:=]\s*["\']?([^"\':\s]+)["\']?',
    r'secret["\']?\s*[:=]\s*["\']?([^"\':\s]+)["\']?',
    r'pass(?:word)?["\']?\s*[:=]\s*["\']?([^"\':\s]+)["\']?',
]

MAX_COMMAND_LENGTH = 10000
MAX_PAYLOAD_SIZE = 1_000_000  # 1MB


class CLIAction(str, Enum):
    """Validated CLI actions."""
    STATUS = "status"
    EXECUTE = "execute"
    THINK = "think"
    DEPLOY = "deploy"
    SCALE = "scale"
    AUTO = "auto"


def sanitize_for_logging(text: str) -> str:
    """Remove sensitive data before logging."""
    if not text:
        return text
    
    result = str(text)
    for pattern in SENSITIVE_PATTERNS:
        result = re.sub(pattern, lambda m: m.group(0)[:len(m.group(0))//2] + '***REDACTED***', 
                       result, flags=re.IGNORECASE)
    
    # Also redact common token formats
    result = re.sub(r'ghp_\w+', 'ghp_***REDACTED***', result)
    result = re.sub(r'gsk_\w+', 'gsk_***REDACTED***', result)
    result = re.sub(r'hf_\w+', 'hf_***REDACTED***', result)
    result = re.sub(r'cfut_\w+', 'cfut_***REDACTED***', result)
    result = re.sub(r'MTU\w+\.\w+\.\w+', 'MTU***REDACTED***', result)
    
    return result


def validate_command(command: str) -> tuple[bool, str]:
    """Validate command for injection attacks and size."""
    if not command:
        return False, "Command cannot be empty"
    
    if len(command) > MAX_COMMAND_LENGTH:
        return False, f"Command exceeds max length ({MAX_COMMAND_LENGTH})"
    
    # Reject obvious injection attempts
    dangerous_patterns = [
        r';\s*rm\s+',
        r'>\s*/dev/',
        r'&&\s*rm\s+',
        r'\|\s*rm\s+',
        r'`rm\s+',
        r'\$\(rm\s+',
    ]
    
    for pattern in dangerous_patterns:
        if re.search(pattern, command, re.IGNORECASE):
            return False, "Command contains dangerous patterns"
    
    return True, "OK"


def validate_action(action: str) -> tuple[bool, CLIAction | None]:
    """Validate CLI action."""
    try:
        return True, CLIAction(action.lower())
    except ValueError:
        return False, None


def validate_api_key(provided_key: str | None) -> bool:
    """Validate API key against environment."""
    if not provided_key:
        return False
    
    expected_key = os.getenv("GHOST_API_KEY")
    if not expected_key:
        # If no key is set in environment, require it to be set
        return False
    
    # Use constant-time comparison to prevent timing attacks
    return hmac.compare_digest(provided_key, expected_key)


def secure_file(path: Path, mode: int = 0o600) -> bool:
    """Set secure permissions (owner read/write only)."""
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.touch(exist_ok=True)
        os.chmod(path, mode)
        return True
    except Exception as e:
        print(f"Warning: Could not set permissions on {path}: {e}")
        return False


def parse_command_safely(command: str) -> List[str]:
    """Parse command into list format without shell."""
    import shlex
    try:
        return shlex.split(command)
    except ValueError:
        # Invalid shell syntax
        return []


def generate_request_signature(data: str, secret: str) -> str:
    """Generate HMAC signature for request verification."""
    return hmac.new(
        secret.encode(),
        data.encode(),
        hashlib.sha256
    ).hexdigest()


def verify_request_signature(data: str, signature: str, secret: str) -> bool:
    """Verify HMAC signature for request."""
    expected = generate_request_signature(data, secret)
    return hmac.compare_digest(signature, expected)


def check_payload_size(content_length: int | None) -> tuple[bool, str]:
    """Check if payload size is acceptable."""
    if content_length is None:
        return True, "OK"
    
    if content_length > MAX_PAYLOAD_SIZE:
        return False, f"Payload exceeds maximum size ({MAX_PAYLOAD_SIZE})"
    
    return True, "OK"


def get_safe_env(key: str, default: str = None) -> str | None:
    """Get environment variable safely without exposing defaults in code."""
    value = os.getenv(key)
    if not value and default:
        return default
    return value


class CredentialManager:
    """Centralized credential management."""
    
    @staticmethod
    def get_gmail():
        """Get Gmail credentials from environment only."""
        return {
            "user": os.getenv("GMAIL_USER"),
            "pass": os.getenv("GMAIL_PASS")
        }
    
    @staticmethod
    def get_tokens():
        """Get all API tokens from environment only."""
        return {
            "HuggingFace": os.getenv("HUGGINGFACE_TOKEN"),
            "Groq": os.getenv("GROQ_API_KEY"),
            "GitHub": os.getenv("GITHUB_TOKEN"),
            "Cloudflare": os.getenv("CLOUDFLARE_TOKEN"),
            "Discord": os.getenv("DISCORD_TOKEN"),
            "DiscordChannel": os.getenv("DISCORD_CHANNEL_ID"),
        }
    
    @staticmethod
    def validate_configured():
        """Check which services are properly configured."""
        gmail = CredentialManager.get_gmail()
        tokens = CredentialManager.get_tokens()
        
        return {
            "Gmail": "Configured" if gmail.get("user") and gmail.get("pass") else "Missing",
            "HuggingFace": "Configured" if tokens.get("HuggingFace") else "Missing",
            "Groq": "Configured" if tokens.get("Groq") else "Missing",
            "GitHub": "Configured" if tokens.get("GitHub") else "Missing",
            "Cloudflare": "Configured" if tokens.get("Cloudflare") else "Missing",
            "Discord": "Configured" if tokens.get("Discord") else "Missing",
        }


# ============= MIDDLEWARE HELPERS =============

def add_security_headers(app):
    """Add security headers to FastAPI app."""
    from starlette.middleware.base import BaseHTTPMiddleware
    
    class SecurityHeaderMiddleware(BaseHTTPMiddleware):
        async def dispatch(self, request, call_next):
            response = await call_next(request)
            response.headers["X-Content-Type-Options"] = "nosniff"
            response.headers["X-Frame-Options"] = "DENY"
            response.headers["X-XSS-Protection"] = "1; mode=block"
            response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
            return response
    
    app.add_middleware(SecurityHeaderMiddleware)


def add_request_size_limit(app, max_size: int = MAX_PAYLOAD_SIZE):
    """Add request size limiting middleware."""
    from fastapi import Request
    from fastapi.responses import JSONResponse
    
    @app.middleware("http")
    async def limit_upload_size(request: Request, call_next):
        if "content-length" in request.headers:
            content_length = int(request.headers["content-length"])
            if content_length > max_size:
                return JSONResponse(
                    {"error": f"Payload exceeds maximum size ({max_size})"},
                    status_code=413
                )
        return await call_next(request)


if __name__ == "__main__":
    print("Security Utilities Module")
    print("=" * 50)
    
    # Test sanitization
    test_strings = [
        "api_key: ghp_1234567890abcdef",
        "password=MySecurePass123",
        "token: gsk_abcd1234",
    ]
    
    print("\nLog Sanitization Tests:")
    for test in test_strings:
        print(f"  Original:  {test}")
        print(f"  Sanitized: {sanitize_for_logging(test)}")
    
    # Test command validation
    print("\nCommand Validation Tests:")
    safe_cmd = "ls -la /home/user"
    dangerous_cmd = "echo hello; rm -rf /"
    
    valid, msg = validate_command(safe_cmd)
    print(f"  Safe: {valid} - {msg}")
    
    valid, msg = validate_command(dangerous_cmd)
    print(f"  Dangerous: {valid} - {msg}")
    
    # Test CLI action validation
    print("\nCLI Action Validation:")
    valid, action = validate_action("status")
    print(f"  'status': {valid} - {action}")
    
    valid, action = validate_action("invalid_action")
    print(f"  'invalid_action': {valid} - {action}")
