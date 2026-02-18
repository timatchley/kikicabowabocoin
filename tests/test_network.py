"""
Tests for KikicabowaboCoin P2P Networking.

Tests the network layer using local loopback connections:
- Node startup and shutdown
- Peer handshake (VERSION / VERACK)
- Initial Block Download (chain sync)
- Block propagation between peers
- Transaction relay between peers
"""

import asyncio
import pytest
import time

from kikicabowabocoin.blockchain import Blockchain, Block
from kikicabowabocoin.mempool import Mempool
from kikicabowabocoin.miner import Miner
from kikicabowabocoin.network import Node, Peer


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_node(port, blockchain=None, mempool=None):
    """Create a Node bound to a specific port."""
    bc = blockchain or Blockchain()
    mp = mempool or Mempool()
    return Node(bc, mp, host="127.0.0.1", port=port)


def _mine_blocks(bc, n, address="TestMiner"):
    """Synchronously mine n blocks onto a blockchain."""
    miner = Miner(bc, address)
    for _ in range(n):
        miner.mine_block()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestNodeLifecycle:
    """Node can start, listen, and stop cleanly."""

    @pytest.mark.asyncio
    async def test_start_and_stop(self):
        node = _make_node(45100)
        await node.start()
        assert node._server is not None
        await node.stop()

    @pytest.mark.asyncio
    async def test_get_status(self):
        node = _make_node(45101)
        await node.start()
        status = node.get_status()
        assert status["port"] == 45101
        assert status["chain_height"] == 0
        assert status["peers"] == 0
        await node.stop()


class TestPeerHandshake:
    """Two nodes can connect and complete the VERSION/VERACK handshake."""

    @pytest.mark.asyncio
    async def test_two_nodes_connect(self):
        node_a = _make_node(45110)
        node_b = _make_node(45111)

        await node_a.start()
        await node_b.start()

        # B connects to A
        await node_b.connect_to_peer("127.0.0.1", 45110)
        await asyncio.sleep(0.5)  # Let handshake complete

        assert len(node_a.peers) == 1
        assert len(node_b.peers) == 1

        await node_a.stop()
        await node_b.stop()

    @pytest.mark.asyncio
    async def test_no_self_connect(self):
        node = _make_node(45120)
        await node.start()
        await node.connect_to_peer("127.0.0.1", 45120)
        await asyncio.sleep(0.3)
        assert len(node.peers) == 0
        await node.stop()


class TestChainSync:
    """A node with a shorter chain syncs from a peer with a longer chain."""

    @pytest.mark.asyncio
    async def test_sync_on_connect(self):
        # Node A mines 5 blocks
        bc_a = Blockchain()
        _mine_blocks(bc_a, 5)
        assert bc_a.height == 5

        node_a = _make_node(45130, blockchain=bc_a)
        node_b = _make_node(45131)  # Fresh chain (height 0)

        await node_a.start()
        await node_b.start()

        # B connects to A and should sync
        await node_b.connect_to_peer("127.0.0.1", 45130)
        await asyncio.sleep(1.0)

        assert node_b.blockchain.height == 5
        assert node_b.blockchain.tip.block_hash == node_a.blockchain.tip.block_hash

        await node_a.stop()
        await node_b.stop()

    @pytest.mark.asyncio
    async def test_sync_many_blocks(self):
        bc_a = Blockchain()
        _mine_blocks(bc_a, 15)

        node_a = _make_node(45140, blockchain=bc_a)
        node_b = _make_node(45141)

        await node_a.start()
        await node_b.start()
        await node_b.connect_to_peer("127.0.0.1", 45140)
        await asyncio.sleep(1.5)

        assert node_b.blockchain.height == 15

        await node_a.stop()
        await node_b.stop()


class TestBlockPropagation:
    """When a node mines a block, connected peers receive it."""

    @pytest.mark.asyncio
    async def test_broadcast_block(self):
        node_a = _make_node(45150)
        node_b = _make_node(45151)

        await node_a.start()
        await node_b.start()
        await node_b.connect_to_peer("127.0.0.1", 45150)
        await asyncio.sleep(0.5)

        # Mine a block on A
        miner = Miner(node_a.blockchain, "MinerA")
        block = miner.mine_block()
        assert block is not None

        # Broadcast it
        await node_a.broadcast_block(block)
        await asyncio.sleep(0.5)

        # B should have received it
        assert node_b.blockchain.height == 1
        assert node_b.blockchain.tip.block_hash == block.block_hash

        await node_a.stop()
        await node_b.stop()

    @pytest.mark.asyncio
    async def test_broadcast_multiple_blocks(self):
        node_a = _make_node(45160)
        node_b = _make_node(45161)

        await node_a.start()
        await node_b.start()
        await node_b.connect_to_peer("127.0.0.1", 45160)
        await asyncio.sleep(0.5)

        miner = Miner(node_a.blockchain, "MinerA")
        for _ in range(3):
            block = miner.mine_block()
            await node_a.broadcast_block(block)
            await asyncio.sleep(0.3)

        assert node_b.blockchain.height == 3

        await node_a.stop()
        await node_b.stop()


class TestTransactionRelay:
    """Transactions are relayed between connected peers."""

    @pytest.mark.asyncio
    async def test_tx_relay(self):
        from kikicabowabocoin.transaction import Transaction

        node_a = _make_node(45170)
        node_b = _make_node(45171)

        await node_a.start()
        await node_b.start()
        await node_b.connect_to_peer("127.0.0.1", 45170)
        await asyncio.sleep(0.5)

        # Mine a block on A to create a UTXO, then create a tx
        miner = Miner(node_a.blockchain, "MinerA")
        miner.mine_block()

        # Create a simple (non-coinbase) transaction to relay
        tx = Transaction(
            version=1,
            inputs=[],
            outputs=[],
            timestamp=time.time(),
        )
        # Manually set a hash so it's not treated as coinbase
        tx.inputs = [
            type("Input", (), {
                "prev_tx_hash": "a" * 64,
                "output_index": 0,
                "signature": "test",
                "public_key": "test",
            })()
        ]
        tx.outputs = [
            type("Output", (), {
                "amount": 50,
                "address": "TestAddr",
            })()
        ]
        tx.tx_hash = tx.compute_hash()

        # Add to A's mempool and broadcast
        node_a.mempool.add_transaction(tx)
        await node_a.broadcast_tx(tx)
        await asyncio.sleep(0.5)

        # B's mempool should have it
        assert node_b.mempool.contains(tx.tx_hash)

        await node_a.stop()
        await node_b.stop()
