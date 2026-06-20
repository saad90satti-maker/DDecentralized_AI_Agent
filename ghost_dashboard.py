"""
Ghost Dashboard — Lightweight web UI for swarm monitoring.
Runs on :8501, shows node status, peers, tasks, metrics, evolution history.
"""

import json
import logging
import time
from datetime import datetime, timezone
from pathlib import Path
from string import Template
from typing import Any, Dict, List, Optional

logger = logging.getLogger("GhostDashboard")

DASHBOARD_PORT = 8501
STATE_DIR = Path(__file__).resolve().parent / "agent_data"
STATE_FILE = STATE_DIR / "agent_state.json"
TASK_DB = STATE_DIR / "ghost_tasks.json"
METRICS_DB = STATE_DIR / "scraper_data.db"
LOG_FILE = Path(__file__).resolve().parent / "agent_logs" / "Ghost_Master_Log.log"

HTML_TEMPLATE = Template("""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Ghost Grid Dashboard</title>
<style>
* { margin:0; padding:0; box-sizing:border-box; }
body { background:#0a0a0a; color:#00ff41; font-family:'Courier New',monospace; padding:20px; }
h1 { text-align:center; font-size:2em; margin-bottom:20px; text-shadow:0 0 10px #00ff41; }
.grid { display:grid; grid-template-columns:1fr 1fr; gap:16px; max-width:1200px; margin:0 auto; }
.card { background:#111; border:1px solid #00ff41; border-radius:8px; padding:16px; }
.card h2 { font-size:1.1em; margin-bottom:10px; color:#00cc33; border-bottom:1px solid #003300; padding-bottom:6px; }
.metric { font-size:2em; font-weight:bold; color:#00ff41; }
.label { color:#00991a; font-size:0.85em; }
.status-ok { color:#00ff41; }
.status-warn { color:#ffaa00; }
.status-fail { color:#ff3333; }
table { width:100%; border-collapse:collapse; font-size:0.85em; }
th, td { padding:4px 8px; text-align:left; border-bottom:1px solid #1a1a1a; }
th { color:#00991a; }
.bar { height:20px; background:#003300; border-radius:4px; overflow:hidden; margin-top:4px; }
.bar-fill { height:100%; background:#00ff41; transition:width 0.3s; }
.footer { text-align:center; margin-top:20px; color:#005500; font-size:0.8em; }
</style>
</head>
<body>
<h1>[ GHOST GRID DASHBOARD ]</h1>
<div class="grid">
  <div class="card">
    <h2>Node Status</h2>
    <div class="metric">$node_id</div>
    <div class="label">Version: $version | Iteration: $iteration</div>
    <div class="label">Uptime: $uptime</div>
  </div>
  <div class="card">
    <h2>Network</h2>
    <div class="metric">$ip</div>
    <div class="label">Country: $country | Proxy: $proxy | Tor: $tor</div>
  </div>
  <div class="card">
    <h2>LLM Router</h2>
    <div class="metric">$llm_tier</div>
    <div class="label">Failovers: $failovers | Status: $llm_status</div>
  </div>
  <div class="card">
    <h2>Swarm</h2>
    <div class="metric">$peers peers</div>
    <div class="label">DHT: $dht | Tasks pending: $tasks_pending</div>
  </div>
  <div class="card" style="grid-column:span 2;">
    <h2>Evolution History</h2>
    <table>
      <tr><th>Cycle</th><th>Version</th><th>Timestamp</th></tr>
      $evolution_rows
    </table>
  </div>
  <div class="card" style="grid-column:span 2;">
    <h2>Recent Logs</h2>
    <div style="max-height:200px;overflow-y:auto;font-size:0.75em;background:#050505;padding:8px;border-radius:4px;">
      $log_tail
    </div>
  </div>
</div>
<div class="footer">Ghost Grid v$version | $timestamp</div>
</body>
</html>""")


def _load_state() -> Dict[str, Any]:
    try:
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _load_tasks() -> List[Dict[str, Any]]:
    try:
        return json.loads(TASK_DB.read_text(encoding="utf-8"))
    except Exception:
        return []


def _load_log_tail(lines: int = 40) -> str:
    try:
        with open(LOG_FILE, "r", encoding="utf-8") as f:
            tail = f.readlines()[-lines:]
        return "".join(tail).replace("<", "&lt;").replace(">", "&gt;")
    except Exception:
        return "(no logs)"


def render_dashboard() -> str:
    state = _load_state()
    tasks = _load_tasks()
    last_cycle = state.get("last_cycle", {})
    network = last_cycle.get("network", {})
    evolution = state.get("evolution_history", [])[-10:]

    evo_rows = ""
    for e in reversed(evolution):
        evo_rows += f"<tr><td>{e.get('cycle','?')}</td><td>{e.get('version','?')}</td><td>{e.get('timestamp','?')[:19]}</td></tr>"

    pending = sum(1 for t in tasks if t.get("status") == "pending")
    running = sum(1 for t in tasks if t.get("status") == "running")
    completed = sum(1 for t in tasks if t.get("status") == "completed")

    start_time = state.get("start_time", time.time())
    uptime_s = time.time() - start_time
    h, m = int(uptime_s // 3600), int((uptime_s % 3600) // 60)

    return HTML_TEMPLATE.safe_substitute(
        node_id=state.get("node_id", state.get("last_cycle", {}).get("cycle", "?")),
        version=state.get("evolution_version", state.get("last_cycle", {}).get("evolution_version", "v1.0.0")),
        iteration=last_cycle.get("cycle", "?"),
        uptime=f"{h}h {m}m",
        ip=network.get("ip", "?"),
        country=network.get("country", "?"),
        proxy=network.get("proxy", "?"),
        tor=network.get("tor_ip") or "inactive",
        llm_tier=last_cycle.get("llm_tier", "none"),
        failovers=state.get("failover_count", 0),
        llm_status=last_cycle.get("llm_status", "none"),
        peers=state.get("peers_total", "?"),
        dht=state.get("dht_active", "?"),
        tasks_pending=f"{pending} pending / {running} running / {completed} done",
        evolution_rows=evo_rows or "<tr><td colspan='3'>No evolution history yet</td></tr>",
        log_tail=_load_log_tail(),
        timestamp=datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
    )


def run_dashboard_server(port: int = DASHBOARD_PORT) -> None:
    from http.server import HTTPServer, BaseHTTPRequestHandler

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            html = render_dashboard()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(html.encode())

        def log_message(self, format, *args):
            pass  # suppress console spam

    server = HTTPServer(("0.0.0.0", port), Handler)
    logger.info("Ghost Dashboard live on http://localhost:%d", port)
    print(f"Ghost Dashboard live on http://localhost:{port}")
    server.serve_forever()
