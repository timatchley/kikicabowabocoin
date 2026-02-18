"""Shared test fixtures for KikicabowaboCoin tests.

Patches Scrypt PoW with fast double-SHA256 so mining tests complete instantly.
"""

import pytest
from unittest.mock import patch
from kikicabowabocoin.crypto import double_sha256


def _fast_hash(data: bytes) -> bytes:
    """Drop-in replacement for scrypt_hash using fast double-SHA256."""
    return double_sha256(data)


@pytest.fixture(autouse=True)
def fast_mining():
    """Automatically replace slow Scrypt with fast SHA256 in all tests.

    scrypt_hash is imported by name into multiple modules, so we must
    patch every cached reference.
    """
    with patch("kikicabowabocoin.crypto.scrypt_hash", side_effect=_fast_hash), \
         patch("kikicabowabocoin.blockchain.scrypt_hash", side_effect=_fast_hash), \
         patch("kikicabowabocoin.miner.scrypt_hash", side_effect=_fast_hash):
        yield
