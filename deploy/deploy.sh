#!/usr/bin/env bash
# ============================================================================
# KikicabowaboCoin — Production Deployment Script
# ============================================================================
# This script sets up a KikicabowaboCoin full node on a fresh Linux server.
#
# Usage:
#   chmod +x deploy/deploy.sh
#   sudo ./deploy/deploy.sh                  # Node only
#   sudo ./deploy/deploy.sh --mine           # Node + mining
#   sudo ./deploy/deploy.sh --seed           # Seed node (public bootstrap)
#
# Tested on: Ubuntu 22.04+, Debian 12+
# ============================================================================

set -euo pipefail

KIKI_USER="kiki"
KIKI_HOME="/opt/kikicabowabocoin"
KIKI_DATA="${KIKI_HOME}/.kikicabowabocoin"
KIKI_VENV="${KIKI_HOME}/venv"
KIKI_REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
ENABLE_MINING=false
SEED_MODE=false

# Parse args
for arg in "$@"; do
    case $arg in
        --mine)   ENABLE_MINING=true ;;
        --seed)   SEED_MODE=true ;;
        --help|-h)
            echo "Usage: sudo $0 [--mine] [--seed]"
            echo "  --mine   Enable mining on this node"
            echo "  --seed   Configure as a public seed node"
            exit 0
            ;;
    esac
done

# --------------------------------------------------------------------------
# Preflight checks
# --------------------------------------------------------------------------
if [[ $EUID -ne 0 ]]; then
    echo "❌ This script must be run as root (use sudo)"
    exit 1
fi

echo "🐕 KikicabowaboCoin Deployment"
echo "══════════════════════════════════════════════════════════════"
echo "  Install dir:  ${KIKI_HOME}"
echo "  Data dir:     ${KIKI_DATA}"
echo "  Mining:       ${ENABLE_MINING}"
echo "  Seed mode:    ${SEED_MODE}"
echo "══════════════════════════════════════════════════════════════"

# --------------------------------------------------------------------------
# 1. System dependencies
# --------------------------------------------------------------------------
echo "📦 Installing system dependencies…"
apt-get update -qq
apt-get install -y -qq python3 python3-venv python3-pip ufw

# --------------------------------------------------------------------------
# 2. Create dedicated user
# --------------------------------------------------------------------------
if ! id -u ${KIKI_USER} &>/dev/null; then
    echo "👤 Creating user '${KIKI_USER}'…"
    useradd --system --home-dir ${KIKI_HOME} --create-home --shell /bin/bash ${KIKI_USER}
fi

# --------------------------------------------------------------------------
# 3. Install KikicabowaboCoin
# --------------------------------------------------------------------------
echo "📥 Installing KikicabowaboCoin…"
mkdir -p ${KIKI_HOME}
cp -r "${KIKI_REPO_DIR}/kikicabowabocoin" "${KIKI_HOME}/"
cp "${KIKI_REPO_DIR}/pyproject.toml" "${KIKI_HOME}/"
cp "${KIKI_REPO_DIR}/README.md" "${KIKI_HOME}/"

# Create virtualenv and install
python3 -m venv "${KIKI_VENV}"
"${KIKI_VENV}/bin/pip" install --upgrade pip
"${KIKI_VENV}/bin/pip" install -e "${KIKI_HOME}"

# Create data directory
mkdir -p "${KIKI_DATA}"
chown -R ${KIKI_USER}:${KIKI_USER} ${KIKI_HOME}

# --------------------------------------------------------------------------
# 4. Generate wallet if none exists
# --------------------------------------------------------------------------
if [[ ! -f "${KIKI_DATA}/wallet.json" ]]; then
    echo "🔑 Generating initial wallet…"
    sudo -u ${KIKI_USER} "${KIKI_VENV}/bin/kiki" wallet create --label "node-wallet"
fi

# --------------------------------------------------------------------------
# 5. Configure firewall
# --------------------------------------------------------------------------
echo "🔥 Configuring firewall…"
ufw allow 44144/tcp comment "KikicabowaboCoin P2P"
ufw allow 22/tcp comment "SSH"

if [[ "${SEED_MODE}" == true ]]; then
    ufw allow 44145/tcp comment "KikicabowaboCoin RPC"
fi

# Enable ufw if not already active (non-interactive)
ufw --force enable 2>/dev/null || true

# --------------------------------------------------------------------------
# 6. Install systemd service
# --------------------------------------------------------------------------
echo "⚙️  Installing systemd service…"
SERVICE_FILE="/etc/systemd/system/kikicabowabocoin.service"

cp "${KIKI_REPO_DIR}/deploy/kikicabowabocoin.service" "${SERVICE_FILE}"

# If mining is enabled, modify the ExecStart line
if [[ "${ENABLE_MINING}" == true ]]; then
    sed -i 's|ExecStart=.*|ExecStart=/opt/kikicabowabocoin/venv/bin/kiki node --port 44144 --mine|' "${SERVICE_FILE}"
fi

systemctl daemon-reload
systemctl enable kikicabowabocoin
systemctl start kikicabowabocoin

# --------------------------------------------------------------------------
# 7. Verify
# --------------------------------------------------------------------------
sleep 2
echo ""
echo "══════════════════════════════════════════════════════════════"
if systemctl is-active --quiet kikicabowabocoin; then
    echo "  ✅ KikicabowaboCoin node is RUNNING!"
else
    echo "  ⚠️  Node may still be starting. Check: journalctl -u kikicabowabocoin -f"
fi
echo ""
echo "  Useful commands:"
echo "    sudo -u kiki ${KIKI_VENV}/bin/kiki info"
echo "    sudo -u kiki ${KIKI_VENV}/bin/kiki wallet list"
echo "    sudo systemctl status kikicabowabocoin"
echo "    journalctl -u kikicabowabocoin -f"
echo ""
echo "  P2P port: 44144"
echo "  Data dir: ${KIKI_DATA}"
echo "══════════════════════════════════════════════════════════════"
echo ""
echo "  🐕 Much deploy. Very node. Wow!"
echo ""
