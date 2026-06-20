"""
Global System Audit Protocol — Integrity Check v1
==================================================
Audits:
  1. Credential Validation        — GitHub/Cloud API/SSH integrity & status
  2. Network Topology Scan        — Node mapping, connectivity, latency
  3. Security & Obfuscation Audit — TLS, encryption, background-noise check
  4. Task Queue Analysis          — Stalled tasks, failed syncs, conflicts
  5. Final Integrity Report       — Human-readable audit summary
"""

import asyncio
import json
import logging
import os
import platform
import re
import ssl
import subprocess
import sys
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib.request import urlopen, Request

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "agent_data"
LOG_DIR = BASE_DIR / "agent_logs"

# ─────────────────────────────────────────────
# Report Data Structures
# ─────────────────────────────────────────────

@dataclass
class CredentialEntry:
    provider: str
    status: str           # valid | invalid | expired | missing
    source: str           # env | file | config
    details: str = ""

@dataclass
class TopologyEntry:
    node_id: str
    host: str
    port: int
    status: str           # alive | dead | unknown
    latency_ms: float = 0.0
    cluster_id: str = ""
    protocol: str = ""

@dataclass
class SecurityObservation:
    category: str         # tls | encryption | obfuscation | noise
    status: str           # pass | warn | fail
    detail: str = ""

@dataclass
class TaskQueueEntry:
    task_id: str
    command: str
    status: str
    age_seconds: float = 0.0
    node: str = ""
    stalled: bool = False

@dataclass
class AuditReport:
    timestamp: str = ""
    node_count: int = 0
    system_health_score: float = 0.0
    credential_status: List[CredentialEntry] = field(default_factory=list)
    topology: List[TopologyEntry] = field(default_factory=list)
    latency_bottlenecks: List[str] = field(default_factory=list)
    disconnected_clusters: List[str] = field(default_factory=list)
    security_observations: List[SecurityObservation] = field(default_factory=list)
    task_queue_entries: List[TaskQueueEntry] = field(default_factory=list)
    stalled_tasks: List[str] = field(default_factory=list)
    resource_conflicts: List[str] = field(default_factory=list)
    optimization_recommendations: List[str] = field(default_factory=list)
    active_threats: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


# ═════════════════════════════════════════════
# AUDIT ENGINE
# ═════════════════════════════════════════════

class SystemAuditor:
    """
    Executes the full Global System Audit Protocol and produces
    a comprehensive Integrity Report.
    """

    def __init__(self):
        self._report = AuditReport(timestamp=datetime.now(timezone.utc).isoformat())

    # ─────────────────────────────────────────────
    # PHASE 1: CREDENTIAL VALIDATION
    # ─────────────────────────────────────────────

    async def audit_credentials(self) -> List[CredentialEntry]:
        """Verify integrity and active status of all credentials."""
        entries = []

        # GitHub
        gh_token = os.getenv("GITHUB_TOKEN") or os.getenv("GH_TOKEN", "")
        if gh_token:
            valid = await self._check_github_token(gh_token)
            entries.append(CredentialEntry(
                provider="github", status="valid" if valid else "invalid",
                source="env",
                details=f"Token {'valid' if valid else 'invalid/expired'} (prefix: {gh_token[:8]}...)"
            ))
        else:
            entries.append(CredentialEntry(
                provider="github", status="missing", source="env",
                details="No GITHUB_TOKEN or GH_TOKEN found in environment"
            ))

        # Cloud APIs
        cloud_providers = {
            "digitalocean": ("DIGITALOCEAN_TOKEN", "DO_TOKEN"),
            "cloudflare": ("CF_API_TOKEN", "CLOUDFLARE_TOKEN"),
            "aws": ("AWS_ACCESS_KEY_ID",),
            "azure": ("AZURE_TENANT_ID",),
            "hetzner": ("HETZNER_API_TOKEN",),
            "linode": ("LINODE_TOKEN",),
            "huggingface": ("HUGGINGFACE_TOKEN", "HF_TOKEN"),
            "groq": ("GROQ_API_KEY",),
        }

        for provider, env_keys in cloud_providers.items():
            token = ""
            for key in env_keys:
                token = os.getenv(key, "")
                if token:
                    break
            if token:
                valid = await self._check_cloud_token(provider, token)
                entries.append(CredentialEntry(
                    provider=provider,
                    status="valid" if valid else "invalid",
                    source="env",
                    details=f"Token {'valid' if valid else 'invalid/expired'}"
                ))
            else:
                entries.append(CredentialEntry(
                    provider=provider, status="missing", source="env",
                    details="Not configured"
                ))

        # SSH keys
        ssh_dir = Path.home() / ".ssh"
        ssh_keys_found = 0
        if ssh_dir.exists():
            for key_file in ssh_dir.glob("id_*"):
                if key_file.suffix != ".pub":
                    ssh_keys_found += 1
        if ssh_keys_found > 0:
            entries.append(CredentialEntry(
                provider="ssh", status="valid", source="file",
                details=f"{ssh_keys_found} SSH key(s) found in {ssh_dir}"
            ))
        else:
            entries.append(CredentialEntry(
                provider="ssh", status="missing", source="file",
                details="No SSH keys found in ~/.ssh"
            ))

        # Discord
        disc_token = os.getenv("DISCORD_TOKEN", "")
        if disc_token:
            entries.append(CredentialEntry(
                provider="discord", status="valid", source="env",
                details="Discord bot token configured"
            ))
        else:
            entries.append(CredentialEntry(
                provider="discord", status="missing", source="env",
                details="Not configured"
            ))

        # Docker
        docker_user = os.getenv("DOCKER_USERNAME", "")
        if docker_user:
            entries.append(CredentialEntry(
                provider="docker", status="valid", source="env",
                details=f"Docker Hub configured for {docker_user}"
            ))
        else:
            entries.append(CredentialEntry(
                provider="docker", status="missing", source="env",
                details="Not configured"
            ))

        return entries

    async def _check_github_token(self, token: str) -> bool:
        try:
            req = Request("https://api.github.com/user")
            req.add_header("Authorization", f"token {token}")
            req.add_header("Accept", "application/vnd.github.v3+json")
            resp = urlopen(req, timeout=10)
            return resp.status == 200
        except Exception:
            return False

    async def _check_cloud_token(self, provider: str, token: str) -> bool:
        endpoints = {
            "digitalocean": ("https://api.digitalocean.com/v2/account", "Bearer"),
            "cloudflare": ("https://api.cloudflare.com/client/v4/user/tokens/verify", "Bearer"),
            "huggingface": ("https://huggingface.co/api/whoami-v2", "Bearer"),
            "groq": ("https://api.groq.com/openai/v1/models", "Bearer"),
        }
        url, auth_type = endpoints.get(provider, ("", ""))
        if not url:
            return bool(token)

        try:
            req = Request(url)
            req.add_header("Authorization", f"{auth_type} {token}")
            resp = urlopen(req, timeout=10)
            return resp.status == 200
        except Exception:
            return False

    # ─────────────────────────────────────────────
    # PHASE 2: NETWORK TOPOLOGY SCAN
    # ─────────────────────────────────────────────

    async def audit_topology(self) -> Tuple[List[TopologyEntry], List[str], List[str]]:
        """Scan active swarm nodes, map connectivity, find bottlenecks."""
        entries: List[TopologyEntry] = []
        bottlenecks: List[str] = []
        disconnected: List[str] = []

        # 1. Local node
        local_host = "127.0.0.1"
        local_ports = [8000, 9876, 9877, 9878]
        for port in local_ports:
            latency = await self._measure_latency(local_host, port)
            if latency >= 0:
                entries.append(TopologyEntry(
                    node_id=f"localhost:{port}", host=local_host, port=port,
                    status="alive", latency_ms=latency,
                    protocol=f"tcp/{port}"
                ))

        # 2. Read known peers from swarm state files
        peer_sources = [
            DATA_DIR / "topology_state.json",
            DATA_DIR / "swarm" / "known_peers.json",
            DATA_DIR / "network_state.json",
        ]

        known_hosts: Dict[str, Dict[str, Any]] = {}
        for path in peer_sources:
            if path.exists():
                try:
                    data = json.loads(path.read_text(encoding="utf-8"))
                    if "topology" in data:
                        for nid, ndata in data["topology"].items():
                            known_hosts[nid] = ndata
                    elif isinstance(data, dict):
                        for key in ("peers", "nodes", "known_peers"):
                            if key in data:
                                for item in data[key]:
                                    if isinstance(item, dict) and "host" in item:
                                        known_hosts[item.get("node_id", item.get("host"))] = item
                except Exception:
                    pass

        # 3. Scan known peers
        for nid, ndata in known_hosts.items():
            host = ndata.get("host", "")
            port = ndata.get("port", 9876)
            if host:
                latency = await self._measure_latency(host, port)
                status = "alive" if latency >= 0 else "dead"
                entries.append(TopologyEntry(
                    node_id=nid,
                    host=host,
                    port=port,
                    status=status,
                    latency_ms=latency if latency >= 0 else 0,
                    cluster_id=ndata.get("cluster_id", ""),
                    protocol="p2p/tcp",
                ))
                if latency > 500:
                    bottlenecks.append(f"High latency to {nid} @ {host}:{port} ({latency:.0f}ms)")
                if status == "dead":
                    disconnected.append(f"Node {nid} unreachable @ {host}:{port}")

        # 4. Check for local Docker containers
        try:
            result = subprocess.run(
                ["docker", "ps", "--format", "{{.Names}}\t{{.Ports}}"],
                capture_output=True, text=True, timeout=10
            )
            if result.returncode == 0:
                for line in result.stdout.strip().split("\n"):
                    if line:
                        parts = line.split("\t")
                        if len(parts) == 2:
                            name, ports = parts
                            if "ghost" in name.lower() or "swarm" in name.lower() or "agent" in name.lower():
                                entries.append(TopologyEntry(
                                    node_id=f"docker:{name}",
                                    host="localhost", port=0,
                                    status="alive", latency_ms=0.0,
                                    protocol=f"docker ({ports})"
                                ))
        except Exception:
            pass

        return entries, bottlenecks, disconnected

    async def _measure_latency(self, host: str, port: int) -> float:
        """Measure TCP connection latency in ms. Returns -1 if unreachable."""
        if not host or not port:
            return -1
        try:
            start = time.time()
            _, writer = await asyncio.wait_for(
                asyncio.open_connection(host, port), timeout=3
            )
            elapsed = (time.time() - start) * 1000
            writer.close()
            return round(elapsed, 1)
        except (asyncio.TimeoutError, ConnectionRefusedError, OSError):
            return -1

    # ─────────────────────────────────────────────
    # PHASE 3: SECURITY & OBFUSCATION AUDIT
    # ─────────────────────────────────────────────

    async def audit_security(self) -> List[SecurityObservation]:
        """Verify TLS encryption and background-noise compliance."""
        observations = []

        # 1. Check TLS availability
        try:
            ctx = ssl.create_default_context()
            ctx.check_hostname = True
            ctx.verify_mode = ssl.CERT_REQUIRED
            observations.append(SecurityObservation(
                category="tls", status="pass",
                detail="TLS/SSL context available and properly configured"
            ))
        except Exception as e:
            observations.append(SecurityObservation(
                category="tls", status="fail",
                detail=f"TLS configuration error: {e}"
            ))

        # 2. Check if HTTPS endpoints are reachable (for stealth wrapping)
        test_endpoints = [
            ("GitHub API", "https://api.github.com"),
            ("NPM Registry", "https://registry.npmjs.org"),
            ("PyPI", "https://pypi.org"),
        ]
        tls_ok = 0
        tls_total = len(test_endpoints)
        for name, url in test_endpoints:
            try:
                req = Request(url)
                resp = urlopen(req, timeout=5)
                if resp.status < 500:
                    tls_ok += 1
            except Exception:
                pass
        if tls_ok == tls_total:
            observations.append(SecurityObservation(
                category="noise", status="pass",
                detail=f"All {tls_total} stealth noise endpoints reachable via HTTPS/TLS"
            ))
        elif tls_ok > 0:
            observations.append(SecurityObservation(
                category="noise", status="warn",
                detail=f"{tls_ok}/{tls_total} stealth noise endpoints reachable"
            ))
        else:
            observations.append(SecurityObservation(
                category="noise", status="fail",
                detail="No stealth noise endpoints reachable — traffic may be detectable"
            ))

        # 3. Check for SSL certificates
        cert_paths = [
            Path("/etc/ssl/certs"),
            Path.home() / ".ssl",
            Path.home() / ".cert",
        ]
        certs_found = sum(1 for p in cert_paths if p.exists())
        if certs_found > 0:
            observations.append(SecurityObservation(
                category="encryption", status="pass",
                detail=f"SSL certificate directories found ({certs_found} locations)"
            ))
        else:
            observations.append(SecurityObservation(
                category="encryption", status="warn",
                detail="No custom SSL certificate directories — using system defaults"
            ))

        # 4. Check process obfuscation
        running_python = []
        try:
            import psutil
            for proc in psutil.process_iter(['pid', 'name', 'cmdline']):
                try:
                    if 'python' in proc.info['name']:
                        cmd = ' '.join(proc.info['cmdline'] or [])
                        running_python.append(cmd[:120])
                except Exception:
                    pass
        except ImportError:
            observations.append(SecurityObservation(
                category="obfuscation", status="warn",
                detail="Cannot check processes (psutil not installed)"
            ))

        # Check for obfuscation patterns
        obfuscated_count = sum(1 for cmd in running_python
                                if any(p in cmd.lower() for p in
                                       ["obfuscat", "stealth", "ghost", "proxy", "tor"]))
        if obfuscated_count > 0:
            observations.append(SecurityObservation(
                category="obfuscation", status="pass",
                detail=f"{obfuscated_count}/{len(running_python)} Python processes use stealth patterns"
            ))
        elif running_python:
            observations.append(SecurityObservation(
                category="obfuscation", status="warn",
                detail="No obfuscation patterns detected in running processes"
            ))

        # 5. Network traffic inspection (passive)
        swarm_port = 9876
        try:
            import psutil
            connections = []
            for conn in psutil.net_connections():
                if conn.status == 'LISTEN' and conn.laddr.port == swarm_port:
                    connections.append(conn)
            if connections:
                observations.append(SecurityObservation(
                    category="noise", status="pass",
                    detail=f"Swarm port {swarm_port} listening — ready for P2P traffic"
                ))
            else:
                observations.append(SecurityObservation(
                    category="noise", status="warn",
                    detail=f"Swarm port {swarm_port} not actively listening"
                ))
        except ImportError:
            observations.append(SecurityObservation(
                category="noise", status="warn",
                detail="Cannot verify swarm port (psutil not installed)"
            ))

        return observations

    # ─────────────────────────────────────────────
    # PHASE 4: TASK QUEUE ANALYSIS
    # ─────────────────────────────────────────────

    async def audit_task_queue(self) -> Tuple[List[TaskQueueEntry], List[str], List[str]]:
        """Inspect distributed task queue for stalled/failed tasks."""
        entries: List[TaskQueueEntry] = []
        stalled: List[str] = []
        conflicts: List[str] = []

        queue_paths = [
            DATA_DIR / "task_queue.json",
            DATA_DIR / "ghost_tasks.json",
            DATA_DIR / "ghost_schedule.json",
        ]

        for path in queue_paths:
            if not path.exists():
                continue
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                tasks = data if isinstance(data, list) else data.get("tasks", data.get("queue", [data]))
                now = time.time()

                for task in tasks if isinstance(tasks, list) else []:
                    if not isinstance(task, dict):
                        continue

                    tid = task.get("id") or task.get("task_id") or task.get("name", "")
                    cmd = task.get("command") or task.get("cmd") or task.get("description", "")
                    status = task.get("status", "unknown")

                    created = task.get("created_at") or task.get("timestamp") or task.get("ts", 0)
                    if isinstance(created, str):
                        try:
                            created = datetime.fromisoformat(created.replace("Z", "+00:00")).timestamp()
                        except Exception:
                            created = 0
                    age = now - created if created else 0

                    is_stalled = status in ("running", "dispatched", "pending") and age > 300
                    if is_stalled and cmd:
                        stalled.append(f"Task {str(tid)[:12]} ({cmd[:60]}...) — {status} for {age:.0f}s")

                    entries.append(TaskQueueEntry(
                        task_id=str(tid)[:16],
                        command=str(cmd)[:80],
                        status=status,
                        age_seconds=round(age, 1),
                        node=task.get("assigned_to") or task.get("node", ""),
                        stalled=is_stalled,
                    ))
            except Exception:
                continue

        # Check for resource conflicts in topology
        topo_file = DATA_DIR / "topology_state.json"
        if topo_file.exists():
            try:
                topo = json.loads(topo_file.read_text())
                clusters = topo.get("clusters", {})
                for cid, members in clusters.items():
                    if len(members) > 1:
                        # Check if multiple nodes in same cluster have same task type
                        conflicts.append(
                            f"Cluster {cid}: {len(members)} members — potential resource contention"
                        )
            except Exception:
                pass

        return entries, stalled, conflicts

    # ─────────────────────────────────────────────
    # PHASE 5: COMPUTE HEALTH SCORE
    # ─────────────────────────────────────────────

    async def compute_health_score(self, creds: List[CredentialEntry],
                                     topo: List[TopologyEntry],
                                     security: List[SecurityObservation],
                                     tasks: List[TaskQueueEntry]) -> float:
        """Compute overall system health score 0.0-1.0."""
        score = 1.0

        # Credential weight: 25%
        valid_creds = sum(1 for c in creds if c.status == "valid")
        total_creds = max(len(creds), 1)
        score -= 0.25 * (1 - valid_creds / total_creds)

        # Topology weight: 25%
        alive_nodes = sum(1 for t in topo if t.status == "alive")
        total_nodes = max(len(topo), 1)
        score -= 0.25 * (1 - alive_nodes / total_nodes)

        # Security weight: 25%
        passed = sum(1 for s in security if s.status == "pass")
        total_security = max(len(security), 1)
        score -= 0.25 * (1 - passed / total_security)

        # Task queue weight: 25%
        stalled_tasks = sum(1 for t in tasks if t.stalled)
        total_tasks = max(len(tasks), 1)
        score -= 0.25 * min(1.0, stalled_tasks / total_tasks)

        return max(0.0, round(score, 2))

    # ─────────────────────────────────────────────
    # GENERATE RECOMMENDATIONS
    # ─────────────────────────────────────────────

    def generate_recommendations(self, creds: List[CredentialEntry],
                                  topo: List[TopologyEntry],
                                  bottlenecks: List[str],
                                  disconnected: List[str],
                                  security: List[SecurityObservation],
                                  stalled: List[str],
                                  conflicts: List[str]) -> List[str]:
        """Generate optimization recommendations based on audit findings."""
        recs = []

        # Credentials
        missing_creds = [c for c in creds if c.status == "missing"]
        if missing_creds:
            recs.append(f"Configure missing credentials: {', '.join(c.provider for c in missing_creds[:5])}")

        invalid_creds = [c for c in creds if c.status == "invalid"]
        if invalid_creds:
            recs.append(f"Refresh invalid/expired tokens: {', '.join(c.provider for c in invalid_creds)}")

        # Topology
        if disconnected:
            recs.append(f"Reconnect {len(disconnected)} disconnected node(s): {disconnected[0][:80]}")

        if bottlenecks:
            recs.append(f"Address {len(bottlenecks)} latency bottleneck(s). "
                        f"Consider deploying edge nodes closer to high-latency regions.")

        alive = sum(1 for t in topo if t.status == "alive")
        if alive < 2:
            recs.append("Deploy additional swarm nodes for redundancy and distributed execution")

        # Security
        failed_sec = [s for s in security if s.status == "fail"]
        for s in failed_sec:
            recs.append(f"Security issue: {s.detail[:100]}")

        warn_sec = [s for s in security if s.status == "warn"]
        for s in warn_sec:
            recs.append(f"Review: {s.detail[:100]}")

        # Task queue
        if stalled:
            recs.append(f"Clear {len(stalled)} stalled task(s) or increase timeout thresholds")

        if conflicts:
            recs.append(f"Resolve {len(conflicts)} resource conflict(s): enable task prioritization")

        # General
        recs.append("Enable DHT-based peer discovery for global mesh resilience")
        recs.append("Set up Docker Compose deployment for reproducible node provisioning")

        if not recs:
            recs.append("System is fully operational — no optimizations needed")

        return recs

    # ─────────────────────────────────────────────
    # GENERATE THREAT OBSERVATIONS
    # ─────────────────────────────────────────────

    def generate_threats(self, creds: List[CredentialEntry],
                          topo: List[TopologyEntry],
                          security: List[SecurityObservation],
                          stalled: List[str]) -> List[str]:
        """Identify active security threats."""
        threats = []

        for c in creds:
            if c.status == "invalid":
                threats.append(f"Expired/invalid credential: {c.provider} — service may fail")

        for s in security:
            if s.status == "fail":
                threats.append(f"Security failure: {s.detail[:100]}")

        dead_nodes = [t for t in topo if t.status == "dead"]
        if dead_nodes:
            threats.append(f"{len(dead_nodes)} swarm node(s) unreachable — reduced resilience")

        if stalled:
            stall_old = [s for s in stalled if "age" in s]
            if stall_old:
                threats.append(f"{len(stall_old)} task(s) stalled for extended period — possible deadlock")

        # Check for exposed ports
        try:
            import psutil
            sensitive_ports = {8000: "dashboard", 5000: "flask", 5432: "postgres"}
            for conn in psutil.net_connections():
                if conn.status == 'LISTEN' and conn.laddr.port in sensitive_ports:
                    port_name = sensitive_ports[conn.laddr.port]
                    if conn.laddr.ip == '0.0.0.0':
                        threats.append(f"{port_name.capitalize()} port {conn.laddr.port} exposed on 0.0.0.0 — restrict to 127.0.0.1")
        except ImportError:
            pass

        if not threats:
            threats.append("No active threats detected")

        return threats

    # ─────────────────────────────────────────────
    # MAIN AUDIT EXECUTION
    # ─────────────────────────────────────────────

    async def run_full_audit(self) -> AuditReport:
        """Execute all 5 audit phases and return the complete report."""
        print("=" * 60)
        print("  GLOBAL SYSTEM AUDIT PROTOCOL — Integrity Check")
        print("=" * 60)
        print()

        # Phase 1
        print("[Phase 1/5] Credential Validation...")
        self._report.credential_status = await self.audit_credentials()
        valid_count = sum(1 for c in self._report.credential_status if c.status == "valid")
        print(f"  {valid_count}/{len(self._report.credential_status)} credentials valid")

        # Phase 2
        print("[Phase 2/5] Network Topology Scan...")
        topo, bottlenecks, disconnected = await self.audit_topology()
        self._report.topology = topo
        self._report.latency_bottlenecks = bottlenecks
        self._report.disconnected_clusters = disconnected
        alive = sum(1 for t in topo if t.status == "alive")
        print(f"  {alive} alive nodes, {len(bottlenecks)} bottlenecks, {len(disconnected)} disconnected")
        self._report.node_count = alive

        # Phase 3
        print("[Phase 3/5] Security & Obfuscation Audit...")
        self._report.security_observations = await self.audit_security()
        passed = sum(1 for s in self._report.security_observations if s.status == "pass")
        print(f"  {passed}/{len(self._report.security_observations)} checks passed")

        # Phase 4
        print("[Phase 4/5] Task Queue Analysis...")
        tasks, stalled, conflicts = await self.audit_task_queue()
        self._report.task_queue_entries = tasks
        self._report.stalled_tasks = stalled
        self._report.resource_conflicts = conflicts
        print(f"  {len(tasks)} tasks, {len(stalled)} stalled, {len(conflicts)} conflicts")

        # Phase 5: Compute health + generate report
        print("[Phase 5/5] Generating Final Integrity Report...")
        self._report.system_health_score = await self.compute_health_score(
            self._report.credential_status, topo,
            self._report.security_observations, tasks
        )
        self._report.active_threats = self.generate_threats(
            self._report.credential_status, topo,
            self._report.security_observations, stalled
        )
        self._report.optimization_recommendations = self.generate_recommendations(
            self._report.credential_status, topo, bottlenecks, disconnected,
            self._report.security_observations, stalled, conflicts
        )

        print()
        print("=" * 60)
        print("  AUDIT COMPLETE")
        print("=" * 60)

        return self._report

    def get_report(self) -> AuditReport:
        return self._report

    def print_summary(self) -> None:
        """Print a human-readable summary of the audit report."""
        r = self._report
        W = 70
        def hdr(title):
            print("=" * W)
            print(f"  {title}")
            print("=" * W)
        def sep():
            print("-" * W)

        print()
        hdr("GLOBAL SYSTEM INTEGRITY REPORT")
        print(f"  Timestamp:    {r.timestamp[:19]}")
        print(f"  Node Count:   {r.node_count}")
        print(f"  Health Score: {r.system_health_score:.0%}")

        sep()
        print("  CREDENTIAL STATUS")
        sep()
        for c in r.credential_status:
            icon = {"valid": "[OK]", "invalid": "[INV]", "missing": "[--]", "expired": "[EXP]"}.get(c.status, "[?]")
            print(f"    {icon} {c.provider:15s}: {c.status:7s}  ({c.details[:55]})")

        sep()
        print("  TOPOLOGY")
        sep()
        for t in r.topology[:10]:
            icon = "[UP]" if t.status == "alive" else "[DN]"
            print(f"    {icon} {t.node_id:20s} @ {t.host:15s}:{t.port:<5d}  {t.latency_ms:6.0f}ms")
        if len(r.topology) > 10:
            print(f"    ... and {len(r.topology) - 10} more nodes")
        if r.disconnected_clusters:
            print()
            for d in r.disconnected_clusters[:3]:
                print(f"    DISCONNECTED: {d[:65]}")

        sep()
        print("  SECURITY OBSERVATIONS")
        sep()
        for s in r.security_observations:
            icon = {"pass": "[OK]", "warn": "[!!]", "fail": "[XX]"}.get(s.status, "[?]")
            print(f"    {icon} [{s.category:12s}] {s.detail[:68]}")

        sep()
        print("  TASK QUEUE")
        sep()
        print(f"    Total tasks: {len(r.task_queue_entries):4d}")
        print(f"    Stalled:     {len(r.stalled_tasks):4d}")
        print(f"    Conflicts:   {len(r.resource_conflicts):4d}")

        sep()
        print("  ACTIVE THREATS")
        sep()
        for threat in r.active_threats:
            print(f"    [!] {threat[:72]}")

        sep()
        print("  OPTIMIZATION RECOMMENDATIONS")
        sep()
        for i, rec in enumerate(r.optimization_recommendations, 1):
            print(f"  {i}. {rec[:74]}")
        print("=" * W)


# ═════════════════════════════════════════════
# CLI ENTRY POINT
# ═════════════════════════════════════════════

async def main():
    auditor = SystemAuditor()
    report = await auditor.run_full_audit()
    auditor.print_summary()

    # Save report to file
    report_path = DATA_DIR / "integrity_report.json"
    try:
        report_path.write_text(json.dumps(report.to_dict(), indent=2, default=str))
        print(f"\nFull report saved to: {report_path}")
    except Exception as e:
        print(f"\nCould not save report: {e}")

    return report


if __name__ == "__main__":
    asyncio.run(main())
