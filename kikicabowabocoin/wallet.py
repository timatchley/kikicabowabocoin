"""
Wallet for KikicabowaboCoin.

Generates ECDSA key pairs (secp256k1, same curve as Bitcoin/Dogecoin),
derives addresses, signs transactions, and manages the user's keys.
"""

import json
import os
import secrets
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from kikicabowabocoin.config import ADDRESS_PREFIX, PRIVKEY_PREFIX, DATA_DIR, WALLET_FILE
from kikicabowabocoin.crypto import (
    base58check_encode,
    base58check_decode,
    double_sha256,
    hash160,
    sha256,
)
from kikicabowabocoin.transaction import Transaction, TxInput, TxOutput


# ---------------------------------------------------------------------------
# Lightweight ECDSA on secp256k1  (pure-Python for portability)
# In production you'd use `ecdsa` or `coincurve`, but we include a minimal
# implementation so the project works out of the box.
# ---------------------------------------------------------------------------

# secp256k1 curve parameters
_P = 0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFEFFFFFC2F
_N = 0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFEBAAEDCE6AF48A03BBFD25E8CD0364141
_Gx = 0x79BE667EF9DCBBAC55A06295CE870B07029BFCDB2DCE28D959F2815B16F81798
_Gy = 0x483ADA7726A3C4655DA4FBFC0E1108A8FD17B448A68554199C47D08FFB10D4B8
_A = 0
_B = 7


def _modinv(a: int, m: int) -> int:
    """Modular inverse using extended Euclidean algorithm."""
    if a < 0:
        a = a % m
    g, x, _ = _extended_gcd(a, m)
    if g != 1:
        raise ValueError("No modular inverse")
    return x % m


def _extended_gcd(a: int, b: int):
    if a == 0:
        return b, 0, 1
    g, x, y = _extended_gcd(b % a, a)
    return g, y - (b // a) * x, x


def _point_add(p1, p2):
    """Add two points on secp256k1."""
    if p1 is None:
        return p2
    if p2 is None:
        return p1

    x1, y1 = p1
    x2, y2 = p2

    if x1 == x2 and y1 != y2:
        return None  # Point at infinity

    if x1 == x2:
        # Point doubling
        lam = (3 * x1 * x1 + _A) * _modinv(2 * y1, _P) % _P
    else:
        lam = (y2 - y1) * _modinv(x2 - x1, _P) % _P

    x3 = (lam * lam - x1 - x2) % _P
    y3 = (lam * (x1 - x3) - y1) % _P
    return (x3, y3)


def _point_multiply(k: int, point=None):
    """Scalar multiplication on secp256k1."""
    if point is None:
        point = (_Gx, _Gy)
    result = None
    addend = point
    while k:
        if k & 1:
            result = _point_add(result, addend)
        addend = _point_add(addend, addend)
        k >>= 1
    return result


def _serialize_public_key(point, compressed: bool = True) -> bytes:
    """Serialize an EC point to bytes."""
    x, y = point
    if compressed:
        prefix = b"\x02" if y % 2 == 0 else b"\x03"
        return prefix + x.to_bytes(32, "big")
    else:
        return b"\x04" + x.to_bytes(32, "big") + y.to_bytes(32, "big")


def _sign(private_key: int, message_hash: bytes) -> Tuple[int, int]:
    """ECDSA sign (returns r, s)."""
    z = int.from_bytes(message_hash, "big")
    while True:
        k = secrets.randbelow(_N - 1) + 1
        point = _point_multiply(k)
        r = point[0] % _N
        if r == 0:
            continue
        s = (_modinv(k, _N) * (z + r * private_key)) % _N
        if s == 0:
            continue
        # Enforce low-S (BIP 62)
        if s > _N // 2:
            s = _N - s
        return (r, s)


def _verify(public_key_point, message_hash: bytes, r: int, s: int) -> bool:
    """ECDSA verify."""
    z = int.from_bytes(message_hash, "big")
    s_inv = _modinv(s, _N)
    u1 = (z * s_inv) % _N
    u2 = (r * s_inv) % _N
    point = _point_add(_point_multiply(u1), _point_multiply(u2, public_key_point))
    if point is None:
        return False
    return point[0] % _N == r


# ---------------------------------------------------------------------------
# Key / Address helpers
# ---------------------------------------------------------------------------

def generate_private_key() -> int:
    """Generate a cryptographically secure private key."""
    return secrets.randbelow(_N - 1) + 1


def private_key_to_public_key(private_key: int) -> bytes:
    """Derive compressed public key from private key."""
    point = _point_multiply(private_key)
    return _serialize_public_key(point, compressed=True)


def public_key_to_address(public_key: bytes) -> str:
    """
    Derive a KikicabowaboCoin address from a public key.

    Same process as Bitcoin/Dogecoin:
    1. SHA-256 → RIPEMD-160 (Hash160)
    2. Prepend version byte
    3. Base58Check encode
    """
    h = hash160(public_key)
    return base58check_encode(ADDRESS_PREFIX, h)


def private_key_to_wif(private_key: int) -> str:
    """
    Encode a private key in WIF (Wallet Import Format).

    Same as Dogecoin WIF: Base58Check( PRIVKEY_PREFIX + key + 0x01 )
    The 0x01 suffix signals the corresponding public key is compressed.
    """
    key_bytes = private_key.to_bytes(32, "big")
    return base58check_encode(PRIVKEY_PREFIX, key_bytes + b"\x01")


def wif_to_private_key(wif: str) -> int:
    """
    Decode a WIF private key back to an integer.
    Strips the compression flag byte if present.
    """
    prefix, payload = base58check_decode(wif)
    if prefix != PRIVKEY_PREFIX:
        raise ValueError("WIF prefix mismatch — wrong network?")
    # Strip compression flag (last byte 0x01) if present
    if len(payload) == 33 and payload[-1] == 0x01:
        payload = payload[:-1]
    if len(payload) != 32:
        raise ValueError("Invalid WIF key length")
    return int.from_bytes(payload, "big")


def public_key_bytes_to_point(pub_bytes: bytes):
    """Deserialize a compressed public key back to a curve point."""
    if pub_bytes[0] in (0x02, 0x03):
        x = int.from_bytes(pub_bytes[1:33], "big")
        y_sq = (pow(x, 3, _P) + _B) % _P
        y = pow(y_sq, (_P + 1) // 4, _P)
        if (y % 2) != (pub_bytes[0] - 2):
            y = _P - y
        return (x, y)
    elif pub_bytes[0] == 0x04:
        x = int.from_bytes(pub_bytes[1:33], "big")
        y = int.from_bytes(pub_bytes[33:65], "big")
        return (x, y)
    raise ValueError("Invalid public key format")


# ---------------------------------------------------------------------------
# Wallet
# ---------------------------------------------------------------------------

@dataclass
class KeyPair:
    """A single key pair with its derived address."""
    private_key: int
    public_key: bytes
    address: str
    label: str = ""
    created_at: float = field(default_factory=time.time)

    def serialize(self) -> dict:
        return {
            "private_key": hex(self.private_key),
            "public_key": self.public_key.hex(),
            "address": self.address,
            "label": self.label,
            "created_at": self.created_at,
        }

    @classmethod
    def deserialize(cls, data: dict) -> "KeyPair":
        return cls(
            private_key=int(data["private_key"], 16),
            public_key=bytes.fromhex(data["public_key"]),
            address=data["address"],
            label=data.get("label", ""),
            created_at=data.get("created_at", 0),
        )


class Wallet:
    """
    KikicabowaboCoin wallet.

    Manages multiple key pairs, creates and signs transactions.
    """

    def __init__(self, filepath: Optional[str] = None):
        self.filepath = filepath or WALLET_FILE
        self.keys: List[KeyPair] = []
        self._address_index: Dict[str, KeyPair] = {}

    # --- Key management ------------------------------------------------------

    def generate_address(self, label: str = "") -> str:
        """Generate a new key pair and return the address."""
        priv = generate_private_key()
        pub = private_key_to_public_key(priv)
        addr = public_key_to_address(pub)
        kp = KeyPair(
            private_key=priv,
            public_key=pub,
            address=addr,
            label=label or f"address-{len(self.keys)}",
        )
        self.keys.append(kp)
        self._address_index[addr] = kp
        return addr

    def get_all_addresses(self) -> List[str]:
        return [kp.address for kp in self.keys]

    def get_keypair(self, address: str) -> Optional[KeyPair]:
        return self._address_index.get(address)

    @property
    def default_address(self) -> str:
        """Return the first address, creating one if needed."""
        if not self.keys:
            self.generate_address(label="default")
        return self.keys[0].address

    # --- Transaction creation ------------------------------------------------

    def create_transaction(
        self,
        from_address: str,
        to_address: str,
        amount: int,
        fee: int,
        utxos: List[dict],
    ) -> Optional[Transaction]:
        """
        Build and sign a transaction sending `amount` KIKI from
        `from_address` to `to_address`.

        `utxos` should be the list from Blockchain.get_utxos_for_address().
        """
        kp = self.get_keypair(from_address)
        if not kp:
            raise ValueError(f"No private key for address {from_address}")

        # Select UTXOs (simple: use all until we have enough)
        selected = []
        input_total = 0
        needed = amount + fee

        for utxo in utxos:
            selected.append(utxo)
            input_total += utxo["amount"]
            if input_total >= needed:
                break

        if input_total < needed:
            raise ValueError(
                f"Insufficient funds: have {input_total}, need {needed}"
            )

        # Build inputs
        inputs = [
            TxInput(
                prev_tx_hash=u["tx_hash"],
                output_index=u["output_index"],
            )
            for u in selected
        ]

        # Build outputs
        outputs = [TxOutput(amount=amount, address=to_address)]
        change = input_total - needed
        if change > 0:
            outputs.append(TxOutput(amount=change, address=from_address))

        tx = Transaction(inputs=inputs, outputs=outputs)

        # Sign each input
        msg_hash = tx.hash_for_signing()
        r, s = _sign(kp.private_key, msg_hash)
        sig_hex = f"{r:064x}{s:064x}"

        for inp in tx.inputs:
            inp.signature = sig_hex
            inp.public_key = kp.public_key.hex()

        tx.tx_hash = tx.compute_hash()
        return tx

    # --- Signature verification (static) ------------------------------------

    @staticmethod
    def verify_transaction_signatures(tx: Transaction) -> bool:
        """Verify all input signatures on a transaction."""
        if tx.is_coinbase():
            return True

        msg_hash = tx.hash_for_signing()

        for inp in tx.inputs:
            if not inp.signature or not inp.public_key:
                return False

            pub_bytes = bytes.fromhex(inp.public_key)
            pub_point = public_key_bytes_to_point(pub_bytes)

            sig = inp.signature
            r = int(sig[:64], 16)
            s = int(sig[64:], 16)

            if not _verify(pub_point, msg_hash, r, s):
                return False

        return True

    # --- Persistence ---------------------------------------------------------

    def save(self):
        """Save wallet keys to disk (encrypted in production!)."""
        os.makedirs(os.path.dirname(self.filepath), exist_ok=True)
        data = {
            "version": 1,
            "keys": [kp.serialize() for kp in self.keys],
        }
        with open(self.filepath, "w") as f:
            json.dump(data, f, indent=2)

    def load(self):
        """Load wallet keys from disk."""
        if not os.path.exists(self.filepath):
            return
        with open(self.filepath, "r") as f:
            data = json.load(f)
        self.keys = [KeyPair.deserialize(k) for k in data.get("keys", [])]
        self._address_index = {kp.address: kp for kp in self.keys}

    def __repr__(self) -> str:
        return f"<Wallet addresses={len(self.keys)}>"
