# =============================================================================
# Ghost Engine — Multi-Stage Docker Build
# Decentralized AI Agent Framework
# =============================================================================
# Build:     docker build -t ghost-engine:latest .
# Run:       docker run -p 8000:8000 -p 9876:9876 --env-file .env ghost-engine
# Compose:   docker compose up -d
# =============================================================================

# ---------------------------------------------------------------------------
# STAGE 1: Base — shared system dependencies
# ---------------------------------------------------------------------------
FROM python:3.11-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    DEBIAN_FRONTEND=noninteractive

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    wget \
    git \
    ca-certificates \
    gnupg \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# ---------------------------------------------------------------------------
# STAGE 2: Python dependencies layer (cached independently of source)
# ---------------------------------------------------------------------------
FROM base AS deps

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Install Playwright system dependencies + Chromium browser
RUN pip install --no-cache-dir playwright \
    && playwright install --with-deps chromium \
    && playwright install-deps \
    && rm -rf /root/.cache /tmp/*

# Additional IPFS and P2P dependencies for decentralized architecture
RUN pip install --no-cache-dir \
    ipfshttpclient \
    web3 \
    eth-account \
    kademlia

# ---------------------------------------------------------------------------
# STAGE 3: Runtime — minimal footprint
# ---------------------------------------------------------------------------
FROM base AS runtime

# Copy installed Python packages from deps stage
COPY --from=deps /usr/local/lib/python3.11/site-packages /usr/local/lib/python3.11/site-packages
COPY --from=deps /usr/local/bin /usr/local/bin

# Copy Playwright browsers
COPY --from=deps /root/.cache/ms-playwright /root/.cache/ms-playwright

# Copy entrypoint script
COPY docker-entrypoint.sh /usr/local/bin/
RUN chmod +x /usr/local/bin/docker-entrypoint.sh

# Create non-root user for security
RUN groupadd -r ghost && useradd -r -g ghost -d /app -s /bin/bash ghost \
    && mkdir -p /app/agent_logs /app/agent_data /app/agent_data/swarm /app/browser_profile \
    && chown -R ghost:ghost /app

# Copy application source
COPY --chown=ghost:ghost . .

# Create directories if missing (for mounted volumes)
RUN mkdir -p agent_logs agent_data browser_profile session_data frames agent_data/swarm

# Expose ports:
#   8000  — FastAPI dashboard / REST API
#   9876  — P2P swarm TCP (libp2p / Kademlia)
#   9877  — P2P swarm UDP broadcast
#   8468  — Kademlia DHT port
EXPOSE 8000 9876 9877 8468

# Volumes for persistent + decentralized data
VOLUME ["/app/agent_logs", "/app/agent_data", "/app/browser_profile", "/app/session_data"]

# Use the smart entrypoint; supports GHOST_MODE=dashboard|agent|cli|executor|autonomous
ENTRYPOINT ["docker-entrypoint.sh"]

# Default mode: FastAPI management dashboard
CMD ["dashboard"]
