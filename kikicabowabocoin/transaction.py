"""
Transaction model for KikicabowaboCoin.

Implements the UTXO (Unspent Transaction Output) model used by
Bitcoin and Dogecoin.  Each transaction consumes inputs (previous UTXOs)
and creates new outputs.
"""

import json
import time
from dataclasses import dataclass, field
from typing import List, Optional

from kikicabowabocoin.crypto import double_sha256


# ---------------------------------------------------------------------------
# Transaction output
# ---------------------------------------------------------------------------

@dataclass
class TxOutput:
    """A single transaction output (destination + amount)."""

    amount: int  # In base units (1 KIKI = 100_000_000 satoshi-equivalents)
    address: str  # Recipient address (Base58Check)

    def serialize(self) -> dict:
        return {"amount": self.amount, "address": self.address}

    @classmethod
    def deserialize(cls, data: dict) -> "TxOutput":
        return cls(amount=data["amount"], address=data["address"])


# ---------------------------------------------------------------------------
# Transaction input
# ---------------------------------------------------------------------------

@dataclass
class TxInput:
    """
    A single transaction input referencing a previous output.

    For coinbase transactions, prev_tx_hash is all zeros and output_index is
    the block height (like Bitcoin/Dogecoin).
    """

    prev_tx_hash: str  # Hash of the transaction containing the UTXO
    output_index: int  # Index of the output in that transaction
    signature: str = ""  # Hex-encoded ECDSA signature
    public_key: str = ""  # Hex-encoded public key of the spender

    def serialize(self) -> dict:
        return {
            "prev_tx_hash": self.prev_tx_hash,
            "output_index": self.output_index,
            "signature": self.signature,
            "public_key": self.public_key,
        }

    @classmethod
    def deserialize(cls, data: dict) -> "TxInput":
        return cls(
            prev_tx_hash=data["prev_tx_hash"],
            output_index=data["output_index"],
            signature=data.get("signature", ""),
            public_key=data.get("public_key", ""),
        )


# ---------------------------------------------------------------------------
# Transaction
# ---------------------------------------------------------------------------

@dataclass
class Transaction:
    """
    A KikicabowaboCoin transaction.

    Mirrors the Bitcoin/Dogecoin transaction structure:
    - version
    - list of inputs (spending previous UTXOs)
    - list of outputs (creating new UTXOs)
    - lock_time (block height or timestamp before which tx is invalid)
    """

    version: int = 1
    inputs: List[TxInput] = field(default_factory=list)
    outputs: List[TxOutput] = field(default_factory=list)
    lock_time: int = 0
    timestamp: float = field(default_factory=time.time)
    tx_hash: str = ""

    # --- Serialisation -------------------------------------------------------

    def serialize(self) -> dict:
        return {
            "version": self.version,
            "inputs": [inp.serialize() for inp in self.inputs],
            "outputs": [out.serialize() for out in self.outputs],
            "lock_time": self.lock_time,
            "timestamp": self.timestamp,
            "tx_hash": self.tx_hash,
        }

    @classmethod
    def deserialize(cls, data: dict) -> "Transaction":
        tx = cls(
            version=data.get("version", 1),
            inputs=[TxInput.deserialize(i) for i in data.get("inputs", [])],
            outputs=[TxOutput.deserialize(o) for o in data.get("outputs", [])],
            lock_time=data.get("lock_time", 0),
            timestamp=data.get("timestamp", time.time()),
        )
        tx.tx_hash = data.get("tx_hash", tx.compute_hash())
        return tx

    # --- Hashing -------------------------------------------------------------

    def _hash_payload(self) -> bytes:
        """Build the byte payload used for hashing (excludes signatures)."""
        payload = {
            "version": self.version,
            "inputs": [
                {
                    "prev_tx_hash": inp.prev_tx_hash,
                    "output_index": inp.output_index,
                }
                for inp in self.inputs
            ],
            "outputs": [out.serialize() for out in self.outputs],
            "lock_time": self.lock_time,
            "timestamp": self.timestamp,
        }
        return json.dumps(payload, sort_keys=True).encode()

    def compute_hash(self) -> str:
        """Compute the double-SHA-256 transaction ID."""
        return double_sha256(self._hash_payload()).hex()

    def hash_for_signing(self) -> bytes:
        """Return the hash that needs to be signed by each input."""
        return double_sha256(self._hash_payload())

    # --- Coinbase helpers ----------------------------------------------------

    @classmethod
    def create_coinbase(
        cls,
        block_height: int,
        reward: int,
        miner_address: str,
        message: str = "",
    ) -> "Transaction":
        """
        Create a coinbase (block reward) transaction.

        Like Dogecoin, this is the first tx in every block and has no real
        inputs — it mints new coins.
        """
        coinbase_input = TxInput(
            prev_tx_hash="0" * 64,
            output_index=block_height,
            signature=message or f"KIKI block {block_height}",
            public_key="",
        )
        reward_output = TxOutput(amount=reward, address=miner_address)

        tx = cls(
            version=1,
            inputs=[coinbase_input],
            outputs=[reward_output],
            timestamp=time.time(),
        )
        tx.tx_hash = tx.compute_hash()
        return tx

    # --- Validation ----------------------------------------------------------

    def is_coinbase(self) -> bool:
        return (
            len(self.inputs) == 1
            and self.inputs[0].prev_tx_hash == "0" * 64
        )

    def total_output(self) -> int:
        return sum(o.amount for o in self.outputs)

    def __repr__(self) -> str:
        kind = "Coinbase" if self.is_coinbase() else "Tx"
        return f"<{kind} {self.tx_hash[:16]}… outputs={self.total_output()} KIKI>"
