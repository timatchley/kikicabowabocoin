"""Tests for wallet."""

import pytest
from kikicabowabocoin.wallet import (
    Wallet,
    generate_private_key,
    private_key_to_public_key,
    public_key_to_address,
    public_key_bytes_to_point,
    _sign,
    _verify,
    _point_multiply,
    _N,
)
from kikicabowabocoin.crypto import double_sha256


class TestKeyGeneration:
    def test_private_key_range(self):
        pk = generate_private_key()
        assert 1 <= pk < _N

    def test_private_keys_unique(self):
        keys = {generate_private_key() for _ in range(10)}
        assert len(keys) == 10

    def test_public_key_from_private(self):
        pk = generate_private_key()
        pub = private_key_to_public_key(pk)
        assert len(pub) == 33  # Compressed public key
        assert pub[0] in (0x02, 0x03)

    def test_address_from_public_key(self):
        pk = generate_private_key()
        pub = private_key_to_public_key(pk)
        addr = public_key_to_address(pub)
        assert isinstance(addr, str)
        assert len(addr) > 20

    def test_different_keys_different_addresses(self):
        pk1 = generate_private_key()
        pk2 = generate_private_key()
        pub1 = private_key_to_public_key(pk1)
        pub2 = private_key_to_public_key(pk2)
        addr1 = public_key_to_address(pub1)
        addr2 = public_key_to_address(pub2)
        assert addr1 != addr2


class TestECDSA:
    def test_sign_and_verify(self):
        pk = generate_private_key()
        pub_point = _point_multiply(pk)
        msg = double_sha256(b"test message")

        r, s = _sign(pk, msg)
        assert _verify(pub_point, msg, r, s)

    def test_verify_wrong_message(self):
        pk = generate_private_key()
        pub_point = _point_multiply(pk)
        msg1 = double_sha256(b"message 1")
        msg2 = double_sha256(b"message 2")

        r, s = _sign(pk, msg1)
        assert not _verify(pub_point, msg2, r, s)

    def test_verify_wrong_key(self):
        pk1 = generate_private_key()
        pk2 = generate_private_key()
        pub2_point = _point_multiply(pk2)
        msg = double_sha256(b"test")

        r, s = _sign(pk1, msg)
        assert not _verify(pub2_point, msg, r, s)

    def test_public_key_serialization_roundtrip(self):
        pk = generate_private_key()
        pub_bytes = private_key_to_public_key(pk)
        point = public_key_bytes_to_point(pub_bytes)
        expected = _point_multiply(pk)
        assert point == expected


class TestWallet:
    def test_create_wallet(self):
        wallet = Wallet(filepath="/tmp/test_kiki_wallet.json")
        assert len(wallet.keys) == 0

    def test_generate_address(self):
        wallet = Wallet(filepath="/tmp/test_kiki_wallet.json")
        addr = wallet.generate_address(label="test")
        assert addr is not None
        assert len(wallet.keys) == 1
        assert wallet.keys[0].label == "test"

    def test_default_address(self):
        wallet = Wallet(filepath="/tmp/test_kiki_wallet.json")
        addr = wallet.default_address
        assert addr is not None
        # Should have auto-created one
        assert len(wallet.keys) == 1

    def test_get_keypair(self):
        wallet = Wallet(filepath="/tmp/test_kiki_wallet.json")
        addr = wallet.generate_address()
        kp = wallet.get_keypair(addr)
        assert kp is not None
        assert kp.address == addr

    def test_get_all_addresses(self):
        wallet = Wallet(filepath="/tmp/test_kiki_wallet.json")
        wallet.generate_address()
        wallet.generate_address()
        addrs = wallet.get_all_addresses()
        assert len(addrs) == 2

    def test_save_and_load(self, tmp_path):
        filepath = str(tmp_path / "wallet.json")
        wallet = Wallet(filepath=filepath)
        addr = wallet.generate_address(label="persist-test")
        wallet.save()

        wallet2 = Wallet(filepath=filepath)
        wallet2.load()
        assert len(wallet2.keys) == 1
        assert wallet2.keys[0].address == addr
        assert wallet2.keys[0].label == "persist-test"

    def test_verify_transaction_signature(self):
        from kikicabowabocoin.transaction import TxInput, TxOutput, Transaction

        wallet = Wallet(filepath="/tmp/test_kiki_wallet.json")
        addr = wallet.generate_address()

        # Create a mock UTXO
        utxos = [{"tx_hash": "a" * 64, "output_index": 0, "amount": 10000}]

        tx = wallet.create_transaction(
            from_address=addr,
            to_address="RecipientAddr123",
            amount=5000,
            fee=1,
            utxos=utxos,
        )

        assert tx is not None
        assert Wallet.verify_transaction_signatures(tx)
