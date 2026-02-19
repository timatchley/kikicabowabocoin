# ==============================================================================
# KikicabowaboCoin (KIKI) Configuration
# Modeled after Dogecoin's parameters
# ==============================================================================

import os

# --- Coin Identity ---
COIN_NAME = "KikicabowaboCoin"
TICKER = "KIKI"
VERSION = "1.0.0"

# --- Network ---
DEFAULT_PORT = 44144
RPC_PORT = 44145
DISCOVERY_PORT = 44146          # UDP port for LAN peer discovery broadcasts
DISCOVERY_INTERVAL = 30         # Seconds between discovery broadcasts
MAGIC_BYTES = b"\xc1\xc1\xca\xb0"  # Network magic for packet framing
MAX_PEERS = 125

# --- Peer Discovery (internet-scale) ---
#
# How a brand-new node finds its first peer (most → least decentralized):
#
#   1. LAN broadcast  — UDP beacon on 255.255.255.255:44146 (same subnet only)
#   2. Seed tracker   — lightweight HTTP registry any node can run
#   3. DNS seeds      — domain names that resolve to known node IPs
#   4. Hardcoded IPs  — static fallback baked into the binary
#   5. --peer flag    — manual override
#
# Once connected to ONE peer, gossip (getaddr/addr) handles the rest.

SEED_TRACKER_URL = os.environ.get(
    "KIKI_SEED_TRACKER",
    "https://seed.kikicabowabo.coin/api",  # default — override via env var
)
SEED_TRACKER_INTERVAL = 300     # Re-register / re-query every 5 minutes

SEED_NODES = [
    # Hardcoded bootstrap nodes (DNS seeds or static IPs).
    # A real network would ship 3-5 of these maintained by trusted operators:
    # ("seed1.kikicabowabo.coin", DEFAULT_PORT),
    # ("seed2.kikicabowabo.coin", DEFAULT_PORT),
]

# --- Block Parameters (Dogecoin-style) ---
TARGET_BLOCK_TIME = 60  # 1 minute (Dogecoin = 1 min)
BLOCK_REWARD = 100  # 100 KIKI per block
HALVING_INTERVAL = None  # No halving – inflationary like Dogecoin post-block 600k
MAX_BLOCK_SIZE = 1_000_000  # 1 MB max block size
COINBASE_MATURITY = 100  # Mined coins locked for 100 blocks

# --- Difficulty / DigiShield ---
#   Dogecoin uses DigiShield v3: retargets every block, dampened to prevent
#   large oscillations.  We replicate that here.
DIFFICULTY_RETARGET_INTERVAL = 1  # Every block (DigiShield)
DIGISHIELD_AVERAGING_WINDOW = 1  # Single-block look-back
DIGISHIELD_MAX_ADJUST_UP = 4  # Max 400% increase
DIGISHIELD_MAX_ADJUST_DOWN = 4  # Max 25% decrease (1/4)
INITIAL_DIFFICULTY_BITS = 0x1e0fffff  # Easy starting difficulty (testnet-like)

# --- Proof of Work ---
POW_ALGORITHM = "scrypt"  # Scrypt PoW like Dogecoin / Litecoin
SCRYPT_N = 1024
SCRYPT_R = 1
SCRYPT_P = 1
SCRYPT_KEY_LEN = 32

# --- Transaction ---
MIN_TX_FEE = 1  # 1 KIKI minimum fee
MAX_TX_SIZE = 100_000  # bytes
SIGHASH_ALL = 0x01

# --- Wallet / Addresses ---
ADDRESS_PREFIX = b"\x1e"  # Gives addresses starting with 'K'
PRIVKEY_PREFIX = b"\x9e"
TESTNET_ADDRESS_PREFIX = b"\x71"  # Testnet prefix 't'

# --- Genesis Block ---
GENESIS_TIMESTAMP = 1739836800  # Feb 18 2026 00:00:00 UTC
GENESIS_NONCE = 0
GENESIS_PREV_HASH = "0" * 64
GENESIS_MESSAGE = "KikicabowaboCoin - much wow, very coin, so crypto!"

# --- Paths ---
DATA_DIR = os.path.expanduser("~/.kikicabowabocoin")
BLOCKCHAIN_DB = os.path.join(DATA_DIR, "blockchain.db")
WALLET_FILE = os.path.join(DATA_DIR, "wallet.json")
MEMPOOL_FILE = os.path.join(DATA_DIR, "mempool.json")
PEERS_FILE = os.path.join(DATA_DIR, "peers.json")
LOG_FILE = os.path.join(DATA_DIR, "kiki.log")
