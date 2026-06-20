"""Tests for security utilities."""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from security_utils import (
    sanitize_for_logging,
    validate_command,
    validate_action,
    CLIAction,
    parse_command_safely,
    check_payload_size,
    MAX_COMMAND_LENGTH,
    MAX_PAYLOAD_SIZE,
)


def test_sanitize_for_logging():
    """Test that sensitive data is redacted in logs."""
    # Test token redaction
    assert "***REDACTED***" in sanitize_for_logging("api_key: ghp_1234567890abcdef")
    assert "***REDACTED***" in sanitize_for_logging("token: gsk_abcd1234")
    assert "***REDACTED***" in sanitize_for_logging("hf_xxxxxxxxxxxx")
    assert "***REDACTED***" in sanitize_for_logging("cfut_xxxxxxxxxxxx")
    
    # Test password patterns
    result = sanitize_for_logging("password=MySecurePass123")
    assert "MySecurePass123" not in result or "***REDACTED***" in result
    
    # Test empty/None
    assert sanitize_for_logging("") == ""
    assert sanitize_for_logging(None) is None


def test_validate_command():
    """Test command validation for injection attacks."""
    # Valid commands
    valid, msg = validate_command("ls -la")
    assert valid is True
    assert msg == "OK"
    
    valid, msg = validate_command("python script.py arg1 arg2")
    assert valid is True
    
    # Empty command
    valid, msg = validate_command("")
    assert valid is False
    assert "empty" in msg.lower()
    
    # Too long command
    valid, msg = validate_command("a" * (MAX_COMMAND_LENGTH + 1))
    assert valid is False
    assert "length" in msg.lower()
    
    # Dangerous patterns
    valid, msg = validate_command("echo hello; rm -rf /")
    assert valid is False
    assert "dangerous" in msg.lower()
    
    valid, msg = validate_command("echo test > /dev/sda")
    assert valid is False
    
    valid, msg = validate_command("`rm -rf /`")
    assert valid is False


def test_validate_action():
    """Test CLI action validation."""
    # Valid actions
    valid, action = validate_action("status")
    assert valid is True
    assert action == CLIAction.STATUS
    
    valid, action = validate_action("execute")
    assert valid is True
    assert action == CLIAction.EXECUTE
    
    valid, action = validate_action("think")
    assert valid is True
    assert action == CLIAction.THINK
    
    valid, action = validate_action("deploy")
    assert valid is True
    assert action == CLIAction.DEPLOY
    
    valid, action = validate_action("scale")
    assert valid is True
    assert action == CLIAction.SCALE
    
    # Invalid action
    valid, action = validate_action("invalid")
    assert valid is False
    assert action is None


def test_parse_command_safely():
    """Test safe command parsing."""
    # Simple command
    result = parse_command_safely("ls -la /home")
    assert result == ["ls", "-la", "/home"]
    
    # Command with quotes
    result = parse_command_safely('echo "hello world"')
    assert result == ["echo", "hello world"]
    
    # Invalid syntax
    result = parse_command_safely("echo 'unclosed")
    assert result == []


def test_check_payload_size():
    """Test payload size checking."""
    # Within limit
    valid, msg = check_payload_size(1000)
    assert valid is True
    assert msg == "OK"
    
    # No limit
    valid, msg = check_payload_size(None)
    assert valid is True
    
    # Exceeds limit
    valid, msg = check_payload_size(MAX_PAYLOAD_SIZE + 1)
    assert valid is False
    assert "exceeds" in msg.lower()


if __name__ == "__main__":
    test_sanitize_for_logging()
    test_validate_command()
    test_validate_action()
    test_parse_command_safely()
    test_check_payload_size()
    print("All security tests passed!")
