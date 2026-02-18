"""
Mempool (Memory Pool) for KikicabowaboCoin.

Holds unconfirmed transactions waiting to be included in the next block.
Transactions are ordered by fee rate (fee per byte), just like
Bitcoin/Dogecoin.
"""

import json
import logging
import os
import threading
import time
from typing import Dict, List, Optional

from kikicabowabocoin.config import MIN_TX_FEE, MAX_TX_SIZE, MEMPOOL_FILE, DATA_DIR
from kikicabowabocoin.transaction import Transaction

logger = logging.getLogger("kiki.mempool")

# Maximum number of transactions in the mempool
MAX_MEMPOOL_SIZE = 5000
# Maximum age of a transaction in the mempool (24 hours)
MAX_TX_AGE = 86400


class Mempool:
    """
    Transaction memory pool.

    Queues unconfirmed transactions and serves them to the miner
    ordered by fee rate (highest first).
    """

    def __init__(self):
        self._pool: Dict[str, Transaction] = {}
        self._lock = threading.Lock()

    # --- Add / Remove --------------------------------------------------------

    def add_transaction(self, tx: Transaction) -> bool:
        """
        Add a transaction to the mempool.

        Returns True if accepted, False if rejected.
        """
        with self._lock:
            # Reject duplicates
            if tx.tx_hash in self._pool:
                logger.debug(f"Duplicate tx {tx.tx_hash[:16]}… rejected")
                return False

            # Reject if mempool is full
            if len(self._pool) >= MAX_MEMPOOL_SIZE:
                logger.warning("Mempool full, rejecting transaction")
                return False

            # Reject coinbase transactions (can't be in mempool)
            if tx.is_coinbase():
                logger.warning("Coinbase tx rejected from mempool")
                return False

            self._pool[tx.tx_hash] = tx
            logger.info(
                f"📝 Tx {tx.tx_hash[:16]}… added to mempool "
                f"(pool size: {len(self._pool)})"
            )
            return True

    def remove_transaction(self, tx_hash: str):
        """Remove a transaction (e.g. after it's been mined)."""
        with self._lock:
            self._pool.pop(tx_hash, None)

    def remove_transactions(self, tx_hashes: List[str]):
        """Remove multiple transactions."""
        with self._lock:
            for h in tx_hashes:
                self._pool.pop(h, None)

    # --- Query ---------------------------------------------------------------

    def get_transaction(self, tx_hash: str) -> Optional[Transaction]:
        return self._pool.get(tx_hash)

    def get_transactions(self, max_count: int = 100) -> List[Transaction]:
        """
        Get transactions ordered by fee rate (highest first) for mining.

        Like Dogecoin, miners prefer transactions with higher fees.
        """
        with self._lock:
            txs = list(self._pool.values())

        # Sort by total output descending as a proxy for fee priority
        # (In a full implementation, you'd compute actual fee rate)
        txs.sort(key=lambda t: t.total_output(), reverse=True)
        return txs[:max_count]

    def contains(self, tx_hash: str) -> bool:
        return tx_hash in self._pool

    @property
    def size(self) -> int:
        return len(self._pool)

    # --- Maintenance ---------------------------------------------------------

    def purge_old(self):
        """Remove transactions older than MAX_TX_AGE."""
        now = time.time()
        with self._lock:
            to_remove = [
                h for h, tx in self._pool.items()
                if now - tx.timestamp > MAX_TX_AGE
            ]
            for h in to_remove:
                del self._pool[h]
            if to_remove:
                logger.info(f"Purged {len(to_remove)} expired transactions")

    def clear(self):
        """Clear the entire mempool."""
        with self._lock:
            self._pool.clear()

    def get_info(self) -> dict:
        return {
            "size": self.size,
            "max_size": MAX_MEMPOOL_SIZE,
        }

    def __repr__(self) -> str:
        return f"<Mempool size={self.size}>"

    # --- Persistence ---------------------------------------------------------

    def save(self, path: str = MEMPOOL_FILE):
        """Persist mempool to disk so pending txs survive restarts."""
        os.makedirs(DATA_DIR, exist_ok=True)
        with self._lock:
            data = [tx.serialize() for tx in self._pool.values()]
        with open(path, "w") as f:
            json.dump(data, f, indent=2)
        logger.debug(f"Mempool saved ({len(data)} txs) → {path}")

    @classmethod
    def load(cls, path: str = MEMPOOL_FILE) -> "Mempool":
        """Load mempool from disk."""
        mp = cls()
        if os.path.exists(path):
            try:
                with open(path, "r") as f:
                    data = json.load(f)
                for tx_data in data:
                    tx = Transaction.deserialize(tx_data)
                    mp._pool[tx.tx_hash] = tx
                logger.info(f"Mempool loaded ({len(mp._pool)} txs) from {path}")
            except (json.JSONDecodeError, KeyError, Exception) as e:
                logger.warning(f"Failed to load mempool: {e}")
        return mp
