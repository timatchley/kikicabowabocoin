"""
Cryptographic utility functions for KikicabowaboCoin.

Uses Scrypt for Proof-of-Work (matching Dogecoin/Litecoin) and standard
SHA-256 / RIPEMD-160 for addresses and Merkle trees.
"""

import hashlib
import struct
from typing import List, Optional

from kikicabowabocoin.config import SCRYPT_N, SCRYPT_R, SCRYPT_P, SCRYPT_KEY_LEN


# ---------------------------------------------------------------------------
# Hashing helpers
# ---------------------------------------------------------------------------

def sha256(data: bytes) -> bytes:
    """Single SHA-256 hash."""
    return hashlib.sha256(data).digest()


def double_sha256(data: bytes) -> bytes:
    """Double SHA-256 (used for tx hashing, Merkle tree, etc.)."""
    return sha256(sha256(data))


def hash160(data: bytes) -> bytes:
    """SHA-256 then RIPEMD-160 (used for address generation)."""
    sha = hashlib.sha256(data).digest()
    ripemd = hashlib.new("ripemd160", sha).digest()
    return ripemd


def scrypt_hash(data: bytes) -> bytes:
    """
    Scrypt hash used for Proof-of-Work.

    Dogecoin (and Litecoin) use Scrypt with N=1024, r=1, p=1 to make mining
    more memory-hard than pure SHA-256.
    """
    return hashlib.scrypt(
        password=data,
        salt=data,
        n=SCRYPT_N,
        r=SCRYPT_R,
        p=SCRYPT_P,
        dklen=SCRYPT_KEY_LEN,
    )


# ---------------------------------------------------------------------------
# Merkle tree
# ---------------------------------------------------------------------------

def merkle_root(hashes: List[bytes]) -> bytes:
    """
    Compute the Merkle root of a list of transaction hashes.

    If the number of hashes is odd, the last hash is duplicated (Bitcoin /
    Dogecoin behaviour).
    """
    if not hashes:
        return b"\x00" * 32

    level = list(hashes)

    while len(level) > 1:
        if len(level) % 2 == 1:
            level.append(level[-1])  # duplicate last

        next_level = []
        for i in range(0, len(level), 2):
            combined = level[i] + level[i + 1]
            next_level.append(double_sha256(combined))
        level = next_level

    return level[0]


# ---------------------------------------------------------------------------
# Compact target ↔ difficulty helpers (nBits encoding like Bitcoin/Dogecoin)
# ---------------------------------------------------------------------------

def bits_to_target(bits: int) -> int:
    """Convert compact nBits representation to a full 256-bit target."""
    exponent = bits >> 24
    mantissa = bits & 0x007FFFFF
    if exponent <= 3:
        mantissa >>= 8 * (3 - exponent)
        target = mantissa
    else:
        target = mantissa << (8 * (exponent - 3))
    return target


def target_to_bits(target: int) -> int:
    """Convert a 256-bit target back to compact nBits form."""
    raw = target.to_bytes(32, "big").lstrip(b"\x00")
    if len(raw) == 0:
        return 0

    # Ensure positive
    if raw[0] & 0x80:
        raw = b"\x00" + raw

    size = len(raw)
    if size >= 3:
        compact = int.from_bytes(raw[:3], "big")
    else:
        compact = int.from_bytes(raw.ljust(3, b"\x00"), "big")

    bits = (size << 24) | compact
    return bits


def target_to_difficulty(target: int) -> float:
    """Calculate human-readable difficulty from target."""
    if target == 0:
        return float("inf")
    max_target = bits_to_target(0x1e0fffff)
    return max_target / target


# ---------------------------------------------------------------------------
# Base58Check encoding (for addresses, same as Bitcoin/Dogecoin)
# ---------------------------------------------------------------------------

_B58_ALPHABET = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"


def base58_encode(data: bytes) -> str:
    """Encode bytes to Base58."""
    num = int.from_bytes(data, "big")
    encoded = ""
    while num > 0:
        num, remainder = divmod(num, 58)
        encoded = _B58_ALPHABET[remainder] + encoded

    # Preserve leading zero bytes
    for byte in data:
        if byte == 0:
            encoded = "1" + encoded
        else:
            break

    return encoded


def base58_decode(s: str) -> bytes:
    """Decode Base58 string to bytes."""
    num = 0
    for char in s:
        num = num * 58 + _B58_ALPHABET.index(char)

    combined = num.to_bytes(25, "big")
    return combined


def base58check_encode(prefix: bytes, payload: bytes) -> str:
    """Base58Check encoding (prefix + payload + 4-byte checksum)."""
    raw = prefix + payload
    checksum = double_sha256(raw)[:4]
    return base58_encode(raw + checksum)


def base58check_decode(address: str) -> tuple:
    """Decode a Base58Check address into (prefix_byte, payload)."""
    raw = base58_decode(address)
    checksum = raw[-4:]
    data = raw[:-4]
    if double_sha256(data)[:4] != checksum:
        raise ValueError("Invalid Base58Check checksum")
    return data[:1], data[1:]
