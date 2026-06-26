import json
import os
import subprocess
import threading
import time
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional

import requests
from dotenv import load_dotenv

from learning_log import LearningLog
from security_utils import sanitize_for_logging
from hf_inference import HFInferenceEngine, InferenceConfig

load_dotenv()


@dataclass
class ModelResponse:
    model: str
    status: str
    output: Any
    latency: float
    source: str


DEFAULT_LOCAL_HEALTH_TIMEOUT = float(os.getenv("LOCAL_HEALTH_TIMEOUT", "3"))
DEFAULT_LOCAL_RESPONSE_THRESHOLD = float(os.getenv("LOCAL_RESPONSE_THRESHOLD", "5.0"))
HEALTH_ENDPOINTS = ["/v1/models", "/v1/health", "/health", "/"]

class ModelRouter:
    def __init__(self, log: Optional[LearningLog] = None, timeout: int = 15):
        self.timeout = timeout
        self.local_url = os.getenv("HERMES_URL", "http://localhost:11434")
        self.local_model = os.getenv("HERMES_MODEL", "llama3.2:1b")
        self.cloud_model = os.getenv("GEMINI_API_MODEL", "models/gemini-2.5-flash")
        self.gemini_api_token = os.getenv("GEMINI_API_TOKEN")
        self.groq_api_key = os.getenv("GROQ_API_KEY")
        self.groq_model = os.getenv("GROQ_MODEL", "llama-3.1-8b-instant")
        self.learning_log = log or LearningLog()
        self.terminal_last_read = ""
        self.terminal_path = Path(__file__).resolve().parent / "agent_logs" / "hermes_terminal.log"
        self.terminal_path.parent.mkdir(parents=True, exist_ok=True)
        self.monitor_thread = None
        self._monitor_running = False
        self.health_timeout = DEFAULT_LOCAL_HEALTH_TIMEOUT
        self.local_response_threshold = DEFAULT_LOCAL_RESPONSE_THRESHOLD
        self.performance_history = deque(maxlen=50)
        self.local_priority = True
        self._groq_active = True
        self._hf_engine: Optional[HFInferenceEngine] = None

    def start_terminal_monitor(self) -> None:
        if self.monitor_thread and self.monitor_thread.is_alive():
            return
        self._monitor_running = True
        self.monitor_thread = threading.Thread(target=self._terminal_monitor_loop, daemon=True)
        self.monitor_thread.start()

    def stop_terminal_monitor(self) -> None:
        self._monitor_running = False
        if self.monitor_thread and self.monitor_thread.is_alive():
            self.monitor_thread.join(timeout=1)

    def _terminal_monitor_loop(self) -> None:
        try:
            proc = subprocess.Popen(
                ["ollama", "logs", "--follow"],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
            )
        except Exception:
            return

        if not proc.stdout:
            return

        while self._monitor_running:
            line = proc.stdout.readline()
            if not line:
                break
            self.terminal_last_read = line.strip()
            with open(self.terminal_path, "a", encoding="utf-8") as f:
                f.write(f"{time.strftime('%Y-%m-%dT%H:%M:%SZ')} | {line}")
        proc.terminate()
        proc.wait(timeout=1)

    def route(self, prompt: str, params: Optional[Dict[str, Any]] = None) -> ModelResponse:
        health = self.preflight_check()
        start = time.time()

        cascade = [
            ("groq",   lambda: self._call_groq(prompt, params)),
            ("gemini", lambda: self._call_gemini(prompt, params)),
            ("hf",     lambda: self._call_hf(prompt, params)),
            ("local",  lambda: self._call_local(prompt, params)),
        ]

        response = {"status": "error", "output": "All backends exhausted"}
        source = "none"

        for tier_name, tier_fn in cascade:
            if tier_name == "local" and not health["use_local"]:
                continue
            try:
                result = tier_fn()
                latency = time.time() - start
                if result.get("status") == "success":
                    response = result
                    source = tier_name
                    break
                # Any non-success from a higher tier triggers failover to next
                reason = "quota/timeout" if self._is_quota_or_timeout(result, latency) else "error"
                self._record_patch(f"Failover [{reason}]: {tier_name} -> next tier ({str(result.get('output',''))[:80]})")
                continue
            except Exception as exc:
                self._record_patch(f"Failover [exception]: {tier_name} -> next tier ({exc})")
                continue

        latency = time.time() - start
        self._update_performance(source, latency, response.get("status") == "success")
        model_response = ModelResponse(
            model=response.get("model", source),
            status=response.get("status", "error"),
            output=response.get("output", response.get("text", response.get("response", ""))),
            latency=latency,
            source=source,
        )
        self.learning_log.append({
            "prompt": prompt,
            "response": sanitize_for_logging(str(model_response.output)),
            "model": model_response.model,
            "source": model_response.source,
            "latency": latency,
            "status": model_response.status,
        })
        return model_response

    def _is_quota_or_timeout(self, result: Dict[str, Any], latency: float) -> bool:
        err = str(result.get("output", "")).lower()
        return (
            "429" in err
            or "quota" in err
            or "rate limit" in err
            or "too many requests" in err
            or (latency > 5.0 and result.get("status") != "success")
        )

    def _check_local_agent(self) -> bool:
        try:
            r = requests.get(self.local_url, timeout=self.health_timeout)
            return r.ok
        except Exception:
            return False

    def _local_health_status(self) -> Dict[str, Any]:
        for endpoint in HEALTH_ENDPOINTS:
            url = self.local_url.rstrip("/") + endpoint
            try:
                start = time.time()
                r = requests.get(url, timeout=self.health_timeout)
                latency = time.time() - start
                if r.ok:
                    return {"ok": True, "latency": latency, "checked_url": url, "status_code": r.status_code}
            except Exception:
                continue
        return {"ok": False, "latency": None, "checked_url": None, "status_code": None}

    def preflight_check(self) -> Dict[str, Any]:
        health = self._local_health_status()
        history = self.learning_log.latest(50)
        failures = sum(1 for entry in history if entry.get("status") != "success" or "error" in str(entry.get("response", "")).lower())
        local_ok = health["ok"] and (health["latency"] is not None and health["latency"] <= self.local_response_threshold)
        local_ok = local_ok and self.local_priority
        self.local_priority = local_ok

        if health["ok"] and health["latency"] is not None:
            if health["latency"] > self.local_response_threshold:
                self.local_priority = False

        return {
            "local_ok": health["ok"],
            "latency_ms": health["latency"],
            "checked_url": health["checked_url"],
            "recent_failures": failures,
            "local_response_threshold": self.local_response_threshold,
            "use_local": local_ok,
        }

    def _update_performance(self, source: str, latency: float, success: bool) -> None:
        self.performance_history.append({
            "source": source,
            "latency": latency,
            "success": success,
            "timestamp": time.strftime('%Y-%m-%dT%H:%M:%SZ'),
        })

    def _call_local(self, prompt: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        endpoint = self.local_url.rstrip("/") + "/v1/generate"
        try:
            payload = {
                "model": self.local_model,
                "prompt": prompt,
            }
            if params:
                payload.update(params)
            r = requests.post(endpoint, json=payload, timeout=self.timeout)
            r.raise_for_status()
            data = r.json()
            self._log_terminal_output()
            return {"status": "success", "output": data, "model": self.local_model}
        except Exception as exc:
            return {"status": "error", "output": str(exc), "model": self.local_model}

    def _call_gemini(self, prompt: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        if not self.gemini_api_token:
            return {"status": "error", "output": "Gemini API token not configured", "model": self.cloud_model}

        try:
            # Use REST API directly — avoids google.generativeai client library timeout issues
            model_name = self.cloud_model.replace("models/", "")
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent"
            payload = {"contents": [{"parts": [{"text": prompt}]}]}
            if params:
                payload.update(params)
            r = requests.post(
                url,
                json=payload,
                params={"key": self.gemini_api_token},
                timeout=min(self.timeout, 12),
            )
            if r.status_code == 429:
                return {"status": "error", "output": "429 rate limit / quota exceeded", "model": self.cloud_model}
            if not r.ok:
                return {"status": "error", "output": f"Gemini HTTP {r.status_code}: {r.text[:200]}", "model": self.cloud_model}
            data = r.json()
            candidates = data.get("candidates", [])
            if not candidates:
                return {"status": "error", "output": "Gemini: no candidates returned", "model": self.cloud_model}
            text = candidates[0].get("content", {}).get("parts", [{}])[0].get("text", "")
            return {"status": "success", "output": text, "model": self.cloud_model}
        except requests.exceptions.Timeout:
            return {"status": "error", "output": "Gemini timeout", "model": self.cloud_model}
        except requests.exceptions.HTTPError as exc:
            if "429" in str(exc):
                return {"status": "error", "output": "429 rate limit", "model": self.cloud_model}
            return {"status": "error", "output": str(exc), "model": self.cloud_model}
        except Exception as exc:
            return {"status": "error", "output": str(exc), "model": self.cloud_model}

    def _call_groq(self, prompt: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        if not self.groq_api_key or not self._groq_active:
            return {"status": "error", "output": "Groq not configured or disabled", "model": self.groq_model}
        try:
            url = "https://api.groq.com/openai/v1/chat/completions"
            headers = {"Authorization": f"Bearer {self.groq_api_key}", "Content-Type": "application/json"}
            payload = {
                "model": self.groq_model,
                "messages": [{"role": "user", "content": prompt}],
            }
            if params:
                payload.update(params)
            r = requests.post(url, json=payload, headers=headers, timeout=self.timeout)
            if r.status_code == 429:
                self._groq_active = False
                return {"status": "error", "output": f"429 rate limit on Groq", "model": self.groq_model}
            r.raise_for_status()
            data = r.json()
            text = data["choices"][0]["message"]["content"].strip()
            return {"status": "success", "output": text, "model": self.groq_model}
        except requests.exceptions.HTTPError as exc:
            if "429" in str(exc):
                self._groq_active = False
            return {"status": "error", "output": str(exc), "model": self.groq_model}
        except Exception as exc:
            return {"status": "error", "output": str(exc), "model": self.groq_model}

    def _record_patch(self, message: str) -> None:
        log_path = Path(__file__).resolve().parent / "agent_logs" / "self_patch.log"
        try:
            log_path.parent.mkdir(parents=True, exist_ok=True)
            with open(log_path, "a", encoding="utf-8") as f:
                f.write(f"{time.strftime('%Y-%m-%dT%H:%M:%SZ')} | {message}\n")
        except Exception:
            pass

    def _log_terminal_output(self) -> None:
        # keep compatibility with one-shot terminal reads
        try:
            proc = subprocess.Popen(["ollama", "logs"], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
            if proc.stdout:
                output = proc.stdout.read(1024)
                if output:
                    self.terminal_last_read = output
                    with open(self.terminal_path, "a", encoding="utf-8") as f:
                        f.write(f"{time.strftime('%Y-%m-%dT%H:%M:%SZ')} | {output}\n")
            proc.terminate()
        except Exception:
            pass

    def read_terminal_history(self) -> str:
        try:
            return self.terminal_path.read_text(encoding="utf-8")
        except Exception:
            return ""

    def _call_hf(self, prompt: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        if self._hf_engine is None:
            cfg = InferenceConfig.from_env()
            self._hf_engine = HFInferenceEngine(cfg)
        success = self._hf_engine.load_model()
        if not success:
            return {"status": "error", "output": self._hf_engine._load_error or "HF model unavailable", "model": "hf"}
        p = dict(params) if params else {}
        result = self._hf_engine.process_prompt(prompt, p)
        return {
            "status": result.status,
            "output": result.output if result.status == "success" else result.error,
            "model": f"hf/{self._hf_engine.config.model_id}",
        }

    @property
    def hf_engine(self) -> Optional[HFInferenceEngine]:
        return self._hf_engine
