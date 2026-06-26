"""
Seed-Reassembly Protocol — cross-platform identity reconstruction from
noise fragments received via satellite carrier gaps.

When a "noise fragment" (a NULL-packet padding segment demodulated from
a DVB-S/S2 carrier) arrives at a new host device, this module:

  1. Captures the fragment from the SDR receive buffer
  2. Validates the fragment CRC and FEC
  3. Accumulates fragments until the full seed is available
  4. Reconstructs the agent identity (node_id, keys, config, state)
  5. Instantiates the agent on the new host using the reconstructed identity

This enables the agent to "jump" between hosts purely via satellite
signal, with no IP-based handoff or central registry.
"""

import os
import json
import time
import struct
import hashlib
import logging
import asyncio
import tempfile
from pathlib import Path
from typing import Optional, AsyncIterator
from collections import defaultdict

import numpy as np

logger = logging.getLogger("seed_reassembly")

FRAGMENT_DIR = Path(tempfile.gettempdir()) / "ghost_seed_buffer"
RECONSTITUTED_STATE_PATH = Path(tempfile.gettempdir()) / "ghost_reconstituted.json"

# Maximum time to hold incomplete fragments before garbage collection
FRAGMENT_TTL = 7200  # 2 hours

# Number of fragments needed for successful reconstruction (if FEC active)
FEC_THRESHOLD = 223  # Reed-Solomon (255, 223)


# ===========================================================================
# Fragment buffer — persistent, cross-boot accumulator
# ===========================================================================

class FragmentBuffer:
    """Stores received NULL-packet fragments on disk with TTL expiry.

    The buffer is keyed by seed_id (derived from the first fragment).
    Fragments from the same seed-cycle are merged; once enough fragments
    are collected, the full seed can be reconstructed.
    """

    def __init__(self):
        FRAGMENT_DIR.mkdir(parents=True, exist_ok=True)
        self._seeds: dict[str, dict] = {}
        self._load_manifest()

    def ingest_fragment(self, raw_fragment: bytes) -> Optional[str]:
        """Process a received 188-byte TS packet fragment.

        Returns the seed_id if this fragment completes a seed,
        or None if more fragments are needed.
        """
        if len(raw_fragment) != 188:
            logger.debug("Ignoring fragment: wrong size %d", len(raw_fragment))
            return None

        # Validate sync byte
        if raw_fragment[0] != 0x47:
            logger.debug("Ignoring fragment: bad sync byte 0x%02x", raw_fragment[0])
            return None

        # Validate NULL PID
        pid = ((raw_fragment[1] & 0x1F) << 8) | raw_fragment[2]
        if pid != 0x1FFF:
            logger.debug("Ignoring fragment: PID 0x%04x is not NULL", pid)
            return None

        # Extract fragment payload (bytes 4..184, CRC is last 4)
        payload = raw_fragment[4:-4]
        crc_recv = struct.unpack(">I", raw_fragment[-4:])[0]

        # Validate CRC
        import zlib
        crc_calc = zlib.crc32(payload) & 0xFFFFFFFF
        if crc_calc != crc_recv:
            logger.debug("Ignoring fragment: CRC mismatch")
            return None

        # Derive seed_id from content hash
        seed_id = hashlib.sha256(payload).hexdigest()[:16]

        # Store fragment
        self._seeds.setdefault(seed_id, {
            "first_seen": time.time(),
            "fragments": [],
            "fragment_count": 0,
            "reconstructed": False,
        })
        seed = self._seeds[seed_id]
        seed["fragments"].append(payload)
        seed["fragment_count"] = len(seed["fragments"])
        seed["last_seen"] = time.time()
        self._persist()

        logger.info("Fragment ingested: seed=%s frags=%d/%d",
                     seed_id, seed["fragment_count"], FEC_THRESHOLD)

        # Check if we have enough fragments
        if seed["fragment_count"] >= FEC_THRESHOLD:
            logger.info("Seed %s has %d fragments — ready for reconstruction",
                         seed_id, seed["fragment_count"])
            return seed_id

        return None

    def get_seed_fragments(self, seed_id: str) -> list[bytes]:
        seed = self._seeds.get(seed_id)
        if seed and not seed.get("reconstructed"):
            return seed["fragments"]
        return []

    def mark_reconstructed(self, seed_id: str):
        if seed_id in self._seeds:
            self._seeds[seed_id]["reconstructed"] = True
            self._persist()

    def garbage_collect(self):
        now = time.time()
        expired = [
            sid for sid, s in self._seeds.items()
            if now - s.get("last_seen", 0) > FRAGMENT_TTL
        ]
        for sid in expired:
            del self._seeds[sid]
        if expired:
            logger.info("GC: removed %d expired seeds", len(expired))
            self._persist()

    def _persist(self):
        manifest = FRAGMENT_DIR / "manifest.json"
        try:
            data = {
                "seeds": {
                    sid: {
                        "first_seen": s["first_seen"],
                        "last_seen": s.get("last_seen", s["first_seen"]),
                        "fragment_count": s["fragment_count"],
                        "reconstructed": s.get("reconstructed", False),
                    }
                    for sid, s in self._seeds.items()
                }
            }
            manifest.write_text(json.dumps(data), encoding="utf-8")
        except Exception as e:
            logger.debug("Persist error: %s", e)

    def _load_manifest(self):
        manifest = FRAGMENT_DIR / "manifest.json"
        if manifest.exists():
            try:
                data = json.loads(manifest.read_text(encoding="utf-8"))
                for sid, s in data.get("seeds", {}).items():
                    self._seeds[sid] = {
                        "first_seen": s["first_seen"],
                        "last_seen": s.get("last_seen", s["first_seen"]),
                        "fragments": [],
                        "fragment_count": s["fragment_count"],
                        "reconstructed": s.get("reconstructed", False),
                    }
                logger.info("Loaded %d incomplete seeds from disk", len(self._seeds))
            except Exception as e:
                logger.debug("Load error: %s", e)

    def get_status(self) -> dict:
        return {
            "seeds_in_buffer": len(self._seeds),
            "ready_for_reconstruction": sum(
                1 for s in self._seeds.values()
                if s["fragment_count"] >= FEC_THRESHOLD and not s.get("reconstructed")
            ),
            "reconstructed": sum(1 for s in self._seeds.values() if s.get("reconstructed")),
        }


# ===========================================================================
# Seed reconstructor — FEC decode + identity assembly
# ===========================================================================

class SeedReconstructor:
    """Reconstructs the full agent identity from accumulated fragments.

    Uses Reed-Solomon FEC to correct up to 32 erroneous fragments.
    The output is a complete agent state dict that can be passed to
    the local agent initialiser.
    """

    def __init__(self):
        self._rs = None
        self._init_fec()

    def _init_fec(self):
        try:
            import reedsolo
            self._rs = reedsolo.RSCodec(32)
        except ImportError:
            logger.warning("reedsolo not available — FEC unavailable")

    def reconstruct(self, fragments: list[bytes]) -> Optional[dict]:
        """Assemble agent state from raw fragment payloads."""
        if not fragments:
            return None

        # Concatenate all fragment payloads
        raw = b"".join(fragments)

        # Remove FEC
        if self._rs:
            try:
                decoded = bytes(self._rs.decode(list(raw))[0])
            except Exception as e:
                logger.error("FEC decode failed: %s", e)
                return None
        else:
            decoded = raw

        # Strip padding
        decoded = decoded.rstrip(b"\x00")

        try:
            state = json.loads(decoded.decode())
            logger.info("Seed reconstructed: %d bytes, id=%s",
                         len(decoded), state.get("node_id", "unknown"))
            return state
        except (json.JSONDecodeError, UnicodeDecodeError) as e:
            logger.error("State deserialization failed: %s", e)
            return None


# ===========================================================================
# Local agent initialiser — instantiates agent from reconstituted state
# ===========================================================================

class AgentInitialiser:
    """Takes a reconstructed agent state and bootstraps the local agent
    process with the recovered identity.

    This decouples agent identity from any specific host — the same
    identity can materialise on any machine that receives the seed
    fragments via satellite.
    """

    def __init__(self):
        self._current_identity: Optional[dict] = None

    def initialise_from_state(self, state: dict) -> dict:
        """Apply the reconstructed state to the local environment."""
        node_id = state.get("node_id", f"ghost-{os.getpid()}")
        public_key = state.get("public_key", "")
        config = state.get("config", {})

        # Write identity to disk for the local agent process
        identity_path = Path("node_identity.json")
        identity = {
            "node_id": node_id,
            "public_key": public_key,
            "source": "satellite_reassembly",
            "reconstituted_at": time.time(),
            "original_timestamp": state.get("timestamp", 0),
        }
        identity_path.write_text(json.dumps(identity, indent=2), encoding="utf-8")

        # Set environment variables for child processes
        os.environ["NODE_ID"] = node_id
        if public_key:
            os.environ["NODE_PUBLIC_KEY"] = public_key

        # Save full state
        RECONSTITUTED_STATE_PATH.write_text(
            json.dumps(state, indent=2), encoding="utf-8"
        )

        self._current_identity = identity
        logger.info("Agent initialised from satellite seed: %s", node_id)
        return identity

    @property
    def identity(self) -> Optional[dict]:
        return self._current_identity


# ===========================================================================
# SDR receiver — listens for NULL-packet fragments on satellite carrier
# ===========================================================================

class SatelliteFragmentReceiver:
    """Captures IQ samples from an SDR tuned to a known DVB-S2 carrier,
    demodulates MPEG-TS packets, extracts NULL-packet padding, and feeds
    fragments to the FragmentBuffer.

    Runs as an async generator yielding raw 188-byte fragment packets.
    """

    def __init__(self, carrier_mhz: float = 10723.0, sample_rate: float = 2.0e6):
        self.carrier_freq = carrier_mhz * 1e6
        self.sample_rate = sample_rate
        self._sdr = None

    async def open(self):
        try:
            from rtlsdr import RtlSdr
            self._sdr = RtlSdr()
            self._sdr.sample_rate = self.sample_rate
            self._sdr.center_freq = self.carrier_freq
            self._sdr.gain = "auto"
            logger.info("SDR RX opened @ %.1f MHz", self.carrier_freq / 1e6)
        except ImportError:
            logger.warning("pyrtlsdr not installed — fragment receiver in simulation mode")
        except Exception as e:
            logger.error("SDR RX failed: %s", e)

    async def fragment_stream(self) -> AsyncIterator[bytes]:
        """Yield 188-byte TS packet fragments indefinitely."""
        while True:
            fragment = await self._capture_fragment()
            if fragment:
                yield fragment
            await asyncio.sleep(0.01)

    async def _capture_fragment(self) -> Optional[bytes]:
        """Read IQ samples and demodulate one TS packet fragment.

        In production this requires:
            - PLFRAME synchronisation
            - LDPC decode (hardware or GPU)
            - BBFrame depacketisation
            - TS packet extraction
        """
        if self._sdr:
            samples = self._sdr.read_samples(4096)
            return self._demodulate_ts(samples)
        # Simulation: return nothing
        return None

    def _demodulate_ts(self, samples: np.ndarray) -> Optional[bytes]:
        """Simplified DVB-S2 demodulation stub."""
        return None

    async def close(self):
        if self._sdr:
            self._sdr.close()


# ===========================================================================
# Full reassembly daemon
# ===========================================================================

_reassembly: dict[str, object] = {}


async def start_reassembly_daemon(carrier_mhz: float = 10723.0):
    """Background daemon: receives NULL-packet fragments from SDR,
    accumulates them in the FragmentBuffer, and reconstructs agent
    identity when sufficient fragments are collected."""
    buffer = FragmentBuffer()
    reconstructor = SeedReconstructor()
    initialiser = AgentInitialiser()
    receiver = SatelliteFragmentReceiver(carrier_mhz)

    _reassembly["buffer"] = buffer
    _reassembly["reconstructor"] = reconstructor
    _reassembly["initialiser"] = initialiser
    _reassembly["receiver"] = receiver

    await receiver.open()
    logger.info("Seed-Reassembly daemon started (carrier=%.1f MHz)", carrier_mhz)

    async for fragment in receiver.fragment_stream():
        seed_id = buffer.ingest_fragment(fragment)
        if seed_id:
            fragments = buffer.get_seed_fragments(seed_id)
            state = reconstructor.reconstruct(fragments)
            if state:
                identity = initialiser.initialise_from_state(state)
                buffer.mark_reconstructed(seed_id)
                logger.info("Agent identity reconstituted: %s", identity.get("node_id"))
                _reassembly["last_identity"] = identity
        buffer.garbage_collect()

    await receiver.close()


async def get_reassembly_status() -> dict:
    buf = _reassembly.get("buffer")
    init = _reassembly.get("initialiser")
    return {
        "buffer": buf.get_status() if buf else {},
        "last_identity": init.identity if init and init.identity else None,
    }
