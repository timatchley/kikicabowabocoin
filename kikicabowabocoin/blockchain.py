"""
Block and Blockchain for KikicabowaboCoin.

Implements:
- Block structure (header + transactions)
- Genesis block creation
- Blockchain with chain validation
- DigiShield difficulty retargeting (Dogecoin's algorithm)
"""

import json
import os
import time
from dataclasses import dataclass, field
from typing import List, Optional, Dict

from kikicabowabocoin.config import (
    BLOCK_REWARD,
    COINBASE_MATURITY,
    GENESIS_MESSAGE,
    GENESIS_NONCE,
    GENESIS_PREV_HASH,
    GENESIS_TIMESTAMP,
    INITIAL_DIFFICULTY_BITS,
    MAX_BLOCK_SIZE,
    TARGET_BLOCK_TIME,
    DIGISHIELD_MAX_ADJUST_DOWN,
    DIGISHIELD_MAX_ADJUST_UP,
    DATA_DIR,
)
from kikicabowabocoin.crypto import (
    double_sha256,
    merkle_root,
    scrypt_hash,
    bits_to_target,
    target_to_bits,
    target_to_difficulty,
)
from kikicabowabocoin.transaction import Transaction, TxOutput, TxInput


# ===========================================================================
# Block
# ===========================================================================

@dataclass
class BlockHeader:
    """Block header — hashed for Proof-of-Work."""

    version: int
    prev_hash: str
    merkle_root: str
    timestamp: float
    bits: int  # Compact difficulty target
    nonce: int

    def serialize_for_hash(self) -> bytes:
        """Pack header fields into bytes for Scrypt hashing."""
        header_str = (
            f"{self.version}:{self.prev_hash}:{self.merkle_root}:"
            f"{self.timestamp}:{self.bits}:{self.nonce}"
        )
        return header_str.encode()

    def compute_hash(self) -> str:
        """Compute the Scrypt PoW hash of this header."""
        return scrypt_hash(self.serialize_for_hash()).hex()


@dataclass
class Block:
    """A full block: header + list of transactions."""

    header: BlockHeader
    transactions: List[Transaction] = field(default_factory=list)
    height: int = 0
    block_hash: str = ""
    size: int = 0

    # --- Serialisation -------------------------------------------------------

    def serialize(self) -> dict:
        return {
            "header": {
                "version": self.header.version,
                "prev_hash": self.header.prev_hash,
                "merkle_root": self.header.merkle_root,
                "timestamp": self.header.timestamp,
                "bits": self.header.bits,
                "nonce": self.header.nonce,
            },
            "transactions": [tx.serialize() for tx in self.transactions],
            "height": self.height,
            "block_hash": self.block_hash,
        }

    @classmethod
    def deserialize(cls, data: dict) -> "Block":
        hdr = data["header"]
        header = BlockHeader(
            version=hdr["version"],
            prev_hash=hdr["prev_hash"],
            merkle_root=hdr["merkle_root"],
            timestamp=hdr["timestamp"],
            bits=hdr["bits"],
            nonce=hdr["nonce"],
        )
        txs = [Transaction.deserialize(t) for t in data.get("transactions", [])]
        block = cls(
            header=header,
            transactions=txs,
            height=data.get("height", 0),
            block_hash=data.get("block_hash", header.compute_hash()),
        )
        return block

    def compute_merkle_root(self) -> str:
        tx_hashes = [bytes.fromhex(tx.compute_hash()) for tx in self.transactions]
        return merkle_root(tx_hashes).hex()

    def compute_hash(self) -> str:
        return self.header.compute_hash()

    def __repr__(self) -> str:
        return (
            f"<Block #{self.height} hash={self.block_hash[:16]}… "
            f"txs={len(self.transactions)} bits=0x{self.header.bits:08x}>"
        )


# ===========================================================================
# Genesis block
# ===========================================================================

def create_genesis_block() -> Block:
    """
    Create the genesis (first) block of the KikicabowaboCoin chain.

    Like Dogecoin's genesis, it contains a fun message and has no real
    previous block.
    """
    coinbase_tx = Transaction.create_coinbase(
        block_height=0,
        reward=BLOCK_REWARD,
        miner_address="KikiGenesis",
        message=GENESIS_MESSAGE,
    )
    coinbase_tx.timestamp = GENESIS_TIMESTAMP

    mr = merkle_root([bytes.fromhex(coinbase_tx.compute_hash())]).hex()

    header = BlockHeader(
        version=1,
        prev_hash=GENESIS_PREV_HASH,
        merkle_root=mr,
        timestamp=GENESIS_TIMESTAMP,
        bits=INITIAL_DIFFICULTY_BITS,
        nonce=GENESIS_NONCE,
    )

    block = Block(
        header=header,
        transactions=[coinbase_tx],
        height=0,
    )
    block.block_hash = block.compute_hash()
    return block


# ===========================================================================
# Blockchain
# ===========================================================================

class Blockchain:
    """
    The KikicabowaboCoin blockchain.

    Maintains:
    - Ordered list of blocks
    - UTXO set for balance lookups
    - DigiShield difficulty adjustment
    """

    def __init__(self):
        self.chain: List[Block] = []
        self.utxo_set: Dict[str, TxOutput] = {}  # key = "txhash:index"
        self.block_index: Dict[str, Block] = {}  # hash -> block

        # Initialise with genesis block
        genesis = create_genesis_block()
        self._add_block_to_chain(genesis)

    # --- Properties ----------------------------------------------------------

    @property
    def height(self) -> int:
        return len(self.chain) - 1

    @property
    def tip(self) -> Block:
        return self.chain[-1]

    @property
    def current_difficulty(self) -> float:
        target = bits_to_target(self.tip.header.bits)
        return target_to_difficulty(target)

    # --- DigiShield Difficulty Retarget --------------------------------------

    def calculate_next_bits(self) -> int:
        """
        DigiShield v3 difficulty retarget (used by Dogecoin).

        Retargets every block.  Uses the time of the previous block to
        calculate actual vs expected time, then adjusts with dampening
        to prevent oscillation.

        Adjustment formula:
            new_target = old_target * ((actual_time - target_time) / 4 + target_time) / target_time

        Clamped to max 4× increase and max 4× decrease.
        """
        if self.height < 1:
            return INITIAL_DIFFICULTY_BITS

        last_block = self.chain[-1]
        prev_block = self.chain[-2]

        actual_time = last_block.header.timestamp - prev_block.header.timestamp

        # Clamp actual time to reasonable bounds (ensure int throughout)
        actual_time = int(actual_time)
        actual_time = max(actual_time, TARGET_BLOCK_TIME // DIGISHIELD_MAX_ADJUST_DOWN)
        actual_time = min(actual_time, TARGET_BLOCK_TIME * DIGISHIELD_MAX_ADJUST_UP)

        # DigiShield dampening:  shift by (actual - target) / 4
        adjusted_time = TARGET_BLOCK_TIME + (actual_time - TARGET_BLOCK_TIME) // 4

        old_target = bits_to_target(last_block.header.bits)
        new_target = old_target * adjusted_time // TARGET_BLOCK_TIME

        # Don't exceed the easiest allowed target
        max_target = bits_to_target(INITIAL_DIFFICULTY_BITS)
        new_target = min(new_target, max_target)

        return target_to_bits(new_target)

    # --- Block validation ----------------------------------------------------

    def validate_block(self, block: Block) -> bool:
        """Validate a block before adding it to the chain."""
        # 1) Check previous hash linkage
        if block.header.prev_hash != self.tip.block_hash:
            raise ValueError(
                f"Block prev_hash mismatch: expected {self.tip.block_hash[:16]}…, "
                f"got {block.header.prev_hash[:16]}…"
            )

        # 2) Verify PoW: block hash must be below target
        target = bits_to_target(block.header.bits)
        block_hash_int = int(block.block_hash, 16)
        if block_hash_int > target:
            raise ValueError("Block hash does not meet difficulty target")

        # 3) Check Merkle root
        expected_mr = block.compute_merkle_root()
        if block.header.merkle_root != expected_mr:
            raise ValueError("Merkle root mismatch")

        # 4) Check coinbase transaction
        if not block.transactions:
            raise ValueError("Block has no transactions")
        if not block.transactions[0].is_coinbase():
            raise ValueError("First transaction must be coinbase")

        # 5) Verify block reward
        coinbase_reward = block.transactions[0].total_output()
        fees = self._calculate_fees(block)
        if coinbase_reward > BLOCK_REWARD + fees:
            raise ValueError(
                f"Coinbase reward too high: {coinbase_reward} > "
                f"{BLOCK_REWARD} + {fees} fees"
            )

        # 6) Timestamp sanity (not more than 2 hours in the future)
        if block.header.timestamp > time.time() + 7200:
            raise ValueError("Block timestamp too far in the future")

        return True

    def _calculate_fees(self, block: Block) -> int:
        """Sum transaction fees in a block (total inputs - total outputs)."""
        total_fees = 0
        for tx in block.transactions[1:]:  # Skip coinbase
            input_total = 0
            for inp in tx.inputs:
                utxo_key = f"{inp.prev_tx_hash}:{inp.output_index}"
                utxo = self.utxo_set.get(utxo_key)
                if utxo:
                    input_total += utxo.amount
            output_total = tx.total_output()
            total_fees += max(0, input_total - output_total)
        return total_fees

    # --- Adding blocks -------------------------------------------------------

    def add_block(self, block: Block) -> bool:
        """Validate and add a block to the chain."""
        self.validate_block(block)
        self._add_block_to_chain(block)
        return True

    def _add_block_to_chain(self, block: Block):
        """Internal: append block and update UTXO set."""
        self.chain.append(block)
        self.block_index[block.block_hash] = block

        for tx in block.transactions:
            # Remove spent UTXOs
            if not tx.is_coinbase():
                for inp in tx.inputs:
                    utxo_key = f"{inp.prev_tx_hash}:{inp.output_index}"
                    self.utxo_set.pop(utxo_key, None)

            # Add new UTXOs
            for idx, out in enumerate(tx.outputs):
                utxo_key = f"{tx.tx_hash}:{idx}"
                self.utxo_set[utxo_key] = out

    # --- UTXO / Balance queries ----------------------------------------------

    def get_balance(self, address: str) -> int:
        """Get total balance for an address from the UTXO set."""
        total = 0
        for key, utxo in self.utxo_set.items():
            if utxo.address == address:
                total += utxo.amount
        return total

    def get_utxos_for_address(self, address: str) -> List[dict]:
        """Get all unspent outputs for an address."""
        utxos = []
        for key, utxo in self.utxo_set.items():
            if utxo.address == address:
                tx_hash, index = key.rsplit(":", 1)
                utxos.append({
                    "tx_hash": tx_hash,
                    "output_index": int(index),
                    "amount": utxo.amount,
                })
        return utxos

    # --- Chain info ----------------------------------------------------------

    def get_block_by_hash(self, block_hash: str) -> Optional[Block]:
        return self.block_index.get(block_hash)

    def get_block_by_height(self, height: int) -> Optional[Block]:
        if 0 <= height < len(self.chain):
            return self.chain[height]
        return None

    def get_chain_info(self) -> dict:
        return {
            "coin": "KikicabowaboCoin (KIKI)",
            "height": self.height,
            "tip_hash": self.tip.block_hash[:32] + "…",
            "difficulty": f"{self.current_difficulty:.4f}",
            "utxo_count": len(self.utxo_set),
            "total_supply": self.height * BLOCK_REWARD,
        }

    # --- Persistence ---------------------------------------------------------

    def save(self, filepath: Optional[str] = None):
        """Save blockchain to a JSON file."""
        filepath = filepath or os.path.join(DATA_DIR, "chain.json")
        os.makedirs(os.path.dirname(filepath), exist_ok=True)
        data = [block.serialize() for block in self.chain]
        with open(filepath, "w") as f:
            json.dump(data, f, indent=2)

    @classmethod
    def load(cls, filepath: Optional[str] = None) -> "Blockchain":
        """Load blockchain from a JSON file."""
        filepath = filepath or os.path.join(DATA_DIR, "chain.json")
        bc = cls.__new__(cls)
        bc.chain = []
        bc.utxo_set = {}
        bc.block_index = {}

        with open(filepath, "r") as f:
            data = json.load(f)

        for block_data in data:
            block = Block.deserialize(block_data)
            bc._add_block_to_chain(block)

        return bc

    def __repr__(self) -> str:
        return f"<Blockchain height={self.height} tip={self.tip.block_hash[:16]}…>"
