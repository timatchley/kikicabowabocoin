"""
Peer-to-Peer networking for KikicabowaboCoin.

Implements a gossip protocol using asyncio streams for:
- Node discovery
- Block propagation  (new blocks broadcast to all peers)
- Transaction propagation
- Initial Block Download (IBD) — sync the longest chain on connect

Compatible with Python 3.7+ (Raspberry Pi Buster ships 3.7.3).
"""

import asyncio
import json
import logging
import os
import time
from typing import Dict, List, Optional, Set

from kikicabowabocoin.config import (
    DEFAULT_PORT,
    MAX_PEERS,
    DATA_DIR,
    PEERS_FILE,
)
from kikicabowabocoin.blockchain import Block, Blockchain
from kikicabowabocoin.transaction import Transaction
from kikicabowabocoin.mempool import Mempool

logger = logging.getLogger("kiki.network")

# Maximum number of blocks to send in a single sync batch
SYNC_BATCH = 50


# ───────────────────────────────────────────────────────────────────────────
# Peer connection — wraps a reader/writer pair
# ───────────────────────────────────────────────────────────────────────────

class Peer:
    """Represents a single TCP connection to another node."""

    def __init__(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
        node: "Node",
        inbound: bool = False,
    ):
        self.reader = reader
        self.writer = writer
        self.node = node
        self.inbound = inbound

        peer = writer.get_extra_info("peername")
        self.host = peer[0] if peer else "unknown"
        self.port = peer[1] if peer else 0
        self.listen_port = 0  # filled in after VERSION handshake
        self.height = 0
        self.connected_at = time.time()
        self._closing = False

    @property
    def address(self):
        """Canonical address used as dict key (uses listen port, not ephemeral)."""
        p = self.listen_port if self.listen_port else self.port
        return "{}:{}".format(self.host, p)

    # ── Send / Receive ──────────────────────────────────────────────────

    async def send(self, msg_type, payload):
        """Send a newline-delimited JSON message."""
        if self._closing:
            return
        msg = json.dumps({"type": msg_type, "payload": payload}) + "\n"
        try:
            self.writer.write(msg.encode())
            await self.writer.drain()
        except (ConnectionError, OSError):
            await self.disconnect()

    async def recv(self):
        """Read the next newline-delimited JSON message."""
        try:
            line = await self.reader.readline()
            if not line:
                return None
            return json.loads(line.decode())
        except (json.JSONDecodeError, UnicodeDecodeError) as e:
            logger.debug("Bad message from {}: {}".format(self.address, e))
            return None
        except (ConnectionError, OSError):
            return None

    async def disconnect(self):
        if self._closing:
            return
        self._closing = True
        try:
            self.writer.close()
        except Exception:
            pass

    def __repr__(self):
        d = "in" if self.inbound else "out"
        return "<Peer {} {} h={}>".format(self.address, d, self.height)


# ───────────────────────────────────────────────────────────────────────────
# Full Node
# ───────────────────────────────────────────────────────────────────────────

class Node:
    """
    A KikicabowaboCoin full node.

    Manages peer connections, block/tx propagation, and chain sync.
    """

    def __init__(
        self,
        blockchain: Blockchain,
        mempool: Mempool,
        host: str = "0.0.0.0",
        port: int = DEFAULT_PORT,
    ):
        self.blockchain = blockchain
        self.mempool = mempool
        self.host = host
        self.port = port

        self.peers = {}           # address → Peer
        self._known_block_hashes = set()
        self._known_tx_hashes = set()
        self._server = None
        self._seed_peers = set()  # (host, port) pairs to reconnect to

        # Callback fired when a new block is accepted (from peer or mined)
        self.on_block_accepted = None

        # Pre-populate known block hashes from our chain
        for blk in self.blockchain.chain:
            self._known_block_hashes.add(blk.block_hash)

    # ── Lifecycle ───────────────────────────────────────────────────────

    async def start(self):
        """Start listening for inbound connections."""
        self._server = await asyncio.start_server(
            self._handle_inbound,
            self.host,
            self.port,
        )
        logger.info("🌐 Node listening on {}:{}".format(self.host, self.port))

        # Try to reconnect to previously known peers
        await self._load_and_connect_peers()

        # Start background reconnect loop
        asyncio.ensure_future(self._reconnect_loop())

    async def stop(self):
        """Gracefully shut down."""
        if self._server:
            self._server.close()
        for peer in list(self.peers.values()):
            await peer.disconnect()
        self.peers.clear()
        self._save_peers()
        self.blockchain.save()
        self.mempool.save()
        logger.info("🛑 Node shut down")

    # ── Inbound connections ─────────────────────────────────────────────

    async def _handle_inbound(self, reader, writer):
        """Called for each new incoming connection."""
        peer = Peer(reader, writer, self, inbound=True)
        logger.info("🔗 Inbound connection from {}:{}".format(peer.host, peer.port))
        await self._run_peer(peer)

    # ── Outbound connections ────────────────────────────────────────────

    async def connect_to_peer(self, host, port):
        """Initiate an outbound connection."""
        addr = "{}:{}".format(host, port)
        # Remember this peer for auto-reconnect
        self._seed_peers.add((host, port))

        if addr in self.peers:
            return
        # Don't connect to self
        if port == self.port and host in ("127.0.0.1", "0.0.0.0", "localhost"):
            return

        try:
            reader, writer = await asyncio.open_connection(host, port)
            peer = Peer(reader, writer, self, inbound=False)
            peer.listen_port = port
            logger.info("🔗 Outbound connection to {}".format(addr))
            asyncio.ensure_future(self._run_peer(peer))
        except (ConnectionRefusedError, OSError) as e:
            logger.debug("Could not connect to {}: {}".format(addr, e))

    # ── Main peer loop ──────────────────────────────────────────────────

    async def _run_peer(self, peer):
        """
        Full peer lifecycle:
        1. VERSION handshake
        2. Initial chain sync (if peer has longer chain)
        3. Message loop (blocks, txs, pings)
        """
        try:
            # --- Handshake: send our VERSION ---
            await peer.send("version", {
                "version": "1.0.0",
                "height": self.blockchain.height,
                "listen_port": self.port,
                "timestamp": time.time(),
            })

            # Wait for their VERSION
            msg = await asyncio.wait_for(peer.recv(), timeout=10)
            if not msg or msg.get("type") != "version":
                logger.debug("Bad handshake from {}".format(peer.address))
                await peer.disconnect()
                return

            payload = msg["payload"]
            peer.height = payload.get("height", 0)
            peer.listen_port = payload.get("listen_port", peer.port)

            # Exchange VERACK
            await peer.send("verack", {})

            msg = await asyncio.wait_for(peer.recv(), timeout=10)
            if not msg or msg.get("type") != "verack":
                logger.debug("No verack from {}".format(peer.address))
                await peer.disconnect()
                return

            # --- Register peer ---
            if len(self.peers) >= MAX_PEERS:
                logger.info("Max peers reached, rejecting {}".format(peer.address))
                await peer.disconnect()
                return

            self.peers[peer.address] = peer
            logger.info(
                "✅ Peer {} connected | theirs={}, ours={}".format(
                    peer.address, peer.height, self.blockchain.height
                )
            )

            # --- Initial Block Download ---
            if peer.height > self.blockchain.height:
                await self._sync_from_peer(peer)

            # --- Message loop ---
            while not peer._closing:
                try:
                    msg = await asyncio.wait_for(peer.recv(), timeout=120)
                except asyncio.TimeoutError:
                    await peer.send("ping", {"nonce": int(time.time())})
                    continue

                if msg is None:
                    break

                await self._handle_message(peer, msg)

        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.debug("Peer {} error: {}".format(
                getattr(peer, 'address', '?'), e
            ))
        finally:
            self.peers.pop(getattr(peer, 'address', ''), None)
            await peer.disconnect()
            logger.info("🔌 Peer {} disconnected".format(
                getattr(peer, 'address', '?')
            ))

    # ── Message dispatch ────────────────────────────────────────────────

    async def _handle_message(self, peer, msg):
        """Route an incoming message to the appropriate handler."""
        msg_type = msg.get("type", "")
        payload = msg.get("payload", {})

        if msg_type == "block":
            await self._on_block(peer, payload)
        elif msg_type == "tx":
            await self._on_tx(peer, payload)
        elif msg_type == "getblocks":
            await self._on_getblocks(peer, payload)
        elif msg_type == "blocks":
            await self._on_blocks(peer, payload)
        elif msg_type == "ping":
            await peer.send("pong", {"nonce": payload.get("nonce")})
        elif msg_type == "pong":
            pass
        elif msg_type == "getaddr":
            await self._on_getaddr(peer)
        elif msg_type == "addr":
            await self._on_addr(payload)
        elif msg_type == "version":
            pass  # Already handled in handshake
        else:
            logger.debug("Unknown message '{}' from {}".format(
                msg_type, peer.address
            ))

    # ── Block handling ──────────────────────────────────────────────────

    async def _on_block(self, peer, payload):
        """Handle a newly announced block from a peer."""
        try:
            block = Block.deserialize(payload)
        except Exception as e:
            logger.debug("Bad block data from {}: {}".format(peer.address, e))
            return

        if block.block_hash in self._known_block_hashes:
            return

        try:
            self.blockchain.add_block(block)
            self._known_block_hashes.add(block.block_hash)

            # Remove mined txs from mempool
            for tx in block.transactions[1:]:
                self.mempool.remove_transaction(tx.tx_hash)

            self.blockchain.save()
            self.mempool.save()

            logger.info(
                "📦 Block #{} from {} | hash={}…".format(
                    block.height, peer.address, block.block_hash[:24]
                )
            )

            # Fire callback (useful for miner to know a new block arrived)
            if self.on_block_accepted:
                self.on_block_accepted(block)

            # Relay to other peers
            await self.broadcast_block(block, exclude=peer.address)
            peer.height = max(peer.height, block.height)

        except ValueError as e:
            logger.debug("Block #{} rejected: {}".format(block.height, e))

    async def _on_tx(self, peer, payload):
        """Handle a new transaction from a peer."""
        try:
            tx = Transaction.deserialize(payload)
        except Exception as e:
            logger.debug("Bad tx from {}: {}".format(peer.address, e))
            return

        if tx.tx_hash in self._known_tx_hashes:
            return

        if self.mempool.add_transaction(tx):
            self._known_tx_hashes.add(tx.tx_hash)
            self.mempool.save()
            await self.broadcast_tx(tx, exclude=peer.address)

    # ── Chain sync ──────────────────────────────────────────────────────

    async def _sync_from_peer(self, peer):
        """Download blocks we're missing from a peer (Initial Block Download)."""
        our_height = self.blockchain.height
        their_height = peer.height

        logger.info(
            "📥 Syncing blocks {}..{} from {}".format(
                our_height + 1, their_height, peer.address
            )
        )

        start = our_height + 1
        while start <= their_height:
            end = min(start + SYNC_BATCH - 1, their_height)
            await peer.send("getblocks", {
                "start_height": start,
                "end_height": end,
            })

            try:
                msg = await asyncio.wait_for(peer.recv(), timeout=30)
            except asyncio.TimeoutError:
                logger.warning("Sync timeout from {}".format(peer.address))
                break

            if not msg or msg.get("type") != "blocks":
                # Might be a different message type — handle and retry
                if msg:
                    await self._handle_message(peer, msg)
                continue

            block_list = msg["payload"].get("blocks", [])
            if not block_list:
                break

            for block_data in block_list:
                try:
                    block = Block.deserialize(block_data)
                    self.blockchain.add_block(block)
                    self._known_block_hashes.add(block.block_hash)
                    logger.info("📦 Synced block #{}".format(block.height))
                except ValueError as e:
                    logger.warning("Sync block rejected: {}".format(e))
                    self.blockchain.save()
                    return

            start = end + 1

        self.blockchain.save()
        logger.info(
            "✅ Sync complete — chain height: {}".format(self.blockchain.height)
        )

    async def _on_getblocks(self, peer, payload):
        """Peer is requesting blocks from us."""
        start = payload.get("start_height", 0)
        end = payload.get("end_height", start + SYNC_BATCH - 1)
        end = min(end, self.blockchain.height)

        blocks = []
        for h in range(start, end + 1):
            block = self.blockchain.get_block_by_height(h)
            if block:
                blocks.append(block.serialize())

        await peer.send("blocks", {"blocks": blocks})
        logger.debug("Sent {} blocks ({}..{}) to {}".format(
            len(blocks), start, end, peer.address
        ))

    async def _on_blocks(self, peer, payload):
        """Handle a batch of blocks (async response to getblocks)."""
        for block_data in payload.get("blocks", []):
            try:
                block = Block.deserialize(block_data)
                if block.block_hash not in self._known_block_hashes:
                    self.blockchain.add_block(block)
                    self._known_block_hashes.add(block.block_hash)
                    logger.info("📦 Block #{} synced".format(block.height))
            except ValueError as e:
                logger.debug("Block rejected during batch: {}".format(e))
        self.blockchain.save()

    # ── Broadcasting ────────────────────────────────────────────────────

    async def broadcast_block(self, block, exclude=""):
        """Send a new block to all connected peers."""
        data = block.serialize()
        for addr, peer in list(self.peers.items()):
            if addr != exclude:
                await peer.send("block", data)
        self._known_block_hashes.add(block.block_hash)

    async def broadcast_tx(self, tx, exclude=""):
        """Send a new transaction to all connected peers."""
        data = tx.serialize()
        for addr, peer in list(self.peers.items()):
            if addr != exclude:
                await peer.send("tx", data)
        self._known_tx_hashes.add(tx.tx_hash)

    # ── Peer discovery ──────────────────────────────────────────────────

    async def _on_getaddr(self, peer):
        addrs = [
            {"host": p.host, "port": p.listen_port}
            for p in self.peers.values()
            if p.address != peer.address
        ]
        await peer.send("addr", {"addresses": addrs})

    async def _on_addr(self, payload):
        for addr in payload.get("addresses", []):
            host = addr["host"]
            port = addr["port"]
            key = "{}:{}".format(host, port)
            if key not in self.peers:
                await self.connect_to_peer(host, port)

    # ── Peer persistence ────────────────────────────────────────────────

    def _save_peers(self):
        os.makedirs(DATA_DIR, exist_ok=True)
        data = [
            {"host": p.host, "port": p.listen_port, "last_seen": time.time()}
            for p in self.peers.values()
        ]
        # Also save seed peers so they survive restarts
        for host, port in self._seed_peers:
            key = "{}:{}".format(host, port)
            if not any(d["host"] == host and d["port"] == port for d in data):
                data.append({"host": host, "port": port, "last_seen": 0})
        with open(PEERS_FILE, "w") as f:
            json.dump(data, f, indent=2)

    async def _load_and_connect_peers(self):
        if not os.path.exists(PEERS_FILE):
            return
        try:
            with open(PEERS_FILE, "r") as f:
                data = json.load(f)
            for p in data:
                await self.connect_to_peer(p["host"], p["port"])
        except (json.JSONDecodeError, KeyError):
            pass

    # ── Auto-reconnect ──────────────────────────────────────────────────

    async def _reconnect_loop(self):
        """Periodically try to reconnect to known seed peers."""
        while True:
            await asyncio.sleep(15)  # Check every 15 seconds
            for host, port in list(self._seed_peers):
                addr = "{}:{}".format(host, port)
                if addr not in self.peers:
                    logger.debug("🔄 Reconnecting to {}...".format(addr))
                    await self.connect_to_peer(host, port)

    # ── Status ──────────────────────────────────────────────────────────

    def get_status(self):
        return {
            "host": self.host,
            "port": self.port,
            "peers": len(self.peers),
            "peer_list": [p.address for p in self.peers.values()],
            "chain_height": self.blockchain.height,
            "mempool_size": self.mempool.size,
        }
