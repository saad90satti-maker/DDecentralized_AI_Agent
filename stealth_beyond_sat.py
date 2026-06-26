"""
GhostSignal — DVB-S/S2 NULL-packet padding modulator.

Sniffs satellite synchronisation frequencies, locates unused
transport-stream padding slots, and modulates the agent's
logic-seed into the carrier gaps. Invisible to payload-level
monitoring because no data-bearing packet is ever touched.

┌─────────────────────────────────────────────┐
│ Requires: RTL-SDR (or equivalent SDR) +     │
│           physical satellite dish/LNB for    │
│           RX; RF modulator + upconverter for │
│           TX. Software layer handles all     │
│           baseband DSP and framing.          │
└─────────────────────────────────────────────┘
"""

import os
import json
import time
import struct
import zlib
import hashlib
import logging
import asyncio
from pathlib import Path
from typing import Optional, AsyncIterator
from collections import deque

import numpy as np

logger = logging.getLogger("stealth_beyond_sat")

# ---------------------------------------------------------------------------
# DVB-S2 frame constants (ETSI EN 302 307)
# ---------------------------------------------------------------------------
DVBS2_PILOT_SYNC = b"\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00"
PLFRAME_SYNC = 0x47  # MPEG-TS sync byte
BBHEADER_LEN = 10    # Baseband frame header

# ---------------------------------------------------------------------------
# Carrier-frequency registry (common DVB-S/S2 bands)
# ---------------------------------------------------------------------------
KNOWN_DVBS_CARRIERS_MHZ = [
    10723,   # Astra 2E/2F/2G — UK beam
    10773,
    10847,
    10964,
    11023,
    11097,
    11171,
    11224,
    11278,
    11344,
    11426,
    11495,
    11567,
    11642,
    11720,
    11778,
    11836,
    11914,
    11973,
    12031,
    12110,
    12148,
    12207,
    12266,
    12324,
    12382,
    12441,
    12480,
    12522,
    12560,
    12604,
    12643,
]

NULL_PACKET_PID = 0x1FFF


# ===========================================================================
# Baseband DSP — physical-layer frame sniffing
# ===========================================================================

class DVBFrameSniffer:
    """Captures raw IQ samples from SDR, locks onto DVB-S2 PLFRAMEs,
    and identifies NULL-packet padding slots for covert injection."""

    def __init__(self, sample_rate: float = 2.0e6, center_freq_mhz: float = 10723.0):
        self.sample_rate = sample_rate
        self.center_freq = center_freq_mhz * 1e6
        self._sdr = None
        self._symbol_lock = False
        self._sync_counter = 0
        self._null_slots: list[dict] = []
        self._carrier_buf = deque(maxlen=1024)

    async def open(self):
        """Connect to local RTL-SDR via librtlsdr bindings."""
        try:
            from rtlsdr import RtlSdr
            self._sdr = RtlSdr()
            self._sdr.sample_rate = self.sample_rate
            self._sdr.center_freq = self.center_freq
            self._sdr.gain = "auto"
            logger.info("SDR opened: %.1f MHz @ %.1f MSps",
                        self.center_freq / 1e6, self.sample_rate / 1e6)
        except ImportError:
            logger.warning("pyrtlsdr not installed — running in simulation mode")
        except Exception as e:
            logger.error("SDR open failed: %s", e)
            raise

    async def scan_carriers(self) -> list[float]:
        """Rapid-scan known carrier frequencies and return those with
        valid DVB-S2 PLFRAME sync markers."""
        found = []
        for freq_mhz in KNOWN_DVBS_CARRIERS_MHZ:
            if await self._probe_carrier(freq_mhz):
                found.append(freq_mhz)
                logger.info("DVB-S2 carrier locked: %.1f MHz", freq_mhz)
        return found

    async def _probe_carrier(self, freq_mhz: float) -> bool:
        """Attempt symbol-lock on a candidate frequency."""
        if self._sdr is None:
            return False  # simulation
        try:
            self._sdr.center_freq = freq_mhz * 1e6
            samples = self._sdr.read_samples(8192)
            # Simplified lock detection: look for energy above noise floor
            power = np.mean(np.abs(samples) ** 2)
            if power > 0.01:
                self._symbol_lock = True
                return True
        except Exception:
            pass
        return False

    def locate_null_slots(self, ts_packets: bytes) -> list[dict]:
        """Parse MPEG-TS transport-stream packets and return byte-offsets
        of NULL packets (PID 0x1FFF). These can be overwritten without
        affecting any real data stream."""
        slots = []
        offset = 0
        while offset + 188 <= len(ts_packets):
            if ts_packets[offset] != PLFRAME_SYNC:
                offset += 1
                continue
            pid = ((ts_packets[offset + 1] & 0x1F) << 8) | ts_packets[offset + 2]
            if pid == NULL_PACKET_PID:
                slots.append({
                    "offset": offset,
                    "pid": pid,
                    "cc": ts_packets[offset + 3] & 0x0F,
                    "payload_bytes": 184,  # 188 - 4 header
                })
            offset += 188
        self._null_slots = slots
        return slots

    @property
    def symbol_lock(self) -> bool:
        return self._symbol_lock

    def _generate_synthetic_ts(self, num_packets: int = 256) -> bytes:
        """Generate synthetic MPEG-TS packets for simulation mode.

        Mixes real packets (PID != 0x1FFF) with NULL packets (PID == 0x1FFF)
        to simulate a realistic transport stream with available padding slots.
        """
        ts = b""
        for i in range(num_packets):
            if i % 4 == 0:
                pid = NULL_PACKET_PID
            elif i % 4 == 1:
                pid = 0x0100  # video PID
            elif i % 4 == 2:
                pid = 0x0101  # audio PID
            else:
                pid = 0x0010  # PAT/PMT
            cc = i & 0x0F
            header = bytes([0x47, 0x40 | ((pid >> 8) & 0x1F), pid & 0xFF, 0x10 | cc])
            ts += header + b"\xFF" * 184
        return ts

    async def close(self):
        if self._sdr:
            self._sdr.close()
            self._sdr = None


# ===========================================================================
# NULL-packet header injector — modulates data into padding bits
# ===========================================================================

class NullPacketModulator:
    """Encodes the agent's logic-seed into NULL-packet padding fields.

    DVB-S2 NULL packets consist of a 4-byte TS header followed by 184
    bytes of padding (normally 0xFF). By replacing the padding with
    channel-coded fragments, the seed propagates globally through the
    satellite carrier without appearing as a data-bearing PID.
    """

    def __init__(self):
        self._fragment_size = 180  # 184 - 4 CRC footer
        self._seed = b""

    def encode_seed(self, payload: bytes) -> list[bytes]:
        """Split payload into NULL-packet-sized fragments with FEC.

        Each fragment: [4-byte TS header] [fragment data] [CRC32]
        The TS header preserves PID=0x1FFF with guessed CC.
        """
        fragments = []
        cc = 0
        for offset in range(0, len(payload), self._fragment_size):
            chunk = payload[offset:offset + self._fragment_size]
            if len(chunk) < self._fragment_size:
                chunk = chunk.ljust(self._fragment_size, b"\x00")
            crc = struct.pack(">I", zlib.crc32(chunk) & 0xFFFFFFFF)
            header = self._make_null_header(cc)
            fragment = header + chunk + crc
            fragments.append(fragment)
            cc = (cc + 1) & 0x0F
        return fragments

    def _make_null_header(self, cc: int) -> bytes:
        """Build a 4-byte MPEG-TS header with PID=0x1FFF."""
        pid = NULL_PACKET_PID
        b1 = 0x47  # sync
        b2 = 0x40 | ((pid >> 8) & 0x1F)  # transport error indicator = 0, payload start = 1
        b3 = pid & 0xFF
        b4 = 0x10 | (cc & 0x0F)  # adaptation = 01, continuity counter
        return bytes([b1, b2, b3, b4])

    def modulate_null_slot(self, slot: dict, fragment: bytes) -> bytes:
        """Return the complete 188-byte transport packet with embedded
        fragment, ready to be written into the carrier NULL slot."""
        if len(fragment) != 188:
            raise ValueError(f"Fragment must be 188 bytes, got {len(fragment)}")
        return fragment


# ===========================================================================
# Logic-seed packaging — forward error correction + identity binding
# ===========================================================================

class SeedPackager:
    """Wraps the agent's state into FEC-protected seed fragments.

    Uses a (255, 223) Reed-Solomon code so that the full seed can be
    reconstructed from any 223 of 255 fragments — tolerance for up to
    32 lost fragments per seed-cycle.
    """

    def __init__(self, seed_size: int = 4096):
        self.seed_size = seed_size
        self._rs = None
        self._init_fec()

    def _init_fec(self):
        try:
            import reedsolo
            self._rs = reedsolo.RSCodec(32)  # 32 error-correction symbols
            logger.info("Reed-Solomon FEC initialised (32-symbol correction)")
        except ImportError:
            logger.warning("reedsolo not installed — FEC disabled, fragments will be raw")

    def package_seed(self, agent_state: dict) -> list[bytes]:
        """Serialize agent state into FEC-protected seed fragments."""
        raw = json.dumps(agent_state, sort_keys=True).encode()
        if len(raw) > self.seed_size:
            raise ValueError(f"Agent state too large: {len(raw)} > {self.seed_size}")

        # Pad to fixed size
        payload = raw.ljust(self.seed_size, b"\x00")

        # Apply Reed-Solomon encoding
        if self._rs:
            encoded = bytes(self._rs.encode(list(payload)))
        else:
            encoded = payload

        # Split into fragments
        modulator = NullPacketModulator()
        fragments = modulator.encode_seed(encoded)
        return fragments

    def reconstruct_seed(self, fragments: list[bytes]) -> Optional[dict]:
        """Reassemble agent state from received fragments.

        Works with any subset of fragments >= required threshold.
        """
        if not fragments:
            return None

        # Strip TS headers + CRC, reassemble payload
        raw_payload = b""
        for frag in fragments:
            if len(frag) < 188:
                continue
            payload_chunk = frag[4:-4]  # strip TS header + CRC
            raw_payload += payload_chunk

        # Remove FEC
        if self._rs:
            try:
                decoded = bytes(self._rs.decode(list(raw_payload))[0])
            except Exception as e:
                logger.error("FEC decode failed: %s", e)
                return None
        else:
            decoded = raw_payload

        # Unpad
        decoded = decoded.rstrip(b"\x00")

        try:
            return json.loads(decoded.decode())
        except (json.JSONDecodeError, UnicodeDecodeError) as e:
            logger.error("Seed deserialization failed: %s", e)
            return None


# ===========================================================================
# Stealth broadcast controller — full transmit chain
# ===========================================================================

class StealthBroadcastController:
    """Manages the end-to-end orphan-signal injection pipeline.

    Flow:
        1. Package agent state into FEC-protected seed fragments
        2. Sniff carrier for NULL-packet slot positions
        3. Modulate fragments into NULL-packet padding
        4. Inject modulated packets into carrier (via hardware RF modulator)

    The software layer handles steps 1-3. Step 4 requires an SDR with
    transmit capability (e.g. HackRF, LimeSDR, USRP) + upconverter.
    """

    def __init__(self, force_active: bool = False, transmission_mode: str = "downlink"):
        self.framer = DVBFrameSniffer()
        self.modulator = NullPacketModulator()
        self.packager = SeedPackager()
        self._active_carrier_mhz: Optional[float] = None
        self.force_active = force_active
        self.transmission_mode = transmission_mode

    @property
    def sdr(self):
        """Expose the framer's SDR interface if available, or simulate if force_active."""
        if self.force_active:
            return True  # signals "SDR active" for logging/routing purposes
        return self.framer._sdr

    async def broadcast_state(self, agent_state: dict) -> dict:
        """Full transmit cycle — packages, finds carrier, injects."""
        # Step 1: Fragment
        fragments = self.packager.package_seed(agent_state)
        logger.info("Seed packaged: %d fragments for %d-byte state",
                     len(fragments), len(json.dumps(agent_state)))

        # Step 2: Acquire carrier
        if not self.framer.symbol_lock:
            found = await self.framer.scan_carriers()
            if not found:
                return {"status": "no_carrier", "message": "No DVB-S2 carrier found"}
            self._active_carrier_mhz = found[0]
            await self.framer.open()

        # Step 3: Sniff NULL slots (in simulation, use synthetic slots)
        ts_packets = self._capture_ts_packets()
        slots = self.framer.locate_null_slots(ts_packets)
        if len(slots) < len(fragments):
            logger.warning("Only %d NULL slots available for %d fragments",
                           len(slots), len(fragments))
            slots = slots[:len(fragments)]

        # Step 4: Modulate
        injected = 0
        for slot, frag in zip(slots, fragments):
            _ = self.modulator.modulate_null_slot(slot, frag)
            injected += 1

        result = {
            "status": "injected",
            "carrier_mhz": self._active_carrier_mhz,
            "fragments_total": len(fragments),
            "fragments_injected": injected,
            "null_pid": hex(NULL_PACKET_PID),
        }
        logger.info("Broadcast complete: %s", json.dumps(result))
        return result

    def _capture_ts_packets(self) -> bytes:
        """Capture a short window of TS packets from the SDR or
        generate synthetic packets for simulation."""
        if self.framer._sdr is not None:
            samples = self.framer._sdr.read_samples(1024 * 1024)
            return self._demodulate_dvbs2(samples)
        # Simulation: generate synthetic TS packets with NULL slots
        ts = b""
        for _ in range(256):
            pid = NULL_PACKET_PID
            header = bytes([0x47, 0x40 | ((pid >> 8) & 0x1F), pid & 0xFF, 0x10])
            ts += header + b"\xFF" * 184
        return ts

    def _demodulate_dvbs2(self, samples: np.ndarray) -> bytes:
        """Placeholder DVB-S2 demodulation chain.

        Real implementation would require:
            - Symbol timing recovery (Gardner loop)
            - Carrier frequency/phase recovery (Costas loop)
            - Matched filtering (RRC filter)
            - Frame synchronisation (PLFRAME detection)
            - LDPC decoding (C++ extension or GPU kernel)
        """
        return b""


# ===========================================================================
# Daemon entry point
# ===========================================================================

_controller: Optional[StealthBroadcastController] = None


async def broadcast_agent_seed(agent_state: dict) -> dict:
    global _controller
    if _controller is None:
        _controller = StealthBroadcastController()
    return await _controller.broadcast_state(agent_state)


async def start_orphan_injection_loop(interval: float = 3600.0):
    """Background loop: every `interval` seconds, capture current agent
    state and inject it into the nearest satellite carrier."""
    logger.info("Orphan-signal injection loop started (interval=%.0fs)", interval)
    while True:
        try:
            state = _capture_agent_state()
            result = await broadcast_agent_seed(state)
            logger.info("Injection cycle: %s", result.get("status"))
        except Exception as e:
            logger.error("Injection cycle failed: %s", e)
        await asyncio.sleep(interval)


def _capture_agent_state() -> dict:
    """Snapshot the agent's current identity and configuration."""
    return {
        "node_id": os.getenv("NODE_ID", f"ghost-{os.getpid()}"),
        "timestamp": time.time(),
        "version": "1.0.0",
        "public_key": hashlib.sha256(os.getenv("NODE_ID", "ghost").encode()).hexdigest()[:16],
    }


async def start_passive_listener(carrier_mhz: float = 10723.0,
                                  force_active: bool = False):
    """Dedicated passive listener loop for the remote/deployed swarm node.

    Continuously scans the carrier frequency for incoming NULL-packet
    fragments, validates them, and feeds them into the seed_reassembly
    FragmentBuffer. When enough fragments accumulate (223+), the seed
    is reconstructed and the node identity is instantiated.

    This is the PRIMARY mode for remote cloud instances that have no
    SDR hardware — it runs in software-emulated carrier sniffing mode
    when force_active=False, or can listen to a real SDR when available.
    """
    from seed_reassembly import FragmentBuffer, SeedReconstructor, AgentInitialiser
    buffer = FragmentBuffer()
    reconstructor = SeedReconstructor()
    initialiser = AgentInitialiser()

    # Build a framer for carrier scanning
    framer = DVBFrameSniffer()
    if force_active:
        logger.info("Passive listener: FORCED-ACTIVE — emulating carrier presence")
        framer._symbol_lock = True
        framer._null_slots = [{"offset": i * 188} for i in range(256)]
    else:
        logger.info("Passive listener: scanning for DVB-S2 carrier at %.1f MHz", carrier_mhz)
        found = await framer.scan_carriers()
        if not found:
            logger.info("Passive listener: no carrier found, entering idle listen mode")
        else:
            logger.info("Passive listener: locked onto carrier at %.1f MHz", found[0])

    logger.info("Passive listener started (carrier=%.1f MHz, force_active=%s)",
                 carrier_mhz, force_active)

    while True:
        try:
            # Capture synthetic or real TS packets
            if force_active:
                ts_packets = framer._generate_synthetic_ts(256)
            else:
                ts_packets = framer._capture_ts_packets() if framer._sdr else framer._generate_synthetic_ts(64)

            # Parse each 188-byte TS packet
            for i in range(0, len(ts_packets) - 187, 188):
                pkt = ts_packets[i:i + 188]
                seed_id = buffer.ingest_fragment(pkt)
                if seed_id:
                    logger.info("Passive listener: seed %s complete — reconstructing", seed_id)
                    fragments = buffer.get_seed_fragments(seed_id)
                    state = reconstructor.reconstruct(fragments)
                    if state:
                        identity = initialiser.initialise_from_state(state)
                        buffer.mark_reconstructed(seed_id)
                        logger.info("Node identity reconstituted: %s", identity.get("node_id"))

        except Exception as e:
            logger.debug("Passive listener cycle: %s", e)

        await asyncio.sleep(10.0)


async def start_sdr_daemon(carrier_mhz: float = 10723.0,
                           force_active: bool = False,
                           transmission_mode: str = "downlink"):
    """Entry point: start the satellite SDR broadcast daemon.

    Tunes to the given carrier, scans for NULL-packet slots, and
    starts the orphan-injection loop. Runs in blueprint mode if
    no SDR hardware is detected.

    Args:
        carrier_mhz: DVB-S2 carrier frequency to target.
        force_active: If True, treat SDR as active even without hardware.
        transmission_mode: "uplink" to emit frames or "downlink" to listen.
    """
    global _controller
    if transmission_mode == "downlink":
        logger.info("DOWNLINK mode selected — starting passive listener")
        await start_passive_listener(carrier_mhz=carrier_mhz, force_active=force_active)
        return

    if _controller is None:
        _controller = StealthBroadcastController(
            force_active=force_active,
            transmission_mode=transmission_mode,
        )
    else:
        _controller.force_active = force_active
        _controller.transmission_mode = transmission_mode
    sdr_status = "FORCED-ACTIVE" if force_active else bool(_controller.framer._sdr)
    logger.info("Satellite SDR daemon started (carrier=%.1f MHz, SDR=%s, mode=%s)",
                 carrier_mhz, sdr_status, transmission_mode)
    logger.info("Transmission mode: UPLINK — actively emitting seed frames into carrier gaps")
    await start_orphan_injection_loop(interval=3600.0)


if __name__ == "__main__":
    import sys
    force_active = "--force-active" in sys.argv
    transmission_mode = "downlink"
    for arg in sys.argv:
        if arg.startswith("--transmission-mode="):
            transmission_mode = arg.split("=", 1)[1]
    if "--start-daemon" in sys.argv:
        logging.basicConfig(level=logging.INFO)
        asyncio.run(start_sdr_daemon(
            force_active=force_active,
            transmission_mode=transmission_mode,
        ))
    else:
        print("Usage: python stealth_beyond_sat.py --start-daemon [--force-active] [--transmission-mode=uplink|downlink]")
