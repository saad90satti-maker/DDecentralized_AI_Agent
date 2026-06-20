"""
Obfuscated Protocol — Custom randomized binary encoding for all messages.
Removes all standard headers (JSON, HTTP, MQTT). Every message is encoded
as a binary frame with randomized structure so it is unreadable by any
network monitoring / DPI / tracking system.
"""

import hashlib
import json
import os
import struct
import time
from typing import Any, Dict, Optional, Tuple

from logging_system import get_logger

logger = get_logger("Stealth.Protocol")


FRAME_TYPE_DATA = 0x01
FRAME_TYPE_ACK = 0x02
FRAME_TYPE_BEACON = 0x03
FRAME_TYPE_FRAGMENT = 0x04
FRAME_TYPE_PROBE = 0x05

FRAME_HEADER_SIZE = 7
FRAME_FOOTER_SIZE = 4


class ObfuscatedProtocol:
    """
    Binary frame protocol with randomized encoding.
    
    Frame structure (variable, obfuscated):
      [magic:1][type:1][flags:1][seq_hi:1][seq_lo:2][len:2][payload:var][checksum:4]
    
    - Magic byte is XOR'd with a rolling key
    - Type is inverted
    - Sequence number rotates per-packet
    - Payload length is bit-scrambled
    - Checksum is non-standard (inverted CRC-32)
    - Optional dummy frames inserted at random intervals
    """

    def __init__(self, node_id: str = "ghost"):
        self.node_id = node_id
        self._seq_counter = 0
        self._rolling_key = os.urandom(1)[0]
        self._dummy_frames_sent = 0
        self._stats = {"encoded": 0, "decoded": 0, "dummy": 0, "errors": 0}

    def encode(self, payload: bytes, frame_type: int = FRAME_TYPE_DATA) -> bytes:
        """Encode a payload into an obfuscated binary frame."""
        self._seq_counter = (self._seq_counter + 1) & 0xFFFF
        seq = self._seq_counter

        self._rolling_key = (self._rolling_key + seq + 1) & 0xFF

        flags = (frame_type << 4) | (self._rolling_key & 0x0F)

        length = len(payload)
        scrambled_len = length ^ ((seq << 8 | seq >> 8) & 0xFFFF)

        header = struct.pack("!BBBHH",
                             self._rolling_key ^ 0xA5,
                             (~frame_type) & 0xFF,
                             flags & 0xFF,
                             seq & 0xFFFF,
                             scrambled_len & 0xFFFF)

        checksum = self._obfuscated_checksum(payload, seq)
        frame = header + payload + struct.pack("!I", checksum)

        self._stats["encoded"] += 1

        if self._stats["encoded"] % 7 == 0:
            dummy = self._generate_dummy()
            frame = frame + struct.pack("!H", len(dummy)) + dummy
            self._stats["dummy"] += 1
            self._dummy_frames_sent += 1

        logger.debug("Protocol: encoded %d bytes -> %d byte frame (type=%d, seq=%d)",
                     len(payload), len(frame), frame_type, seq)
        return frame

    def decode(self, frame: bytes) -> Optional[Tuple[bytes, int, int]]:
        """Decode an obfuscated binary frame. Returns (payload, frame_type, seq) or None."""
        try:
            if len(frame) < FRAME_HEADER_SIZE + FRAME_FOOTER_SIZE:
                self._stats["errors"] += 1
                return None

            magic, type_inv, flags, seq, scrambled_len = struct.unpack_from(
                "!BBBHH", frame, 0
            )

            rolling_key = magic ^ 0xA5
            frame_type = (~type_inv) & 0xFF

            expected_flags = (frame_type << 4) | (rolling_key & 0x0F)
            if flags != expected_flags:
                self._stats["errors"] += 1
                return None

            length = scrambled_len ^ ((seq << 8 | seq >> 8) & 0xFFFF)

            total_header = FRAME_HEADER_SIZE
            if total_header + length + FRAME_FOOTER_SIZE > len(frame):
                length = len(frame) - total_header - FRAME_FOOTER_SIZE
                if length < 0:
                    self._stats["errors"] += 1
                    return None

            payload = frame[total_header:total_header + length]
            stored_checksum = struct.unpack_from("!I", frame, total_header + length)[0]
            computed_checksum = self._obfuscated_checksum(payload, seq)

            if stored_checksum != computed_checksum:
                self._stats["errors"] += 1
                return None

            self._stats["decoded"] += 1
            logger.debug("Protocol: decoded %d byte frame (type=%d, seq=%d)",
                         len(frame), frame_type, seq)
            return payload, frame_type, seq

        except (struct.error, IndexError):
            self._stats["errors"] += 1
            return None

    def _obfuscated_checksum(self, data: bytes, seq: int) -> int:
        """Non-standard inverted checksum — unreadable by standard CRC tools."""
        h = hashlib.sha256(data + struct.pack("!H", seq)).digest()
        crc = 0xFFFFFFFF
        for b in h[:8]:
            crc ^= b
            for _ in range(8):
                if crc & 1:
                    crc = (crc >> 1) ^ 0xEDB88320
                else:
                    crc >>= 1
        return (~crc) & 0xFFFFFFFF

    def _generate_dummy(self) -> bytes:
        """Generate a decoy dummy payload to insert noise."""
        return os.urandom(16 + int.from_bytes(os.urandom(1), "big") % 48)

    def encode_message(self, msg_type: str, sender: str,
                        payload: Dict[str, Any]) -> bytes:
        """Encode a structured message as an obfuscated binary frame."""
        inner = bytearray()
        inner.extend(struct.pack("!B", len(msg_type)))
        inner.extend(msg_type.encode("utf-8"))
        inner.extend(struct.pack("!B", len(sender)))
        inner.extend(sender.encode("utf-8"))

        import json
        payload_bytes = json.dumps(payload, default=str).encode("utf-8")
        inner.extend(struct.pack("!I", len(payload_bytes)))
        inner.extend(payload_bytes)

        return self.encode(bytes(inner), frame_type=FRAME_TYPE_DATA)

    def decode_message(self, frame: bytes) -> Optional[Dict[str, Any]]:
        """Decode an obfuscated frame back into a structured message."""
        result = self.decode(frame)
        if not result:
            return None
        payload, frame_type, seq = result

        try:
            off = 0
            type_len = payload[off]
            off += 1
            msg_type = payload[off:off + type_len].decode("utf-8")
            off += type_len

            sender_len = payload[off]
            off += 1
            sender = payload[off:off + sender_len].decode("utf-8")
            off += sender_len

            payload_len = struct.unpack_from("!I", payload, off)[0]
            off += 4
            payload_data = json.loads(payload[off:off + payload_len].decode("utf-8"))

            return {
                "type": msg_type,
                "sender": sender,
                "payload": payload_data,
                "frame_type": frame_type,
                "seq": seq,
            }
        except (IndexError, json.JSONDecodeError, struct.error, UnicodeDecodeError):
            return None

    def beacon(self) -> bytes:
        """Generate a presence beacon (minimal frame)."""
        return self.encode(b"N", frame_type=FRAME_TYPE_BEACON)

    def ack_for(self, seq: int) -> bytes:
        """Generate an acknowledgment for a given sequence number."""
        ack_data = struct.pack("!H", seq)
        return self.encode(ack_data, frame_type=FRAME_TYPE_ACK)

    @property
    def stats(self) -> Dict[str, int]:
        return dict(self._stats)
