# KikicabowaboCoin (KIKI) 🐕✨

> **Much coin. Very crypto. Wow!**

A Dogecoin-inspired cryptocurrency built in Python. KikicabowaboCoin replicates the core mechanics that make Dogecoin work, including Scrypt Proof-of-Work, inflationary supply, and fast block times.

---

## 🎯 How It Works (Dogecoin Style)

| Feature | Dogecoin | KikicabowaboCoin |
|---|---|---|
| **PoW Algorithm** | Scrypt | Scrypt |
| **Block Time** | 1 minute | 1 minute |
| **Block Reward** | 10,000 DOGE | 100 KIKI |
| **Supply Cap** | ∞ (inflationary) | ∞ (inflationary) |
| **Difficulty Adjust** | DigiShield v3 (every block) | DigiShield v3 (every block) |
| **Transaction Model** | UTXO | UTXO |
| **Address Format** | Base58Check | Base58Check |
| **Signatures** | ECDSA (secp256k1) | ECDSA (secp256k1) |

## 📦 Installation

```bash
# Clone the repository
cd kikicabowabocoin

# Install in development mode
pip install -e .

# Or install with dev dependencies
pip install -e ".[dev]"
```

## 🚀 Quick Start

### View Blockchain Info
```bash
kiki info
```

### Create a Wallet
```bash
kiki wallet create --label "my-wallet"
kiki wallet list
```

### Mine Blocks
```bash
# Mine 5 blocks (earns 100 KIKI each!)
kiki mine --blocks 5

# Mine to a specific address
kiki mine --blocks 3 --address <your-address>
```

### Send Coins
```bash
kiki send <recipient-address> 5000 --fee 1
```

### View a Block
```bash
# Latest block
kiki block

# By height
kiki block --height 0

# By hash
kiki block --hash <block-hash>
```

### View Genesis Block
```bash
kiki genesis
```

### Start a Full Node
```bash
# Start node (listens on port 44144)
kiki node --port 44144

# Start node with mining enabled
kiki node --mine

# Connect to a specific peer
kiki node --mine --peer 192.168.1.100:44144

# Connect to multiple peers
kiki node --mine --peer 192.168.1.100:44144 --peer 10.0.0.5:44144
```

## 🌐 Networking

KIKI nodes communicate via a gossip protocol over TCP (port 44144). When two
nodes connect they perform a VERSION/VERACK handshake, then the node with the
shorter chain downloads blocks from its peer (Initial Block Download). After
sync, newly mined blocks and transactions are relayed in real-time.

```
  Desktop (192.168.1.10)            Raspberry Pi (192.168.1.20)
  ┌─────────────────┐               ┌──────────────────┐
  │  kiki node       │◄─────────────►│  kiki node        │
  │  --mine          │  TCP 44144    │  --mine           │
  │  height: 16      │  blocks/txs   │  height: 16       │
  └─────────────────┘               └──────────────────┘
```

### Multi-Node Setup

1. **Start the first node** on Machine A:
   ```bash
   kiki node --mine
   ```

2. **Start the second node** on Machine B, pointing at Machine A:
   ```bash
   kiki node --mine --peer 192.168.1.10:44144
   ```

3. Both nodes will sync to the longest chain and relay new blocks to each other.

## 🏗️ Architecture

```
kikicabowabocoin/
├── __init__.py          # Package metadata
├── __main__.py          # python -m entry point
├── config.py            # All chain parameters (Dogecoin-style)
├── crypto.py            # Scrypt PoW, SHA-256, Merkle trees, Base58
├── transaction.py       # UTXO transaction model
├── blockchain.py        # Block structure, chain, DigiShield difficulty
├── wallet.py            # ECDSA key management, signing, addresses
├── miner.py             # Scrypt PoW miner (single & continuous)
├── mempool.py           # Unconfirmed transaction pool
├── network.py           # P2P gossip protocol (asyncio)
└── cli.py               # Command-line interface
```

## 🔧 Key Design Decisions

### Scrypt Proof of Work
Like Dogecoin (inherited from Litecoin), KIKI uses Scrypt for mining instead of SHA-256. This makes mining more memory-hard and was originally designed to be ASIC-resistant.

### DigiShield Difficulty Adjustment
Dogecoin adopted DigiShield v3 to prevent difficulty oscillation from multipools. It retargets every single block with dampening:
```
new_target = old_target × ((actual_time - target_time) / 4 + target_time) / target_time
```

### Inflationary Supply
Like Dogecoin, there is **no supply cap**. Every block mints 100 KIKI forever, providing a small constant inflation rate that decreases as a percentage over time. This keeps KIKI accessible and encourages spending over hoarding.

### UTXO Model
Transactions use the Unspent Transaction Output model (same as Bitcoin/Dogecoin). Coins exist as discrete outputs that are consumed whole and produce new outputs (with change returned to the sender).

## 🧪 Running Tests

```bash
# Install dev dependencies
pip install -e ".[dev]"

# Run all tests
pytest

# Run with coverage
pytest --cov=kikicabowabocoin
```

## 📁 Data Directory

All blockchain data, wallet keys, and peer info are stored in:
```
~/.kikicabowabocoin/
├── chain.json       # Blockchain data
├── wallet.json      # Wallet keys (back this up!)
├── mempool.json     # Pending unconfirmed transactions
├── peers.json       # Known peer addresses
└── kiki.log         # Node log
```

## ⚠️ Disclaimer

This is an **educational project** demonstrating how Dogecoin-style cryptocurrencies work. It is not intended for production use or real financial transactions. The cryptographic implementations prioritise clarity over performance.

## 📜 License

MIT License — feel free to fork, modify, and have fun! 🎉
