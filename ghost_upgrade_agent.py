"""
GhostUpgradeAgent — Self-upgrading deployment controller with Flask status API.

Pulls latest code from GitHub, injects logic, restarts stack, and serves
live orbital relay status on port 8080.
"""
import os
import sys
import json
import time
import subprocess
import threading
import httpx
from pathlib import Path

BASE = Path(__file__).parent.resolve()
GHOST_CORE_URL = os.environ.get("GHOST_CORE_URL", "http://localhost:7861")
UPGRADE_LOG = BASE / "agent_logs" / "ghost_upgrade.log"

# ── Flask status API ──────────────────────────────────────────────────
try:
    from flask import Flask, jsonify, request
    HAS_FLASK = True
except ImportError:
    HAS_FLASK = False


class GhostUpgradeAgent:
    """Self-upgrading agent: pull, inject, restart, report."""

    def __init__(self, repo_url: str = "https://github.com/anomalyco/opencode.git"):
        self.repo_url = repo_url
        self.local_path = str(BASE)
        self.last_pull_time = 0
        self.pull_count = 0
        self.inject_count = 0
        self.restart_count = 0
        self._http = httpx.Client(timeout=5.0)

    def pull_latest_updates(self):
        """Git pull from remote repository."""
        print("[UPGRADE] Pulling latest logic from GitHub...")
        try:
            result = subprocess.run(
                ["git", "pull", self.repo_url],
                cwd=self.local_path,
                capture_output=True, text=True, timeout=30,
            )
            self.pull_count += 1
            self.last_pull_time = time.time()
            print(f"[UPGRADE] Pull OK: {result.stdout.strip()[:80]}")
            return True
        except Exception as e:
            print(f"[UPGRADE] Pull failed: {e}")
            return False

    def inject_new_logic(self, code_snippet: str, target_file: str = "ghost_orbital_relay.py"):
        """Append new code logic to a target file."""
        target = BASE / target_file
        if not target.exists():
            print(f"[UPGRADE] Target not found: {target}")
            return False
        try:
            with open(target, "a", encoding="utf-8") as f:
                f.write(f"\n# --- GHOST UPGRADE INJECTION [{time.ctime()}] ---\n")
                f.write(code_snippet)
                if not code_snippet.endswith("\n"):
                    f.write("\n")
            self.inject_count += 1
            print(f"[UPGRADE] Logic injected into {target_file}")
            return True
        except Exception as e:
            print(f"[UPGRADE] Inject failed: {e}")
            return False

    def restart_stack(self):
        """Restart all ghost daemons."""
        print("[UPGRADE] Restarting Ghost Orbital Relay...")
        try:
            for proc_name in ["ghost_orbital_relay", "ghost_node_prime", "ghost_app"]:
                subprocess.run(
                    ["taskkill", "/F", "/IM", "python.exe", "/FI", f'CMDLINE LIKE "%{proc_name}%"'],
                    capture_output=True, timeout=10,
                )
            time.sleep(2)
            # Start fresh
            subprocess.Popen(
                [sys.executable, "-u", "ghost_orbital_relay.py"],
                cwd=self.local_path, creationflags=subprocess.CREATE_NO_WINDOW,
            )
            self.restart_count += 1
            print("[UPGRADE] Stack restarted")
            return True
        except Exception as e:
            print(f"[UPGRADE] Restart failed: {e}")
            return False

    def fetch_live_telemetry(self) -> dict:
        """Fetch live telemetry from ghost-core."""
        try:
            r = self._http.get(f"{GHOST_CORE_URL}/telemetry", timeout=3)
            if r.status_code == 200:
                t = r.json()
                fft = t.get("telemetry", {}).get("fft", {})
                return {
                    "node": t.get("node_id", "?"),
                    "cycle": t.get("cycle", 0),
                    "snr_db": fft.get("snr_after_db", 0),
                    "gate_db": fft.get("gate_threshold_db", 0),
                }
        except Exception:
            pass
        return {"node": "offline", "cycle": 0, "snr_db": 0, "gate_db": 0}

    def status(self) -> dict:
        telemetry = self.fetch_live_telemetry()
        return {
            "service": "GhostUpgradeAgent",
            "status": "AUTONOMOUS",
            "repo": self.repo_url,
            "pull_count": self.pull_count,
            "inject_count": self.inject_count,
            "restart_count": self.restart_count,
            "telemetry": telemetry,
            "signal_db": telemetry.get("snr_db", 0),
            "connection": "CONNECTED" if telemetry.get("snr_db", 0) else "OFFLINE",
            "node": "ACTIVE" if telemetry.get("cycle", 0) else "STANDBY",
            "timestamp": time.time(),
        }


# ── Flask status server ──────────────────────────────────────────────

def start_flask_api(agent: GhostUpgradeAgent, port: int = 8080):
    """Start Flask status endpoint in a background thread."""
    if not HAS_FLASK:
        print("[FLASK] Flask not available - status API disabled")
        return

    app = Flask(__name__)

    @app.route("/")
    def root():
        return jsonify({"service": "GhostUpgradeAgent", "version": "1.0.0", "status": "running"})

    @app.route("/status")
    def get_status():
        s = agent.status()
        return jsonify({
            "signal": f"{s['signal_db']:.2f} dB",
            "status": s["connection"],
            "node": s["node"],
            "telemetry": s["telemetry"],
            "upgrade": {
                "pulls": s["pull_count"],
                "injects": s["inject_count"],
                "restarts": s["restart_count"],
            },
        })

    @app.route("/upgrade/pull")
    def api_pull():
        ok = agent.pull_latest_updates()
        return jsonify({"pull": "ok" if ok else "failed", "count": agent.pull_count})

    @app.route("/relay/ultra-fast", methods=["GET", "POST"])
    def api_ultra_fast_relay():
        """Send data via ultra-fast relay to satellite gateway.

        GET  /relay/ultra-fast?data=HELLO
        POST /relay/ultra-fast  {"data": "HELLO"}
        """
        from ghost_orbital_relay import ultra_fast_relay, SATELLITE_GATEWAY_HOST
        if request.method == "POST" and request.is_json:
            data = request.json.get("data", "")
        else:
            data = request.args.get("data", "")
        if not data:
            return jsonify({"error": "no data provided"}), 400
        ultra_fast_relay(data)
        return jsonify({
            "relayed": True,
            "data": data,
            "gateway": SATELLITE_GATEWAY_HOST,
            "port": 5006,
        })

    @app.route("/fleet/command", methods=["GET", "POST"])
    def api_fleet_command():
        """Broadcast a signed command to the global fleet.

        GET  /fleet/command?cmd=DEPLOY_DSP_PATCH_V2
        POST /fleet/command  {"command": "DEPLOY_DSP_PATCH_V2"}
        """
        from ghost_orbital_relay import orchestrate_global_fleet, GLOBAL_FLEET_NODES
        if request.method == "POST" and request.is_json:
            cmd = request.json.get("command", "")
        else:
            cmd = request.args.get("cmd", "")
        if not cmd:
            return jsonify({"error": "no command provided"}), 400
        orchestrate_global_fleet(cmd)
        return jsonify({
            "orchestrated": True,
            "command": cmd,
            "nodes": GLOBAL_FLEET_NODES,
            "message": f"Signed '{cmd}' broadcast to global fleet",
        })

    @app.route("/trigger/action")
    def api_trigger_action():
        """Trigger a verified handshake action (console + log).

        Query params:
          ?cmd=START_DSP    — execute a remote command after triggering
          ?cmd=SHUTDOWN_RELAY
          ?cmd=UPDATE_PROTOCOL
        """
        from ghost_orbital_relay import ActionTrigger
        t = ActionTrigger()
        cmd = request.args.get("cmd", "")
        if cmd:
            full_payload = f"GHOST-8880-VERIFIED:{cmd}"
            t.fire_with_payload(request.remote_addr or "api", full_payload)
        else:
            t.fire(request.remote_addr or "api")
        return jsonify({
            "action": "triggered",
            "total_fires": t.total_fires,
            "message": "Handshake confirmed! Relay active.",
            "command": cmd or None,
        })

    @app.route("/upgrade/inject", methods=["POST"])
    def api_inject():
        from flask import request
        code = request.json.get("code", "") if request.is_json else ""
        if not code:
            return jsonify({"error": "no code provided"}), 400
        ok = agent.inject_new_logic(code)
        return jsonify({"inject": "ok" if ok else "failed", "count": agent.inject_count})

    def run_flask():
        print(f"[FLASK] Status API on http://0.0.0.0:{port}")
        app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False)

    t = threading.Thread(target=run_flask, daemon=True)
    t.start()


# ── CLI entry ────────────────────────────────────────────────────────

def main():
    agent = GhostUpgradeAgent()
    print(f"{'='*55}")
    print(f"  GhostUpgradeAgent | PID {os.getpid()}")
    print(f"  Repo: {agent.repo_url}")
    print(f"  Status: http://localhost:8080/status")
    print(f"{'='*55}")

    start_flask_api(agent)

    # Initial telemetry fetch
    s = agent.status()
    print(f"[AGENT] Telemetry: {s['signal_db']:.2f} dB | Node: {s['node']}")

    # Keep alive
    try:
        while True:
            time.sleep(30)
            s = agent.status()
            print(f"[AGENT] Heartbeat: {s['signal_db']:.1f} dB | "
                  f"Pulls={s['pull_count']} Injects={s['inject_count']} Restarts={s['restart_count']}")
    except KeyboardInterrupt:
        print("[AGENT] Shutdown")


if __name__ == "__main__":
    main()
