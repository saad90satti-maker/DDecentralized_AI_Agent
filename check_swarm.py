"""
Check swarm peer discovery by reading status files from docker-compose.swarm.yml

Usage:
  docker compose -f docker-compose.swarm.yml up --build -d
  python check_swarm.py
"""
import json
import subprocess
import time
from pathlib import Path


def find_status_files():
    """Locate status files from the swarm-status Docker volume."""
    containers = ["ghost-swarm-node1", "ghost-swarm-node2"]
    for cname in containers:
        try:
            result = subprocess.run(
                ["docker", "inspect", cname],
                capture_output=True, text=True, timeout=5
            )
            if result.returncode != 0:
                continue
            data = json.loads(result.stdout)
            mounts = data[0].get("Mounts", [])
            for m in mounts:
                if m["Destination"] == "/shared":
                    src = Path(m["Source"])
                    files = sorted(src.glob("status_*.json"))
                    if files:
                        return src, files
        except Exception:
            continue
    return None, []


def print_table(rows, headers):
    col_widths = [
        max(len(str(row[i])) for row in rows + [headers])
        for i in range(len(headers))
    ]
    header_line = " | ".join(
        h.ljust(w) for h, w in zip(headers, col_widths)
    )
    sep = "-+-".join("-" * w for w in col_widths)
    print(f"  {header_line}")
    print(f"  {sep}")
    for row in rows:
        print(f"  {' | '.join(str(v).ljust(w) for v, w in zip(row, col_widths))}")


def main():
    print()
    print("=" * 64)
    print("  GHOST ENGINE \u2014 P2P Swarm Peer Discovery Check")
    print("=" * 64)
    print()

    base_dir, files = find_status_files()

    if not files:
        print("  [!] No swarm status files found.")
        print()
        print("  Make sure the swarm containers are running:")
        print("    docker compose -f docker-compose.swarm.yml up --build -d")
        print()
        print("  Check container logs:")
        print("    docker logs ghost-swarm-node1")
        print("    docker logs ghost-swarm-node2")
        print()
        return

    print(f"  Status directory: {base_dir}")
    print(f"  Nodes found:      {len(files)}")
    print()

    all_nodes = {}
    for f in files:
        try:
            data = json.loads(f.read_text("utf-8"))
            nid = data.get("node_id", f.stem)
            all_nodes[nid] = data
        except (json.JSONDecodeError, KeyError) as e:
            print(f"  [!] Could not read {f.name}: {e}")

    for nid, data in all_nodes.items():
        peers = data.get("peers", [])
        alive_peers = [p for p in peers if p.get("alive")]

        print(f"  Node: {nid}")
        print(f"  {'-' * 60}")
        print(f"    Port:          {data.get('port', '?')}")
        print(f"    Running:       {data.get('running', False)}")
        print(f"    DHT ready:     {data.get('dht', False)}")
        print(f"    Mode:          {data.get('mode', '?')}")
        print(f"    Peers total:   {data.get('peers_total', 0)}")
        print(f"    Peers alive:   {data.get('peers_alive', 0)}")
        print(f"    Tasks pending: {data.get('pending_tasks', 0)}")
        print()

        if peers:
            headers = ["Peer ID", "Host", "Port", "Alive", "Capabilities", "Version"]
            rows = []
            for p in peers:
                pid = p.get("node_id", "?")[:24]
                host = p.get("host", "?")
                port = str(p.get("port", "?"))
                alive = "YES" if p.get("alive") else "no"
                caps = ",".join(p.get("capabilities", [])) or "-"
                ver = p.get("version", "-")[:10]
                rows.append((pid, host, port, alive, caps, ver))
            print_table(rows, headers)
        else:
            print("    [No peers discovered]")
        print()

    print(f"  {'=' * 60}")
    total_peers = sum(data.get("peers_alive", 0) for data in all_nodes.values())
    print(f"  Total nodes: {len(all_nodes)} | Total live peer connections: {total_peers}")
    print()

    if len(all_nodes) >= 2:
        all_discovered = True
        for nid, data in all_nodes.items():
            alive = data.get("peers_alive", 0)
            expected = len(all_nodes) - 1
            if alive < expected:
                all_discovered = False
                print(f"  [!] {nid} has only {alive}/{expected} expected peers")

        if all_discovered:
            print("  [OK] All nodes successfully discovered each other!")
        else:
            print("  [~] Some nodes have not fully connected yet (may need more time)")
    else:
        print("  [~] Only one node found - waiting for the second to come online")
    print()


if __name__ == "__main__":
    main()
