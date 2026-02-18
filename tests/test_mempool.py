"""Tests for mempool."""

import pytest
from kikicabowabocoin.mempool import Mempool
from kikicabowabocoin.transaction import Transaction, TxInput, TxOutput
from kikicabowabocoin.config import BLOCK_REWARD


def _make_tx(amount=1000) -> Transaction:
    """Helper to create a simple test transaction."""
    tx = Transaction(
        inputs=[TxInput(prev_tx_hash="a" * 64, output_index=0)],
        outputs=[TxOutput(amount=amount, address="recipient")],
    )
    tx.tx_hash = tx.compute_hash()
    return tx


class TestMempool:
    def test_add_transaction(self):
        pool = Mempool()
        tx = _make_tx()
        assert pool.add_transaction(tx)
        assert pool.size == 1

    def test_reject_duplicate(self):
        pool = Mempool()
        tx = _make_tx()
        pool.add_transaction(tx)
        assert not pool.add_transaction(tx)
        assert pool.size == 1

    def test_reject_coinbase(self):
        pool = Mempool()
        tx = Transaction.create_coinbase(1, BLOCK_REWARD, "addr")
        assert not pool.add_transaction(tx)

    def test_remove_transaction(self):
        pool = Mempool()
        tx = _make_tx()
        pool.add_transaction(tx)
        pool.remove_transaction(tx.tx_hash)
        assert pool.size == 0

    def test_get_transactions_ordered(self):
        pool = Mempool()
        tx1 = _make_tx(amount=100)
        tx2 = _make_tx(amount=5000)
        tx3 = _make_tx(amount=500)
        pool.add_transaction(tx1)
        pool.add_transaction(tx2)
        pool.add_transaction(tx3)

        txs = pool.get_transactions()
        # Should be ordered by output amount (descending)
        assert txs[0].total_output() >= txs[1].total_output()

    def test_contains(self):
        pool = Mempool()
        tx = _make_tx()
        pool.add_transaction(tx)
        assert pool.contains(tx.tx_hash)
        assert not pool.contains("nonexistent")

    def test_clear(self):
        pool = Mempool()
        for i in range(5):
            pool.add_transaction(_make_tx(amount=i * 100 + 1))
        pool.clear()
        assert pool.size == 0

    def test_get_info(self):
        pool = Mempool()
        info = pool.get_info()
        assert "size" in info
        assert "max_size" in info
