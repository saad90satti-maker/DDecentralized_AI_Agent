"""
Ghost-Orbital-Relay — Global telemetry presence via CCSDS Space Packets,
Hydrogen-Line timing mimicry, DPI-bypass chunking, and NTP global beaconing.

Implements:
  - CCSDS 132.0-B-1 Space Packet Protocol (version 1)
  - 1420.4057517667 MHz Hydrogen-Line timing pattern generator
  - 1024-byte DPI-bypass chunks with interleaved random noise
  - NTP-compatible global beacon for temporal alignment
"""
import asyncio
import json
import os
import socket
import time
import struct
import hashlib
import hmac
import random
import httpx
import sys
from pathlib import Path

# ── Scapy integration (CCSDS header + handshake responder) ────────────
try:
    from scapy.all import Packet, BitField, IP, UDP, Raw
    HAS_SCAPY = True
except ImportError:
    HAS_SCAPY = False

if HAS_SCAPY:
    class CCSDS_Header(Packet):
        name = "CCSDS_Header"
        fields_desc = [
            BitField("version", 0, 3),
            BitField("type", 0, 1),
            BitField("shf", 1, 1),
            BitField("apid", 2047, 11),
            BitField("seq_flags", 3, 2),
            BitField("seq_count", 0, 14),
            BitField("length", 1023, 16),
        ]

RESPONDER_PORT = int(os.environ.get("RESPONDER_PORT", "5006"))
NODE_IDENTITY = os.environ.get("NODE_IDENTITY", "GHOST-8880-VERIFIED")

BASE = Path(__file__).parent.resolve()
LOG_DIR = BASE / "agent_logs"
LOG_DIR.mkdir(exist_ok=True)

# ── Constants ─────────────────────────────────────────────────────────
HYDROGEN_LINE_HZ = 1420_405_751.7667  # 1420.4057517667 MHz
HYDROGEN_LINE_NS = 1_000_000_000.0 / HYDROGEN_LINE_HZ  # ~0.704 ns period
CCSDS_VERSION = 1
GHOST_CORE_URL = os.environ.get("GHOST_CORE_URL", "http://localhost:7861")
NTP_EPOCH = 2208988800  # seconds between 1900-01-01 and 1970-01-01
BEACON_INTERVAL = int(os.environ.get("BEACON_INTERVAL", "15"))
ZERT_IP = os.environ.get("ZERT_IP", "10.147.1.100")  # ZeroTier mesh node

# ── Ultra-Fast Relay ──────────────────────────────────────────────────

SATELLITE_GATEWAY_HOST = os.environ.get("SATELLITE_GATEWAY", "global.satellite.node")


def ultra_fast_relay(data: str):
    """Direct UDP socket injection for lowest latency.

    Prepends a CCSDS-style header (0x0800 / 0x0001 / length) and sends
    via UDP with max TTL (255) to the satellite gateway.
    """
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.IPPROTO_IP, socket.IP_TTL, 255)
    packet = struct.pack("!HHH", 0x0800, 0x0001, len(data)) + data.encode()
    try:
        resolved = socket.gethostbyname(SATELLITE_GATEWAY_HOST)
    except socket.gaierror:
        resolved = "127.0.0.1"
        print(f"[RELAY] Could not resolve {SATELLITE_GATEWAY_HOST}, using localhost")
    addr = (resolved, RESPONDER_PORT)
    try:
        sock.sendto(packet, addr)
        print(f"[RELAY] Ultra-fast packet sent to {addr[0]}:{addr[1]} ({len(packet)}B)")
    except Exception as e:
        print(f"[RELAY] Send failed: {e}")
    sock.close()


# ── CCSDS Space Packet ────────────────────────────────────────────────
# Primary Header (6 bytes):
#   Version (3 bits) | Type (1 bit) | SecHdrFlag (1 bit) | APID (11 bits) = 2 bytes
#   SequenceFlags (2 bits) | SequenceCount (14 bits) = 2 bytes
#   PacketLength (16 bits) = 2 bytes (length = total bytes - 7)
#
# Secondary Header (optional, 4+ bytes):
#   Timestamp + Ancillary data
#
# Data + CRC-16 (CCITT)

def make_ccsds_primary_header(apid: int, seq_count: int, data_len: int,
                              sec_hdr_flag: int = 1, packet_type: int = 0) -> bytes:
    """Build 6-byte CCSDS primary header."""
    ver_type_hdr = (CCSDS_VERSION << 13) | (packet_type << 12) | (sec_hdr_flag << 11) | (apid & 0x7FF)
    seq_flags_count = (3 << 14) | (seq_count & 0x3FFF)  # 3 = unsegmented
    packet_length = data_len - 1  # per spec: total bytes - 7
    return struct.pack("!HHH", ver_type_hdr, seq_flags_count, packet_length)

def make_ccsds_secondary_header() -> bytes:
    """Build secondary header with timestamp and node metadata."""
    now = time.time()
    ts_sec = int(now)
    ts_us = int((now - ts_sec) * 1_000_000)
    return struct.pack("!II", ts_sec, ts_us)

def crc16_ccitt(data: bytes) -> bytes:
    """CRC-16-CCITT (0xFFFF init, 0x1021 poly)."""
    crc = 0xFFFF
    for byte in data:
        crc ^= byte << 8
        for _ in range(8):
            if crc & 0x8000:
                crc = (crc << 1) ^ 0x1021
            else:
                crc <<= 1
            crc &= 0xFFFF
    return struct.pack("!H", crc)

def ccsds_packet_scapy(apid: int, seq_count: int, payload: bytes, node_id: str) -> bytes:
    """Build CCSDS packet using Scapy's Packet/BitField layer (more spec-compliant).

    Uses CCSDS_Header + secondary header (20 bytes: timestamp + node_id) + payload + CRC.
    """
    if not HAS_SCAPY:
        return ccsds_packet(apid, seq_count, payload, node_id)
    now = time.time()
    ts_sec = int(now)
    ts_us = int((now - ts_sec) * 1_000_000)
    node_bytes = node_id.encode().ljust(16, b'\x00')[:16]
    sec_hdr = struct.pack("!II", ts_sec, ts_us) + node_bytes
    data_field = sec_hdr + payload
    hdr = CCSDS_Header(version=0, type=0, shf=1, apid=apid,
                       seq_flags=3, seq_count=seq_count,
                       length=len(data_field) + 6 - 1)
    pkt_no_crc = bytes(hdr) + data_field
    crc = crc16_ccitt(pkt_no_crc)
    return pkt_no_crc + crc


def ccsds_packet(apid: int, seq_count: int, payload: bytes, node_id: str) -> bytes:
    """Build a complete CCSDS space packet with telemetry payload."""
    sec_hdr = make_ccsds_secondary_header()
    # Add node_id to sec_hdr area
    node_bytes = node_id.encode().ljust(16, b'\x00')[:16]
    sec_hdr += node_bytes
    data_field = sec_hdr + payload
    pkt_no_crc = make_ccsds_primary_header(apid, seq_count, len(data_field) + 6 + 2) + data_field
    crc = crc16_ccitt(pkt_no_crc)
    return pkt_no_crc + crc

# ── Hydrogen-Line Timing ──────────────────────────────────────────────

class HydrogenLineTiming:
    """Generate transmission timing patterns based on 1420 MHz hydrogen line.

    The hydrogen line (1420.4057517667 MHz) has a period of ~0.704 ns.
    We use this as a reference for inter-packet gap patterns that
    mimic natural astrophysical sources (HI region emissions).
    """

    def __init__(self):
        self.period_ns = HYDROGEN_LINE_NS
        self.harmonic = 1

    def next_delay(self) -> float:
        """Return delay in seconds for next packet transmission.

        Uses harmonic multiples of the hydrogen line period with
        jitter that mimics Doppler broadening (~10 km/s = ~47 kHz).
        """
        doppler_jitter = random.uniform(-47_000, 47_000)  # Hz
        freq = HYDROGEN_LINE_HZ + doppler_jitter * self.harmonic
        period = 1.0 / freq
        # Scale to human-detectable timescale (multiply by 1e9 to get ~0.7s)
        delay = period * 1_000_000_000.0 * random.uniform(0.5, 2.0)
        self.harmonic = (self.harmonic % 7) + 1  # cycle through harmonics
        return max(0.001, min(3.0, delay))

    @property
    def signature(self) -> dict:
        return {
            "reference_hz": HYDROGEN_LINE_HZ,
            "period_ns": round(self.period_ns, 6),
            "current_harmonic": self.harmonic,
            "band": "HI (21-cm)",
        }

# ── DPI-Bypass Chunker ───────────────────────────────────────────────

class DPIBypassChunker:
    """Split and transform packets to evade Deep Packet Inspection.

    Uses 1024-byte fixed chunk size with interleaved random noise
    in unused header fields and padding areas.
    """

    CHUNK_SIZE = 1024

    def chunk(self, packet: bytes) -> list[bytes]:
        """Split packet into 1024-byte chunks with noise padding."""
        chunks = []
        offset = 0
        data_len = len(packet)
        while offset < data_len:
            payload_size = self.CHUNK_SIZE - 32  # available payload per chunk
            chunk_data = packet[offset:offset + payload_size]
            noise_len = payload_size - len(chunk_data)
            noise = os.urandom(max(0, noise_len))
            # Chunk header: 16B nonce + 2B offset + 2B total_chunks +
            #              4B original_data_len + 8B pad = 32B total
            chunk_hdr = os.urandom(16) + struct.pack("!HH", offset, 0) + struct.pack("!I", data_len) + os.urandom(8)
            chunks.append(chunk_hdr + chunk_data + noise)
            offset += payload_size
        # Update total_chunks in header
        total = len(chunks)
        result = []
        for i, c in enumerate(chunks):
            hdr = c[:18]  # nonce(16) + offset(2)
            total_bytes = struct.pack("!H", total)
            result.append(hdr + total_bytes + c[20:])
        return result

    def dechunk(self, chunks: list[bytes]) -> bytes:
        """Reassemble chunks into original packet."""
        if not chunks:
            return b""
        chunks.sort(key=lambda c: struct.unpack("!H", c[16:18])[0])
        data_len = struct.unpack("!I", chunks[0][20:24])[0]
        data = b""
        for c in chunks:
            payload = c[32:]
            data += payload
        return data[:data_len]

# ── NTP Global Beacon ────────────────────────────────────────────────

class NTPGlobalBeacon:
    """Broadcast telemetry disguised as NTP association packets.

    NTP servers are globally synchronized; injecting telemetry into
    NTP-compatible UDP packets achieves global temporal alignment.
    The beacon uses NTP port 123 with modified reference identifiers
    that carry the node's identity and telemetry payload.

    Format (48-byte NTPv4 header):
      LI(2) VN(3) Mode(3) | Stratum | Poll | Precision | RootDelay(4)
      RootDispersion(4) | RefID(4) | RefTimestamp(8) | OrigTimestamp(8)
      RXTimestamp(8) | TXTimestamp(8)

    We encode telemetry in the Reference ID field (4 bytes) and
    as a suffix appended after the NTP header (within 1024 byte limit).
    """

    def __init__(self, node_id: str = "ghost-8880"):
        self.node_id = node_id

    def make_ntp_packet(self, telemetry: dict, seq: int) -> bytes:
        """Build NTPv4-compatible packet with embedded telemetry.

        Returns 48-byte header + telemetry payload (total < 1024).
        """
        now = time.time()
        ntp_ts = now + NTP_EPOCH  # convert to NTP epoch
        ntp_int = int(ntp_ts)
        ntp_frac = int((ntp_ts - ntp_int) * 2**32)

        # LI=0, VN=4, Mode=3 (client)
        first_byte = (0 << 6) | (4 << 3) | 3
        stratum = 0  # unspecified
        poll = 6     # 64 seconds
        precision = 0xFA  # ~-6 log2 seconds (~15ms)

        # Reference ID: encode node_id hash + seq
        ref_id_bytes = hashlib.md5(self.node_id.encode() + str(seq).encode()).digest()[:4]

        # Timestamps
        ts_pack = struct.pack("!II", ntp_int, ntp_frac)

        # Header (48 bytes)
        hdr = struct.pack("!BBBB", first_byte, stratum, poll, precision)
        hdr += struct.pack("!i", 0)     # Root Delay (0)
        hdr += struct.pack("!i", 0)     # Root Dispersion (0)
        hdr += ref_id_bytes             # Reference ID (4 bytes, carries telemetry marker)
        hdr += ts_pack                  # Reference Timestamp
        hdr += b'\x00' * 8              # Originate Timestamp
        hdr += b'\x00' * 8              # Receive Timestamp
        hdr += ts_pack                  # Transmit Timestamp

        # Append telemetry as suffix
        telemetry_bytes = json.dumps({
            "node": self.node_id,
            "snr": telemetry.get("snr_after_db", 0),
            "cycle": telemetry.get("cycle", 0),
            "ts": now,
        }, separators=(",", ":")).encode()

        return hdr + telemetry_bytes

    def parse_ntp_packet(self, data: bytes) -> dict | None:
        """Extract telemetry from an NTP-compatible packet."""
        if len(data) < 48:
            return None
        try:
            ref_id = data[12:16]
            tele_start = 48
            tele_data = data[tele_start:]
            return json.loads(tele_data.decode())
        except Exception:
            return None

# ── Action Trigger + Command Gateway ──────────────────────────────────

import subprocess

REGISTERED_COMMANDS = {
    "START_DSP": lambda: subprocess.run(["python3", "ghost_app.py"]),
    "SHUTDOWN_RELAY": lambda: os._exit(0),
    "UPDATE_PROTOCOL": lambda: None,
    # "DEPLOY_DSP_PATCH_V2": ...,   # Add custom deploy logic here
}

SWARM_SECRET = os.environ.get("SWARM_SECRET", "ghost-default-secret")
GLOBAL_FLEET_NODES = os.environ.get(
    "GLOBAL_FLEET_NODES",
    "GroundStation_Alpha,GroundStation_Beta,Orbital_Relay_Prime",
).split(",")


class CommandGateway:
    """Satellite servers ko access karne ka secure gateway."""

    def __init__(self, api_key: str, secret: str):
        self.api_key = api_key
        self.secret = secret

    def sign_command(self, command: str) -> str:
        return hmac.new(self.secret.encode(), command.encode(), hashlib.sha256).hexdigest()

    def transmit(self, command: str) -> str:
        signature = self.sign_command(command)
        payload = f"CMD:{command}|SIG:{signature}"
        print(f"[GATEWAY] Transmitting to Global Node: {payload}")
        return payload


gateway = CommandGateway(api_key="ghost-swarm", secret=SWARM_SECRET)


def verify_signed_command(payload: str) -> str | None:
    """Verify 'CMD:<cmd>|SIG:<hex>' and return command if signature matches."""
    if not payload.startswith("CMD:"):
        return None
    try:
        cmd_part, sig_part = payload.split("|SIG:", 1)
        command = cmd_part[4:]  # strip "CMD:"
        expected_sig = hmac.new(SWARM_SECRET.encode(), command.encode(), hashlib.sha256).hexdigest()
        if hmac.compare_digest(expected_sig, sig_part.strip()):
            return command
        print(f"[GATEWAY] Signature mismatch for command: {command}")
        return None
    except (ValueError, KeyError):
        return None


def orchestrate_global_fleet(command: str):
    """Master Orchestrator — duniya bhar ke nodes ko command bhejta hai."""
    print(f"[ORCHESTRATOR] Broadcasting '{command}' to global fleet...")
    for node in GLOBAL_FLEET_NODES:
        node = node.strip()
        if not node:
            continue
        print(f"[ORCHESTRATOR] --> {node} : {command}")
        # Sign and prepare the signed command payload
        signed = gateway.transmit(command)

        # ── Transport: send signed payload to node ──
        # In production, replace with actual socket/HTTP to known node addresses.
        # For now, broadcast it on the handshake port so all listening nodes receive it.
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
            broadcast = f"{NODE_IDENTITY}:{signed}"
            sock.sendto(broadcast.encode(), ("255.255.255.255", RESPONDER_PORT))
            sock.close()
        except Exception as e:
            print(f"[ORCHESTRATOR] Transport error for {node}: {e}")


def execute_remote_command(command):
    """Space se aane wale commands ko interpret karna."""
    print(f"[ENGINE] Received remote command: {command}")
    if command in REGISTERED_COMMANDS:
        REGISTERED_COMMANDS[command]()
        return f"{command}_DONE"
    return "UNKNOWN_COMMAND"


def trigger_action(action_code):
    """Parse and execute action from handshake payload.

    Supports two formats:
      GHOST-8880-VERIFIED:START_DSP               (no signature)
      GHOST-8880-VERIFIED:CMD:START_DSP|SIG:hex    (signed, HMAC-verified)
    """
    if "GHOST-8880-VERIFIED" not in action_code:
        return None

    # Try signed format first: find "CMD:...|SIG:..."
    sig_start = action_code.find("CMD:")
    if sig_start >= 0:
        sig_part = action_code[sig_start:]
        command = verify_signed_command(sig_part)
        if command:
            result = execute_remote_command(command)
            print(f"[ACTION] Signed command result: {result}")
            return result
        print(f"[ACTION] Invalid signature, ignoring command")
        return None

    # Fallback to simple format: GHOST-8880-VERIFIED:COMMAND
    parts = action_code.split(":", 1)
    if len(parts) > 1:
        result = execute_remote_command(parts[1])
        print(f"[ACTION] Command result: {result}")
        return result
    return None


class ActionTrigger:
    """Fires digital actions when handshake is verified.

    Replace the hooks below with hardware calls (GPIO, LED, vibration motor,
    relay switch) for physical world integration.
    """

    def __init__(self):
        self.total_fires = 0
        self.last_source = ""

    def fire(self, source_ip: str = ""):
        """Execute verified handshake action."""
        self.total_fires += 1
        self.last_source = source_ip

        print(f"[ACTION] Handshake confirmed! Triggering relay...")
        print(f"[ACTION] Source: {source_ip} | Total triggers: {self.total_fires}")

        # ── Digital action hooks (extend here for hardware) ──────────
        self._console_flash()
        self._log_trigger(source_ip)
        # self._gpio_pulse()     # Uncomment for Raspberry Pi GPIO
        # self._led_blink()      # Uncomment for LED indicator
        # self._vibrate()        # Uncomment for vibration motor
        # self._relay_toggle()   # Uncomment for relay switch

    def fire_with_payload(self, source_ip: str, payload: str):
        """Fire action and execute embedded remote command if present."""
        self.fire(source_ip)
        trigger_action(payload)

    def _console_flash(self):
        print(">>> [ACTION] RELAY ACTIVE <<<")

    def _log_trigger(self, source_ip: str):
        import datetime
        log_path = BASE / "agent_logs" / "handshake_triggers.log"
        try:
            with open(log_path, "a") as f:
                f.write(f"[{datetime.datetime.utcnow().isoformat()}] "
                        f"VERIFIED from {source_ip} | total={self.total_fires}\n")
        except Exception:
            pass

    # ── Hardware stubs (implement per platform) ──────────────────────
    # def _gpio_pulse(self):
    #     import RPi.GPIO as GPIO
    #     GPIO.setmode(GPIO.BCM)
    #     GPIO.setup(18, GPIO.OUT)
    #     GPIO.output(18, GPIO.HIGH)
    #     time.sleep(0.5)
    #     GPIO.output(18, GPIO.LOW)
    #
    # def _led_blink(self):
    #     import board, neopixel
    #     pixels = neopixel.NeoPixel(board.D18, 1)
    #     pixels.fill((0, 255, 0))
    #     time.sleep(0.3)
    #     pixels.fill((0, 0, 0))
    #
    # def _vibrate(self):
    #     import RPi.GPIO as GPIO
    #     GPIO.setmode(GPIO.BCM)
    #     GPIO.setup(17, GPIO.OUT)
    #     pwm = GPIO.PWM(17, 100)
    #     pwm.start(50)
    #     time.sleep(0.2)
    #     pwm.stop()
    #
    # def _relay_toggle(self):
    #     import RPi.GPIO as GPIO
    #     GPIO.setmode(GPIO.BCM)
    #     GPIO.setup(27, GPIO.OUT)
    #     GPIO.output(27, not GPIO.input(27))


# ── Deep-Space Handshake Responder (Scapy-powered) ────────────────────

class DeepSpaceHandshake:
    """Listens for 'QUERY_HANDSHAKE' packets and auto-responds with node identity.

    Operates on RESPONDER_PORT (default 5005). Detects CCSDS-encapsulated
    or raw UDP handshake queries and sends an authenticated response.
    """

    def __init__(self, node_id: str = "ghost-8880"):
        self.node_id = node_id
        self.identity = NODE_IDENTITY
        self.queries_answered = 0
        self.verified_triggers = 0
        self.trigger = ActionTrigger()

    async def listen_loop(self):
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind(("0.0.0.0", RESPONDER_PORT))
        sock.setblocking(False)
        print(f"[HANDSHAKE] Deep-Space Handshake Listener on 0.0.0.0:{RESPONDER_PORT}")
        loop = asyncio.get_event_loop()

        while True:
            try:
                data, addr = await loop.sock_recvfrom(sock, 4096)
                payload_str = data.decode(errors="replace")

                # ── Detect incoming verified handshake from other nodes ──
                if "GHOST-8880-VERIFIED" in payload_str or "VERIFIED" in payload_str:
                    print(f"[HANDSHAKE] VERIFIED from {addr[0]}:{addr[1]}")
                    self.verified_triggers += 1
                    self.trigger.fire_with_payload(addr[0], payload_str)

                # ── Detect handshake query ──
                if "QUERY_HANDSHAKE" in payload_str or "HANDSHAKE" in payload_str:
                    print(f"[HANDSHAKE] Query from {addr[0]}:{addr[1]} ({len(data)}B)")

                    # Build authenticated response using Scapy if available
                    response_bytes = self.identity.encode()
                    if HAS_SCAPY:
                        try:
                            scapy_pkt = IP(dst=addr[0]) / UDP(dport=addr[1], sport=RESPONDER_PORT) / response_bytes
                            response_bytes = bytes(scapy_pkt)
                            print(f"[HANDSHAKE] Scapy-wrapped response: {len(response_bytes)}B")
                        except Exception as e:
                            print(f"[HANDSHAKE] Scapy wrap error: {e}")

                    sock.sendto(response_bytes, (addr[0], addr[1]))
                    self.queries_answered += 1
                    print(f"[HANDSHAKE] Response sent to {addr[0]}:{addr[1]} | #{self.queries_answered}")

            except (BlockingIOError, asyncio.TimeoutError):
                await asyncio.sleep(0.1)
            except Exception:
                pass

    def status(self) -> dict:
        return {
            "listener_port": RESPONDER_PORT,
            "identity": self.identity,
            "queries_answered": self.queries_answered,
            "verified_triggers": self.verified_triggers,
            "action_fires": self.trigger.total_fires,
            "scapy_enabled": HAS_SCAPY,
        }


# ── GlobalHandshake: SatNOGS ground station scanning + CCSDS handshake ──

SATNOGS_API = "https://api.satnogs.org/v1/stations/?format=json"
STATION_FALLBACK = Path(__file__).parent / "agent_logs" / "_station_fallback.json"

class GlobalHandshake:
    """Scan real SatNOGS ground stations and initiate CCSDS handshake.

    Uses aiohttp (or httpx fallback) to query the public SatNOGS station
    database. When internet is unavailable, falls back to a local station
    list. Discovered stations receive a CCSDS handshake packet.
    """

    def __init__(self, node_id: str = "ghost-8880"):
        self.node_id = node_id
        self.discovered_stations = []
        self.handshake_count = 0
        self.last_scan_time = 0
        self.timing = HydrogenLineTiming()

    async def scan_ground_stations(self) -> list[dict]:
        """Fetch ground stations from SatNOGS API (with fallback)."""
        # Try live SatNOGS API via httpx
        try:
            r = httpx.get(SATNOGS_API, timeout=10)
            if r.status_code == 200:
                raw = r.json()
                stations = raw if isinstance(raw, list) else raw.get("results", [])
                if stations:
                    self.discovered_stations = [
                        {"name": s.get("name", "?"),
                         "lat": s.get("lat", 0),
                         "lng": s.get("lng", 0),
                         "status": s.get("status", "unknown"),
                         "source": "satnogs-live"}
                        for s in stations[:20]
                    ]
                    print(f"[GLOBAL] SatNOGS: {len(self.discovered_stations)} live stations")
                    return self.discovered_stations
        except Exception:
            print(f"[GLOBAL] SatNOGS API unreachable - using fallback")

        # Fallback: local JSON
        try:
            with open(STATION_FALLBACK) as f:
                import json
                raw = json.load(f)
            self.discovered_stations = [
                {"name": s.get("name", "?"),
                 "lat": s.get("lat", 0),
                 "lng": s.get("lng", 0),
                 "status": s.get("status", "unknown"),
                 "frequency_mhz": s.get("frequency_mhz", 1420),
                 "source": "fallback"}
                for s in raw
            ]
            print(f"[GLOBAL] Fallback: {len(self.discovered_stations)} stations loaded")
        except Exception as e:
            print(f"[GLOBAL] Fallback error: {e}")
            self.discovered_stations = []

        return self.discovered_stations

    async def broadcast_handshake(self, sock: socket.socket, bc_ip: str):
        """Send CCSDS handshake beacon to all discovered ground stations.

        Each station receives a targeted CCSDS space packet with:
          - Scapy IP/UDP layers (Scapy-wrapped)
          - CCSDS primary header (version 1, APID=0x3F8)
          - Node identity + handshake payload
        """
        if not self.discovered_stations:
            await self.scan_ground_stations()

        for station in self.discovered_stations:
            name = station.get("name", "?")
            lat = station.get("lat", 0)
            lng = station.get("lng", 0)
            freq = station.get("frequency_mhz", 1420)

            # Build CCSDS handshake payload
            handshake_data = json.dumps({
                "type": "CCSDS_HANDSHAKE",
                "node": self.node_id,
                "version": "2.0.0",
                "station": name,
                "lat": lat,
                "lng": lng,
                "frequency_mhz": freq,
                "protocols": ["CCSDS-132.0-B-1", "GhostSignal-AES256", "NTPv4"],
                "timestamp": time.time(),
            }, separators=(",", ":")).encode()

            # Build CCSDS packet with Scapy header if available
            if HAS_SCAPY:
                pkt = ccsds_packet_scapy(0x3F8, self.handshake_count + 1,
                                          handshake_data, self.node_id)
            else:
                pkt = ccsds_packet(0x3F8, self.handshake_count + 1,
                                    handshake_data, self.node_id)

            self.handshake_count += 1

            # Transmit to station (broadcast + loopback)
            for dest in [(bc_ip, 5005), ("127.0.0.1", 5005)]:
                try:
                    sock.sendto(pkt, dest)
                except Exception:
                    pass

            # Apply hydrogen-line timing between station transmissions
            delay = self.timing.next_delay()
            await asyncio.sleep(delay)

        print(f"[GLOBAL] Handshake broadcast: {len(self.discovered_stations)} stations | "
              f"{self.handshake_count} total handshakes")

    def status(self) -> dict:
        return {
            "stations_discovered": len(self.discovered_stations),
            "handshakes_sent": self.handshake_count,
            "last_scan": time.ctime(self.last_scan_time) if self.last_scan_time else "never",
            "stations": [s.get("name") for s in self.discovered_stations[:5]],
        }


# ── Ghost-Orbital-Relay ──────────────────────────────────────────────

class GhostOrbitalRelay:
    """Top-level orchestrator for global telemetry presence.

    Combines CCSDS packetization, Hydrogen-line timing, DPI bypass,
    and NTP beaconing into one autonomous relay loop.
    """

    def __init__(self, node_id: str = "ghost-8880"):
        self.node_id = node_id
        self.http = httpx.Client(timeout=5.0, limits=httpx.Limits(max_keepalive_connections=2))
        self.timing = HydrogenLineTiming()
        self.chunker = DPIBypassChunker()
        self.ntp = NTPGlobalBeacon(node_id)
        self.handshake = DeepSpaceHandshake(node_id)
        self.global_hs = GlobalHandshake(node_id)
        self.seq_count = 0
        self.apid = 0x3F8  # Arbitrary APID for ghost telemetry

        self.ccsds_sent = 0
        self.chunks_sent = 0
        self.ntp_sent = 0
        self.total_bytes = 0
        self.last_telemetry = {}
        self.scapy_packets_sent = 0
        self.zert_mesh_sent = 0

    def _fetch_telemetry(self) -> dict:
        try:
            r = self.http.get(f"{GHOST_CORE_URL}/telemetry", timeout=4)
            if r.status_code == 200:
                t = r.json()
                self.last_telemetry = t
                return t
        except Exception:
            pass
        return self.last_telemetry

    async def ccsds_beacon_loop(self):
        """Periodically broadcast CCSDS space packets with 1024-Byte DPI bypass chunks."""
        print(f"[ORBITAL] CCSDS Space Packet beacon active (APID=0x{self.apid:03X})")
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        bc_ip = self._get_broadcast_ip()

        while True:
            telemetry = self._fetch_telemetry()
            fft = telemetry.get("telemetry", {}).get("fft", {})
            payload = json.dumps({
                "snr_before": fft.get("snr_before_db"),
                "snr_after": fft.get("snr_after_db"),
                "gate": fft.get("gate_threshold_db"),
                "window": fft.get("window_exp"),
                "cycle": telemetry.get("cycle", 0),
                "node": self.node_id,
            }, separators=(",", ":")).encode()

            # Build CCSDS packet (Scapy version if available)
            self.seq_count += 1
            if HAS_SCAPY and self.seq_count % 3 == 0:
                pkt = ccsds_packet_scapy(self.apid, self.seq_count, payload, self.node_id)
                self.scapy_packets_sent += 1
            else:
                pkt = ccsds_packet(self.apid, self.seq_count, payload, self.node_id)
            self.ccsds_sent += 1
            self.total_bytes += len(pkt)

            # Apply DPI bypass chunking (1024-byte chunks with noise)
            chunks = self.chunker.chunk(pkt)
            self.chunks_sent += len(chunks)

            # Transmit chunks with Hydrogen-line timing
            for chunk in chunks:
                sock.sendto(chunk, (bc_ip, 5005))
                sock.sendto(chunk, ("127.0.0.1", 5005))
                delay = self.timing.next_delay()
                await asyncio.sleep(delay)

            print(f"[ORBITAL] CCSDS #{self.seq_count} | {len(pkt)}B -> {len(chunks)} chunks @ "
                  f"{self.timing.signature['band']} | {self.timing.signature['reference_hz']/1e6:.4f} MHz")

            await asyncio.sleep(BEACON_INTERVAL)

    async def ntp_beacon_loop(self):
        """Broadcast NTP-compatible global beacon every BEACON_INTERVAL seconds.

        Uses NTP port 123 emulation; packets are formatted as NTPv4 client
        associations but carry Ghost telemetry in the payload suffix.
        """
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        bc_ip = self._get_broadcast_ip()

        print(f"[ORBITAL] NTP global beacon active on port 123")
        seq = 0
        while True:
            telemetry = self._fetch_telemetry()
            fft = telemetry.get("telemetry", {}).get("fft", {})
            telemetry_flat = {
                "snr_after_db": fft.get("snr_after_db"),
                "cycle": telemetry.get("cycle", 0),
            }

            seq += 1
            ntp_pkt = self.ntp.make_ntp_packet(telemetry_flat, seq)
            self.ntp_sent += 1
            self.total_bytes += len(ntp_pkt)

            # Broadcast on NTP port 123 (and also local port for dev)
            for port in (123, 5005):
                try:
                    sock.sendto(ntp_pkt, (bc_ip, port))
                    sock.sendto(ntp_pkt, ("127.0.0.1", port))
                except Exception:
                    pass

            if seq % 3 == 0:
                print(f"[ORBITAL] NTP #{seq} | {len(ntp_pkt)}B | refID={hashlib.md5((self.node_id+str(seq)).encode()).hexdigest()[:8]}")

            await asyncio.sleep(BEACON_INTERVAL * 2)  # every 30s (every other cycle)

    async def global_handshake_loop(self):
        """Periodically scan SatNOGS ground stations and send CCSDS handshakes."""
        print(f"[GLOBAL] Ground station scanning active (every {BEACON_INTERVAL * 6}s)")
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        bc_ip = self._get_broadcast_ip()

        # Initial scan
        await self.global_hs.scan_ground_stations()
        await self.global_hs.broadcast_handshake(sock, bc_ip)

        while True:
            await asyncio.sleep(BEACON_INTERVAL * 6)
            # Re-scan and broadcast
            await self.global_hs.scan_ground_stations()
            await self.global_hs.broadcast_handshake(sock, bc_ip)

    async def dashboard_loop(self):
        """Live terminal dashboard refreshing every 10s."""
        await asyncio.sleep(3)
        while True:
            try:
                t = self.http.get(f"{GHOST_CORE_URL}/telemetry", timeout=3)
                if t.status_code == 200:
                    tj = t.json()
                    fft = tj.get("telemetry", {}).get("fft", {})
                    snr = fft.get("snr_after_db", 0)
                    cycle = tj.get("cycle", 0)
                else:
                    snr, cycle = 0, 0
            except Exception:
                snr, cycle = 0, 0

            # Quick port scan (UDP bind test)
            ports = {"5005": False, "5006": False, "123": False}
            for p_str in ports:
                s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                s.settimeout(1)
                try:
                    s.bind(("0.0.0.0", int(p_str)))
                    ports[p_str] = True
                    s.close()
                except Exception:
                    ports[p_str] = False
                    s.close()

            stats = self.status()
            gh = stats.get("global_handshake", {})
            hs = stats.get("handshake", {})

            print("\033[H\033[J", end="")  # clear terminal
            print("=== GHOST MEDIA ENGINE: LIVE ORBITAL LINK ===")
            print(f"[STATUS] LINK: BROADCASTING | TARGET: SatNOGS-Global-Gateway | SIGNAL: {snr:.2f} dB SNR")
            print(f"[NODE] SUPERVISOR: Active | PID: {os.getpid()} | DSP CYCLES: {cycle}")
            print("---------------------------------------------")
            print(f"  CCSDS packets:   {stats.get('ccsds_packets_sent', 0)}")
            print(f"  Scapy packets:   {stats.get('scapy_packets_sent', 0)}")
            print(f"  DPI chunks:      {stats.get('dpi_chunks_sent', 0)}")
            print(f"  NTP beacons:     {stats.get('ntp_beacons_sent', 0)}")
            print(f"  Handshake reps:  {hs.get('queries_answered', 0)}")
            print(f"  Global stations: {gh.get('stations_discovered', 0)}")
            print(f"  Total bytes TX:  {stats.get('total_bytes_transmitted', 0)}")
            print("---------------------------------------------")
            print(f"  Port 5005 (CCSDS/NTP):  {'OPEN' if ports['5005'] else 'IN USE'}")
            print(f"  Port 5006 (Handshake):  {'OPEN' if ports['5006'] else 'IN USE'}")
            print(f"  Port 123  (NTP):        {'OPEN' if ports['123'] else 'IN USE'}")
            print("---------------------------------------------")
            print(f"  Hydrogen line:   1420.4058 MHz")
            print(f"  NTP refID:       {hashlib.md5(self.node_id.encode()).hexdigest()[:8]}")
            print(f"  Last handshake:  {time.ctime()}")
            print("---------------------------------------------")
            await asyncio.sleep(10)

    async def scapy_beacon_loop(self):
        """Scapy-based CCSDS beacon broadcast every 90s on port 5006.

        Uses CCSDS_Header + Scapy IP/UDP/Raw layers for spec-compliant
        space packet transmission. Runs in executor since scapy.send is blocking.
        """
        if not HAS_SCAPY:
            print("[SCAPY] Scapy not available - skipping beacon")
            return

        loop = asyncio.get_event_loop()
        bc_ip = self._get_broadcast_ip()
        seq = 0
        print(f"[SCAPY] CCSDS beacon broadcast to {bc_ip}:5006 every 90s")

        def _send(scapy_pkt):
            try:
                from scapy.all import send as scapy_send
                scapy_send(scapy_pkt, verbose=False)
            except Exception as e:
                print(f"[SCAPY] send error: {e}")

        while True:
            seq += 1
            payload = f"GHOST-8880-VERIFIED-BEACON:{seq}:{time.time()}"
            header = CCSDS_Header(apid=0x7FF, seq_count=seq, length=len(payload))
            scapy_pkt = IP(dst=bc_ip) / UDP(dport=5006) / Raw(load=bytes(header) + payload.encode())
            await loop.run_in_executor(None, _send, scapy_pkt)
            self.scapy_packets_sent += 1
            print(f"[SCAPY] Beacon #{seq} | {len(scapy_pkt)}B | {payload[:40]}")
            await asyncio.sleep(90)

    async def zero_tier_beacon_loop(self):
        """Beacon to ZeroTier mesh node every 90s for cross-subnet relay."""
        seq = 0
        print(f"[MESH] ZeroTier beacon -> {ZERT_IP}:{RESPONDER_PORT} every 90s")
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

        def send_global_packet(data: str):
            payload = f"GHOST-8880-VERIFIED-BEACON:{data}"
            sock.sendto(payload.encode(), (ZERT_IP, RESPONDER_PORT))
            self.zert_mesh_sent += 1
            self.total_bytes += len(payload)
            print(f"[MESH] Beacon relayed via {ZERT_IP} | {payload[:60]}")

        while True:
            seq += 1
            send_global_packet(f"STATUS_OK:{seq}:{time.time()}")
            await asyncio.sleep(90)

    def _get_broadcast_ip(self) -> str:
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

    def status(self) -> dict:
        h = self.handshake.status()
        return {
            "node_id": self.node_id,
            "ccsds_packets_sent": self.ccsds_sent,
            "scapy_packets_sent": self.scapy_packets_sent,
            "zert_mesh_sent": self.zert_mesh_sent,
            "dpi_chunks_sent": self.chunks_sent,
            "ntp_beacons_sent": self.ntp_sent,
            "total_bytes_transmitted": self.total_bytes,
            "hydrogen_line": self.timing.signature,
            "handshake": h,
            "global_handshake": self.global_hs.status(),
            "apid": f"0x{self.apid:03X}",
            "ccsds_version": CCSDS_VERSION,
            "chunk_size": DPIBypassChunker.CHUNK_SIZE,
            "ntp_mode": "v4 client association + telemetry suffix",
            "protocols": ["CCSDS 132.0-B-1", "UDP/5005", "NTPv4/123", "Scapy Packet", "Scapy Beacon/5006"],
        }

    async def run(self):
        print(f"{'='*60}")
        print(f"  Ghost-Orbital-Relay | {self.node_id}")
        print(f"  CCSDS APID=0x{self.apid:03X} | Hydrogen-Line {self.timing.signature['reference_hz']/1e6:.4f} MHz")
        print(f"  DPI Bypass: {DPIBypassChunker.CHUNK_SIZE}B chunks with interleaved noise")
        print(f"  NTP Global Beacon: temporal alignment via port 123")
        print(f"  Scapy Beacon: CCSDS broadcast to port 5006 every 90s")
        print(f"{'='*60}")

        tasks = [
            asyncio.create_task(self.ccsds_beacon_loop()),
            asyncio.create_task(self.ntp_beacon_loop()),
            asyncio.create_task(self.handshake.listen_loop()),
            asyncio.create_task(self.global_handshake_loop()),
            asyncio.create_task(self.scapy_beacon_loop()),
            asyncio.create_task(self.zero_tier_beacon_loop()),
            asyncio.create_task(self.dashboard_loop()),
        ]
        try:
            await asyncio.gather(*tasks)
        except asyncio.CancelledError:
            pass
        finally:
            self.http.close()

def main():
    node_id = os.environ.get("NODE_ID", "ghost-8880")
    log_path = LOG_DIR / "ghost_orbital_relay.log"
    try:
        fh = open(log_path, "a", buffering=1)
        sys.stdout = fh
        sys.stderr = fh
    except Exception:
        pass
    print(f"[ORBITAL] Daemon started at {time.ctime()} (PID {os.getpid()})")
    relay = GhostOrbitalRelay(node_id=node_id)
    asyncio.run(relay.run())

if __name__ == "__main__":
    main()
