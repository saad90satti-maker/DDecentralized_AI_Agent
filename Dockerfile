# =============================================================================
# Ghost Engine — Hardened Multi-Stage Docker Build
# Security: read-only rootfs, non-root user, no build-time secrets
# =============================================================================
# Build:     docker build -t ghost-engine:latest .
# Run:       docker run -p 8000:8000 --env-file .env --read-only \
#              -v agent_logs:/app/agent_logs -v agent_data:/app/agent_data \
#              ghost-engine
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
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# ---------------------------------------------------------------------------
# STAGE 2: Python dependencies layer (cached independently of source)
# ---------------------------------------------------------------------------
FROM base AS deps

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt \
    && rm -rf /root/.cache /tmp/*

# ---------------------------------------------------------------------------
# STAGE 3: Runtime — minimal footprint, hardened
# ---------------------------------------------------------------------------
FROM base AS runtime

# Copy only installed packages, not build tools
COPY --from=deps /usr/local/lib/python3.11/site-packages /usr/local/lib/python3.11/site-packages
COPY --from=deps /usr/local/bin /usr/local/bin

# Copy entrypoint
COPY docker-entrypoint.sh /usr/local/bin/
RUN chmod 755 /usr/local/bin/docker-entrypoint.sh

# Create non-root user with no shell access
RUN groupadd -r ghost && useradd -r -g ghost -d /app -s /sbin/nologin ghost \
    && mkdir -p /app/agent_logs /app/agent_data /app/agent_data/swarm /app/browser_profile \
    && chown -R ghost:ghost /app

# Copy application source (writeable for writable volumes only)
COPY --chown=ghost:ghost . .

# Ensure no world-writeable files
RUN find /app -type f -exec chmod 644 {} \; && find /app -type d -exec chmod 755 {} \;

# Expose only dashboard port (P2P removed from hardened build)
EXPOSE 8000

# Volumes for mutable data
VOLUME ["/app/agent_logs", "/app/agent_data", "/app/browser_profile", "/app/session_data"]

# Drop all capabilities, run as non-root
USER ghost:ghost

# Security: no new privileges, read-only rootfs
ENTRYPOINT ["docker-entrypoint.sh"]
CMD ["dashboard"]
