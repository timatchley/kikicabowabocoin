"""Tests for the miner."""

import pytest
from kikicabowabocoin.blockchain import Blockchain
from kikicabowabocoin.miner import Miner
from kikicabowabocoin.config import BLOCK_REWARD


class TestMiner:
    def test_mine_single_block(self):
        bc = Blockchain()
        miner = Miner(blockchain=bc, miner_address="MinerTestAddr")

        block = miner.mine_block()
        assert block is not None
        assert block.height == 1
        assert bc.height == 1

    def test_mine_reward(self):
        bc = Blockchain()
        miner = Miner(blockchain=bc, miner_address="MinerTestAddr")

        miner.mine_block()
        balance = bc.get_balance("MinerTestAddr")
        assert balance == BLOCK_REWARD

    def test_mine_multiple_blocks(self):
        bc = Blockchain()
        miner = Miner(blockchain=bc, miner_address="MinerTestAddr")

        for _ in range(3):
            block = miner.mine_block()
            assert block is not None

        assert bc.height == 3
        assert miner.blocks_mined == 3
        balance = bc.get_balance("MinerTestAddr")
        assert balance == BLOCK_REWARD * 3

    def test_miner_status(self):
        bc = Blockchain()
        miner = Miner(blockchain=bc, miner_address="MinerTestAddr")
        miner.mine_block()

        status = miner.get_status()
        assert status["blocks_mined"] == 1
        assert status["miner_address"] == "MinerTestAddr"
        assert status["chain_height"] == 1

    def test_callback_on_block_mined(self):
        bc = Blockchain()
        mined_blocks = []

        miner = Miner(
            blockchain=bc,
            miner_address="MinerTestAddr",
            on_block_mined=lambda b: mined_blocks.append(b),
        )
        miner.mine_block()

        assert len(mined_blocks) == 1
        assert mined_blocks[0].height == 1
