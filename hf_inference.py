"""
HuggingFace Model Inference Engine — local transformer inference with caching.
Loads models from HuggingFace Hub with local disk cache, processes prompts,
and reports status to the dashboard in real-time.
"""

import json
import logging
import os
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger("HFInference")

BASE_DIR = Path(__file__).resolve().parent
STATUS_FILE = BASE_DIR / "agent_data" / "hf_inference_status.json"

@dataclass
class InferenceConfig:
    model_id: str = "microsoft/Phi-3-mini-4k-instruct"
    device_map: str = "auto"
    max_new_tokens: int = 512
    temperature: float = 0.7
    top_p: float = 0.9
    repetition_penalty: float = 1.1
    load_in_8bit: bool = False
    cache_dir: Optional[str] = None
    trust_remote_code: bool = False

    @classmethod
    def from_env(cls):
        return cls(
            model_id=os.getenv("HF_INFERENCE_MODEL", cls.model_id),
            device_map=os.getenv("HF_DEVICE_MAP", cls.device_map),
            max_new_tokens=int(os.getenv("HF_MAX_NEW_TOKENS", str(cls.max_new_tokens))),
            temperature=float(os.getenv("HF_TEMPERATURE", str(cls.temperature))),
            load_in_8bit=os.getenv("HF_LOAD_IN_8BIT", "").lower() in ("1", "true", "yes"),
            cache_dir=os.getenv("HF_CACHE_DIR") or os.getenv("HUGGINGFACE_HUB_CACHE"),
            trust_remote_code=os.getenv("HF_TRUST_REMOTE_CODE", "").lower() in ("1", "true"),
        )

@dataclass
class InferenceResult:
    status: str = "pending"
    output: str = ""
    model: str = ""
    latency: float = 0.0
    tokens_generated: int = 0
    error: str = ""

class HFInferenceEngine:
    """Thread-safe HuggingFace model inference with local disk caching."""

    def __init__(self, config: Optional[InferenceConfig] = None):
        self.config = config or InferenceConfig.from_env()
        self._model = None
        self._tokenizer = None
        self._lock = threading.Lock()
        self._loaded = False
        self._load_error: Optional[str] = None
        self._stats: Dict[str, Any] = {
            "total_queries": 0,
            "successful_queries": 0,
            "failed_queries": 0,
            "total_tokens": 0,
            "avg_latency": 0.0,
            "last_query_time": None,
            "model": self.config.model_id,
        }
        self._ready_event = threading.Event()
        self._stopped = False
        self._status_callback: Optional[callable] = None

    # ---- Public API ----

    def load_model(self) -> bool:
        """Load model and tokenizer from HuggingFace Hub (uses local cache if available)."""
        with self._lock:
            if self._loaded:
                return True

            hf_token = os.getenv("HUGGINGFACE_TOKEN") or os.getenv("HF_TOKEN")
            cache_dir = self.config.cache_dir

            try:
                from transformers import AutoModelForCausalLM, AutoTokenizer
                logger.info("Loading model: %s (device: %s)", self.config.model_id, self.config.device_map)

                tokenizer_kwargs = {"use_fast": True}
                if hf_token:
                    tokenizer_kwargs["token"] = hf_token
                if cache_dir:
                    tokenizer_kwargs["cache_dir"] = cache_dir

                self._tokenizer = AutoTokenizer.from_pretrained(
                    self.config.model_id,
                    **tokenizer_kwargs
                )
                if self._tokenizer.pad_token_id is None:
                    self._tokenizer.pad_token_id = self._tokenizer.eos_token_id

                model_kwargs = {
                    "device_map": self.config.device_map,
                    "trust_remote_code": self.config.trust_remote_code,
                }
                if hf_token:
                    model_kwargs["token"] = hf_token
                if cache_dir:
                    model_kwargs["cache_dir"] = cache_dir

                self._model = AutoModelForCausalLM.from_pretrained(
                    self.config.model_id,
                    **model_kwargs
                )

                self._loaded = True
                self._load_error = None
                self._ready_event.set()
                logger.info("Model loaded successfully: %s", self.config.model_id)
                return True

            except Exception as e:
                self._loaded = False
                self._load_error = str(e)
                logger.error("Failed to load model %s: %s", self.config.model_id, e)
                return False

    def unload_model(self):
        """Unload model to free memory."""
        with self._lock:
            self._model = None
            self._tokenizer = None
            self._loaded = False
            self._ready_event.clear()
            logger.info("Model unloaded")

    def process_prompt(self, prompt: str, params: Optional[Dict[str, Any]] = None) -> InferenceResult:
        """Process a prompt through the loaded model and return the result."""
        result = InferenceResult()
        result.model = self.config.model_id

        if not self._loaded:
            success = self.load_model()
            if not success:
                result.status = "error"
                result.error = self._load_error or "Model not loaded"
                self._record_query(result)
                return result

        p = {**self._default_params(), **(params or {})}
        start = time.time()

        try:
            with self._lock:
                inputs = self._tokenizer(prompt, return_tensors="pt", truncation=True, max_length=p.get("max_input_length", 2048))

                generate_kwargs = {
                    "max_new_tokens": p["max_new_tokens"],
                    "temperature": p["temperature"],
                    "top_p": p["top_p"],
                    "repetition_penalty": p["repetition_penalty"],
                    "do_sample": p["temperature"] > 0,
                    "pad_token_id": self._tokenizer.pad_token_id,
                    "eos_token_id": self._tokenizer.eos_token_id,
                }

                output_ids = self._model.generate(**inputs, **generate_kwargs)
                generated_ids = output_ids[0][inputs["input_ids"].shape[1]:]
                result.tokens_generated = len(generated_ids)
                result.output = self._tokenizer.decode(generated_ids, skip_special_tokens=True).strip()

        except Exception as e:
            result.status = "error"
            result.error = str(e)
            logger.error("Inference error: %s", e)
        else:
            result.status = "success"
            result.latency = time.time() - start

        self._record_query(result)
        return result

    def get_status(self) -> Dict[str, Any]:
        """Return status dict for dashboard /api/status endpoint."""
        upstream = self._test_upstream_api()
        return {
            "hf_model_loaded": self._loaded,
            "hf_model": self.config.model_id,
            "hf_load_error": self._load_error,
            "hf_upstream_api": upstream,
            "hf_stats": {**self._stats},
            "hf_device": self._get_device_info(),
        }

    def set_status_callback(self, callback: callable):
        """Set a callback that will be called with status updates."""
        self._status_callback = callback

    def warmup(self) -> bool:
        """Load model in background thread."""
        def _load():
            if not self._loaded:
                self.load_model()
        t = threading.Thread(target=_load, daemon=True)
        t.start()
        return True

    # ---- Internal ----

    def _default_params(self) -> Dict:
        return {
            "max_new_tokens": self.config.max_new_tokens,
            "temperature": self.config.temperature,
            "top_p": self.config.top_p,
            "repetition_penalty": self.config.repetition_penalty,
        }

    def _record_query(self, result: InferenceResult):
        self._stats["total_queries"] += 1
        if result.status == "success":
            self._stats["successful_queries"] += 1
            self._stats["total_tokens"] += result.tokens_generated
            n = self._stats["successful_queries"]
            self._stats["avg_latency"] = (
                (self._stats["avg_latency"] * (n - 1) + result.latency) / n
            )
        else:
            self._stats["failed_queries"] += 1
        self._stats["last_query_time"] = time.time()
        self._persist_status()
        if self._status_callback:
            try:
                self._status_callback(self.get_status())
            except Exception:
                pass

    def _persist_status(self):
        try:
            STATUS_FILE.parent.mkdir(parents=True, exist_ok=True)
            STATUS_FILE.write_text(json.dumps(self.get_status(), indent=2), encoding="utf-8")
        except Exception:
            pass

    def _get_device_info(self) -> str:
        if not self._model:
            return "N/A"
        try:
            return str(self._model.device)
        except Exception:
            return "unknown"

    def _test_upstream_api(self) -> str:
        """Test if the HF Inference API is reachable as fallback."""
        token = os.getenv("HUGGINGFACE_TOKEN") or os.getenv("HF_TOKEN")
        if not token:
            return "no_token"
        try:
            import requests
            r = requests.get(
                "https://api-inference.huggingface.co/status",
                headers={"Authorization": f"Bearer {token}"},
                timeout=5,
            )
            return "ok" if r.ok else f"error_{r.status_code}"
        except Exception as e:
            return f"unreachable_{str(e)[:30]}"


def create_default_engine() -> HFInferenceEngine:
    """Create and return a pre-configured HFInferenceEngine ready for use."""
    config = InferenceConfig.from_env()
    engine = HFInferenceEngine(config)
    engine.warmup()
    return engine
