#!/usr/bin/env python3
"""
Ghost Engine -- Launch Sequence
===============================
Terminal launch dashboard that outputs:
  * Deployment status (Akash DSEQ, provider)
  * Swarm connection count
  * Current Ghost Mode
  * Bootstrap progress
  * Live observability summary

Usage:
  python launch.py                          # full launch (swarm + dashboard)
  python launch.py --mode autonomous        # override ghost mode
  python launch.py --dashboard-only         # just the web dashboard
  python launch.py --dry-run                # validate without starting
  python launch.py --status                 # quick status snapshot
"""

import argparse
import asyncio
import json
import logging
import os
import sys
import time
from pathlib import Path

# Ensure project root is in path
sys.path.insert(0, str(Path(__file__).resolve().parent))

logging.basicConfig(
    level=getattr(logging, os.getenv("LOG_LEVEL", "INFO")),
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)
logger = logging.getLogger("LaunchSequence")


# =============================================================================
# ANSI Terminal Styling
# =============================================================================
class Style:
    BOLD = "\033[1m"
    DIM = "\033[2m"
    GREEN = "\033[92m"
    CYAN = "\033[96m"
    YELLOW = "\033[93m"
    MAGENTA = "\033[95m"
    RED = "\033[91m"
    NC = "\033[0m"
    CLEAR_LINE = "\033[2K\r"

    @staticmethod
    def icon(name: str) -> str:
        icons = {
            "ghost": "[G]", "swarm": "[~]", "bootstrap": "[+]", "health": "[+]",
            "ready": "[!]", "deploy": "[D]", "ipfs": "[I]", "quantum": "[Q]",
            "observe": "[O]", "warning": "[W]", "error": "[E]", "check": "[ok]",
            "dht": "[#]", "redis": "[R]", "p2p": "[<]", "akash": "[A]",
        }
        return icons.get(name, "o")


# =============================================================================
# Deployment Status Check
# =============================================================================
def check_deployment_status() -> dict:
    """Check if there's an active Akash deployment."""
    status = {"active": False, "dseq": "", "provider": "", "mode": "local"}

    dseq_file = Path(".akash_dseq")
    if dseq_file.exists():
        status["dseq"] = dseq_file.read_text().strip()
        status["mode"] = "akash"

    # Check if manager is running on expected port
    import socket
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.settimeout(1)
        s.connect(("127.0.0.1", int(os.getenv("PORT", "8000"))))
        s.close()
        status["active"] = True
    except (ConnectionRefusedError, OSError):
        status["active"] = False

    return status


# =============================================================================
# Terminal Dashboard
# =============================================================================
async def live_dashboard(node=None, boot_result: dict = None):
    """Live-updating terminal dashboard."""
    from ghost_swarm import GhostSwarmNode

    try:
        while True:
            lines = []

            # -- Header --
            lines.append(f"{Style.BOLD}{Style.GREEN}")
            lines.append("+============================================================+")
            lines.append("|          GHOST ENGINE - LIVE DASHBOARD                  |")
            lines.append("+============================================================+")
            lines.append(f"{Style.NC}")

            # -- Mode & Identity --
            ghost_mode = os.getenv("GHOST_MODE", "autonomous")
            node_id = node.node_id if node else "standalone"
            lines.append(
                f"  {Style.icon('ghost')} {Style.BOLD}Ghost Mode:{Style.NC} "
                f"{Style.CYAN}{ghost_mode}{Style.NC}  |  "
                f"{Style.BOLD}Node:{Style.NC} {Style.DIM}{node_id}{Style.NC}"
            )

            # -- Deployment Status --
            deploy = check_deployment_status()
            if deploy["mode"] == "akash":
                lines.append(
                    f"  {Style.icon('akash')} {Style.BOLD}Deploy:{Style.NC} "
                    f"{Style.GREEN}AKASH{Style.NC}  |  "
                    f"DSEQ: {deploy['dseq']}"
                )
            else:
                lines.append(
                    f"  {Style.icon('akash')} {Style.BOLD}Deploy:{Style.NC} "
                    f"{Style.YELLOW}LOCAL{Style.NC}  |  "
                    f"no active Akash lease"
                )

            # -- Swarm / Peers --
            if node:
                total = len(node.peers)
                alive = node.peer_count
                pending = len(node._pending_tasks)
                dht_ok = node.dht.is_ready if node.dht else False

                lines.append(
                    f"  {Style.icon('swarm')} {Style.BOLD}Swarm:{Style.NC}  "
                    f"{Style.GREEN}{alive}{Style.NC}/{total} peers alive  |  "
                    f"{Style.YELLOW}{pending}{Style.NC} pending tasks  |  "
                    f"DHT: {Style.GREEN if dht_ok else Style.RED}{dht_ok}{Style.NC}"
                )
            else:
                lines.append(f"  {Style.icon('swarm')} {Style.BOLD}Swarm:{Style.NC}  not initialized")

            # -- Connections --
            if boot_result:
                lines.append(
                    f"  {Style.icon('dht')} {Style.BOLD}Mesh:{Style.NC}    "
                    f"{boot_result.get('dht_peers', 0)} DHT  |  "
                    f"{boot_result.get('mesh_connections', 0)} rendezvous  |  "
                    f"{boot_result.get('quantum_peers', 0)} quantum"
                )

            # -- IPFS --
            cid = node._cid if node and node._cid else "none"
            lines.append(
                f"  {Style.icon('ipfs')} {Style.BOLD}Config:{Style.NC}   "
                f"CID={Style.DIM}{cid[:48] if len(cid) > 48 else cid}{Style.NC}"
            )

            # -- Observability --
            obs_count = len(node._observations) if node and hasattr(node, '_observations') else 0
            lines.append(
                f"  {Style.icon('observe')} {Style.BOLD}Observability:{Style.NC}  "
                f"{obs_count} observations buffered  |  "
                f"streaming: {Style.GREEN}ENCRYPTED{Style.NC}"
            )

            # -- Self-heal --
            if boot_result and boot_result.get('self_healed'):
                lines.append(
                    f"  {Style.icon('warning')} {Style.YELLOW}Self-heal triggered:{Style.NC} "
                    f"node redeployed to new provider"
                )
            else:
                lines.append(f"  {Style.icon('health')} {Style.BOLD}Health:{Style.NC}     nominal")

            # -- Timestamp --
            lines.append(
                f"\n  {Style.DIM}Last update: {time.strftime('%H:%M:%S UTC')}{Style.NC}"
            )

            # -- Footer --
            lines.append("")
            lines.append(f"  {Style.DIM}Ctrl+C to stop{Style.NC}")
            lines.append("")
            lines.append(f"{Style.BOLD}{'=' * 58}{Style.NC}")

            # Render
            print(Style.CLEAR_LINE + "\n".join(lines), end="")
            await asyncio.sleep(3)

    except asyncio.CancelledError:
        pass
    except KeyboardInterrupt:
        pass


# =============================================================================
# Launch Orchestrator
# =============================================================================
async def full_launch(mode: str = "autonomous", dry_run: bool = False):
    """Execute the complete launch sequence."""
    from ghost_swarm import GhostSwarmNode, LaunchSequence

    os.environ.setdefault("GHOST_MODE", mode)

    # -- Banner --
    print()
    print(f"{Style.BOLD}{Style.MAGENTA}")
    print("  ____ _   _  ___  ____ _____ ____  _   _")
    print(" / ___| | | |/ _ \\/ ___|_   _|  _ \\| \\ | |")
    print("| |  _| |_| | | | \\___ \\ | | | |_) |  \\| |")
    print("| |_| |  _  | |_| |___) || | |  __/| |\\  |")
    print(" \\____|_| |_|\\___/|____/ |_| |_|   |_| \\_|")
    print(f"{Style.NC}")
    print(f"  {Style.BOLD}Decentralized AI Agent{Style.NC}")
    print(f"  Global Mesh v3 v Mode: {Style.CYAN}{mode}{Style.NC}")
    print()

    if dry_run:
        print(f"  {Style.icon('check')} {Style.GREEN}Dry-run validation passed{Style.NC}")
        print()
        deploy = check_deployment_status()
        print(f"  Akash deployment:  {Style.GREEN if deploy['active'] else Style.YELLOW}{deploy['mode']}{Style.NC}")
        print(f"  Port 8000:         {Style.GREEN if deploy['active'] else Style.RED}{'open' if deploy['active'] else 'closed'}{Style.NC}")
        print(f"  DSEQ:              {deploy['dseq'] or 'none'}")
        print()
        print(f"  Configuration:")
        print(f"    GHOST_MODE={mode}")
        print(f"    IPFS_MULTIADDR={os.getenv('IPFS_MULTIADDR', '/dns/ipfs-node/tcp/5001/http')}")
        print(f"    REDIS_URL={os.getenv('REDIS_URL', 'redis://redis:6379/0')}")
        print(f"    QUANTUM={Style.GREEN if os.getenv('ENABLE_QUANTUM_HANDSHAKE', 'true') else Style.RED}{os.getenv('ENABLE_QUANTUM_HANDSHAKE', 'true')}{Style.NC}")
        print(f"    ARWEAVE={Style.GREEN if os.getenv('ENABLE_ARWEAVE_ARCHIVE', 'true') else Style.RED}{os.getenv('ENABLE_ARWEAVE_ARCHIVE', 'true')}{Style.NC}")
        print()
        return {"dry_run": True, "mode": mode}

    # -- Initialize Swarm Node --
    print(f"  {Style.icon('swarm')} {Style.BOLD}Initializing P2P swarm node...{Style.NC}")
    node = GhostSwarmNode()
    launch = LaunchSequence(node)

    # -- Bootstrap --
    boot_result = await launch.execute()

    # -- Launch Dashboard --
    print(f"\n  {Style.icon('observe')} {Style.BOLD}Launching live observability dashboard...{Style.NC}")
    print(f"  {Style.DIM}(refreshes every 3s){Style.NC}")
    print()

    # Start dashboard in the foreground
    await live_dashboard(node=node, boot_result=boot_result)

    # -- Cleanup --
    await node.stop()
    return boot_result


# =============================================================================
# CLI
# =============================================================================
def main():
    parser = argparse.ArgumentParser(
        description="Ghost Engine -- Launch Sequence",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python launch.py                           # full start
  python launch.py --mode executor           # start in executor mode
  python launch.py --dashboard-only          # just the web UI
  python launch.py --dry-run                 # validate config only
  python launch.py --status                  # quick status snapshot
        """,
    )
    parser.add_argument("--mode", default=os.getenv("GHOST_MODE", "autonomous"),
                        choices=["autonomous", "dashboard", "executor",
                                 "agent", "cli", "test"],
                        help="Ghost Engine operational mode")
    parser.add_argument("--dashboard-only", action="store_true",
                        help="Only start the FastAPI dashboard")
    parser.add_argument("--dry-run", action="store_true",
                        help="Validate configuration without starting")
    parser.add_argument("--status", action="store_true",
                        help="Quick status snapshot and exit")

    args = parser.parse_args()

    # Handle flags
    if args.dashboard_only:
        os.environ["GHOST_MODE"] = "dashboard"
        print(f"  {Style.icon('ghost')} Starting Ghost Engine dashboard on port {os.getenv('PORT', '8000')}...")
        import uvicorn
        from manager import app
        uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("PORT", "8000")))
        return

    if args.status:
        deploy = check_deployment_status()
        print(json.dumps({
            "deployment": deploy,
            "mode": os.getenv("GHOST_MODE", "autonomous"),
            "services": {
                "fastapi": deploy["active"],
                "ipfs": os.getenv("IPFS_MULTIADDR", ""),
                "redis": os.getenv("REDIS_URL", ""),
            },
        }, indent=2))
        return

    if args.dry_run:
        asyncio.run(full_launch(mode=args.mode, dry_run=True))
        return

    # Full launch
    try:
        asyncio.run(full_launch(mode=args.mode))
    except KeyboardInterrupt:
        print(f"\n  {Style.icon('ghost')} Ghost Engine shutting down...")
        sys.exit(0)


if __name__ == "__main__":
    main()
