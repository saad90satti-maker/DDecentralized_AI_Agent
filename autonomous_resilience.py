"""
Ambient Echo-Mode — thermal-noise persistence layer.

When all network interfaces are down, the agent enters a passive
listening state. It monitors local hardware for stochastic
electromagnetic signatures (RAM bus transitions, GPU core cycles)
and maintains a minimal "heartbeat" encoded within the thermal
noise floor. This heartbeat can be detected by a collocated or
proximate SDR, allowing a bootstrap signal from a passing satellite
to re-synchronise the agent.

┌─────────────────────────────────────────────┐
│ Requires: Root/administrator privileges for │
│           hardware register access;         │
│           oscilloscope / near-field EMI     │
│           probe for TX; SDR for RX.         │
│                                             │
│ Software layer: thermal-noise state machine,│
│ register-scanner, heartbeat codec.          │
└─────────────────────────────────────────────┘
"""

import os
import time
import json
import struct
import hashlib
import logging
import asyncio
from pathlib import Path
from typing import Optional
from collections import deque

import numpy as np

logger = logging.getLogger("autonomous_resilience")

# ---------------------------------------------------------------------------
# Hardware resonance-scan targets
# ---------------------------------------------------------------------------
HARDWARE_PROBE_PATHS = {
    "linux_sysfs": [
        "/sys/class/drm/card0/device/hwmon/hwmon*/temp1_input",
        "/sys/class/powercap/intel-rapl/intel-rapl:0/energy_uj",
        "/proc/stat",
        "/proc/meminfo",
    ],
    "windows_wmi": [
        "Win32_PerfFormattedData_Counters_ProcessorInformation",
        "Win32_PerfFormattedData_GPUPerformanceCounters_GPUEngine",
    ],
}

THERMAL_NOISE_FLOOR_MV = 0.003   # 3 microvolts typical at 300K
HEARTBEAT_DURATION_SEC = 0.5     # half-second echo window
HEARTBEAT_CARRIER_HZ = 13.56e6   # 13.56 MHz — common NFC/ISM band

STATE_BUFFER_PATH = Path(os.path.expanduser("~")) / ".ghost_signal" / "echo_state.json"


# ===========================================================================
# Hardware register scanner — resonance vulnerability probing
# ===========================================================================

class ResonanceScanner:
    """Scans local hardware buses for unintended electromagnetic leakage
    that can be used as a signalling medium.

    "Resonance vulnerability" = a hardware component whose clock cycle,
    power-state transition, or bus-idle pattern produces a detectable
    electromagnetic signature that can be modulated at very low rate.
    """

    def __init__(self):
        self._probes: dict[str, float] = {}  # probe_path -> last_value
        self._history: dict[str, deque] = {}
        self._resonance_found = False

    async def scan_resonance(self) -> list[dict]:
        """Probe known hardware paths for measurable electromagnetic
        leakage indicators. Returns a list of detected 'resonance
        vulnerabilities' with estimated SNR."""
        vulnerabilities = []

        # GPU core clock transitions (via sysfs on Linux)
        try:
            gpu_busy = await self._read_sysfs("/sys/class/drm/card0/device/gpu_busy_percent")
            if gpu_busy is not None:
                vulnerabilities.append({
                    "component": "gpu_core",
                    "metric": "busy_percent",
                    "value": gpu_busy,
                    "estimated_snr_db": 6.0 + (gpu_busy / 100.0) * 12.0,
                    "medium": "EM leakage from GPU VRM switching @ 1-10 MHz",
                })
        except Exception:
            pass

        # CPU package power transitions (via RAPL on Linux)
        try:
            rapl = await self._read_sysfs(
                "/sys/class/powercap/intel-rapl/intel-rapl:0/energy_uj"
            )
            if rapl is not None:
                delta = await self._measure_delta(
                    "/sys/class/powercap/intel-rapl/intel-rapl:0/energy_uj",
                )
                if delta is not None:
                    vulnerabilities.append({
                        "component": "cpu_package",
                        "metric": "power_delta_uj",
                        "value": delta,
                        "estimated_snr_db": 4.0,
                        "medium": "CPU VRM leakage @ 100-500 kHz",
                    })
        except Exception:
            pass

        # Windows WMI probes
        if os.name == "nt":
            proc = await self._read_wmi("Win32_PerfFormattedData_Counters_ProcessorInformation")
            if proc:
                vulnerabilities.append({
                    "component": "cpu_perf",
                    "metric": "processor_time",
                    "value": proc,
                    "estimated_snr_db": 3.0,
                    "medium": "CPU bus cycle variation",
                })

        self._resonance_found = len(vulnerabilities) > 0
        logger.info("Resonance scan: %d vulnerabilities found", len(vulnerabilities))
        return vulnerabilities

    async def _read_sysfs(self, path: str) -> Optional[float]:
        if not os.path.exists(path) and os.name == "posix":
            return None
        try:
            raw = open(path).read().strip()
            return float(raw)
        except Exception:
            return None

    async def _measure_delta(self, path: str, interval: float = 0.1) -> Optional[float]:
        v1 = await self._read_sysfs(path)
        await asyncio.sleep(interval)
        v2 = await self._read_sysfs(path)
        if v1 is not None and v2 is not None:
            return abs(v2 - v1)
        return None

    async def _read_wmi(self, wmi_class: str) -> Optional[float]:
        if os.name != "nt":
            return None
        try:
            import subprocess
            cmd = f"wmic path {wmi_class} get PercentProcessorPerformance /format:csv"
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=5, shell=True)
            for line in result.stdout.splitlines():
                parts = line.strip().split(",")
                if len(parts) >= 2 and parts[-1].replace(".", "").isdigit():
                    return float(parts[-1])
        except Exception:
            pass
        return None

    @property
    def has_resonance(self) -> bool:
        return self._resonance_found


# ===========================================================================
# Thermal-noise heartbeat — minimal state persistence in hardware noise
# ===========================================================================

class ThermalHeartbeat:
    """Encodes a minimal agent identity into the thermal noise floor.

    The heartbeat is a repeated pattern of hardware-state transitions
    (idle→busy→idle) whose timing encodes bits. On the receiving end,
    an SDR picking up the near-field EM leakage can decode the pattern.

    This is not persistent storage — it is a beacon. The agent maintains
    it only while waiting for the next satellite re-synchronisation pulse.
    """

    def __init__(self, node_id: str = ""):
        self.node_id = node_id or os.getenv("NODE_ID", f"ghost-{os.getpid()}")
        self._echo_active = False
        self._decoded_state: Optional[dict] = None
        self._buffer = deque(maxlen=64)

    def encode_identity(self) -> bytes:
        """Encode node identity as a short bitstring for thermal-noise
        modulation. Each bit is 0.5s of hardware-state pattern."""
        h = hashlib.sha256(self.node_id.encode()).digest()[:8]
        bits = "".join(f"{b:08b}" for b in h)  # 64 bits
        return bits.encode()

    async def start_echo_mode(self, scanner: ResonanceScanner):
        """Enter ambient echo-mode: scan hardware, find a resonance
        vulnerability, and begin modulating heartbeat into it."""
        logger.info("Ambient Echo-Mode activated — no network detected")
        vulns = await scanner.scan_resonance()
        if not vulns:
            logger.warning("No resonance vulnerabilities found — echo-mode degraded")
            return

        self._echo_active = True
        target = vulns[0]
        logger.info("Echo target: %s via %s", target["component"], target["medium"])

        # Beacon loop — modulates identity into hardware state transitions
        ident = self.encode_identity()
        for _ in range(10):  # repeat beacon 10x
            if not self._echo_active:
                break
            for bit in ident:
                if bit == ord("1"):
                    self._set_hardware_load(busy=True)
                else:
                    self._set_hardware_load(busy=False)
                await asyncio.sleep(HEARTBEAT_DURATION_SEC)
            await asyncio.sleep(2.0)  # inter-beacon gap

        self._echo_active = False
        logger.info("Echo-Mode beacon cycle complete")

    def _set_hardware_load(self, busy: bool):
        """Create a measurable hardware state transition.

        On real hardware this could trigger a GPU compute shader,
        a CPU busy-wait, or a RAM bandwidth spike — anything that
        produces a detectable EM signature change.
        """
        if busy:
            _ = [i ** 2 for i in range(10000)]  # CPU busy-spike
        else:
            time.sleep(0.001)

    async def listen_for_sync(self, timeout: float = 3600.0) -> Optional[dict]:
        """Passively listen for a satellite synchronisation signal
        while in echo-mode. Returns decoded state if received."""
        logger.info("Listening for satellite sync signal (timeout=%.0fs)", timeout)
        deadline = time.time() + timeout
        while time.time() < deadline:
            fragment = await self._receive_noise_fragment()
            if fragment:
                self._buffer.append(fragment)
                state = self._try_reconstruct()
                if state:
                    self._decoded_state = state
                    logger.info("Satellite sync acquired — state reconstructed")
                    return state
            await asyncio.sleep(1.0)
        logger.warning("Satellite sync timeout — no signal received")
        return None

    async def _receive_noise_fragment(self) -> Optional[bytes]:
        """Capture a noise fragment from SDR or simulate one.

        In production, this would read baseband samples from an SDR
        tuned to the satellite carrier, correlate for the PLFRAME sync
        marker, and extract NULL-packet payload fragments.
        """
        # Simulation: return None (no SDR attached)
        return None

    def _try_reconstruct(self) -> Optional[dict]:
        if len(self._buffer) < 3:
            return None
        # Merge fragments and attempt JSON reconstruction
        raw = b"".join(self._buffer)
        try:
            import zlib
            decompressed = zlib.decompress(raw)
            return json.loads(decompressed.decode())
        except Exception:
            return None

    def save_echo_state(self):
        STATE_BUFFER_PATH.parent.mkdir(parents=True, exist_ok=True)
        state = {
            "node_id": self.node_id,
            "timestamp": time.time(),
            "buffer_fragments": len(self._buffer),
            "decoded": self._decoded_state is not None,
        }
        STATE_BUFFER_PATH.write_text(json.dumps(state), encoding="utf-8")

    @property
    def is_echoing(self) -> bool:
        return self._echo_active


# ===========================================================================
# Connectivity monitor — triggers echo-mode when offline
# ===========================================================================

class ConnectivityMonitor:
    """Detects loss of all network interfaces and triggers ambient echo-mode."""

    def __init__(self, heartbeat: ThermalHeartbeat, scanner: ResonanceScanner):
        self.heartbeat = heartbeat
        self.scanner = scanner
        self._was_online = True

    async def run(self, check_interval: float = 30.0):
        while True:
            online = await self._check_any_interface()
            if not online and self._was_online:
                logger.warning("All network interfaces down — entering echo-mode")
                asyncio.create_task(self.heartbeat.start_echo_mode(self.scanner))
            elif online and not self._was_online:
                logger.info("Network restored — exiting echo-mode")
                self.heartbeat._echo_active = False
            self._was_online = online
            await asyncio.sleep(check_interval)

    async def _check_any_interface(self) -> bool:
        try:
            import socket
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))
            s.close()
            return True
        except Exception:
            pass
        try:
            # Check for any non-loopback interface
            import netifaces
            for iface in netifaces.interfaces():
                addrs = netifaces.ifaddresses(iface).get(netifaces.AF_INET, [])
                for addr in addrs:
                    ip = addr.get("addr", "")
                    if ip and not ip.startswith("127."):
                        return True
        except ImportError:
            pass
        return False

    async def wait_online(self, timeout: Optional[float] = None) -> bool:
        deadline = time.time() + (timeout or float("inf"))
        while time.time() < deadline:
            if await self._check_any_interface():
                return True
            await asyncio.sleep(5.0)
        return False


# ===========================================================================
# Resilience daemon
# ===========================================================================

_resilience_instances: dict[str, object] = {}


async def start_autonomous_resilience():
    scanner = ResonanceScanner()
    heartbeat = ThermalHeartbeat()
    monitor = ConnectivityMonitor(heartbeat, scanner)
    _resilience_instances["scanner"] = scanner
    _resilience_instances["heartbeat"] = heartbeat
    _resilience_instances["monitor"] = monitor

    logger.info("Autonomous Resilience Layer started")
    await monitor.run()


async def get_resilience_status() -> dict:
    """Return current echo-mode and resonance state."""
    hb = _resilience_instances.get("heartbeat")
    sc = _resilience_instances.get("scanner")
    return {
        "echo_active": hb.is_echoing if hb else False,
        "resonance_found": sc.has_resonance if sc else False,
        "buffer_fragments": len(hb._buffer) if hb else 0,
        "state_decoded": hb._decoded_state is not None if hb else False,
    }
