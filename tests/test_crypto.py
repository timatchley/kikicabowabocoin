"""Tests for cryptographic utilities."""

import pytest
from kikicabowabocoin.crypto import (
    sha256,
    double_sha256,
    hash160,
    scrypt_hash,
    merkle_root,
    bits_to_target,
    target_to_bits,
    target_to_difficulty,
    base58_encode,
    base58_decode,
    base58check_encode,
    base58check_decode,
)


class TestHashing:
    def test_sha256_deterministic(self):
        h1 = sha256(b"kikicabowabocoin")
        h2 = sha256(b"kikicabowabocoin")
        assert h1 == h2
        assert len(h1) == 32

    def test_sha256_different_inputs(self):
        assert sha256(b"hello") != sha256(b"world")

    def test_double_sha256(self):
        h = double_sha256(b"test")
        assert len(h) == 32
        # double sha256 ≠ single sha256
        assert h != sha256(b"test")

    def test_hash160(self):
        h = hash160(b"public_key_data")
        assert len(h) == 20  # RIPEMD-160 output

    def test_scrypt_hash(self):
        h = scrypt_hash(b"block_header_data")
        assert len(h) == 32
        # Deterministic
        assert h == scrypt_hash(b"block_header_data")

    def test_scrypt_different_inputs(self):
        h1 = scrypt_hash(b"block1")
        h2 = scrypt_hash(b"block2")
        assert h1 != h2


class TestMerkleRoot:
    def test_single_hash(self):
        h = b"\x01" * 32
        root = merkle_root([h])
        assert root == h

    def test_two_hashes(self):
        h1 = sha256(b"tx1")
        h2 = sha256(b"tx2")
        root = merkle_root([h1, h2])
        assert len(root) == 32
        assert root != h1
        assert root != h2

    def test_odd_number_duplicates_last(self):
        h1 = sha256(b"tx1")
        h2 = sha256(b"tx2")
        h3 = sha256(b"tx3")
        root = merkle_root([h1, h2, h3])
        assert len(root) == 32

    def test_empty_returns_zeros(self):
        root = merkle_root([])
        assert root == b"\x00" * 32

    def test_deterministic(self):
        hashes = [sha256(f"tx{i}".encode()) for i in range(5)]
        assert merkle_root(hashes) == merkle_root(hashes)


class TestDifficulty:
    def test_bits_to_target_roundtrip(self):
        bits = 0x1e0fffff
        target = bits_to_target(bits)
        assert target > 0
        # Round-trip (may not be exact due to compact encoding)
        recovered = target_to_bits(target)
        assert bits_to_target(recovered) == target

    def test_higher_bits_means_easier(self):
        easy = bits_to_target(0x1e0fffff)
        hard = bits_to_target(0x1d0fffff)
        assert easy > hard

    def test_difficulty_inverse_of_target(self):
        easy_target = bits_to_target(0x1e0fffff)
        hard_target = bits_to_target(0x1d0fffff)
        assert target_to_difficulty(hard_target) > target_to_difficulty(easy_target)


class TestBase58:
    def test_encode_decode_roundtrip(self):
        data = b"\x00" + b"\x01\x02\x03" + b"\x00" * 17 + b"\xab\xcd"
        encoded = base58_encode(data)
        # base58_decode returns 25 bytes
        decoded = base58_decode(encoded)
        # The significant bytes should match
        assert decoded[-len(data):] == data or data in decoded

    def test_base58check_roundtrip(self):
        prefix = b"\x1e"
        payload = b"\xab\xcd\xef" + b"\x00" * 17
        encoded = base58check_encode(prefix, payload)
        dec_prefix, dec_payload = base58check_decode(encoded)
        assert dec_prefix == prefix
        assert dec_payload == payload

    def test_base58check_invalid_checksum(self):
        prefix = b"\x1e"
        payload = b"\xab\xcd\xef" + b"\x00" * 17
        encoded = base58check_encode(prefix, payload)
        # Corrupt the last character
        corrupted = encoded[:-1] + ("1" if encoded[-1] != "1" else "2")
        with pytest.raises(ValueError, match="checksum"):
            base58check_decode(corrupted)
