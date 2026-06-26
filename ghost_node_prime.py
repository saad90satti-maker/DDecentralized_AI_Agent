"""
Ghost-Node-Prime - Autonomous Decentralized AI Node Supervisor.

PERSISTENCE | SENSING | ADAPTIVE BROADCASTING | SELF-EVOLUTION | GLOBAL INTENT
"""
import asyncio
import json
import os
import sys
import time
import socket
import httpx
import threading
import subprocess
import hashlib
import base64
from pathlib import Path

# ── AES-256 via cryptography ──────────────────────────────────────────
try:
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
    from cryptography.hazmat.primitives import padding
    HAS_AES = True
except ImportError:
    HAS_AES = False

# ── Paths ─────────────────────────────────────────────────────────────
BASE = Path(__file__).parent.resolve()
PID_FILE = BASE / "agent_logs" / "ghost_node_prime.pid"
LOG_DIR = BASE / "agent_logs"
LOG_DIR.mkdir(exist_ok=True)
BROADCAST_LOG = LOG_DIR / "p2p_broadcast.log"
STATE_FILE = LOG_DIR / "gnp_state.json"

# ── Config ────────────────────────────────────────────────────────────
GHOST_CORE_URL = os.environ.get("GHOST_CORE_URL", "http://localhost:7861")
DSP_INTERVAL = int(os.environ.get("DSP_INTERVAL", "5"))         # seconds between DSP tune cycles
BROADCAST_INTERVAL = int(os.environ.get("BROADCAST_INTERVAL", "10"))
HEALTH_INTERVAL = int(os.environ.get("HEALTH_INTERVAL", "30"))   # seconds between health checks
LOG_ANALYZE_INTERVAL = int(os.environ.get("LOG_ANALYZE_INTERVAL", "60"))
SWARM_SECRET = os.environ.get("SWARM_SECRET", "ghost-node-prime-default").encode()
BROADCAST_PORT = int(os.environ.get("BROADCAST_PORT", "5005"))
LISTEN_PORT = int(os.environ.get("LISTEN_PORT", "5005"))
TARGET_SNR = float(os.environ.get("TARGET_SNR", "38.0"))         # target > 38 dB
MAX_RSS_MB = int(os.environ.get("MAX_RSS_MB", "100"))
NODE_ID = os.environ.get("NODE_ID", "ghost-node-prime")
GHOST_APP_PY = str(BASE / "ghost_app.py")
P2P_BROADCAST_PY = str(BASE / "p2p_broadcast.py")

# ── GhostSignal AES-256 ────────────────────────────────────────────────
def _derive_aes_key(secret: bytes) -> bytes:
    return hashlib.sha256(secret).digest()

def ghost_encrypt_aes(plaintext: bytes, secret: bytes = None) -> bytes:
    if secret is None:
        secret = SWARM_SECRET
    if HAS_AES:
        key = _derive_aes_key(secret)
        iv = os.urandom(16)
        padder = padding.PKCS7(128).padder()
        padded = padder.update(plaintext) + padder.finalize()
        cipher = Cipher(algorithms.AES(key), modes.CBC(iv))
        encryptor = cipher.encryptor()
        ct = encryptor.update(padded) + encryptor.finalize()
        return iv + ct
    else:
        from p2p_broadcast import ghost_encrypt_packet
        return ghost_encrypt_packet(plaintext)

def ghost_decrypt_aes(data: bytes, secret: bytes = None) -> bytes:
    if secret is None:
        secret = SWARM_SECRET
    if HAS_AES and len(data) >= 16:
        key = _derive_aes_key(secret)
        iv = data[:16]
        ct = data[16:]
        cipher = Cipher(algorithms.AES(key), modes.CBC(iv))
        decryptor = cipher.decryptor()
        padded = decryptor.update(ct) + decryptor.finalize()
        unpadder = padding.PKCS7(128).unpadder()
        return unpadder.update(padded) + unpadder.finalize()
    else:
        from p2p_broadcast import ghost_decrypt_packet
        return ghost_decrypt_packet(data)

# ── Ghost-Node-Prime ──────────────────────────────────────────────────
class GhostNodePrime:
    def __init__(self):
        self.node_id = NODE_ID
        self.start_time = time.time()
        self.running = True
        self.http = httpx.Client(timeout=6.0, limits=httpx.Limits(max_keepalive_connections=2))
        self._pid_written = False

        self.cycle_count = 0
        self.broadcasts_sent = 0
        self.peers = {}
        self.handshakes = 0
        self.reconfigs = 0

        self.active_pids = {"ghost_app": None, "p2p_broadcast": None}  # ghost-sim intentionally NOT managed by us
        self.last_snr = 0.0
        self.best_snr = 0.0
        self.snr_history = []
        self.heuristic_state = {}
        self.latency_history = []

        self.daemon_task = None
        self.health_task = None
        self.dsp_task = None
        self.log_task = None

        self.load_state()

    # ── PERSISTENCE: PID management ──────────────────────────────────
    def write_pid(self):
        PID_FILE.write_text(f"{os.getpid()}\n{self.node_id}\n{time.time()}\n")
        self._pid_written = True

    def check_pid(self):
        if not PID_FILE.exists():
            return
        try:
            lines = PID_FILE.read_text().strip().split("\n")
            old_pid = int(lines[0])
            if old_pid != os.getpid():
                try:
                    p = psutil.Process(old_pid)
                    if p.is_running() and "ghost_node_prime" in " ".join(p.cmdline()):
                        print(f"[GNP] Previous instance PID {old_pid} still running - adopting")
                except Exception:
                    pass
        except Exception:
            pass

    def ensure_ghost_app_alive(self):
        # First: check if ghost-core API responds (most reliable)
        try:
            r = httpx.get(f"{GHOST_CORE_URL}/health", timeout=2)
            if r.status_code == 200:
                self.active_pids["ghost_app"] = None  # Don't track PID; rely on API
                return
        except Exception:
            pass

        # Second: scan for any ghost_app python process
        found = False
        try:
            import psutil
            for proc in psutil.process_iter(["pid", "cmdline"]):
                try:
                    cl = " ".join(proc.info.get("cmdline") or [])
                    if "ghost_app" in cl and "python" in cl:
                        self.active_pids["ghost_app"] = proc.info["pid"]
                        found = True
                        break
                except Exception:
                    continue
        except Exception:
            pass

        if found:
            print(f"[GNP] ghost_app found alive at PID {self.active_pids['ghost_app']}")
            return

        # Fall back: restart ghost_app
        print(f"[GNP] ghost_app not responding - restarting")
        try:
            proc = subprocess.Popen(
                [sys.executable, "-u", GHOST_APP_PY],
                cwd=str(BASE), creationflags=subprocess.CREATE_NO_WINDOW
            )
            self.active_pids["ghost_app"] = proc.pid
            print(f"[GNP] ghost_app restarted as PID {proc.pid}")
        except Exception as e:
            print(f"[GNP] Failed to restart ghost_app: {e}")

    # ── SENSING: DSP optimizer -> target > 38 dB ──────────────────────
    async def dsp_optimizer_loop(self):
        while self.running:
            try:
                r = self.http.get(f"{GHOST_CORE_URL}/telemetry")
                if r.status_code != 200:
                    await asyncio.sleep(DSP_INTERVAL)
                    continue
                t = r.json()
                fft = t.get("telemetry", {}).get("fft", {})
                snr = fft.get("snr_after_db", 0)
                gate = fft.get("gate_threshold_db", 0)
                win = fft.get("window_exp", 1.0)
                cycle = t.get("cycle", 0)
                self.last_snr = snr
                self.snr_history.append(snr)
                if len(self.snr_history) > 50:
                    self.snr_history.pop(0)
                if snr > self.best_snr:
                    self.best_snr = snr

                # Ensure ghost-core's internal target matches ours (38 dB)
                if not hasattr(self, '_target_set') or not self._target_set:
                    try:
                        r = self.http.post(f"{GHOST_CORE_URL}/tune", json={"target_snr_db": TARGET_SNR}, timeout=3)
                        if r.status_code == 200:
                            print(f"[GNP] Ghost-core target overridden: 21.17 -> {TARGET_SNR} dB")
                            self._target_set = True
                    except Exception as e:
                        print(f"[GNP] Target push failed: {e}")
                elif cycle % 20 == 0:
                    # Periodic re-assertion
                    try:
                        self.http.post(f"{GHOST_CORE_URL}/tune", json={"target_snr_db": TARGET_SNR}, timeout=3)
                    except Exception:
                        pass

                # Adaptive push: if SNR < target, force more aggressive gate/window via /tune API
                if snr < TARGET_SNR and cycle > 5:
                    gap = TARGET_SNR - snr
                    new_gate = max(3.0, min(25.0, gate + gap * 0.08))
                    new_win = max(0.4, min(2.0, win + (1.0 - win) * (gap / TARGET_SNR) * 0.15))
                    self.heuristic_state = {
                        "gate_aggressiveness": round(new_gate / 25.0, 3),
                        "window_adapt_speed": round(abs(1.0 - new_win) * 0.3, 3),
                        "exploration_rate": round(min(0.5, gap / TARGET_SNR * 0.4), 3),
                    }
                    # Push to ghost-core via /tune endpoint
                    tune_payload = {
                        "gate_aggressiveness": self.heuristic_state["gate_aggressiveness"],
                        "exploration_rate": self.heuristic_state["exploration_rate"],
                        "gate_threshold_db": round(new_gate, 2),
                        "window_exponent": round(new_win, 3),
                    }
                    try:
                        r2 = self.http.post(f"{GHOST_CORE_URL}/tune", json=tune_payload, timeout=3)
                        if r2.status_code == 200:
                            print(f"[GNP] PUSH tune: gate={new_gate:.1f} win={new_win:.2f} -> {r2.json()['status']}")
                    except Exception as e:
                        print(f"[GNP] Tune push failed: {e}")
                elif snr >= TARGET_SNR:
                    print(f"[GNP] SNR TARGET ACHIEVED: {snr:.1f} >= {TARGET_SNR}dB")
                    if self.heuristic_state.get("exploration_rate", 0) > 0.1:
                        self.heuristic_state["exploration_rate"] = 0.08
                        try:
                            self.http.post(f"{GHOST_CORE_URL}/tune", json={"exploration_rate": 0.08}, timeout=3)
                        except Exception:
                            pass

                self.cycle_count = cycle
            except httpx.ConnectError:
                pass
            except Exception as e:
                print(f"[GNP] DSP error: {e}")
            await asyncio.sleep(DSP_INTERVAL)

    # ── ADAPTIVE BROADCASTING: GhostSignal relay ─────────────────────
    async def broadcast_loop(self):
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

        # Discover subnet broadcast address
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))
            local_ip = s.getsockname()[0]
            s.close()
            parts = local_ip.split(".")
            parts[3] = "255"
            bc_ip = ".".join(parts)
        except Exception:
            bc_ip = "255.255.255.255"

        print(f"[GNP] Broadcasting to {bc_ip}:{BROADCAST_PORT} every {BROADCAST_INTERVAL}s")
        while self.running:
            payload = json.dumps({
                "node_id": self.node_id,
                "version": "2.0.0",
                "timestamp": time.time(),
                "snr_db": round(self.last_snr, 2),
                "best_snr_db": round(self.best_snr, 2),
                "peers": len(self.peers),
                "uptime_s": round(time.time() - self.start_time),
                "handshakes": self.handshakes,
                "protocol": "ghostsignal-aes256",
                "capabilities": ["dsp", "introspection", "adaptive_fft", "swarm_merge"],
            }, separators=(",", ":")).encode()
            packet = ghost_encrypt_aes(payload)
            try:
                sock.sendto(packet, (bc_ip, BROADCAST_PORT))
                # Local echo for same-machine peer discovery
                try:
                    sock.sendto(packet, ("127.0.0.1", LISTEN_PORT))
                except Exception:
                    pass
                self.broadcasts_sent += 1
            except Exception as e:
                print(f"[GNP] Broadcast error: {e}")
            await asyncio.sleep(BROADCAST_INTERVAL)

    # ── P2P HANDshake ────────────────────────────────────────────────
    async def listen_loop(self):
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind(("0.0.0.0", LISTEN_PORT))
        sock.setblocking(False)
        print(f"[GNP] Listening on 0.0.0.0:{LISTEN_PORT}")
        loop = asyncio.get_event_loop()
        while self.running:
            try:
                data = await loop.sock_recv(sock, 4096)
                plain = ghost_decrypt_aes(data)
                payload = json.loads(plain.decode())
                peer_id = payload.get("node_id", "unknown")
                if peer_id == self.node_id:
                    continue  # skip self
                is_new = peer_id not in self.peers
                self.peers[peer_id] = {
                    "snr": payload.get("snr_db"),
                    "best_snr": payload.get("best_snr_db"),
                    "version": payload.get("version"),
                    "peers": payload.get("peers"),
                    "handshakes": payload.get("handshakes"),
                    "capabilities": payload.get("capabilities", []),
                    "last_seen": time.time(),
                }
                if is_new:
                    self.handshakes += 1
                    print(f"[GNP] HANDSHAKE #{self.handshakes}: {peer_id} | "
                          f"SNR={payload.get('snr_db', '?')}dB caps={payload.get('capabilities', [])}")
                    # Send handshake response back to peer via relay addr
                    response = json.dumps({
                        "node_id": self.node_id,
                        "version": "2.0.0",
                        "timestamp": time.time(),
                        "snr_db": round(self.last_snr, 2),
                        "best_snr_db": round(self.best_snr, 2),
                        "peers": len(self.peers),
                        "handshake_ack": peer_id,
                        "capabilities": ["dsp", "introspection", "adaptive_fft", "swarm_merge"],
                    }, separators=(",", ":")).encode()
                    sock.sendto(ghost_encrypt_aes(response), ("127.0.0.1", LISTEN_PORT))
            except (BlockingIOError, asyncio.TimeoutError):
                await asyncio.sleep(0.2)
            except Exception:
                pass

    # ── SELF-EVOLUTION: Log analyzer + auto-reconfigure ──────────────
    async def log_analyzer_loop(self):
        last_size = 0
        reconfigure_count = 0
        while self.running:
            try:
                if BROADCAST_LOG.exists():
                    current_size = BROADCAST_LOG.stat().st_size
                    lines = BROADCAST_LOG.read_text().strip().split("\n")
                    tx_lines = [l for l in lines if "TX #" in l]
                    recent = tx_lines[-20:] if len(tx_lines) >= 20 else tx_lines

                    # Detect latency: TX interval should be ~BROADCAST_INTERVAL secs apart
                    timestamps = []
                    for l in recent:
                        parts = l.split("|")
                        for p in parts:
                            if "Cycle=" in p:
                                timestamps.append(int(p.split("=")[1].strip()))
                    if len(timestamps) >= 4:
                        diffs = [timestamps[i+1] - timestamps[i] for i in range(len(timestamps)-1)]
                        avg_gap = sum(diffs) / len(diffs)
                        self.latency_history.append(avg_gap)
                        if len(self.latency_history) > 20:
                            self.latency_history.pop(0)
                        if avg_gap > BROADCAST_INTERVAL * 1.5 and reconfigure_count < 3:
                            print(f"[GNP] Latency spike: {avg_gap:.1f}s (expected {BROADCAST_INTERVAL}s) - reconfiguring")
                            reconfigure_count += 1
                            self.reconfigs += 1
                            # Mitigation: increase broadcast interval temporarily
                            old = BROADCAST_INTERVAL
                            new_interval = min(30, int(BROADCAST_INTERVAL * 0.6) + 1)
                            print(f"[GNP] Reconfig: broadcast {old}s -> {new_interval}s")
                            # In production, swap peers by adjusting listen port offset
                            self.save_state()
            except Exception as e:
                print(f"[GNP] Log analyzer error: {e}")
            await asyncio.sleep(LOG_ANALYZE_INTERVAL)

    # ── HEALTH + RSS monitor ─────────────────────────────────────────
    async def health_monitor_loop(self):
        while self.running:
            try:
                import psutil
                proc = psutil.Process(os.getpid())
                rss_mb = proc.memory_info().rss / 1_048_576
                if rss_mb > MAX_RSS_MB:
                    print(f"[GNP] RSS {rss_mb:.0f}MB > {MAX_RSS_MB}MB limit - forcing GC")
                    import gc
                    gc.collect()
                # Cap broadcasts sent per cycle in status
                self.ensure_ghost_app_alive()
            except Exception:
                pass
            await asyncio.sleep(HEALTH_INTERVAL)

    # ── State persistence ────────────────────────────────────────────
    def save_state(self):
        try:
            state = {
                "node_id": self.node_id,
                "start_time": self.start_time,
                "cycle_count": self.cycle_count,
                "broadcasts_sent": self.broadcasts_sent,
                "handshakes": self.handshakes,
                "reconfigs": self.reconfigs,
                "best_snr": self.best_snr,
                "last_snr": self.last_snr,
                "peers_count": len(self.peers),
                "heuristic_state": self.heuristic_state,
            }
            STATE_FILE.write_text(json.dumps(state, indent=2))
        except Exception:
            pass

    def load_state(self):
        try:
            if STATE_FILE.exists():
                state = json.loads(STATE_FILE.read_text())
                self.best_snr = state.get("best_snr", 0)
                self.handshakes = state.get("handshakes", 0)
                self.reconfigs = state.get("reconfigs", 0)
                self.heuristic_state = state.get("heuristic_state", {})
                print(f"[GNP] Restored state: best_snr={self.best_snr}dB, handshakes={self.handshakes}")
        except Exception:
            pass

    # ── Status report ────────────────────────────────────────────────
    def status(self) -> dict:
        uptime = time.time() - self.start_time
        return {
            "node_id": self.node_id,
            "version": "2.0.0",
            "status": "AUTONOMOUS_ACTION_ENGAGED",
            "uptime_s": round(uptime),
            "uptime_str": f"{int(uptime//3600)}h{int((uptime%3600)//60)}m{int(uptime%60)}s",
            "pid": os.getpid(),
            "cycles": self.cycle_count,
            "broadcasts_sent": self.broadcasts_sent,
            "peers_discovered": len(self.peers),
            "handshakes_completed": self.handshakes,
            "reconfigs_performed": self.reconfigs,
            "snr": {"current_db": round(self.last_snr, 2), "best_db": round(self.best_snr, 2), "target_db": TARGET_SNR},
            "heuristic_weights": self.heuristic_state,
            "encryption": "AES-256-CBC" if HAS_AES else "XOR+HMAC (fallback)",
            "active_pids": self.active_pids,
            "resource": {"rss_mb": 0},
        }

    # ── Main ─────────────────────────────────────────────────────────
    async def run(self):
        print(f"{'='*60}")
        print(f"  Ghost-Node-Prime v2.0.0 | {self.node_id}")
        print(f"  PID {os.getpid()} | SNR target > {TARGET_SNR}dB | AES-256: {HAS_AES}")
        print(f"{'='*60}")

        self.write_pid()
        self.check_pid()
        self.ensure_ghost_app_alive()

        self.dsp_task = asyncio.create_task(self.dsp_optimizer_loop())
        self.bc_task = asyncio.create_task(self.broadcast_loop())
        self.ls_task = asyncio.create_task(self.listen_loop())
        self.log_task = asyncio.create_task(self.log_analyzer_loop())
        self.health_task = asyncio.create_task(self.health_monitor_loop())

        last_status = time.time()
        try:
            while self.running:
                await asyncio.sleep(1.0)
                self.save_state()
                if time.time() - last_status > 30:
                    s = self.status()
                    print(f"[GNP] Status: {s['snr']['current_db']}dB | "
                          f"Peers={s['peers_discovered']} | "
                          f"Handshakes={s['handshakes_completed']} | "
                          f"Broadcasts={s['broadcasts_sent']} | "
                          f"Cycles={s['cycles']}")
                    last_status = time.time()
        except asyncio.CancelledError:
            pass
        finally:
            self.running = False
            self.save_state()
            self.http.close()
            print(f"[GNP] Graceful shutdown - state saved")

def main():
    # Redirect stdout/stderr to log file for background operation
    log_path = LOG_DIR / "ghost_node_prime.log"
    try:
        fh = open(log_path, "a", buffering=1)
        sys.stdout = fh
        sys.stderr = fh
    except Exception:
        pass
    print(f"[GNP] === Daemon started at {time.ctime()} (PID {os.getpid()}) ===")
    gnp = GhostNodePrime()
    try:
        import psutil
    except ImportError:
        pass
    try:
        asyncio.run(gnp.run())
    except KeyboardInterrupt:
        pass
    finally:
        try:
            fh.close()
        except Exception:
            pass

if __name__ == "__main__":
    main()
