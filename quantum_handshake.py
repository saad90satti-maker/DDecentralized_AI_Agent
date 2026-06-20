"""
Ghost Engine — Quantum-Safe Handshake
======================================
Post-quantum key exchange for P2P swarm communication using CRYSTALS-Kyber
(ML-KEM, FIPS-203), the NIST-standardized KEM resistant to Shor's algorithm.

Architecture:
  Peer A (Initiator)          Peer B (Responder)
  ─────────────────────────────────────────────────
  1. Generate Kyber1024 KP ──► send public_key ──►
  2.                              encap_secret(pk)
  3. ◄── recv ciphertext ─────── send ciphertext ──
  4. decap_secret(ct)           shared_secret_B
     shared_secret_A
  5. HKDF-Expand(ss, "ghost-p2p") → 32-byte session key
  6. ChaCha20-Poly1305 encrypted tunnel

  Algorithm: CRYSTALS-Kyber-1024 (NIST Level 5 security)
  KDF:       HKDF-SHA256
  AEAD:      ChaCha20-Poly1305 (post-quantum symmetric)

Dependencies:
  pip install liboqs-python cryptography

  liboqs C library is required. Install via:
    apt:  sudo apt install liboqs-dev
    brew: brew install liboqs
    src:  git clone https://github.com/open-quantum-safe/liboqs && cd liboqs && mkdir build && cd build && cmake -DCMAKE_INSTALL_PREFIX=/usr .. && make -j && sudo make install

Usage:
  # Quantum handshake over an existing TCP socket
  from quantum_handshake import QuantumHandshakeClient, QuantumHandshakeServer

  # Server side (responder)
  server = QuantumHandshakeServer()
  session_key = await server.handshake(reader, writer)

  # Client side (initiator)
  client = QuantumHandshakeClient()
  session_key = await client.handshake(reader, writer)
"""

import asyncio
import hashlib
import hmac
import logging
import os
import struct
from typing import Optional, Tuple

logger = logging.getLogger("QuantumHandshake")

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
KYBER_ALGORITHM = "Kyber1024"       # NIST Level 5: 256-bit security
KDF_ALGORITHM = "HKDF-SHA256"
AEAD_ALGORITHM = "ChaCha20-Poly1305"
SESSION_KEY_LENGTH = 32             # 256-bit session key
HANDSHAKE_TIMEOUT = 30              # seconds
PROTOCOL_VERSION = b"GHOST-QSH-v1"  # protocol identifier
SALT = b"Ghost-Engine-Quantum-Handshake-v1"


# ---------------------------------------------------------------------------
# Lazy liboqs importer with graceful fallback
# ---------------------------------------------------------------------------
class OQSProvider:
    """Provides access to liboqs Kyber KEM operations with fallback."""

    def __init__(self):
        self._available = False
        self._kem = None
        self._init()

    def _init(self):
        try:
            import oqs
            # Verify Kyber1024 is available
            if KYBER_ALGORITHM in oqs.get_enabled_kem_mechanisms():
                self._available = True
                logger.info("liboqs loaded — Kyber1024 available for PQC handshake")
            else:
                logger.warning("Kyber1024 not enabled in this liboqs build")
        except ImportError:
            logger.warning(
                "liboqs-python not installed. Quantum handshake disabled. "
                "Install: pip install liboqs-python"
            )
        except Exception as exc:
            logger.warning("liboqs init failed: %s", exc)

    @property
    def available(self) -> bool:
        return self._available

    def generate_keypair(self) -> Tuple[bytes, bytes]:
        """Generate a Kyber1024 keypair. Returns (secret_key, public_key)."""
        import oqs
        kem = oqs.KeyEncapsulation(KYBER_ALGORITHM)
        public_key = kem.generate_keypair()
        secret_key = kem.export_secret_key()
        kem.free()
        return secret_key, public_key

    def encapsulate(self, public_key: bytes) -> Tuple[bytes, bytes]:
        """Encapsulate a shared secret. Returns (ciphertext, shared_secret)."""
        import oqs
        kem = oqs.KeyEncapsulation(KYBER_ALGORITHM)
        ciphertext, shared_secret = kem.encap_secret(public_key)
        kem.free()
        return ciphertext, shared_secret

    def decapsulate(self, secret_key: bytes, ciphertext: bytes) -> bytes:
        """Decapsulate to recover the shared secret."""
        import oqs
        kem = oqs.KeyEncapsulation(KYBER_ALGORITHM)
        kem.set_secret_key(secret_key)
        shared_secret = kem.decap_secret(ciphertext)
        kem.free()
        return shared_secret

    def generate_hybrid_keypair(self) -> Tuple[dict, dict]:
        """
        Generate a hybrid (Kyber + X25519) keypair for forward compatibility.
        Returns (secret_dict, public_dict).
        """
        from cryptography.hazmat.primitives.asymmetric import x25519
        from cryptography.hazmat.primitives import serialization

        # Kyber component
        import oqs
        kem = oqs.KeyEncapsulation(KYBER_ALGORITHM)
        kyber_pub = kem.generate_keypair()
        kyber_sec = kem.export_secret_key()
        kem.free()

        # X25519 component
        x25519_sec = x25519.X25519PrivateKey.generate()
        x25519_pub = x25519_sec.public_key().public_bytes(
            serialization.Encoding.Raw, serialization.PublicFormat.Raw
        )

        return (
            {"kyber": kyber_sec, "x25519": x25519_sec},
            {"kyber": kyber_pub, "x25519": x25519_pub},
        )


# ---------------------------------------------------------------------------
# Session Key Derivation
# ---------------------------------------------------------------------------
def derive_session_key(shared_secret: bytes, peer_id: str, salt: bytes = SALT) -> bytes:
    """
    Derive a 256-bit session key from the Kyber shared secret using HKDF.
    Binds the key to the peer's identity to prevent KCI attacks.
    """
    from cryptography.hazmat.primitives.kdf.hkdf import HKDF
    from cryptography.hazmat.primitives import hashes

    hkdf = HKDF(
        algorithm=hashes.SHA256(),
        length=SESSION_KEY_LENGTH,
        salt=salt,
        info=f"ghost-p2p-session:{peer_id}".encode(),
    )
    return hkdf.derive(shared_secret)


# ---------------------------------------------------------------------------
# Secure Channel (symmetric encryption using the session key)
# ---------------------------------------------------------------------------
class SecureChannel:
    """
    ChaCha20-Poly1305 encrypted channel over an existing asyncio stream.
    Each message is independently encrypted with an incrementing nonce.
    """

    def __init__(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter,
                 session_key: bytes, peer_id: str):
        self.reader = reader
        self.writer = writer
        self.session_key = session_key
        self.peer_id = peer_id
        self._nonce = 0

    def _build_nonce(self) -> bytes:
        """64-bit big-endian nonce (first 8 bytes), 4 bytes zero padding."""
        nonce = struct.pack(">Q", self._nonce)
        self._nonce += 1
        return nonce + b"\x00\x00\x00\x00"

    async def send_encrypted(self, plaintext: bytes) -> None:
        """Encrypt and send a message using ChaCha20-Poly1305."""
        from cryptography.hazmat.primitives.ciphers.aead import ChaCha20Poly1305

        aad = struct.pack(">I", len(plaintext))
        chacha = ChaCha20Poly1305(self.session_key)
        ciphertext = chacha.encrypt(self._build_nonce(), plaintext, aad)

        # Wire format: 4-byte length, 4-byte AAD, ciphertext+tag
        self.writer.write(struct.pack(">I", len(ciphertext)))
        self.writer.write(ciphertext)
        await self.writer.drain()

    async def recv_encrypted(self) -> bytes:
        """Receive and decrypt a message."""
        from cryptography.hazmat.primitives.ciphers.aead import ChaCha20Poly1305

        size_data = await self.reader.readexactly(4)
        msg_len = struct.unpack(">I", size_data)[0]
        ciphertext = await self.reader.readexactly(msg_len)

        aad = struct.pack(">I", msg_len)
        chacha = ChaCha20Poly1305(self.session_key)
        plaintext = chacha.decrypt(self._build_nonce(), ciphertext, aad)
        return plaintext

    async def close(self) -> None:
        self.writer.close()
        try:
            await self.writer.wait_closed()
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Quantum Handshake Protocol
# ---------------------------------------------------------------------------
class QuantumHandshakeServer:
    """
    Responder side of the quantum-safe handshake.
    Waits for an initiator's public key, encapsulates, returns ciphertext.
    """

    def __init__(self, peer_id: str = "server"):
        self.oqs = OQSProvider()
        self.peer_id = peer_id
        self._fallback = not self.oqs.available

    async def handshake(self, reader: asyncio.StreamReader,
                        writer: asyncio.StreamWriter) -> Optional[bytes]:
        """
        Execute the responder side of the Kyber handshake.

        Protocol:
          1. Read protocol version from initiator
          2. Read Kyber public key
          3. Encapsulate shared secret
          4. Send ciphertext + key identifier
          5. Derive and return session key
        """
        try:
            # 1. Read protocol version
            version = await asyncio.wait_for(
                reader.readexactly(len(PROTOCOL_VERSION)), HANDSHAKE_TIMEOUT
            )
            if version != PROTOCOL_VERSION:
                logger.error("Protocol version mismatch: %s", version)
                return None

            # 2. Read public key size + public key
            pk_size_data = await asyncio.wait_for(
                reader.readexactly(2), HANDSHAKE_TIMEOUT
            )
            pk_size = struct.unpack(">H", pk_size_data)[0]
            public_key = await asyncio.wait_for(
                reader.readexactly(pk_size), HANDSHAKE_TIMEOUT
            )

            peer_id_size_data = await asyncio.wait_for(
                reader.readexactly(2), HANDSHAKE_TIMEOUT
            )
            peer_id_size = struct.unpack(">H", peer_id_size_data)[0]
            initiator_peer_id = (await asyncio.wait_for(
                reader.readexactly(peer_id_size), HANDSHAKE_TIMEOUT
            )).decode()

            logger.info(
                "Quantum handshake initiated by %s (pk=%d bytes)",
                initiator_peer_id, pk_size
            )

            # 3. Encapsulate shared secret
            if self._fallback:
                shared_secret = await self._fallback_encapsulate(public_key)
            else:
                ciphertext, shared_secret = self.oqs.encapsulate(public_key)

            # 4. Send ciphertext
            writer.write(struct.pack(">H", len(ciphertext)))
            writer.write(ciphertext)
            await writer.drain()

            # 5. Derive session key bound to both peer IDs
            combined_id = f"{initiator_peer_id}:{self.peer_id}"
            session_key = derive_session_key(shared_secret, combined_id)

            logger.info(
                "Quantum handshake complete — session established with %s",
                initiator_peer_id
            )
            return session_key

        except asyncio.TimeoutError:
            logger.error("Handshake timeout (%ds)", HANDSHAKE_TIMEOUT)
            return None
        except Exception as exc:
            logger.error("Handshake failed: %s", exc)
            return None

    async def _fallback_encapsulate(self, public_key: bytes) -> bytes:
        """
        Fallback when liboqs is unavailable: use X25519 ECDH.
        The 'public_key' in this case is an X25519 public key.
        """
        from cryptography.hazmat.primitives.asymmetric import x25519
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.kdf.hkdf import HKDF
        from cryptography.hazmat.primitives import hashes

        # Generate ephemeral X25519 keypair
        private_key = x25519.X25519PrivateKey.generate()
        public_bytes = private_key.public_key().public_bytes(
            serialization.Encoding.Raw, serialization.PublicFormat.Raw
        )
        peer_public = x25519.X25519PublicKey.from_public_bytes(public_key)

        # Compute shared secret
        shared_secret = private_key.exchange(peer_public)
        logger.warning("FALLBACK: using X25519 ECDH (not quantum-safe!)")
        return shared_secret


class QuantumHandshakeClient:
    """
    Initiator side of the quantum-safe handshake.
    Generates a Kyber keypair, sends the public key, receives ciphertext.
    """

    def __init__(self, peer_id: str = "client"):
        self.oqs = OQSProvider()
        self.peer_id = peer_id
        self._fallback = not self.oqs.available
        self._kyber_pub: Optional[bytes] = None
        self._kyber_sec: Optional[bytes] = None

    @property
    def public_key(self) -> Optional[bytes]:
        """Return the generated Kyber public key (after keygen)."""
        return self._kyber_pub

    async def handshake(self, reader: asyncio.StreamReader,
                        writer: asyncio.StreamWriter) -> Optional[bytes]:
        """
        Execute the initiator side of the Kyber handshake.

        Protocol:
          1. Send protocol version
          2. Generate Kyber keypair
          3. Send public key + peer ID
          4. Read ciphertext
          5. Decapsulate shared secret
          6. Derive and return session key
        """
        try:
            # 1. Send protocol version
            writer.write(PROTOCOL_VERSION)
            await writer.drain()

            # 2. Generate keypair
            if self._fallback:
                public_key = await self._fallback_keygen()
            else:
                self._kyber_sec, self._kyber_pub = self.oqs.generate_keypair()
                public_key = self._kyber_pub

            # 3. Send public key size + public key + peer ID
            peer_id_bytes = self.peer_id.encode()
            writer.write(struct.pack(">H", len(public_key)))
            writer.write(public_key)
            writer.write(struct.pack(">H", len(peer_id_bytes)))
            writer.write(peer_id_bytes)
            await writer.drain()

            # 4. Read ciphertext
            ct_size_data = await asyncio.wait_for(
                reader.readexactly(2), HANDSHAKE_TIMEOUT
            )
            ct_size = struct.unpack(">H", ct_size_data)[0]
            ciphertext = await asyncio.wait_for(
                reader.readexactly(ct_size), HANDSHAKE_TIMEOUT
            )

            # 5. Decapsulate shared secret
            if self._fallback:
                shared_secret = await self._fallback_decapsulate(
                    reader, writer, self._kyber_sec
                )
                # Re-derive for fallback path (already handled)
            else:
                shared_secret = self.oqs.decapsulate(self._kyber_sec, ciphertext)

            # Derive session key bound to both peer IDs
            # (at this point we don't know the server's peer_id yet,
            #  the server will append its own ID)
            session_key = derive_session_key(shared_secret, f"{self.peer_id}:server")

            logger.info("Quantum handshake complete — session established")
            return session_key

        except asyncio.TimeoutError:
            logger.error("Handshake timeout (%ds)", HANDSHAKE_TIMEOUT)
            return None
        except Exception as exc:
            logger.error("Handshake failed: %s", exc)
            return None

    async def _fallback_keygen(self) -> bytes:
        """Fallback X25519 key generation."""
        from cryptography.hazmat.primitives.asymmetric import x25519
        from cryptography.hazmat.primitives import serialization

        private_key = x25519.X25519PrivateKey.generate()
        self._kyber_sec = private_key  # Store the private key object
        self._kyber_pub = private_key.public_key().public_bytes(
            serialization.Encoding.Raw, serialization.PublicFormat.Raw
        )
        logger.warning("FALLBACK: using X25519 ECDH keypair (not quantum-safe!)")
        return self._kyber_pub

    async def _fallback_decapsulate(self, reader, writer, private_key) -> bytes:
        """Fallback: read server's X25519 public, compute ECDH."""
        from cryptography.hazmat.primitives.asymmetric import x25519
        from cryptography.hazmat.primitives import serialization

        serv_pk_size_data = await asyncio.wait_for(
            reader.readexactly(2), HANDSHAKE_TIMEOUT
        )
        serv_pk_size = struct.unpack(">H", serv_pk_size_data)[0]
        serv_pub_bytes = await asyncio.wait_for(
            reader.readexactly(serv_pk_size), HANDSHAKE_TIMEOUT
        )
        serv_pub = x25519.X25519PublicKey.from_public_bytes(serv_pub_bytes)
        shared_secret = private_key.exchange(serv_pub)
        return shared_secret


# ---------------------------------------------------------------------------
# Convenience: establish a quantum-safe connection
# ---------------------------------------------------------------------------
async def quantum_connect(
    host: str, port: int, peer_id: str = "client"
) -> Optional[Tuple[asyncio.StreamReader, asyncio.StreamWriter, bytes]]:
    """Open a TCP connection and perform a quantum-safe handshake."""
    try:
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(host, port), timeout=HANDSHAKE_TIMEOUT
        )
        client = QuantumHandshakeClient(peer_id=peer_id)
        session_key = await client.handshake(reader, writer)
        if session_key:
            return reader, writer, session_key
        writer.close()
        return None
    except Exception as exc:
        logger.error("Quantum connect failed to %s:%d: %s", host, port, exc)
        return None


async def quantum_serve(
    host: str, port: int, peer_id: str = "server",
    handler=None
):
    """Start a TCP server that performs a quantum-safe handshake on each connection."""
    from cryptography.hazmat.primitives.ciphers.aead import ChaCha20Poly1305

    async def _on_connect(reader, writer):
        server = QuantumHandshakeServer(peer_id=peer_id)
        session_key = await server.handshake(reader, writer)
        if session_key and handler:
            channel = SecureChannel(reader, writer, session_key, peer_id)
            await handler(channel)

    server = await asyncio.start_server(_on_connect, host, port)
    logger.info("Quantum-safe server listening on %s:%d (Kyber1024)", host, port)
    async with server:
        await server.serve_forever()


# ---------------------------------------------------------------------------
# Example / self-test
# ---------------------------------------------------------------------------
async def _example():
    """Demonstrate a loopback quantum handshake."""

    async def echo_handler(channel: SecureChannel):
        data = await channel.recv_encrypted()
        logger.info("Server received: %s", data.decode())
        await channel.send_encrypted(b"echo: " + data)

    # Start server in background
    server_task = asyncio.create_task(
        quantum_serve("127.0.0.1", 9999, peer_id="server-test", handler=echo_handler)
    )
    await asyncio.sleep(0.5)

    # Connect client
    result = await quantum_connect("127.0.0.1", 9999, peer_id="client-test")
    if result:
        reader, writer, session_key = result
        client_channel = SecureChannel(reader, writer, session_key, "client-test")
        await client_channel.send_encrypted(b"Hello quantum world!")
        response = await client_channel.recv_encrypted()
        logger.info("Client received: %s", response.decode())
        await client_channel.close()

    server_task.cancel()
    try:
        await server_task
    except asyncio.CancelledError:
        pass


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    )
    asyncio.run(_example())
