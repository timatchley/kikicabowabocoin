"""Tests for transactions."""

import pytest
from kikicabowabocoin.transaction import Transaction, TxInput, TxOutput
from kikicabowabocoin.config import BLOCK_REWARD


class TestTxOutput:
    def test_serialize_deserialize(self):
        out = TxOutput(amount=5000, address="KikiTestAddr123")
        data = out.serialize()
        recovered = TxOutput.deserialize(data)
        assert recovered.amount == 5000
        assert recovered.address == "KikiTestAddr123"


class TestTxInput:
    def test_serialize_deserialize(self):
        inp = TxInput(
            prev_tx_hash="abcd1234" * 8,
            output_index=0,
            signature="sig_hex",
            public_key="pub_hex",
        )
        data = inp.serialize()
        recovered = TxInput.deserialize(data)
        assert recovered.prev_tx_hash == inp.prev_tx_hash
        assert recovered.output_index == 0
        assert recovered.signature == "sig_hex"


class TestTransaction:
    def test_create_coinbase(self):
        tx = Transaction.create_coinbase(
            block_height=1,
            reward=BLOCK_REWARD,
            miner_address="KikiMiner123",
        )
        assert tx.is_coinbase()
        assert tx.total_output() == BLOCK_REWARD
        assert tx.outputs[0].address == "KikiMiner123"
        assert tx.tx_hash != ""

    def test_coinbase_hash_deterministic(self):
        tx = Transaction.create_coinbase(1, BLOCK_REWARD, "addr")
        hash1 = tx.compute_hash()
        hash2 = tx.compute_hash()
        assert hash1 == hash2

    def test_regular_transaction(self):
        tx = Transaction(
            inputs=[
                TxInput(prev_tx_hash="a" * 64, output_index=0),
            ],
            outputs=[
                TxOutput(amount=3000, address="recipient"),
                TxOutput(amount=6999, address="sender_change"),
            ],
        )
        assert not tx.is_coinbase()
        assert tx.total_output() == 9999

    def test_serialize_deserialize(self):
        tx = Transaction.create_coinbase(5, BLOCK_REWARD, "TestAddr")
        data = tx.serialize()
        recovered = Transaction.deserialize(data)
        assert recovered.tx_hash == tx.tx_hash
        assert recovered.is_coinbase()
        assert recovered.total_output() == BLOCK_REWARD

    def test_different_txs_different_hashes(self):
        tx1 = Transaction.create_coinbase(1, BLOCK_REWARD, "addr1")
        tx2 = Transaction.create_coinbase(2, BLOCK_REWARD, "addr2")
        assert tx1.compute_hash() != tx2.compute_hash()
