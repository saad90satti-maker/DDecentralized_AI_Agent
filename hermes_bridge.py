"""
Hermes Bridge

Provides a simple, safe IPC/HTTP/CLI bridge to a local Hermes/Ollama instance.
Designed for local testing only. Uses `requests` HTTP calls first and falls back
to the `ollama` CLI when available.

Usage:
    from hermes_bridge import HermesBridge
    hb = HermesBridge()
    result = hb.analyze("Summarize this text...")

Environment variables:
    HERMES_URL - base URL for Hermes HTTP API (default: http://localhost:11434)
    HERMES_MODEL - name of the model to call (default: hermes)

"""

import os
import shlex
import json
import logging
import subprocess
from typing import Dict, Any, Optional

import requests

logging.getLogger(__name__)

HERMES_URL = os.getenv("HERMES_URL", "http://localhost:11434")
HERMES_MODEL = os.getenv("HERMES_MODEL", "hermes")

class HermesBridge:
    def __init__(self, url: Optional[str] = None, model: Optional[str] = None, cli_fallback: bool = True):
        self.url = (url or HERMES_URL).rstrip("/")
        self.model = model or HERMES_MODEL
        self.cli_fallback = cli_fallback
        self.timeout = 15

    def is_http_available(self) -> bool:
        try:
            r = requests.get(self.url, timeout=3)
            return r.ok
        except Exception:
            return False

    def send_prompt_http(self, prompt: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Try several common HTTP endpoints used by local LLM services.
        Returns the first successful response as a dict.
        """
        endpoints = ["/v1/generate", "/generate", "/api/generate", "/completion", "/api/complete"]
        for ep in endpoints:
            try:
                url = self.url + ep
                payload = {"model": self.model, "prompt": prompt}
                if params:
                    payload.update(params)
                r = requests.post(url, json=payload, timeout=self.timeout)
                if r.ok:
                    try:
                        return {"status": "success", "endpoint": ep, "response": r.json()}
                    except Exception:
                        return {"status": "success", "endpoint": ep, "text": r.text}
            except Exception as exc:
                logging.debug("hermes http attempt failed %s %s", ep, exc)
        return {"status": "unavailable", "reason": "no endpoints responded"}

    def send_prompt_cli(self, prompt: str) -> Dict[str, Any]:
        """Fallback to calling `ollama run <model> --prompt '<prompt>'` if available."""
        # Try invoking ollama/cli by sending the prompt on stdin (works for many CLI versions)
        try:
            # Capture raw bytes and decode safely to avoid encoding errors on Windows
            proc = subprocess.run(["ollama", "run", self.model], input=prompt.encode("utf-8"), capture_output=True, text=False, timeout=60)
            out = proc.stdout.decode("utf-8", errors="replace") if isinstance(proc.stdout, (bytes, bytearray)) else str(proc.stdout)
            err = proc.stderr.decode("utf-8", errors="replace") if isinstance(proc.stderr, (bytes, bytearray)) else str(proc.stderr)
            return {
                "status": "success" if proc.returncode == 0 else "error",
                "stdout": out.strip(),
                "stderr": err.strip(),
                "returncode": proc.returncode,
            }
        except FileNotFoundError:
            return {"status": "error", "exception": "ollama CLI not found"}
        except Exception as exc:
            # Last-resort: try previous --prompt style for older/newer variants
            try:
                cmd = f"ollama run {shlex.quote(self.model)} --prompt {shlex.quote(prompt)}"
                completed = subprocess.run(cmd, shell=True, capture_output=True, text=False, timeout=60)
                out = completed.stdout.decode("utf-8", errors="replace") if isinstance(completed.stdout, (bytes, bytearray)) else str(completed.stdout)
                err = completed.stderr.decode("utf-8", errors="replace") if isinstance(completed.stderr, (bytes, bytearray)) else str(completed.stderr)
                return {
                    "status": "success" if completed.returncode == 0 else "error",
                    "stdout": out.strip(),
                    "stderr": err.strip(),
                    "returncode": completed.returncode,
                }
            except Exception as exc2:
                return {"status": "error", "exception": str(exc2)}

    def analyze(self, prompt: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Main orchestration method: prefer HTTP then CLI fallback."""
        http = self.send_prompt_http(prompt, params)
        if http.get("status") == "success":
            return http
        if self.cli_fallback:
            return self.send_prompt_cli(prompt)
        return http

    def orchestrate_task(self, task_input: Dict[str, Any]) -> Dict[str, Any]:
        """Helper that builds a prompt from task input and returns Hermes output.
        Example task_input: {"id": 123, "text": "Analyze me", "meta": {...}}
        """
        prompt = task_input.get("text") or task_input.get("command") or str(task_input)
        params = task_input.get("params")
        return self.analyze(prompt, params)


# Simple CLI test harness when run directly
if __name__ == "__main__":
    hb = HermesBridge()
    test_prompt = os.getenv("HERMES_TEST_PROMPT", "Hello from HermesBridge. Summarize: The quick brown fox.")
    print(json.dumps(hb.analyze(test_prompt), indent=2))
