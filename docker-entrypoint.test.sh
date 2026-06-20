#!/bin/sh
# =============================================================================
# Ghost Engine — Test Entrypoint
# =============================================================================
set -e

echo "╔══════════════════════════════════════════════════╗"
echo "║   Ghost Engine — Automated Test Runner            ║"
echo "╚══════════════════════════════════════════════════╝"

echo ""
echo "Environment:"
echo "  IPFS:  ${IPFS_MULTIADDR:-(none, mock mode)}"
echo "  Redis: ${REDIS_URL:-(none, mock mode)}"
echo "  Ollama: ${HERMES_URL:-(none, mock mode)}"
echo "  Logs:  ${LOG_DIR:-/app/agent_logs}"
echo ""

# Validate that required services are reachable before running tests
echo "Pre-flight checks..."

# IPFS check (if configured)
if [ -n "$IPFS_MULTIADDR" ]; then
    IPFS_API="${IPFS_MULTIADDR#*/dns/}"
    IPFS_HOST=$(echo "$IPFS_API" | cut -d/ -f1)
    IPFS_PORT=$(echo "$IPFS_API" | cut -d/ -f3)
    if nc -z "$IPFS_HOST" "$IPFS_PORT" 2>/dev/null; then
        echo "  ✓ IPFS reachable at $IPFS_HOST:$IPFS_PORT"
    else
        echo "  ⚠ IPFS not reachable — integration tests will mock it"
    fi
fi

# Redis check (if configured)
if [ -n "$REDIS_URL" ]; then
    REDIS_HOST=$(echo "$REDIS_URL" | sed 's|redis://||' | cut -d: -f1)
    REDIS_PORT=$(echo "$REDIS_URL" | sed 's|redis://||' | cut -d: -f2 | cut -d/ -f1)
    if nc -z "$REDIS_HOST" "${REDIS_PORT:-6379}" 2>/dev/null; then
        echo "  ✓ Redis reachable at $REDIS_HOST:${REDIS_PORT:-6379}"
    else
        echo "  ⚠ Redis not reachable — integration tests will mock it"
    fi
fi

# FastAPI health check (if running)
if nc -z localhost 8000 2>/dev/null; then
    echo "  ✓ FastAPI dashboard reachable on port 8000"
else
    echo "  ○ FastAPI dashboard not running (inferring from module tests)"
fi

echo ""
echo "Starting test suite..."
echo "  Command: $@"
echo ""

# Run the test command (default: pytest)
exec "$@"
