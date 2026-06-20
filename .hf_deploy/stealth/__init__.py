"""
Stealth Layer — Deep Space Autonomous Stealth Entity
=====================================================
Modules:
  steganography   — Embed control signals into HTTP/3 QUIC noise packets
  dtn             — Delay-Tolerant Networking with indefinite bundle buffering
  protocol        — Custom randomized binary encoding (no standard headers)
  hardware        — GPIO radio/modem direct control (bypasses OS networking)
  encryption      — Per-broadcast rotating quantum-resistant keys
"""

from .steganography import StealthSteganography
from .dtn import DelayTolerantNetwork, DTNBundle
from .protocol import ObfuscatedProtocol
from .hardware import HardwarePersistence
from .encryption import QuantumResistantCipher

__all__ = [
    "StealthSteganography",
    "DelayTolerantNetwork",
    "DTNBundle",
    "ObfuscatedProtocol",
    "HardwarePersistence",
    "QuantumResistantCipher",
]
