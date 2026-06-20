"""
Ghost Master — Full System Launcher
Connects: Dashboard + Discord + Hermes + Ghost Media + Swarm + Compute + Scheduler
Run: python ghost_launcher.py
"""

import asyncio
import json
import logging
import os
import sys
import threading
import time
import webbrowser
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

from flask import Flask, jsonify, request, Response
from string import Template

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "agent_data"
LOG_DIR = BASE_DIR / "agent_logs"
STATE_FILE = DATA_DIR / "agent_state.json"

DATA_DIR.mkdir(parents=True, exist_ok=True)
LOG_DIR.mkdir(parents=True, exist_ok=True)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(message)s")
logger = logging.getLogger("GhostMaster")

app = Flask(__name__)

# ──── Module Registry ────

MODULES = [
    ("ghost_executor.py", "Master autonomous loop"),
    ("ghost_swarm.py", "P2P TCP + UDP broadcast + Kademlia DHT"),
    ("ghost_compute.py", "Distributed task queue"),
    ("ghost_scheduler.py", "Cron-like periodic jobs"),
    ("ghost_dashboard.py", "Web dashboard module"),
    ("ghost_launcher.py", "This launcher — full system integration"),
    ("tor_controller.py", "Tor routing + shadow mode"),
    ("proxy_rotator.py", "SOCKS5 proxy pool"),
    ("scraper_engine.py", "BeautifulSoup + SQLite storage"),
    ("github_sync.py", "Auto-sync to GitHub"),
    ("hf_spaces.py", "HuggingFace inference + deploy"),
    ("human_mimicry.py", "Random delays + rotating UAs"),
    ("model_router.py", "3-tier LLM failover"),
    ("learning_log.py", "Learning metrics"),
    ("security_utils.py", "Security utilities"),
    ("hermes_bridge.py", "Hermes/Ollama bridge"),
    ("hermes_agent_bridge.py", "Multi-agent bridge (85+ tools)"),
    ("discord_bot.py", "Discord remote control"),
    ("execution_core.py", "Task queue with process pools"),
    ("run_agent.py", "Agent runtime orchestrator"),
    ("manager.py", "FastAPI dashboard (port 8000)"),
    ("cli.py", "CLI interface"),
    ("browser_agent.py", "Playwright browser agent"),
    ("stealth_browser.py", "Anti-detection browser"),
    ("intelligent_agent.py", "Vision-based browser agent"),
    ("autonomous_agent.py", "Self-evolving LLM agent"),
    ("email_agent.py", "Gmail IMAP/SMTP"),
    ("security_utils.py", "Security utilities"),
]

GHOST_MEDIA_MODULES = [
    ("ghost_media_engine/config.py", "Typed config dataclasses"),
    ("ghost_media_engine/logging.py", "Structured logging + correlation IDs"),
    ("ghost_media_engine/browser/controller.py", "Self-healing Playwright"),
    ("ghost_media_engine/browser/tasks.py", "Gmail, YouTube, GitHub tasks"),
    ("ghost_media_engine/browser/workflows.py", "Multi-step workflows"),
    ("ghost_media_engine/llm/base.py", "BaseLLM + RateLimiter + CircuitBreaker"),
    ("ghost_media_engine/llm/gemini.py", "Async Gemini API"),
    ("ghost_media_engine/llm/hermes.py", "Async Hermes/Ollama"),
    ("ghost_media_engine/pipeline/base.py", "Pipeline step system"),
    ("ghost_media_engine/pipeline/youtube_pipeline.py", "YouTube publish pipeline"),
    ("ghost_media_engine/security/validator.py", "Input validation"),
    ("ghost_media_engine/utils/retry.py", "RetryPolicy + CircuitBreaker"),
]


def _load_state() -> Dict[str, Any]:
    try:
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _load_log_tail(lines: int = 50) -> str:
    log_file = LOG_DIR / "Ghost_Master_Log.log"
    try:
        with open(log_file, "r", encoding="utf-8") as f:
            tail = f.readlines()[-lines:]
        return "".join(tail).replace("<", "&lt;").replace(">", "&gt;")
    except Exception:
        return "(no logs yet)"


def _hermes_analyze(prompt: str) -> Dict[str, Any]:
    try:
        from hermes_bridge import HermesBridge
        hb = HermesBridge(cli_fallback=True)
        return hb.analyze(prompt)
    except Exception as e:
        return {"status": "error", "message": str(e)}


def _hermes_status() -> Dict[str, Any]:
    try:
        import requests
        r = requests.get("http://localhost:11434", timeout=3)
        return {"available": r.ok, "url": "http://localhost:11434"}
    except Exception:
        return {"available": False, "url": "http://localhost:11434"}


def _discord_status() -> Dict[str, Any]:
    token = os.getenv("DISCORD_TOKEN", "")
    return {
        "configured": bool(token),
        "token_preview": f"{token[:8]}..." if token else "NOT SET",
        "channel_id": os.getenv("DISCORD_CHANNEL_ID", "NOT SET"),
    }


def _ghost_media_status() -> Dict[str, Any]:
    try:
        from ghost_media_engine import EngineConfig
        return {"available": True, "version": "3.0.0"}
    except Exception:
        return {"available": False, "version": "unknown"}


# ──── Flask Routes ────

@app.route("/")
def dashboard():
    return Response(render_full_dashboard(), mimetype="text/html")


@app.route("/api/health")
def api_health():
    return jsonify({
        "status": "ok",
        "modules": len(MODULES),
        "ghost_media_modules": len(GHOST_MEDIA_MODULES),
        "hermes": _hermes_status(),
        "discord": _discord_status(),
        "ghost_media": _ghost_media_status(),
    })


@app.route("/api/state")
def api_state():
    return jsonify(_load_state())


@app.route("/api/logs")
def api_logs():
    return Response(_load_log_tail(200), mimetype="text/plain")


@app.route("/api/hermes", methods=["POST"])
def api_hermes():
    data = request.get_json() or {}
    prompt = data.get("prompt", "")
    if not prompt:
        return jsonify({"error": "No prompt provided"}), 400
    result = _hermes_analyze(prompt)
    return jsonify(result)


@app.route("/api/hermes/status")
def api_hermes_status():
    return jsonify(_hermes_status())


@app.route("/api/discord/status")
def api_discord_status():
    return jsonify(_discord_status())


@app.route("/api/ghost-media/status")
def api_ghost_media_status():
    return jsonify(_ghost_media_status())


@app.route("/api/modules")
def api_modules():
    modules = []
    for name, desc in MODULES:
        exists = (BASE_DIR / name).exists()
        modules.append({"name": name, "description": desc, "available": exists})
    return jsonify(modules)


# ──── Dashboard HTML ────

DASHBOARD_HTML = Template("""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Ghost Master — Full System Dashboard</title>
<meta http-equiv="refresh" content="15">
<style>
* { margin:0; padding:0; box-sizing:border-box; }
body { background:#0a0a0a; color:#00ff41; font-family:'Courier New',monospace; padding:16px; }
h1 { text-align:center; font-size:1.8em; margin-bottom:8px; text-shadow:0 0 15px #00ff41; letter-spacing:4px; }
.subtitle { text-align:center; color:#00991a; margin-bottom:16px; font-size:0.85em; }
.nav { display:flex; justify-content:center; gap:8px; margin-bottom:16px; flex-wrap:wrap; }
.nav a { color:#00ff41; text-decoration:none; padding:5px 12px; border:1px solid #003300; border-radius:4px; font-size:0.8em; }
.nav a:hover { background:#003300; }
.grid { display:grid; grid-template-columns:repeat(auto-fit, minmax(260px, 1fr)); gap:10px; max-width:1600px; margin:0 auto; }
.card { background:#111; border:1px solid #004400; border-radius:8px; padding:12px; }
.card h2 { font-size:0.9em; color:#00cc33; border-bottom:1px solid #003300; padding-bottom:4px; margin-bottom:6px; }
.metric { font-size:1.6em; font-weight:bold; color:#00ff41; }
.small { font-size:0.75em; color:#00991a; }
.logs { max-height:200px; overflow-y:auto; font-size:0.65em; background:#050505; padding:8px; border-radius:4px; white-space:pre-wrap; line-height:1.3; }
.status-dot { display:inline-block; width:8px; height:8px; border-radius:50%; margin-right:4px; }
.dot-green { background:#00ff41; box-shadow:0 0 6px #00ff41; }
.dot-red { background:#ff3333; box-shadow:0 0 6px #ff3333; }
.dot-yellow { background:#ffaa00; box-shadow:0 0 6px #ffaa00; }
.footer { text-align:center; margin-top:12px; color:#004400; font-size:0.7em; }
table { width:100%; font-size:0.75em; border-collapse:collapse; }
th, td { padding:3px 6px; text-align:left; border-bottom:1px solid #1a1a1a; }
th { color:#00991a; }
input[type=text] { background:#050505; color:#00ff41; border:1px solid #003300; padding:6px 10px; border-radius:4px; font-family:monospace; width:100%; font-size:0.85em; }
button { background:#003300; color:#00ff41; border:1px solid #004400; padding:6px 14px; border-radius:4px; cursor:pointer; font-family:monospace; font-size:0.85em; }
button:hover { background:#004400; }
#hermes-output { max-height:150px; overflow-y:auto; font-size:0.7em; background:#050505; padding:6px; border-radius:4px; margin-top:6px; white-space:pre-wrap; }
</style>
</head>
<body>
<h1>[ GHOST MASTER — FULL SYSTEM DASHBOARD ]</h1>
<div class="subtitle">$total_files files | $total_modules modules | $total_gme ghost_media_engine files</div>

<div class="nav">
  <a href="/api/health">Health</a>
  <a href="/api/state">State</a>
  <a href="/api/logs">Logs</a>
  <a href="/api/modules">Modules</a>
  <a href="/api/hermes/status">Hermes</a>
  <a href="/api/discord/status">Discord</a>
  <a href="/api/ghost-media/status">GME</a>
</div>

<div class="grid">
  <div class="card">
    <h2>Engine Status</h2>
    <div class="metric"><span class="status-dot dot-green"></span>ONLINE</div>
    <div class="small">Version: $version | Cycle: $iteration</div>
    <div class="small">Uptime: $uptime</div>
  </div>

  <div class="card">
    <h2>Network</h2>
    <div class="metric" style="font-size:1.1em;">$ip</div>
    <div class="small">Country: $country | Proxy: $proxy</div>
    <div class="small">Tor: $tor</div>
  </div>

  <div class="card">
    <h2>LLM Router</h2>
    <div class="metric" style="font-size:1.3em;">$llm_tier</div>
    <div class="small">Failovers: $failovers | Status: $llm_status</div>
  </div>

  <div class="card">
    <h2>Swarm</h2>
    <div class="metric">$peers peers</div>
    <div class="small">DHT: UDP :8468 | TCP: :9876</div>
  </div>

  <div class="card">
    <h2>Hermes Agent</h2>
    <div class="metric" style="font-size:1.1em;">$hermes_status</div>
    <div class="small">$hermes_url</div>
    <div class="small">85+ tools | 17 skill categories</div>
  </div>

  <div class="card">
    <h2>Discord Bot</h2>
    <div class="metric" style="font-size:1.1em;">$discord_status</div>
    <div class="small">Token: $discord_token</div>
    <div class="small">Channel: $discord_channel</div>
  </div>

  <div class="card">
    <h2>Ghost Media Engine</h2>
    <div class="metric" style="font-size:1.1em;">$gme_status</div>
    <div class="small">Version: $gme_version</div>
    <div class="small">Browser + LLM + Pipeline + Security</div>
  </div>

  <div class="card">
    <h2>Evolution</h2>
    <div class="metric" style="font-size:1.1em;">$evolution_version</div>
    <div class="small">Mutations: $mutation_count</div>
  </div>

  <div class="card" style="grid-column:span 2;">
    <h2>Hermes Control (Send prompt)</h2>
    <div style="display:flex;gap:6px;">
      <input type="text" id="hermes-prompt" placeholder="Ask Hermes anything...">
      <button onclick="sendHermes()">Send</button>
    </div>
    <div id="hermes-output">Response will appear here...</div>
  </div>

  <div class="card" style="grid-column:span 2;">
    <h2>Core Modules ($total_modules)</h2>
    <table>
      <tr><th>Module</th><th>Status</th><th>Description</th></tr>
      $module_rows
    </table>
  </div>

  <div class="card" style="grid-column:span 2;">
    <h2>Ghost Media Engine ($total_gme files)</h2>
    <table>
      <tr><th>File</th><th>Status</th><th>Description</th></tr>
      $gme_rows
    </table>
  </div>

  <div class="card" style="grid-column:span 2;">
    <h2>Evolution History (last 10)</h2>
    <table>
      <tr><th>Cycle</th><th>Version</th><th>Timestamp</th></tr>
      $evolution_rows
    </table>
  </div>

  <div class="card" style="grid-column:span 2;">
    <h2>Live Logs</h2>
    <div class="logs">$log_tail</div>
  </div>
</div>

<div class="footer">Ghost Master $version | Auto-refresh 15s | $timestamp</div>

<script>
async function sendHermes() {
  const prompt = document.getElementById('hermes-prompt').value;
  const output = document.getElementById('hermes-output');
  output.textContent = 'Sending to Hermes...';
  try {
    const r = await fetch('/api/hermes', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({prompt: prompt})
    });
    const data = await r.json();
    output.textContent = JSON.stringify(data, null, 2);
  } catch(e) {
    output.textContent = 'Error: ' + e.message;
  }
}
</script>
</body>
</html>""")


def render_full_dashboard() -> str:
    state = _load_state()
    last_cycle = state.get("last_cycle", {})
    network = last_cycle.get("network", {})
    evolution = state.get("evolution_history", [])[-10:]

    start_time = state.get("start_time", time.time())
    uptime_s = time.time() - start_time
    h, m = int(uptime_s // 3600), int((uptime_s % 3600) // 60)

    evo_rows = ""
    for e in reversed(evolution):
        evo_rows += f"<tr><td>{e.get('cycle','?')}</td><td>{e.get('version','?')}</td><td>{e.get('timestamp','?')[:19]}</td></tr>"

    module_rows = ""
    for name, desc in MODULES:
        exists = (BASE_DIR / name).exists()
        dot = "dot-green" if exists else "dot-red"
        status = "Available" if exists else "Missing"
        module_rows += f'<tr><td>{name}</td><td><span class="status-dot {dot}"></span>{status}</td><td class="small">{desc}</td></tr>'

    gme_rows = ""
    for name, desc in GHOST_MEDIA_MODULES:
        exists = (BASE_DIR / name).exists()
        dot = "dot-green" if exists else "dot-red"
        status = "Available" if exists else "Missing"
        gme_rows += f'<tr><td>{name}</td><td><span class="status-dot {dot}"></span>{status}</td><td class="small">{desc}</td></tr>'

    hermes = _hermes_status()
    discord = _discord_status()
    gme = _ghost_media_status()

    return DASHBOARD_HTML.safe_substitute(
        total_files=len(MODULES) + len(GHOST_MEDIA_MODULES),
        total_modules=len(MODULES),
        total_gme=len(GHOST_MEDIA_MODULES),
        version=state.get("evolution_version", last_cycle.get("evolution_version", "v1.0.0")),
        iteration=last_cycle.get("cycle", "0"),
        uptime=f"{h}h {m}m",
        ip=network.get("ip", "110.37.110.106"),
        country=network.get("country", "PK"),
        proxy=network.get("proxy", "False"),
        tor=network.get("tor_ip") or "inactive",
        llm_tier=last_cycle.get("llm_tier", "gemini"),
        failovers=state.get("failover_count", 0),
        llm_status=last_cycle.get("llm_status", "none"),
        peers=state.get("peers_total", "0"),
        hermes_status="ONLINE" if hermes["available"] else "OFFLINE",
        hermes_url=hermes["url"],
        discord_status="CONFIGURED" if discord["configured"] else "NO TOKEN",
        discord_token=discord["token_preview"],
        discord_channel=discord["channel_id"],
        gme_status="ONLINE" if gme["available"] else "AVAILABLE",
        gme_version=gme["version"],
        evolution_version=state.get("evolution_version", "v1.0.0"),
        mutation_count=len(evolution),
        module_rows=module_rows,
        gme_rows=gme_rows,
        evolution_rows=evo_rows or "<tr><td colspan='3' class='small'>No evolution history yet</td></tr>",
        log_tail=_load_log_tail(),
        timestamp=datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
    )


# ──── Background Threads ────

def _start_swarm():
    try:
        from ghost_swarm import GhostSwarmNode
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        node = GhostSwarmNode(node_id="ghost-master", port=9876)
        loop.run_until_complete(node.start())
        loop.run_forever()
    except Exception as e:
        logger.warning("Swarm: %s", e)


def _start_discord():
    try:
        import discord_bot
        if discord_bot.DISCORD_TOKEN:
            asyncio.run(discord_bot.main())
        else:
            logger.info("Discord: No DISCORD_TOKEN set — bot not started")
    except Exception as e:
        logger.warning("Discord: %s", e)


# ──── Main ────

if __name__ == "__main__":
    print("=" * 60)
    print("  GHOST MASTER — Full System Launcher")
    print("=" * 60)

    state = _load_state()
    state["start_time"] = time.time()
    STATE_FILE.write_text(json.dumps(state, indent=2), encoding="utf-8")

    print(f"[*] Modules: {len(MODULES)} core + {len(GHOST_MEDIA_MODULES)} ghost_media_engine")
    print(f"[*] Hermes: {_hermes_status()['url']}")
    print(f"[*] Discord: {'configured' if os.getenv('DISCORD_TOKEN') else 'no token'}")

    print("[*] Starting P2P Swarm on :9876...")
    threading.Thread(target=_start_swarm, daemon=True).start()

    print("[*] Starting Discord bot...")
    threading.Thread(target=_start_discord, daemon=True).start()

    print("[*] Dashboard: http://localhost:8080")
    print("[*] APIs: /api/health | /api/state | /api/logs | /api/hermes | /api/discord/status")

    threading.Timer(2.0, lambda: webbrowser.open("http://localhost:8080")).start()

    app.run(host='0.0.0.0', port=8080, debug=False)
