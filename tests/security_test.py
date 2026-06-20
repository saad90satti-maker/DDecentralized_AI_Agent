#!/usr/bin/env python3
"""
Ghost Engine Security Test Suite

Run this to validate security fixes and identify remaining vulnerabilities.

Usage:
  python security_test.py [--full]
"""

import os
import re
import sys
import json
import subprocess
from pathlib import Path
from typing import Dict, List, Tuple

# Colors for terminal output
RED = "\033[91m"
GREEN = "\033[92m"
YELLOW = "\033[93m"
BLUE = "\033[94m"
RESET = "\033[0m"


class SecurityTester:
    def __init__(self):
        self.issues = []
        self.warnings = []
        self.passes = []
        self.root_dir = Path(__file__).parent
    
    def test_hard_coded_credentials(self):
        """Check for hard-coded credentials in source code."""
        print(f"\n{BLUE}[TEST] Hard-coded Credentials{RESET}")
        
        patterns = [
            (r'os\.getenv\(["\']GMAIL_USER["\'],\s*["\']', "Gmail user default"),
            (r'os\.getenv\(["\']GMAIL_PASS["\'],\s*["\']', "Gmail password default"),
            (r'os\.getenv\(["\']GROQ_API_KEY["\'],\s*["\']gsk_', "Groq key default"),
            (r'os\.getenv\(["\']GITHUB_TOKEN["\'],\s*["\']ghp_', "GitHub token default"),
            (r'os\.getenv\(["\']DISCORD_TOKEN["\'],\s*["\']MT', "Discord token default"),
            (r'os\.getenv\(["\']CLOUDFLARE_TOKEN["\'],\s*["\']cfut_', "Cloudflare token default"),
            (r'os\.getenv\(["\']HUGGINGFACE_TOKEN["\'],\s*["\']hf_', "HuggingFace token default"),
        ]
        
        manager_file = self.root_dir / "manager.py"
        if not manager_file.exists():
            print(f"{YELLOW}  ⊘ manager.py not found{RESET}")
            return
        
        content = manager_file.read_text(encoding='utf-8', errors='ignore')
        
        found_issues = False
        for pattern, description in patterns:
            if re.search(pattern, content):
                self.issues.append(f"Hard-coded {description} found in manager.py")
                print(f"{RED}  ✗ CRITICAL: {description} found{RESET}")
                found_issues = True
        
        if not found_issues:
            self.passes.append("No hard-coded credentials found")
            print(f"{GREEN}  ✓ PASS: No hard-coded credentials{RESET}")
    
    def test_shell_true_usage(self):
        """Check for dangerous subprocess.run with shell=True."""
        print(f"\n{BLUE}[TEST] Subprocess Security{RESET}")
        
        files_to_check = ["manager.py", "hermes_bridge.py", "cli.py"]
        found_issues = False
        
        for filename in files_to_check:
            file_path = self.root_dir / filename
            if not file_path.exists():
                continue
            
            content = file_path.read_text(encoding='utf-8', errors='ignore')
            
            # Look for shell=True with user input
            if "shell=True" in content and ("command" in content or "cmd" in content):
                self.issues.append(f"shell=True usage found in {filename}")
                print(f"{RED}  ✗ CRITICAL: shell=True found in {filename}{RESET}")
                found_issues = True
        
        if not found_issues:
            self.passes.append("No dangerous shell=True usage detected")
            print(f"{GREEN}  ✓ PASS: No shell=True with user input{RESET}")
    
    def test_api_authentication(self):
        """Check for API authentication."""
        print(f"\n{BLUE}[TEST] API Authentication{RESET}")
        
        manager_file = self.root_dir / "manager.py"
        if not manager_file.exists():
            print(f"{YELLOW}  ⊘ manager.py not found{RESET}")
            return
        
        content = manager_file.read_text(encoding='utf-8', errors='ignore')
        
        # Check for verify_api_key or authentication decorator
        has_auth = "verify_api_key" in content or "Depends(verify" in content or "@limiter.limit" in content
        
        if has_auth:
            self.passes.append("API authentication found")
            print(f"{GREEN}  ✓ PASS: API authentication implemented{RESET}")
        else:
            self.warnings.append("No API authentication found")
            print(f"{YELLOW}  ⚠ WARNING: No API key validation found{RESET}")
    
    def test_input_validation(self):
        """Check for input validation."""
        print(f"\n{BLUE}[TEST] Input Validation{RESET}")
        
        manager_file = self.root_dir / "manager.py"
        if not manager_file.exists():
            print(f"{YELLOW}  ⊘ manager.py not found{RESET}")
            return
        
        content = manager_file.read_text(encoding='utf-8', errors='ignore')
        
        has_validation = "validate_command" in content or "CLIAction" in content or "Enum" in content
        
        if has_validation:
            self.passes.append("Input validation implemented")
            print(f"{GREEN}  ✓ PASS: Input validation found{RESET}")
        else:
            self.warnings.append("Limited input validation")
            print(f"{YELLOW}  ⚠ WARNING: Input validation not comprehensive{RESET}")
    
    def test_log_sanitization(self):
        """Check for log sanitization."""
        print(f"\n{BLUE}[TEST] Log Sanitization{RESET}")
        
        security_utils = self.root_dir / "security_utils.py"
        if not security_utils.exists():
            self.warnings.append("security_utils.py not found")
            print(f"{YELLOW}  ⚠ WARNING: security_utils.py not found{RESET}")
            return
        
        content = security_utils.read_text(encoding='utf-8', errors='ignore')
        
        has_sanitization = "sanitize_for_logging" in content or "REDACTED" in content
        
        if has_sanitization:
            self.passes.append("Log sanitization implemented")
            print(f"{GREEN}  ✓ PASS: Log sanitization found{RESET}")
        else:
            self.issues.append("No log sanitization found")
            print(f"{RED}  ✗ CRITICAL: Log sanitization missing{RESET}")
    
    def test_file_permissions(self):
        """Check for secure file permissions."""
        print(f"\n{BLUE}[TEST] File Permissions{RESET}")
        
        sensitive_dirs = ["agent_logs", "agent_data"]
        found_issues = False
        
        for dirname in sensitive_dirs:
            dir_path = self.root_dir / dirname
            if not dir_path.exists():
                print(f"{YELLOW}  ⊘ {dirname} not found{RESET}")
                continue
            
            # Check permissions (Unix-style)
            try:
                mode = oct(dir_path.stat().st_mode)[-3:]
                if mode != "700":  # Should be owner-only
                    self.warnings.append(f"{dirname} permissions too permissive ({mode})")
                    print(f"{YELLOW}  ⚠ WARNING: {dirname} has permissions {mode} (should be 700){RESET}")
                    found_issues = True
            except Exception as e:
                print(f"{YELLOW}  ⊘ Could not check {dirname}: {e}{RESET}")
        
        if not found_issues:
            self.passes.append("File permissions are secure")
            print(f"{GREEN}  ✓ PASS: Sensitive directories have secure permissions{RESET}")
    
    def test_rate_limiting(self):
        """Check for rate limiting."""
        print(f"\n{BLUE}[TEST] Rate Limiting{RESET}")
        
        manager_file = self.root_dir / "manager.py"
        if not manager_file.exists():
            print(f"{YELLOW}  ⊘ manager.py not found{RESET}")
            return
        
        content = manager_file.read_text(encoding='utf-8', errors='ignore')
        
        has_rate_limiting = "@limiter" in content or "rate_limit" in content or "RateLimitExceeded" in content
        
        if has_rate_limiting:
            self.passes.append("Rate limiting implemented")
            print(f"{GREEN}  ✓ PASS: Rate limiting found{RESET}")
        else:
            self.warnings.append("No rate limiting found")
            print(f"{YELLOW}  ⚠ WARNING: Rate limiting not implemented{RESET}")
    
    def test_security_headers(self):
        """Check for security headers."""
        print(f"\n{BLUE}[TEST] Security Headers{RESET}")
        
        security_utils = self.root_dir / "security_utils.py"
        if not security_utils.exists():
            print(f"{YELLOW}  ⊘ security_utils.py not found{RESET}")
            return
        
        content = security_utils.read_text(encoding='utf-8', errors='ignore')
        
        headers = [
            "X-Content-Type-Options",
            "X-Frame-Options",
            "X-XSS-Protection",
            "Strict-Transport-Security"
        ]
        
        found_headers = sum(1 for h in headers if h in content)
        
        if found_headers >= 3:
            self.passes.append("Security headers implemented")
            print(f"{GREEN}  ✓ PASS: Security headers found ({found_headers}/{len(headers)}){RESET}")
        elif found_headers > 0:
            self.warnings.append(f"Only {found_headers} security headers found")
            print(f"{YELLOW}  ⚠ WARNING: Partial security headers ({found_headers}/{len(headers)}){RESET}")
        else:
            self.warnings.append("No security headers found")
            print(f"{YELLOW}  ⚠ WARNING: Security headers not implemented{RESET}")
    
    def test_env_example(self):
        """Check .env.example for exposed secrets."""
        print(f"\n{BLUE}[TEST] Environment Configuration{RESET}")
        
        env_file = self.root_dir / ".env.example"
        if not env_file.exists():
            print(f"{YELLOW}  ⊘ .env.example not found{RESET}")
            return
        
        content = env_file.read_text(encoding='utf-8', errors='ignore')
        
        # Check for actual values (not placeholders)
        dangerous_patterns = [
            (r'GROQ_API_KEY\s*=\s*gsk_[a-zA-Z0-9]+', "Groq key"),
            (r'GITHUB_TOKEN\s*=\s*ghp_[a-zA-Z0-9]+', "GitHub token"),
            (r'DISCORD_TOKEN\s*=\s*MT[a-zA-Z0-9]+', "Discord token"),
        ]
        
        found_secrets = False
        for pattern, name in dangerous_patterns:
            if re.search(pattern, content):
                self.issues.append(f"Exposed {name} in .env.example")
                print(f"{RED}  ✗ CRITICAL: Exposed {name} in .env.example{RESET}")
                found_secrets = True
        
        if not found_secrets:
            self.passes.append(".env.example has no exposed secrets")
            print(f"{GREEN}  ✓ PASS: .env.example uses placeholders{RESET}")
    
    def run_all_tests(self):
        """Run all security tests."""
        print(f"\n{BLUE}{'='*60}")
        print(f"Ghost Engine Security Test Suite{RESET}")
        print(f"{BLUE}{'='*60}{RESET}\n")
        
        self.test_hard_coded_credentials()
        self.test_shell_true_usage()
        self.test_api_authentication()
        self.test_input_validation()
        self.test_log_sanitization()
        self.test_file_permissions()
        self.test_rate_limiting()
        self.test_security_headers()
        self.test_env_example()
        
        self.print_summary()
    
    def print_summary(self):
        """Print test summary."""
        print(f"\n{BLUE}{'='*60}")
        print(f"Test Summary{RESET}")
        print(f"{BLUE}{'='*60}{RESET}\n")
        
        if self.issues:
            print(f"{RED}Critical Issues ({len(self.issues)}):{RESET}")
            for issue in self.issues:
                print(f"  {RED}✗{RESET} {issue}")
        
        if self.warnings:
            print(f"\n{YELLOW}Warnings ({len(self.warnings)}):{RESET}")
            for warning in self.warnings:
                print(f"  {YELLOW}⚠{RESET} {warning}")
        
        if self.passes:
            print(f"\n{GREEN}Passed ({len(self.passes)}):{RESET}")
            for passed in self.passes:
                print(f"  {GREEN}✓{RESET} {passed}")
        
        # Final status
        print(f"\n{BLUE}{'='*60}{RESET}")
        if self.issues:
            print(f"{RED}Status: CRITICAL ISSUES FOUND - DO NOT DEPLOY{RESET}")
            return 1
        elif self.warnings:
            print(f"{YELLOW}Status: Some warnings - Review before deployment{RESET}")
            return 2
        else:
            print(f"{GREEN}Status: PASS - System appears secure{RESET}")
            return 0


def main():
    tester = SecurityTester()
    exit_code = tester.run_all_tests()
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
