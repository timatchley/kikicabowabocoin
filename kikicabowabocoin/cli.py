"""
KikicabowaboCoin CLI — Command-Line Interface.

Provides a full node experience:
  - Wallet management (create, list, balance)
  - Send KIKI coins
  - Mine blocks
  - View blockchain info
  - Start a network node

Usage:
    python -m kikicabowabocoin.cli [command] [options]
"""

import argparse
import asyncio
import json
import logging
import os
import sys
import time

from kikicabowabocoin import __version__, __coin_name__, __ticker__
from kikicabowabocoin.config import (
    BLOCK_REWARD,
    DATA_DIR,
    DEFAULT_PORT,
    MIN_TX_FEE,
    TARGET_BLOCK_TIME,
)
from kikicabowabocoin.blockchain import Blockchain
from kikicabowabocoin.wallet import Wallet
from kikicabowabocoin.miner import Miner
from kikicabowabocoin.mempool import Mempool
from kikicabowabocoin.network import Node

logger = logging.getLogger("kiki.cli")


BANNER = r"""
  _  ___ _    _           _                         _            ____      _
 | |/ (_) | _(_) ___ __ _| |__   _____      ____ _| |__   ___  / ___|___ (_)_ __
 | ' /| | |/ / |/ __/ _` | '_ \ / _ \ \ /\ / / _` | '_ \ / _ \| |   / _ \| | '_ \
 | . \| |   <| | (_| (_| | |_) | (_) \ V  V / (_| | |_) | (_) | |__| (_) | | | | |
 |_|\_\_|_|\_\_|\___\__,_|_.__/ \___/ \_/\_/ \__,_|_.__/ \___/ \____\___/|_|_| |_|

                        ✨ Much coin. Very crypto. Wow! ✨
                        Version {version} — Ticker: {ticker}
"""


def setup_logging(verbose: bool = False):
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
        datefmt="%H:%M:%S",
    )


def get_blockchain() -> Blockchain:
    """Load existing blockchain or create a new one."""
    chain_file = os.path.join(DATA_DIR, "chain.json")
    if os.path.exists(chain_file):
        try:
            return Blockchain.load(chain_file)
        except Exception:
            pass
    return Blockchain()


def get_wallet() -> Wallet:
    """Load existing wallet or create a new one."""
    wallet = Wallet()
    wallet.load()
    return wallet


# ===========================================================================
# Commands
# ===========================================================================

def cmd_info(args):
    """Show blockchain information."""
    bc = get_blockchain()
    info = bc.get_chain_info()
    print(f"\n{'═' * 50}")
    print(f"  {__coin_name__} ({__ticker__}) — Chain Info")
    print(f"{'═' * 50}")
    for key, val in info.items():
        print(f"  {key:>20s}: {val}")
    print(f"  {'block_reward':>20s}: {BLOCK_REWARD:,} {__ticker__}")
    print(f"  {'target_block_time':>20s}: {TARGET_BLOCK_TIME}s")
    print(f"  {'supply_cap':>20s}: ∞ (inflationary)")
    print(f"{'═' * 50}\n")


def cmd_wallet_create(args):
    """Create a new wallet address."""
    wallet = get_wallet()
    label = args.label or f"address-{len(wallet.keys)}"
    address = wallet.generate_address(label=label)
    wallet.save()
    print(f"\n✅ New address created: {address}")
    print(f"   Label: {label}")
    print(f"   ⚠️  Back up your wallet file: {wallet.filepath}\n")


def cmd_wallet_list(args):
    """List all wallet addresses."""
    wallet = get_wallet()
    if not wallet.keys:
        print("\nNo addresses yet. Create one with: kiki wallet create\n")
        return

    print(f"\n{'═' * 60}")
    print(f"  {__coin_name__} Wallet — {len(wallet.keys)} address(es)")
    print(f"{'═' * 60}")

    bc = get_blockchain()
    for kp in wallet.keys:
        balance = bc.get_balance(kp.address)
        print(f"  [{kp.label}]")
        print(f"    Address: {kp.address}")
        print(f"    Balance: {balance:,} {__ticker__}")
        print()
    print(f"{'═' * 60}\n")


def cmd_wallet_balance(args):
    """Check balance of an address."""
    bc = get_blockchain()
    balance = bc.get_balance(args.address)
    print(f"\n  Address: {args.address}")
    print(f"  Balance: {balance:,} {__ticker__}\n")


def cmd_send(args):
    """Send KIKI coins to another address."""
    wallet = get_wallet()
    bc = get_blockchain()

    from_addr = args.from_address or wallet.default_address
    to_addr = args.to_address
    amount = int(args.amount)
    fee = int(args.fee) if args.fee else MIN_TX_FEE

    # Get UTXOs for the sender
    utxos = bc.get_utxos_for_address(from_addr)
    balance = sum(u["amount"] for u in utxos)

    if balance < amount + fee:
        print(f"\n❌ Insufficient balance: {balance:,} < {amount + fee:,}\n")
        return

    try:
        tx = wallet.create_transaction(from_addr, to_addr, amount, fee, utxos)
        print(f"\n✅ Transaction created!")
        print(f"   TxID:   {tx.tx_hash}")
        print(f"   From:   {from_addr}")
        print(f"   To:     {to_addr}")
        print(f"   Amount: {amount:,} {__ticker__}")
        print(f"   Fee:    {fee:,} {__ticker__}")
        print(f"\n   Transaction will be included in the next mined block.\n")

        # Add to mempool (in a full node, this would broadcast too)
        mempool = Mempool.load()
        mempool.add_transaction(tx)
        mempool.save()

    except ValueError as e:
        print(f"\n❌ Error: {e}\n")


def cmd_mine(args):
    """Mine blocks."""
    wallet = get_wallet()
    bc = get_blockchain()
    mempool = Mempool.load()

    address = args.address or wallet.default_address
    num_blocks = args.blocks or 1

    print(f"\n⛏  Mining {num_blocks} block(s) to address: {address}")
    print(f"   Block reward: {BLOCK_REWARD:,} {__ticker__} per block\n")

    def on_block_mined(block):
        balance = bc.get_balance(address)
        print(
            f"   ✅ Block #{block.height} mined | "
            f"hash={block.block_hash[:24]}… | "
            f"balance={balance:,} {__ticker__}"
        )

    miner = Miner(
        blockchain=bc,
        miner_address=address,
        on_block_mined=on_block_mined,
    )

    for i in range(num_blocks):
        txs = mempool.get_transactions()
        block = miner.mine_block(transactions=txs)
        if block:
            # Remove mined txs from mempool
            for tx in block.transactions[1:]:
                mempool.remove_transaction(tx.tx_hash)
            # Save chain and mempool after every block
            bc.save()
            mempool.save()

    wallet.save()

    status = miner.get_status()
    print(f"\n   Mining complete!")
    print(f"   Blocks mined this session: {status['blocks_mined']}")
    print(f"   Chain height: {bc.height}")
    print(f"   Last hashrate: {status['hashrate']}\n")


def cmd_block(args):
    """Show block details."""
    bc = get_blockchain()

    if args.hash:
        block = bc.get_block_by_hash(args.hash)
    elif args.height is not None:
        block = bc.get_block_by_height(args.height)
    else:
        block = bc.tip

    if not block:
        print("\n❌ Block not found\n")
        return

    print(f"\n{'═' * 60}")
    print(f"  Block #{block.height}")
    print(f"{'═' * 60}")
    print(f"  Hash:        {block.block_hash}")
    print(f"  Prev Hash:   {block.header.prev_hash}")
    print(f"  Merkle Root: {block.header.merkle_root}")
    print(f"  Timestamp:   {time.ctime(block.header.timestamp)}")
    print(f"  Bits:        0x{block.header.bits:08x}")
    print(f"  Nonce:       {block.header.nonce}")
    print(f"  Txs:         {len(block.transactions)}")
    print(f"{'─' * 60}")
    for i, tx in enumerate(block.transactions):
        kind = "COINBASE" if tx.is_coinbase() else "TX"
        print(f"  [{i}] {kind} {tx.tx_hash[:32]}…")
        for j, out in enumerate(tx.outputs):
            print(f"      → {out.address}: {out.amount:,} {__ticker__}")
    print(f"{'═' * 60}\n")


def cmd_node(args):
    """Start a full network node (optionally mining)."""
    bc = get_blockchain()
    mempool = Mempool.load()
    node = Node(bc, mempool, port=args.port)

    # Disable LAN discovery if requested
    if getattr(args, 'no_discovery', False):
        node._discovery_disabled = True

    # Disable seed tracker if requested
    if getattr(args, 'no_tracker', False):
        node._tracker_disabled = True

    print(BANNER.format(version=__version__, ticker=__ticker__))
    print(f"  Starting node on port {args.port}...")
    print(f"  Chain height: {bc.height}")
    if not getattr(args, 'no_discovery', False):
        print("  LAN peer discovery: enabled (automatic)")
    if not getattr(args, 'no_tracker', False):
        from kikicabowabocoin.config import SEED_TRACKER_URL
        print(f"  Seed tracker: {SEED_TRACKER_URL}")
    if args.peers:
        print(f"  Manual peers: {', '.join(args.peers)}")
    print()

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    miner = None
    miner_address = None

    if args.mine:
        wallet = get_wallet()
        miner_address = args.mine_address or wallet.default_address
        print(f"  ⛏  Mining enabled → {miner_address}\n")

    async def run():
        await node.start()

        # Connect to explicitly specified peers
        if args.peers:
            for p in args.peers:
                if ":" in p:
                    host, port_str = p.rsplit(":", 1)
                    await node.connect_to_peer(host, int(port_str))
                else:
                    await node.connect_to_peer(p, DEFAULT_PORT)

        # Mining loop (runs in the asyncio loop with yielding)
        if args.mine and miner_address:
            miner_obj = Miner(bc, miner_address)

            # When a block arrives from the network, cancel the miner
            # so it immediately restarts on the new tip
            def on_network_block(block):
                miner_obj.cancel()
                logger.info(
                    "📡 Network block #{} → cancelling miner, will restart "
                    "on new tip".format(block.height)
                )

            node.on_block_accepted = on_network_block

            async def mine_loop():
                while True:
                    # Pull txs from mempool
                    txs = mempool.get_transactions()

                    # Mine in a thread so we don't block the event loop
                    block = await loop.run_in_executor(
                        None, lambda: miner_obj.mine_block(transactions=txs)
                    )

                    if block:
                        # Remove mined txs from mempool
                        for tx in block.transactions[1:]:
                            mempool.remove_transaction(tx.tx_hash)
                        bc.save()
                        mempool.save()

                        balance = bc.get_balance(miner_address)
                        print(
                            f"   ✅ Block #{block.height} mined | "
                            f"hash={block.block_hash[:24]}… | "
                            f"balance={balance:,} {__ticker__} | "
                            f"peers={len(node.peers)}"
                        )

                        # Broadcast to all peers
                        await node.broadcast_block(block)

                    # Small yield to let network messages process
                    await asyncio.sleep(0.1)

            asyncio.ensure_future(mine_loop())

        # Status printer
        async def status_printer():
            while True:
                await asyncio.sleep(60)
                status = node.get_status()
                logger.info(
                    "📊 height={} peers={} mempool={}".format(
                        status["chain_height"],
                        status["peers"],
                        status["mempool_size"],
                    )
                )

        asyncio.ensure_future(status_printer())

        # Run forever
        try:
            while True:
                await asyncio.sleep(1)
        except asyncio.CancelledError:
            pass

    try:
        loop.run_until_complete(run())
    except KeyboardInterrupt:
        print("\n  Shutting down…")
        loop.run_until_complete(node.stop())
        print(f"  Chain height: {bc.height}")
        print(f"  Chain saved. Goodbye! 🐕\n")


def cmd_genesis(args):
    """Show genesis block info."""
    bc = Blockchain()
    genesis = bc.chain[0]
    print(f"\n{'═' * 60}")
    print(f"  {__coin_name__} — Genesis Block")
    print(f"{'═' * 60}")
    print(f"  Hash:      {genesis.block_hash}")
    print(f"  Message:   {genesis.transactions[0].inputs[0].signature}")
    print(f"  Timestamp: {time.ctime(genesis.header.timestamp)}")
    print(f"  Reward:    {BLOCK_REWARD:,} {__ticker__}")
    print(f"{'═' * 60}\n")


def cmd_seed(args):
    """Run a seed tracker (peer discovery service for internet nodes)."""
    from kikicabowabocoin.seed_tracker import run_seed_tracker
    run_seed_tracker(host=args.host, port=args.port)


# ===========================================================================
# Argument parser
# ===========================================================================

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="kiki",
        description=f"{__coin_name__} ({__ticker__}) — A Dogecoin-inspired cryptocurrency",
    )
    parser.add_argument(
        "-v", "--verbose", action="store_true", help="Enable debug logging"
    )
    parser.add_argument(
        "--version", action="version", version=f"%(prog)s {__version__}"
    )

    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # info
    subparsers.add_parser("info", help="Show blockchain information")

    # genesis
    subparsers.add_parser("genesis", help="Show genesis block")

    # wallet
    wallet_parser = subparsers.add_parser("wallet", help="Wallet management")
    wallet_sub = wallet_parser.add_subparsers(dest="wallet_cmd")

    create_p = wallet_sub.add_parser("create", help="Create a new address")
    create_p.add_argument("--label", type=str, default="", help="Address label")

    wallet_sub.add_parser("list", help="List all addresses")

    balance_p = wallet_sub.add_parser("balance", help="Check address balance")
    balance_p.add_argument("address", type=str, help="Address to check")

    # send
    send_p = subparsers.add_parser("send", help="Send KIKI coins")
    send_p.add_argument("to_address", type=str, help="Recipient address")
    send_p.add_argument("amount", type=str, help="Amount to send")
    send_p.add_argument("--from", dest="from_address", type=str, help="Sender address")
    send_p.add_argument("--fee", type=str, default=None, help="Transaction fee")

    # mine
    mine_p = subparsers.add_parser("mine", help="Mine blocks")
    mine_p.add_argument(
        "--blocks", "-n", type=int, default=1, help="Number of blocks to mine"
    )
    mine_p.add_argument("--address", type=str, help="Mining reward address")

    # block
    block_p = subparsers.add_parser("block", help="Show block details")
    block_g = block_p.add_mutually_exclusive_group()
    block_g.add_argument("--hash", type=str, help="Block hash")
    block_g.add_argument("--height", type=int, help="Block height")

    # node
    node_p = subparsers.add_parser("node", help="Start a full node")
    node_p.add_argument(
        "--port", type=int, default=DEFAULT_PORT, help="Listening port"
    )
    node_p.add_argument("--mine", action="store_true", help="Enable mining")
    node_p.add_argument("--mine-address", type=str, help="Mining reward address")
    node_p.add_argument(
        "--peer", dest="peers", action="append", default=[],
        help="Extra peer to connect to (host:port). Optional — nodes "
             "discover each other automatically on the LAN.",
    )
    node_p.add_argument(
        "--no-discovery", action="store_true",
        help="Disable automatic LAN peer discovery (UDP broadcast)",
    )
    node_p.add_argument(
        "--no-tracker", action="store_true",
        help="Disable seed tracker registration/queries (HTTP)",
    )

    # seed (tracker)
    seed_p = subparsers.add_parser(
        "seed", help="Run a seed tracker (peer discovery service)"
    )
    seed_p.add_argument(
        "--port", type=int, default=None,
        help="HTTP port (default: $PORT or 44147)",
    )
    seed_p.add_argument(
        "--host", type=str, default="0.0.0.0",
        help="Bind address (default: 0.0.0.0)",
    )

    return parser


# ===========================================================================
# Main entry point
# ===========================================================================

def main():
    parser = build_parser()
    args = parser.parse_args()

    setup_logging(args.verbose)
    os.makedirs(DATA_DIR, exist_ok=True)

    commands = {
        "info": cmd_info,
        "genesis": cmd_genesis,
        "wallet": lambda a: {
            "create": cmd_wallet_create,
            "list": cmd_wallet_list,
            "balance": cmd_wallet_balance,
        }.get(a.wallet_cmd, lambda _: parser.parse_args(["wallet", "-h"]))(a),
        "send": cmd_send,
        "mine": cmd_mine,
        "block": cmd_block,
        "node": cmd_node,
        "seed": cmd_seed,
    }

    if args.command in commands:
        commands[args.command](args)
    else:
        print(BANNER.format(version=__version__, ticker=__ticker__))
        parser.print_help()


if __name__ == "__main__":
    main()
