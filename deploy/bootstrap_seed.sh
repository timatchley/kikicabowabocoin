#!/usr/bin/env bash
# ============================================================================
# KikicabowaboCoin — Seed Node Bootstrap
# ============================================================================
# Sets up the initial seed nodes that new nodes connect to for peer discovery.
# Run this on 2-3 servers with public IPs before launching mainnet.
#
# Usage:
#   chmod +x deploy/bootstrap_seed.sh
#   sudo ./deploy/bootstrap_seed.sh
# ============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

echo "🌱 Bootstrapping KikicabowaboCoin Seed Node"
echo ""

# Deploy as a seed node
"${SCRIPT_DIR}/deploy.sh" --seed

# Get the public IP for other nodes to connect to
PUBLIC_IP=$(curl -s ifconfig.me 2>/dev/null || echo "unknown")

echo ""
echo "══════════════════════════════════════════════════════════════"
echo "  🌐 Seed Node Ready!"
echo ""
echo "  Public IP:   ${PUBLIC_IP}"
echo "  P2P Port:    44144"
echo ""
echo "  Add this to config.py SEED_NODES on other nodes:"
echo ""
echo "    SEED_NODES = ["
echo "        (\"${PUBLIC_IP}\", 44144),"
echo "    ]"
echo ""
echo "  Or connect manually from another node:"
echo "    kiki node --connect ${PUBLIC_IP}:44144"
echo "══════════════════════════════════════════════════════════════"
