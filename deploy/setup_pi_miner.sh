#!/usr/bin/env bash
# ============================================================================
# KikicabowaboCoin — Raspberry Pi Miner Setup
# ============================================================================
# Run on the Pi:  bash setup_pi_miner.sh
# This will:
#   1. Install Python & dependencies
#   2. Clone/copy kikicabowabocoin
#   3. Create a wallet
#   4. Set up systemd service to mine on every boot
# ============================================================================

set -euo pipefail

KIKI_DIR="$HOME/kikicabowabocoin"
KIKI_VENV="$KIKI_DIR/venv"
KIKI_DATA="$HOME/.kikicabowabocoin"

echo ""
echo "  🐕 KikicabowaboCoin Raspberry Pi Miner Setup"
echo "  ═══════════════════════════════════════════════"
echo ""

# --------------------------------------------------------------------------
# 1. System dependencies
# --------------------------------------------------------------------------
echo "📦 Installing system dependencies..."
sudo apt-get update -qq
sudo apt-get install -y -qq python3 python3-venv python3-pip git

# --------------------------------------------------------------------------
# 2. Clone the repo
# --------------------------------------------------------------------------
if [[ -d "$KIKI_DIR" ]]; then
    echo "📥 Updating existing installation..."
    cd "$KIKI_DIR"
    git pull origin main || true
else
    echo "📥 Cloning KikicabowaboCoin..."
    git clone https://github.com/timatchley/kikicabowabocoin.git "$KIKI_DIR"
    cd "$KIKI_DIR"
fi

# --------------------------------------------------------------------------
# 3. Python virtual environment
# --------------------------------------------------------------------------
echo "🐍 Setting up Python environment..."
python3 -m venv "$KIKI_VENV"
"$KIKI_VENV/bin/pip" install --upgrade pip -q
"$KIKI_VENV/bin/pip" install -e "$KIKI_DIR" -q

# --------------------------------------------------------------------------
# 4. Generate wallet if needed
# --------------------------------------------------------------------------
mkdir -p "$KIKI_DATA"
if [[ ! -f "$KIKI_DATA/wallet.json" ]]; then
    echo "🔑 Generating mining wallet..."
    "$KIKI_VENV/bin/kiki" wallet create --label "pi-miner"
else
    echo "🔑 Wallet already exists"
fi

# Show the address
echo ""
"$KIKI_VENV/bin/kiki" wallet list
echo ""

# --------------------------------------------------------------------------
# 5. Create systemd service for auto-mining on boot
# --------------------------------------------------------------------------
echo "⚙️  Setting up auto-mining service..."

MINER_SERVICE="[Unit]
Description=KikicabowaboCoin (KIKI) Miner
Documentation=https://github.com/timatchley/kikicabowabocoin
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=$(whoami)
WorkingDirectory=$KIKI_DIR
Environment=\"HOME=$HOME\"

# Mine continuously (10000 blocks, then restart)
ExecStart=$KIKI_VENV/bin/kiki mine --blocks 10000

# Auto-restart when the batch finishes or if it crashes
Restart=always
RestartSec=5

# Resource limits (be nice to the Pi)
Nice=10
CPUQuota=75%

[Install]
WantedBy=multi-user.target"

echo "$MINER_SERVICE" | sudo tee /etc/systemd/system/kiki-miner.service > /dev/null

sudo systemctl daemon-reload
sudo systemctl enable kiki-miner
sudo systemctl start kiki-miner

# --------------------------------------------------------------------------
# 6. Verify
# --------------------------------------------------------------------------
sleep 3
echo ""
echo "  ═══════════════════════════════════════════════"
if systemctl is-active --quiet kiki-miner; then
    echo "  ✅ KIKI miner is RUNNING on this Raspberry Pi!"
else
    echo "  ⏳ Miner starting... check: sudo systemctl status kiki-miner"
fi
echo ""
echo "  Useful commands:"
echo "    $KIKI_VENV/bin/kiki wallet list     # Check balance"
echo "    $KIKI_VENV/bin/kiki info             # Chain info"
echo "    sudo systemctl status kiki-miner     # Miner status"
echo "    journalctl -u kiki-miner -f          # Live mining log"
echo "    sudo systemctl stop kiki-miner       # Stop mining"
echo "    sudo systemctl start kiki-miner      # Start mining"
echo ""
echo "  🐕 Your Pi is now mining KIKI! Much wow!"
echo "  ═══════════════════════════════════════════════"
echo ""
