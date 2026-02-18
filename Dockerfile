# ============================================================================
# KikicabowaboCoin Node — Production Dockerfile
# ============================================================================
# Build:  docker build -t kikicabowabocoin .
# Run:    docker run -d --name kiki-node -p 44144:44144 -p 44145:44145 \
#              -v kiki-data:/root/.kikicabowabocoin kikicabowabocoin
# ============================================================================

FROM python:3.12-slim AS base

LABEL maintainer="KikicabowaboCoin Developers"
LABEL description="KikicabowaboCoin (KIKI) full node"
LABEL version="1.0.0"

# Don't write .pyc files and enable unbuffered stdout for logging
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Install system deps (none required for pure Python, but useful for healthchecks)
RUN apt-get update && \
    apt-get install -y --no-install-recommends curl && \
    rm -rf /var/lib/apt/lists/*

# Copy and install
COPY pyproject.toml README.md ./
COPY kikicabowabocoin/ ./kikicabowabocoin/

RUN pip install --no-cache-dir -e .

# Persistent data volume
VOLUME ["/root/.kikicabowabocoin"]

# P2P port + RPC port
EXPOSE 44144 44145

# Health check: ensure the process is still running
HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
    CMD pgrep -f "kikicabowabocoin" || exit 1

# Default: start a full node with mining disabled
# Override with: docker run ... kikicabowabocoin kiki node --mine
ENTRYPOINT ["kiki"]
CMD ["node"]
