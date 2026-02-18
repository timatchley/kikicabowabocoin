"""Tests for blockchain."""

import pytest
from kikicabowabocoin.blockchain import (
    Block,
    BlockHeader,
    Blockchain,
    create_genesis_block,
)
from kikicabowabocoin.config import BLOCK_REWARD, INITIAL_DIFFICULTY_BITS
from kikicabowabocoin.crypto import bits_to_target


class TestGenesisBlock:
    def test_genesis_created(self):
        genesis = create_genesis_block()
        assert genesis.height == 0
        assert genesis.block_hash != ""
        assert len(genesis.transactions) == 1
        assert genesis.transactions[0].is_coinbase()

    def test_genesis_message(self):
        genesis = create_genesis_block()
        msg = genesis.transactions[0].inputs[0].signature
        assert "KikicabowaboCoin" in msg

    def test_genesis_reward(self):
        genesis = create_genesis_block()
        assert genesis.transactions[0].total_output() == BLOCK_REWARD


class TestBlockchain:
    def test_init_with_genesis(self):
        bc = Blockchain()
        assert bc.height == 0
        assert len(bc.chain) == 1
        assert bc.tip == bc.chain[0]

    def test_chain_info(self):
        bc = Blockchain()
        info = bc.get_chain_info()
        assert info["height"] == 0
        assert "KIKI" in info["coin"]

    def test_get_block_by_height(self):
        bc = Blockchain()
        block = bc.get_block_by_height(0)
        assert block is not None
        assert block.height == 0

    def test_get_block_by_height_invalid(self):
        bc = Blockchain()
        assert bc.get_block_by_height(999) is None

    def test_get_block_by_hash(self):
        bc = Blockchain()
        genesis = bc.chain[0]
        found = bc.get_block_by_hash(genesis.block_hash)
        assert found is not None
        assert found.height == 0

    def test_utxo_set_after_genesis(self):
        bc = Blockchain()
        # Genesis coinbase creates one UTXO
        assert len(bc.utxo_set) == 1

    def test_genesis_balance(self):
        bc = Blockchain()
        # Genesis reward goes to "KikiGenesis"
        balance = bc.get_balance("KikiGenesis")
        assert balance == BLOCK_REWARD

    def test_calculate_next_bits(self):
        bc = Blockchain()
        bits = bc.calculate_next_bits()
        # At height 0, should return initial difficulty
        assert bits == INITIAL_DIFFICULTY_BITS


class TestBlockSerialization:
    def test_block_roundtrip(self):
        genesis = create_genesis_block()
        data = genesis.serialize()
        recovered = Block.deserialize(data)
        assert recovered.height == genesis.height
        assert recovered.block_hash == genesis.block_hash
        assert len(recovered.transactions) == len(genesis.transactions)

    def test_block_header_hash(self):
        header = BlockHeader(
            version=1,
            prev_hash="0" * 64,
            merkle_root="a" * 64,
            timestamp=1000000,
            bits=0x1e0fffff,
            nonce=42,
        )
        h1 = header.compute_hash()
        h2 = header.compute_hash()
        assert h1 == h2
        assert len(h1) == 64  # hex-encoded 32 bytes
