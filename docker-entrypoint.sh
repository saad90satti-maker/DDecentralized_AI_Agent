#!/bin/sh
# =============================================================================
# Ghost Engine — Docker Entrypoint
# =============================================================================
set -e

echo "╔══════════════════════════════════════════════════╗"
echo "║        Ghost Engine — Decentralized AI Agent     ║"
echo "╚══════════════════════════════════════════════════╝"

# ---------------------------------------------------------------------------
# 1. Validate required environment variables
# ---------------------------------------------------------------------------
if [ -z "$GEMINI_API_KEY" ] && [ -z "$GROQ_API_KEY" ]; then
    echo "⚠ WARNING: No GEMINI_API_KEY or GROQ_API_KEY set."
    echo "  Agent will fall back to local Ollama (if available)."
fi

# ---------------------------------------------------------------------------
# 2. Check IPFS connectivity
# ---------------------------------------------------------------------------
IPFS_MULTIADDR="${IPFS_MULTIADDR:-/dns/ipfs-node/tcp/5001/http}"
if command -v curl >/dev/null 2>&1; then
    IPFS_API="${IPFS_MULTIADDR#*/dns/}"
    IPFS_HOST=$(echo "$IPFS_API" | cut -d/ -f1)
    IPFS_PORT=$(echo "$IPFS_API" | cut -d/ -f3)
    if curl -sf "http://${IPFS_HOST}:${IPFS_PORT}/api/v0/version" >/dev/null 2>&1; then
        echo "✓ IPFS node reachable at ${IPFS_MULTIADDR}"
    else
        echo "⚠ IPFS node not reachable at ${IPFS_MULTIADDR}"
        echo "  Agent will operate in offline mode."
    fi
fi

# ---------------------------------------------------------------------------
# 3. Initialize agent data directories
# ---------------------------------------------------------------------------
mkdir -p /app/agent_logs /app/agent_data /app/browser_profile /app/session_data

# ---------------------------------------------------------------------------
# 4. Start the application
# ---------------------------------------------------------------------------
echo "Starting Ghost Engine..."
echo "  Mode:   ${GHOST_MODE:-dashboard}"
echo "  Port:   ${PORT:-8000}"
echo "  P2P:    ${ENABLE_P2P:-true} (port ${SWARM_PORT:-9876})"
echo ""

case "${GHOST_MODE:-dashboard}" in
    dashboard)
        exec uvicorn manager:app --host 0.0.0.0 --port "${PORT:-8000}" "$@"
        ;;
    agent)
        exec python run_agent.py "$@"
        ;;
    cli)
        exec python cli.py "$@"
        ;;
    executor)
        exec python ghost_executor.py "$@"
        ;;
    autonomous)
        exec python autonomous_agent.py "$@"
        ;;
    *)
        exec "$@"
        ;;
esac
