"""
Cloud-Native Execution Layer v2 — NAT detection, auto-tunnel heartbeat,
and proactive external peering. If the system detects it is behind a
local NAT, it triggers an automated tunnel to expose the swarm mesh
to external peers.
"""

import os
import sys
import json
import time
import socket
import struct
import logging
import asyncio
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

logger = logging.getLogger("cloud_native")

# ---------------------------------------------------------------------------
# Private IP ranges for NAT detection
# ---------------------------------------------------------------------------

_PRIVATE_RANGES = [
    ("10.0.0.0", "10.255.255.255"),
    ("172.16.0.0", "172.31.255.255"),
    ("192.168.0.0", "192.168.255.255"),
    ("127.0.0.0", "127.255.255.255"),
]


def _ip_to_int(ip: str) -> int:
    return struct.unpack("!I", socket.inet_aton(ip))[0]


def is_private_ip(ip: str) -> bool:
    try:
        addr = _ip_to_int(ip)
        for start, end in _PRIVATE_RANGES:
            if _ip_to_int(start) <= addr <= _ip_to_int(end):
                return True
    except OSError:
        pass
    return False


def detect_nat() -> bool:

    # [AUTO-PATCH] Cache check — avoid redundant socket calls
    now = time.time()
    if (_NAT_CACHE["is_nat"] is not None
            and now - _NAT_CACHE["timestamp"] < _NAT_CACHE_TTL):
        return _NAT_CACHE["is_nat"], _NAT_CACHE["local_ip"]
    """Detect if this machine is behind NAT by checking its local IP."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("8.8.8.8", 80))
            local_ip = s.getsockname()[0]
        behind_nat = is_private_ip(local_ip)
        logger.info("NAT detection: local_ip=%s behind_nat=%s", local_ip, behind_nat)
        # [AUTO-PATCH] Update cache
        _NAT_CACHE["is_nat"] = is_nat
        _NAT_CACHE["local_ip"] = local_ip
        _NAT_CACHE["timestamp"] = time.time()
    
        return behind_nat
    except Exception as e:
        logger.warning("NAT detection failed: %s (assuming behind NAT)", e)
        return True


# ---------------------------------------------------------------------------
# Environment-based configuration
# ---------------------------------------------------------------------------


@dataclass
class CloudNativeConfig:
    host: str = os.getenv("HOST", "0.0.0.0")
    port: int = int(os.getenv("PORT", "7860"))
    public_url: str = os.getenv("PUBLIC_URL", "")
    manager_url: str = os.getenv("MANAGER_URL", f"http://localhost:{os.getenv('PORT', '7860')}")

    cdp_host: str = os.getenv("CDP_HOST", "127.0.0.1")
    cdp_port: int = int(os.getenv("CDP_PORT", "9222"))

    swarm_host: str = os.getenv("SWARM_HOST", "0.0.0.0")
    swarm_port: int = int(os.getenv("SWARM_PORT", "9876"))
    swarm_udp_port: int = int(os.getenv("SWARM_UDP_PORT", "8468"))

    dht_enabled: bool = os.getenv("DHT_ENABLED", "true").lower() == "true"
    dht_port: int = int(os.getenv("DHT_PORT", "8468"))
    dht_bootstrap: list = field(default_factory=lambda: os.getenv(
        "DHT_BOOTSTRAP",
        "router.bittorrent.com:6881,dht.libtorrent.org:25401,router.utorrent.com:6881",
    ).split(","))

    tunnel_enabled: bool = os.getenv("CF_TUNNEL_ENABLED", "false").lower() == "true"
    tunnel_token: str = os.getenv("CF_TUNNEL_TOKEN", "")
    auto_tunnel: bool = os.getenv("AUTO_TUNNEL", "true").lower() == "true"

    preferred_provider: str = os.getenv("PREFERRED_PROVIDER", "groq")
    preferred_model: str = os.getenv("PREFERRED_MODEL", "llama-3.3-70b")
    fallback_provider: str = os.getenv("FALLBACK_PROVIDER", "deepseek")
    fallback_model: str = os.getenv("FALLBACK_MODEL", "deepseek-chat")

    tor_enabled: bool = os.getenv("TOR_ENABLED", "false").lower() == "true"
    tor_socks_port: int = int(os.getenv("TOR_SOCKS_PORT", "9050"))
    tor_control_port: int = int(os.getenv("TOR_CONTROL_PORT", "9051"))

    redis_url: str = os.getenv("REDIS_URL", "")

    def to_dict(self) -> dict:
        return {k: v for k, v in self.__dict__.items() if not k.startswith("_")}

    def is_cloud_deployment(self) -> bool:
        return bool(self.public_url) or self.tunnel_enabled


# ---------------------------------------------------------------------------
# Cloudflare Tunnel Manager
# ---------------------------------------------------------------------------


class CloudflareTunnel:
    def __init__(self, config: CloudNativeConfig):
        self.config = config
        self._process: Optional[asyncio.subprocess.Process] = None
        self._tunnel_url: Optional[str] = None

    async def start(self) -> bool:
        if not self.config.tunnel_token:
            logger.warning("CF_TUNNEL_TOKEN not set")
            return False

        token = self.config.tunnel_token
        cmd = ["cloudflared", "tunnel", "--no-autoupdate", "run", "--token", token]
        logger.info("Starting Cloudflare Tunnel (port %d)...", self.config.port)
        try:
            self._process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            try:
                async with asyncio.timeout(15):
                    while True:
                        line = await self._process.stdout.readline()
                        decoded = line.decode(errors="replace").strip()
                        if decoded:
                            logger.info("[cloudflared] %s", decoded)
                            if "https://" in decoded and ".trycloudflare.com" in decoded:
                                for word in decoded.split():
                                    if word.startswith("https://") and ".trycloudflare.com" in word:
                                        self._tunnel_url = word.rstrip(".")
                                        logger.info("Tunnel URL: %s", self._tunnel_url)
                                        return True
                        if self._process.returncode is not None:
                            break
            except TimeoutError:
                logger.info("Tunnel started (URL pending)")
                return True
            return True
        except FileNotFoundError:
            logger.error("cloudflared not found: https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/downloads/")
            return False
        except Exception as e:
            logger.error("Tunnel error: %s", e)
            return False

    async def stop(self):
        if self._process:
            self._process.terminate()
            try:
                await asyncio.wait_for(self._process.wait(), timeout=10)
            except asyncio.TimeoutError:
                self._process.kill()
            self._process = None
            logger.info("Tunnel stopped")

    @property
    def url(self) -> str:
        return self._tunnel_url or self.config.public_url or f"http://localhost:{self.config.port}"

    def is_active(self) -> bool:
        return self._process is not None and self._process.returncode is None


# ---------------------------------------------------------------------------
# Heartbeat — announces this node's public endpoint to the swarm mesh
# ---------------------------------------------------------------------------


class HeartbeatSignal:
    """Periodic heartbeat that announces the node's public tunnel URL
    to external peers so the swarm mesh can discover and connect."""

    def __init__(self, config: CloudNativeConfig, tunnel: CloudflareTunnel,
                 interval: float = 60.0, shared_knowledge=None):
        self.config = config
        self.tunnel = tunnel
        self.interval = interval
        self._shared_knowledge = shared_knowledge
        self._running = False

    async def run_forever(self):
        if self.config.is_cloud_deployment():
            logger.info("Heartbeat: cloud deployment detected, skipping NAT tunnel")
            return

        behind_nat = detect_nat()
        if not behind_nat:
            logger.info("Heartbeat: not behind NAT, no tunnel needed")
            return

        logger.info("Heartbeat: behind NAT — activating auto-tunnel...")

        # Auto-activate tunnel if not already running
        if not self.tunnel.is_active():
            if self.config.auto_tunnel:
                # Try quick tunnel first (ephemeral, no token required)
                logger.info("Heartbeat: starting Cloudflare quick tunnel...")
                try:
                    self.tunnel._process = await asyncio.create_subprocess_exec(
                        "cloudflared", "tunnel", "--url", f"http://localhost:{self.config.port}",
                        "--no-autoupdate",
                        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
                    )
                    await asyncio.sleep(5)
                    if self.tunnel._process.returncode is not None:
                        logger.warning("Quick tunnel failed, trying token-based tunnel")
                        await self.tunnel.start()
                except FileNotFoundError:
                    logger.warning("cloudflared not available for auto-tunnel")
                    return
            else:
                logger.info("Heartbeat: auto_tunnel disabled")

        # Heartbeat loop — periodically announce public URL + shared knowledge
        self._running = True
        logger.info("Heartbeat started (interval=%ds, shared_knowledge=%s)",
                    self.interval, self._shared_knowledge is not None)

        import httpx
        while self._running:
            try:
                public = self.tunnel.url

                # Build payload with shared knowledge
                payload = {
                    "url": public,
                    "node_id": socket.gethostname(),
                    "role": "agent",
                }
                if self._shared_knowledge:
                    payload["knowledge"] = self._shared_knowledge.get_heartbeat_payload()

                async with httpx.AsyncClient(timeout=5) as client:
                    await client.post(
                        f"{self.config.manager_url}/api/swarm/announce",
                        json=payload,
                    )
            except Exception as e:
                logger.debug("Heartbeat announce: %s", e)

            await asyncio.sleep(self.interval)

    def stop(self):
        self._running = False


# ---------------------------------------------------------------------------
# NAT-aware startup helper
# ---------------------------------------------------------------------------


async def ensure_public_endpoint(config: CloudNativeConfig) -> Optional[str]:
    """If behind NAT, start a tunnel and return the public URL."""
    if not detect_nat():
        logger.info("Public endpoint: not behind NAT, using direct IP")
        return None

    if config.is_cloud_deployment():
        logger.info("Public endpoint: cloud deployment with URL=%s", config.public_url)
        return config.public_url

    tunnel = CloudflareTunnel(config)
    success = await tunnel.start()
    if success:
        logger.info("Public endpoint: tunnel active at %s", tunnel.url)
        return tunnel.url

    logger.warning("Public endpoint: tunnel failed, no external access")
    return None


# ---------------------------------------------------------------------------
# Env template
# ---------------------------------------------------------------------------


def generate_env_template(path: Optional[Path] = None) -> str:
    content = """# =============================================================================
# Ghost Engine — Cloud-Native Environment Configuration v2
# =============================================================================

HOST=0.0.0.0
PORT=7860
PUBLIC_URL=
MANAGER_URL=http://localhost:7860

# --- Remote LLM Providers ---
GROQ_API_KEY=
DEEPSEEK_API_KEY=
GEMINI_API_KEY=
OPENAI_API_KEY=
PREFERRED_PROVIDER=groq
PREFERRED_MODEL=llama-3.3-70b
FALLBACK_PROVIDER=deepseek
FALLBACK_MODEL=deepseek-chat

# --- API Gateway (latency-based switching) ---
GATEWAY_TIMEOUT=60
GATEWAY_MAX_RETRIES=3
GATEWAY_LATENCY_WINDOW=10
GATEWAY_LATENCY_THRESHOLD=5000

# --- Cloudflare Tunnel ---
CF_TUNNEL_ENABLED=false
CF_TUNNEL_TOKEN=
AUTO_TUNNEL=true

# --- Swarm Mesh ---
SWARM_HOST=0.0.0.0
SWARM_PORT=9876
SWARM_UDP_PORT=8468
DHT_ENABLED=true
DHT_PORT=8468
DHT_BOOTSTRAP=router.bittorrent.com:6881,dht.libtorrent.org:25401,router.utorrent.com:6881

# --- Chrome / CDP ---
CDP_HOST=127.0.0.1
CDP_PORT=9222

# --- Tor ---
TOR_ENABLED=false
TOR_SOCKS_PORT=9050
TOR_CONTROL_PORT=9051

# --- Redis ---
REDIS_URL=
"""
    if path:
        path.write_text(content)
        logger.info("Written .env template to %s", path)
    return content
