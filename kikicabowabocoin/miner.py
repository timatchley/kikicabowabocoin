"""
Miner for KikicabowaboCoin.

Implements Scrypt-based Proof-of-Work mining (same algorithm as Dogecoin
and Litecoin).  The miner:

1. Assembles a candidate block from the mempool
2. Constructs the coinbase transaction (100 KIKI reward)
3. Iterates nonces until the Scrypt hash meets the difficulty target
4. Submits the solved block to the blockchain
"""

import logging
import time
import threading
from typing import List, Optional, Callable

from kikicabowabocoin.config import BLOCK_REWARD, TARGET_BLOCK_TIME
from kikicabowabocoin.crypto import bits_to_target, scrypt_hash
from kikicabowabocoin.blockchain import Block, BlockHeader, Blockchain
from kikicabowabocoin.transaction import Transaction
from kikicabowabocoin.crypto import merkle_root

logger = logging.getLogger("kiki.miner")


class Miner:
    """
    KikicabowaboCoin miner.

    Call `mine_block()` for a single block, or `start()` / `stop()` for
    continuous background mining.
    """

    def __init__(
        self,
        blockchain: Blockchain,
        miner_address: str,
        on_block_mined: Optional[Callable[[Block], None]] = None,
    ):
        self.blockchain = blockchain
        self.miner_address = miner_address
        self.on_block_mined = on_block_mined

        self._running = False
        self._thread: Optional[threading.Thread] = None
        self.hashrate: float = 0.0
        self.blocks_mined: int = 0

    # --- Single block mining -------------------------------------------------

    def mine_block(
        self,
        transactions: Optional[List[Transaction]] = None,
        max_nonce: int = 2**32,
    ) -> Optional[Block]:
        """
        Mine a single block.

        Args:
            transactions: Transactions to include (from mempool).
            max_nonce: Maximum nonce to try before giving up.

        Returns:
            The mined Block, or None if max_nonce reached.
        """
        height = self.blockchain.height + 1
        prev_hash = self.blockchain.tip.block_hash
        bits = self.blockchain.calculate_next_bits()
        target = bits_to_target(bits)

        # Create coinbase transaction (block reward)
        # Flat 100 KIKI coin reward, no halving — inflationary by design
        coinbase_tx = Transaction.create_coinbase(
            block_height=height,
            reward=BLOCK_REWARD,
            miner_address=self.miner_address,
        )

        # Assemble transaction list
        block_txs = [coinbase_tx]
        if transactions:
            block_txs.extend(transactions)

        # Compute Merkle root
        tx_hashes = [bytes.fromhex(tx.compute_hash()) for tx in block_txs]
        mr = merkle_root(tx_hashes).hex()

        # Build header
        header = BlockHeader(
            version=1,
            prev_hash=prev_hash,
            merkle_root=mr,
            timestamp=time.time(),
            bits=bits,
            nonce=0,
        )

        logger.info(
            f"⛏  Mining block #{height} | difficulty bits=0x{bits:08x} | "
            f"target={target:#066x}"
        )

        # PoW loop: iterate nonces
        start_time = time.time()
        nonce = 0

        while nonce < max_nonce:
            if not self._running and self._thread is not None:
                # Stopped by external call
                return None

            header.nonce = nonce
            block_hash = header.compute_hash()
            hash_int = int(block_hash, 16)

            if hash_int <= target:
                elapsed = time.time() - start_time
                self.hashrate = nonce / elapsed if elapsed > 0 else 0

                block = Block(
                    header=header,
                    transactions=block_txs,
                    height=height,
                    block_hash=block_hash,
                )

                logger.info(
                    f"✅ Block #{height} mined! "
                    f"hash={block_hash[:24]}… nonce={nonce} "
                    f"time={elapsed:.1f}s rate={self.hashrate:.0f} H/s"
                )

                # Add to our chain
                self.blockchain.add_block(block)
                self.blocks_mined += 1

                if self.on_block_mined:
                    self.on_block_mined(block)

                return block

            nonce += 1

            # Update timestamp occasionally (keep it fresh)
            if nonce % 100_000 == 0:
                header.timestamp = time.time()
                # Recompute merkle root isn't needed (txs unchanged)

        logger.warning(f"Max nonce reached for block #{height}, retrying…")
        return None

    # --- Continuous mining ---------------------------------------------------

    def start(self, mempool=None):
        """Start mining in a background thread."""
        if self._running:
            return

        self._running = True
        self._thread = threading.Thread(
            target=self._mine_loop,
            args=(mempool,),
            daemon=True,
        )
        self._thread.start()
        logger.info(f"🚀 Miner started — address: {self.miner_address}")

    def stop(self):
        """Stop the background miner."""
        self._running = False
        if self._thread:
            self._thread.join(timeout=5)
            self._thread = None
        logger.info("🛑 Miner stopped")

    def _mine_loop(self, mempool=None):
        """Continuous mining loop."""
        while self._running:
            # Pull transactions from mempool
            txs = []
            if mempool:
                txs = mempool.get_transactions()

            block = self.mine_block(transactions=txs)

            if block and mempool:
                # Remove mined transactions from mempool
                for tx in block.transactions[1:]:  # skip coinbase
                    mempool.remove_transaction(tx.tx_hash)

    # --- Status --------------------------------------------------------------

    def get_status(self) -> dict:
        return {
            "running": self._running,
            "miner_address": self.miner_address,
            "blocks_mined": self.blocks_mined,
            "hashrate": f"{self.hashrate:.0f} H/s",
            "chain_height": self.blockchain.height,
        }
