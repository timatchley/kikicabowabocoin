"""
Peer-to-Peer networking for KikicabowaboCoin.

Implements a simple gossip protocol for:
- Node discovery
- Block propagation
- Transaction propagation
- Chain synchronisation

Similar in spirit to Dogecoin's networking (inherited from Bitcoin),
but simplified for clarity.
"""

import asyncio
import json
import logging
import os
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set

from kikicabowabocoin.config import (
    DEFAULT_PORT,
    MAX_PEERS,
    SEED_NODES,
    DATA_DIR,
    PEERS_FILE,
)
from kikicabowabocoin.blockchain import Block, Blockchain
from kikicabowabocoin.transaction import Transaction
from kikicabowabocoin.mempool import Mempool

logger = logging.getLogger("kiki.network")


# ===========================================================================
# Message types
# ===========================================================================

class MessageType:
    VERSION = "version"
    VERACK = "verack"
    GETBLOCKS = "getblocks"
    INV = "inv"
    GETDATA = "getdata"
    BLOCK = "block"
    TX = "tx"
    GETADDR = "getaddr"
    ADDR = "addr"
    PING = "ping"
    PONG = "pong"


# ===========================================================================
# Peer info
# ===========================================================================

@dataclass
class PeerInfo:
    host: str
    port: int
    last_seen: float = field(default_factory=time.time)
    version: str = ""
    height: int = 0

    @property
    def address(self) -> str:
        return f"{self.host}:{self.port}"


# ===========================================================================
# Protocol handler
# ===========================================================================

class PeerProtocol(asyncio.Protocol):
    """Handles communication with a single peer."""

    def __init__(self, node: "Node"):
        self.node = node
        self.transport = None
        self.peer_info: Optional[PeerInfo] = None
        self._buffer = b""

    def connection_made(self, transport):
        self.transport = transport
        peername = transport.get_extra_info("peername")
        logger.info(f"🔗 Connected to {peername}")
        # Send version message
        self.send_message(MessageType.VERSION, {
            "version": "1.0.0",
            "height": self.node.blockchain.height,
            "timestamp": time.time(),
        })

    def connection_lost(self, exc):
        if self.peer_info:
            self.node.remove_peer(self.peer_info.address)
            logger.info(f"🔌 Disconnected from {self.peer_info.address}")

    def data_received(self, data: bytes):
        self._buffer += data
        while b"\n" in self._buffer:
            line, self._buffer = self._buffer.split(b"\n", 1)
            try:
                message = json.loads(line.decode())
                self._handle_message(message)
            except (json.JSONDecodeError, UnicodeDecodeError) as e:
                logger.warning(f"Invalid message: {e}")

    def send_message(self, msg_type: str, payload: dict):
        """Send a JSON message to this peer."""
        message = {"type": msg_type, "payload": payload}
        data = json.dumps(message).encode() + b"\n"
        if self.transport and not self.transport.is_closing():
            self.transport.write(data)

    def _handle_message(self, message: dict):
        msg_type = message.get("type")
        payload = message.get("payload", {})

        handlers = {
            MessageType.VERSION: self._on_version,
            MessageType.VERACK: self._on_verack,
            MessageType.GETBLOCKS: self._on_getblocks,
            MessageType.INV: self._on_inv,
            MessageType.GETDATA: self._on_getdata,
            MessageType.BLOCK: self._on_block,
            MessageType.TX: self._on_tx,
            MessageType.GETADDR: self._on_getaddr,
            MessageType.ADDR: self._on_addr,
            MessageType.PING: self._on_ping,
            MessageType.PONG: self._on_pong,
        }

        handler = handlers.get(msg_type)
        if handler:
            handler(payload)
        else:
            logger.debug(f"Unknown message type: {msg_type}")

    # --- Message handlers ----------------------------------------------------

    def _on_version(self, payload: dict):
        peername = self.transport.get_extra_info("peername")
        self.peer_info = PeerInfo(
            host=peername[0],
            port=peername[1],
            version=payload.get("version", ""),
            height=payload.get("height", 0),
        )
        self.node.add_peer(self.peer_info, self)
        self.send_message(MessageType.VERACK, {})

        # If peer has a longer chain, request blocks
        if self.peer_info.height > self.node.blockchain.height:
            self.send_message(MessageType.GETBLOCKS, {
                "start_height": self.node.blockchain.height + 1,
            })

    def _on_verack(self, payload: dict):
        logger.debug("Received verack")

    def _on_getblocks(self, payload: dict):
        start = payload.get("start_height", 0)
        blocks = []
        for h in range(start, min(start + 500, self.node.blockchain.height + 1)):
            block = self.node.blockchain.get_block_by_height(h)
            if block:
                blocks.append(block.serialize())
        self.send_message(MessageType.INV, {"blocks": blocks})

    def _on_inv(self, payload: dict):
        for block_data in payload.get("blocks", []):
            block = Block.deserialize(block_data)
            try:
                self.node.blockchain.add_block(block)
                logger.info(f"📦 Synced block #{block.height}")
            except ValueError as e:
                logger.debug(f"Block rejected: {e}")

    def _on_getdata(self, payload: dict):
        block_hash = payload.get("block_hash")
        if block_hash:
            block = self.node.blockchain.get_block_by_hash(block_hash)
            if block:
                self.send_message(MessageType.BLOCK, block.serialize())

        tx_hash = payload.get("tx_hash")
        if tx_hash:
            tx = self.node.mempool.get_transaction(tx_hash)
            if tx:
                self.send_message(MessageType.TX, tx.serialize())

    def _on_block(self, payload: dict):
        block = Block.deserialize(payload)
        try:
            self.node.blockchain.add_block(block)
            logger.info(f"📦 Received block #{block.height}")
            # Relay to other peers
            self.node.broadcast_block(block, exclude=self.peer_info.address)
        except ValueError as e:
            logger.debug(f"Block rejected: {e}")

    def _on_tx(self, payload: dict):
        tx = Transaction.deserialize(payload)
        if self.node.mempool.add_transaction(tx):
            # Relay to other peers
            self.node.broadcast_transaction(tx, exclude=self.peer_info.address)

    def _on_getaddr(self, payload: dict):
        addrs = [
            {"host": p.host, "port": p.port}
            for p in self.node.peers.values()
        ]
        self.send_message(MessageType.ADDR, {"addresses": addrs})

    def _on_addr(self, payload: dict):
        for addr in payload.get("addresses", []):
            host, port = addr["host"], addr["port"]
            key = f"{host}:{port}"
            if key not in self.node.peers:
                asyncio.ensure_future(self.node.connect_to_peer(host, port))

    def _on_ping(self, payload: dict):
        self.send_message(MessageType.PONG, {"nonce": payload.get("nonce")})

    def _on_pong(self, payload: dict):
        if self.peer_info:
            self.peer_info.last_seen = time.time()


# ===========================================================================
# Node
# ===========================================================================

class Node:
    """
    A KikicabowaboCoin network node.

    Manages peer connections, block/transaction propagation, and
    chain synchronisation.
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

        self.peers: Dict[str, PeerInfo] = {}
        self._connections: Dict[str, PeerProtocol] = {}
        self._server = None
        self._loop = None

    # --- Peer management -----------------------------------------------------

    def add_peer(self, peer: PeerInfo, protocol: PeerProtocol):
        if len(self.peers) < MAX_PEERS:
            self.peers[peer.address] = peer
            self._connections[peer.address] = protocol

    def remove_peer(self, address: str):
        self.peers.pop(address, None)
        self._connections.pop(address, None)

    # --- Broadcasting --------------------------------------------------------

    def broadcast_block(self, block: Block, exclude: str = ""):
        """Send a new block to all connected peers."""
        data = block.serialize()
        for addr, proto in self._connections.items():
            if addr != exclude:
                proto.send_message(MessageType.BLOCK, data)

    def broadcast_transaction(self, tx: Transaction, exclude: str = ""):
        """Send a new transaction to all connected peers."""
        data = tx.serialize()
        for addr, proto in self._connections.items():
            if addr != exclude:
                proto.send_message(MessageType.TX, data)

    # --- Server lifecycle ----------------------------------------------------

    async def start(self):
        """Start listening for incoming peer connections."""
        self._loop = asyncio.get_event_loop()

        self._server = await self._loop.create_server(
            lambda: PeerProtocol(self),
            self.host,
            self.port,
        )
        logger.info(f"🌐 Node listening on {self.host}:{self.port}")

        # Connect to seed nodes
        for host, port in SEED_NODES:
            await self.connect_to_peer(host, port)

        # Load saved peers
        await self._load_and_connect_peers()

    async def stop(self):
        """Shut down the node."""
        if self._server:
            self._server.close()
            await self._server.wait_closed()
        self._save_peers()
        logger.info("Node shut down")

    async def connect_to_peer(self, host: str, port: int):
        """Initiate an outbound connection to a peer."""
        address = f"{host}:{port}"
        if address in self.peers:
            return

        try:
            await self._loop.create_connection(
                lambda: PeerProtocol(self),
                host,
                port,
            )
            logger.info(f"🔗 Connected to peer {address}")
        except (ConnectionRefusedError, OSError) as e:
            logger.debug(f"Could not connect to {address}: {e}")

    # --- Peer persistence ----------------------------------------------------

    def _save_peers(self):
        os.makedirs(DATA_DIR, exist_ok=True)
        data = [
            {"host": p.host, "port": p.port, "last_seen": p.last_seen}
            for p in self.peers.values()
        ]
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

    # --- Status --------------------------------------------------------------

    def get_status(self) -> dict:
        return {
            "host": self.host,
            "port": self.port,
            "peers": len(self.peers),
            "chain_height": self.blockchain.height,
            "mempool_size": self.mempool.size,
        }
