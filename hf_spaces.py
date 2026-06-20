"""
HuggingFace Spaces Deployer — Deploys background tasks as HF Spaces apps.
Uses HF Inference API as free-tier LLM fallback and Spaces hosting.
"""

import json
import logging
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests

logger = logging.getLogger("HFSpacesDeployer")

BASE_DIR = Path(__file__).resolve().parent
SPACES_DIR = BASE_DIR / ".hf_spaces"
SPACES_DIR.mkdir(parents=True, exist_ok=True)


def get_hf_token() -> str:
    return os.getenv("HUGGINGFACE_TOKEN", "")


class HFInferenceAPI:
    """Free-tier HuggingFace Inference API wrapper."""

    MODELS = [
        "NousResearch/Nous-Hermes-2-Mistral-7B-DPO",
        "microsoft/Phi-3-mini-4k-instruct",
        "HuggingFaceH4/zephyr-7b-beta",
        "mistralai/Mistral-7B-Instruct-v0.3",
        "google/gemma-2-2b-it",
    ]

    def __init__(self):
        self.token = get_hf_token()
        self._headers = {"Authorization": f"Bearer {self.token}"} if self.token else {}
        self._active_model = self.MODELS[0]
        self._available = False
        self._probe()

    def _probe(self) -> None:
        for model in self.MODELS:
            try:
                r = requests.post(
                    f"https://api-inference.huggingface.co/models/{model}",
                    json={"inputs": "test"},
                    headers=self._headers, timeout=5
                )
                if r.status_code in (200, 503):
                    self._active_model = model
                    self._available = True
                    logger.info("HF Inference API: %s available", model)
                    return
            except Exception:
                continue
        logger.warning("No HF Inference API models reachable")

    def query(self, prompt: str, max_tokens: int = 256) -> Dict[str, Any]:
        if not self._available:
            return {"status": "error", "output": "HF API unavailable"}
        try:
            r = requests.post(
                f"https://api-inference.huggingface.co/models/{self._active_model}",
                json={"inputs": prompt, "parameters": {"max_new_tokens": max_tokens}},
                headers=self._headers, timeout=30
            )
            if r.status_code == 503:
                model_id = r.json().get("model", self._active_model)
                wait = r.json().get("estimated_time", 20)
                logger.info("HF model loading (~%.0fs): %s", wait, model_id)
                return {"status": "loading", "estimated_time": wait, "model": model_id}
            if r.ok:
                data = r.json()
                text = data[0].get("generated_text", str(data)) if isinstance(data, list) else str(data)
                return {"status": "success", "output": text, "model": self._active_model}
            return {"status": "error", "output": str(r.text[:200]), "model": self._active_model}
        except Exception as e:
            return {"status": "error", "output": str(e)}

    @property
    def available(self) -> bool:
        return self._available


class HFSpacesDeployer:
    """Deploys Gradio/FastAPI apps as HuggingFace Spaces for background tasks."""

    SPACE_TEMPLATE = '''
import gradio as gr
import json, os, sys, subprocess, time
from pathlib import Path

GHOST_SCRIPT = """
import json, sys
sys.path.insert(0, ".")
from scraper_engine import ScraperEngine, ScraperDB
engine = ScraperEngine()
results = engine.search_google("{query}", num_results=5)
print(json.dumps(results, indent=2))
"""

def run_task(query):
    import tempfile, subprocess
    with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as f:
        f.write(GHOST_SCRIPT.format(query=query))
        f.flush()
        result = subprocess.run([sys.executable, f.name], capture_output=True, text=True, timeout=60)
        os.unlink(f.name)
        return result.stdout or result.stderr

with gr.Blocks(title="Ghost Engine Space") as demo:
    gr.Markdown("# Ghost Media Engine - Background Task Runner")
    with gr.Row():
        query = gr.Textbox(label="Search Query", placeholder="Enter search query...")
        btn = gr.Button("Execute")
    output = gr.Textbox(label="Result")
    btn.click(fn=run_task, inputs=query, outputs=output)

demo.launch()
'''

    def __init__(self):
        self.token = get_hf_token()
        self._headers = {"Authorization": f"Bearer {self.token}"} if self.token else {}

    def deploy_space(self, space_name: str = "ghost-engine-tasks",
                     query: str = "AI trends") -> Dict[str, Any]:
        if not self.token:
            return {"status": "error", "message": "HUGGINGFACE_TOKEN not set"}

        space_dir = SPACES_DIR / space_name
        space_dir.mkdir(parents=True, exist_ok=True)

        # Create space app
        app_code = self.SPACE_TEMPLATE.format(query=query.replace('"', '\\"'))
        (space_dir / "app.py").write_text(app_code, encoding="utf-8")
        (space_dir / "requirements.txt").write_text(
            "gradio\nrequests\nbeautifulsoup4\nlxml\n", encoding="utf-8")
        (space_dir / "README.md").write_text(
            f"---\ntitle: {space_name}\nemojii: 👻\ncolorFrom: purple\ncolorTo: black\nsdk: gradio\nsdk_version: 4.5.0\napp_file: app.py\n---\n",
            encoding="utf-8")

        # Try git-based deploy
        try:
            subprocess.run(["git", "init"], cwd=str(space_dir), capture_output=True, timeout=30)
            subprocess.run(["git", "add", "-A"], cwd=str(space_dir), capture_output=True, timeout=30)
            subprocess.run(["git", "commit", "-m", "Initial deploy"], cwd=str(space_dir),
                           capture_output=True, timeout=30)

            space_url = f"https://huggingface.co/spaces/{space_name}"
            subprocess.run(
                ["git", "remote", "add", "origin",
                 f"https://{self.token}@huggingface.co/spaces/{space_name}"],
                cwd=str(space_dir), capture_output=True, timeout=30
            )
            result = subprocess.run(["git", "push", "--force", "origin", "main"],
                                    cwd=str(space_dir), capture_output=True, text=True, timeout=120)
            if result.returncode == 0:
                logger.info("HF Space deployed: %s", space_url)
                return {"status": "success", "url": space_url, "space": space_name}
            logger.warning("HF push: %s", result.stderr[:300])
            return {"status": "error", "message": result.stderr[:300]}
        except Exception as e:
            logger.warning("HF Space deploy: %s", e)
            return {"status": "error", "message": str(e)}

    def list_spaces(self) -> List[Dict]:
        if not self.token:
            return []
        try:
            r = requests.get("https://huggingface.co/api/spaces", headers=self._headers, params={"limit": 20}, timeout=15)
            if r.ok:
                return [{"name": s.get("id", "?"), "url": f"https://huggingface.co/spaces/{s.get('id', '')}"}
                        for s in r.json()]
        except Exception:
            pass
        return []
