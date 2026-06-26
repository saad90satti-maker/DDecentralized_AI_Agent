"""
P2P Broadcast Daemon — Ghost-Infinite swarm heartbeat & peer discovery.

Broadcasts live ghost-core telemetry as GhostSignal-encrypted UDP packets.
Listens for peer broadcasts and registers discovered nodes.
"""
import asyncio
import json
import socket
import time
import httpx
import struct
import os
import sys
import argparse

DEFAULT_NODE_ID = os.environ.get("NODE_ID", "ghost-8880")
GHOST_CORE_URL = os.environ.get("GHOST_CORE_URL", "http://localhost:7861")
BROADCAST_PORT = int(os.environ.get("BROADCAST_PORT", "5005"))
LISTEN_PORT = int(os.environ.get("LISTEN_PORT", "5005"))
BROADCAST_INTERVAL = int(os.environ.get("BROADCAST_INTERVAL", "15"))

def parse_args():
    p = argparse.ArgumentParser(description="Ghost-Infinite P2P Broadcast Daemon")
    p.add_argument("--node-id", default=DEFAULT_NODE_ID, help="Node identifier (default: ghost-8880)")
    p.add_argument("--ghost-core-url", default=GHOST_CORE_URL, help="Ghost-Core HTTP endpoint")
    p.add_argument("--broadcast-port", type=int, default=BROADCAST_PORT)
    p.add_argument("--listen-port", type=int, default=LISTEN_PORT)
    p.add_argument("--interval", type=int, default=BROADCAST_INTERVAL, help="Broadcast interval in seconds")
    return p.parse_args()

ARGS = parse_args()
NODE_ID = ARGS.node_id
GHOST_CORE_URL = ARGS.ghost_core_url
BROADCAST_PORT = ARGS.broadcast_port
LISTEN_PORT = ARGS.listen_port
BROADCAST_INTERVAL = ARGS.interval

# Derive subnet broadcast from local IP
def get_subnet_broadcast():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        local_ip = s.getsockname()[0]
        s.close()
        parts = local_ip.split(".")
        parts[3] = "255"
        return ".".join(parts)
    except Exception:
        return "255.255.255.255"

BROADCAST_IP = os.environ.get("BROADCAST_IP") or get_subnet_broadcast()

# Proxy ghost_encrypt_packet from swarm_security
def ghost_encrypt_packet(payload: bytes, nonce: bytes = None) -> bytes:
    if nonce is None:
        nonce = os.urandom(16)
    secret = os.environ.get("SWARM_SECRET", "ghost-infinite-default").encode()
    cipher = bytes([p ^ s for p, s in zip(payload, (secret * (len(payload) // len(secret) + 1))[:len(payload)])])
    return nonce + cipher

def ghost_decrypt_packet(data: bytes) -> bytes:
    if len(data) < 16:
        return data
    nonce = data[:16]
    cipher = data[16:]
    secret = os.environ.get("SWARM_SECRET", "ghost-infinite-default").encode()
    return bytes([c ^ s for c, s in zip(cipher, (secret * (len(cipher) // len(secret) + 1))[:len(cipher)])])

class P2PBroadcastDaemon:
    def __init__(self):
        self.peers = {}
        self.broadcast_count = 0
        self.listen_count = 0
        self.last_telemetry = {}
        self.running = True
        self.http = httpx.Client(timeout=5.0)

    def fetch_telemetry(self):
        try:
            r = self.http.get(f"{GHOST_CORE_URL}/telemetry")
            if r.status_code == 200:
                self.last_telemetry = r.json()
                return self.last_telemetry
        except Exception:
            pass
        return self.last_telemetry

    def build_payload(self, telemetry):
        t = telemetry.get("telemetry", {})
        fft = t.get("fft", {})
        payload = {
            "node_id": NODE_ID,
            "timestamp": time.time(),
            "snr_db": round(fft.get("snr_after_db", 0), 2),
            "gate_db": fft.get("gate_threshold_db", 0),
            "window_exp": fft.get("window_exp", 1.0),
            "cycle": telemetry.get("cycle", 0),
            "peers": len(self.peers),
            "load": t.get("processes", {}).get("total", 0),
            "role": "MASTER",
            "protocol": "ghostsignal",
        }
        return json.dumps(payload, separators=(",", ":")).encode()

    async def broadcast_loop(self):
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        print(f"[P2P] Broadcasting on {BROADCAST_IP}:{BROADCAST_PORT} every {BROADCAST_INTERVAL}s")
        while self.running:
            telemetry = self.fetch_telemetry()
            plain = self.build_payload(telemetry)
            packet = ghost_encrypt_packet(plain)
            try:
                sock.sendto(packet, (BROADCAST_IP, BROADCAST_PORT))
                # Also echo locally so same-machine peers can discover each other
                try:
                    sock.sendto(packet, ("127.0.0.1", LISTEN_PORT))
                except Exception:
                    pass
                self.broadcast_count += 1
                snr = telemetry.get("telemetry", {}).get("fft", {}).get("snr_after_db", 0)
                print(f"[P2P] TX #{self.broadcast_count} | SNR={snr:.1f}dB | Cycle={telemetry.get('cycle', 0)} | "
                      f"Peers={len(self.peers)} | {len(packet)}B encrypted")
            except Exception as e:
                print(f"[P2P] TX error: {e}")
            await asyncio.sleep(BROADCAST_INTERVAL)

    async def listen_loop(self):
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind(("0.0.0.0", LISTEN_PORT))
        sock.setblocking(False)
        print(f"[P2P] Listening on 0.0.0.0:{LISTEN_PORT} for peer broadcasts")
        loop = asyncio.get_event_loop()
        while self.running:
            try:
                data, addr = await loop.sock_recv(sock, 4096)
                plain = ghost_decrypt_packet(data)
                payload = json.loads(plain.decode())
                peer_id = payload.get("node_id", "unknown")
                self.peers[peer_id] = {
                    "addr": f"{addr[0]}:{addr[1]}",
                    "snr": payload.get("snr_db"),
                    "cycle": payload.get("cycle"),
                    "role": payload.get("role"),
                    "last_seen": time.time(),
                }
                self.listen_count += 1
                print(f"[P2P] RX #{self.listen_count} | {peer_id} @ {addr[0]} | "
                      f"SNR={payload.get('snr_db', '?')}dB | Peers={len(self.peers)}")
            except (BlockingIOError, asyncio.CancelledError):
                await asyncio.sleep(0.2)
            except Exception as e:
                # Silently skip malformed packets
                pass

    async def run(self):
        print(f"[P2P] Ghost-Infinite Broadcast Daemon | Node {NODE_ID}")
        print(f"[P2P] Broadcast: {BROADCAST_IP}:{BROADCAST_PORT} | Listen: 0.0.0.0:{LISTEN_PORT}")
        tx_task = asyncio.create_task(self.broadcast_loop())
        rx_task = asyncio.create_task(self.listen_loop())
        try:
            await asyncio.gather(tx_task, rx_task)
        except asyncio.CancelledError:
            pass
        finally:
            self.running = False
            self.http.close()
            print("[P2P] Daemon shut down")

    def status(self):
        return {
            "node_id": NODE_ID,
            "broadcasts_sent": self.broadcast_count,
            "packets_received": self.listen_count,
            "peers_discovered": len(self.peers),
            "peers": {k: {kk: vv for kk, vv in v.items() if kk != "addr"} for k, v in self.peers.items()},
            "broadcast_addr": f"{BROADCAST_IP}:{BROADCAST_PORT}",
            "listen_port": LISTEN_PORT,
            "last_snr": self.last_telemetry.get("telemetry", {}).get("fft", {}).get("snr_after_db", 0),
        }

def main():
    import sys
    # Redirect stdout to file for background operation
    log_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "agent_logs", "p2p_broadcast.log")
    os.makedirs(os.path.dirname(log_path), exist_ok=True)
    fh = open(log_path, "a", buffering=1)
    sys.stdout = fh
    sys.stderr = fh
    print(f"[P2P] Daemon started at {time.ctime()}")
    daemon = P2PBroadcastDaemon()
    try:
        asyncio.run(daemon.run())
    except KeyboardInterrupt:
        pass
    finally:
        fh.close()

if __name__ == "__main__":
    main()
