"""Tests for config.crypto — cryptographic primitive utilities."""

import pytest

from config.crypto import (
    EncryptedMessage,
    KyberKeyPair,
    X25519KeyPair,
    aes256_decrypt,
    aes256_encrypt,
    generate_hybrid_keypair,
    generate_kyber_keypair,
    generate_x25519_keypair,
    hmac_sha256,
    hmac_sha512,
    hmac_verify,
    hybrid_decrypt,
    hybrid_encrypt,
    kyber_decapsulate,
    kyber_encapsulate,
    x25519_shared_secret,
)

# ── X25519 ────────────────────────────────────────────────────────────────────


class TestX25519:
    def test_generate_keypair_returns_correct_type(self):
        kp = generate_x25519_keypair()
        assert isinstance(kp, X25519KeyPair)

    def test_public_key_is_32_bytes(self):
        kp = generate_x25519_keypair()
        assert len(kp.public_bytes()) == 32

    def test_private_key_is_32_bytes(self):
        kp = generate_x25519_keypair()
        assert len(kp.private_bytes()) == 32

    def test_keypairs_are_distinct(self):
        a = generate_x25519_keypair()
        b = generate_x25519_keypair()
        assert a.public_bytes() != b.public_bytes()

    def test_dh_shared_secret_is_symmetric(self):
        alice = generate_x25519_keypair()
        bob = generate_x25519_keypair()
        alice_secret = x25519_shared_secret(alice.private_key, bob.public_key)
        bob_secret = x25519_shared_secret(bob.private_key, alice.public_key)
        assert alice_secret == bob_secret

    def test_dh_shared_secret_is_32_bytes(self):
        alice = generate_x25519_keypair()
        bob = generate_x25519_keypair()
        secret = x25519_shared_secret(alice.private_key, bob.public_key)
        assert len(secret) == 32

    def test_different_peers_give_different_secrets(self):
        alice = generate_x25519_keypair()
        bob = generate_x25519_keypair()
        charlie = generate_x25519_keypair()
        secret_ab = x25519_shared_secret(alice.private_key, bob.public_key)
        secret_ac = x25519_shared_secret(alice.private_key, charlie.public_key)
        assert secret_ab != secret_ac


# ── Kyber-1024 ────────────────────────────────────────────────────────────────


class TestKyber1024:
    def test_generate_keypair_returns_correct_type(self):
        kp = generate_kyber_keypair()
        assert isinstance(kp, KyberKeyPair)

    def test_public_key_length(self):
        kp = generate_kyber_keypair()
        assert len(kp.public_key) == 1568

    def test_secret_key_length(self):
        kp = generate_kyber_keypair()
        assert len(kp.secret_key) == 3168

    def test_keypairs_are_distinct(self):
        a = generate_kyber_keypair()
        b = generate_kyber_keypair()
        assert a.public_key != b.public_key

    def test_encapsulate_returns_secret_and_ciphertext(self):
        kp = generate_kyber_keypair()
        shared_secret, ciphertext = kyber_encapsulate(kp.public_key)
        assert len(shared_secret) == 32
        assert len(ciphertext) == 1568

    def test_decapsulate_recovers_shared_secret(self):
        kp = generate_kyber_keypair()
        shared_secret, ciphertext = kyber_encapsulate(kp.public_key)
        recovered = kyber_decapsulate(kp.secret_key, ciphertext)
        assert recovered == shared_secret

    def test_wrong_secret_key_gives_different_secret(self):
        kp1 = generate_kyber_keypair()
        kp2 = generate_kyber_keypair()
        shared_secret, ciphertext = kyber_encapsulate(kp1.public_key)
        wrong = kyber_decapsulate(kp2.secret_key, ciphertext)
        assert wrong != shared_secret


# ── AES-256-GCM ───────────────────────────────────────────────────────────────


class TestAes256Gcm:
    def _key(self) -> bytes:
        import os

        return os.urandom(32)

    def test_encrypt_returns_ciphertext_and_nonce(self):
        key = self._key()
        ct, nonce = aes256_encrypt(key, b"hello")
        assert isinstance(ct, bytes)
        assert len(nonce) == 12

    def test_ciphertext_differs_from_plaintext(self):
        key = self._key()
        plaintext = b"secret message"
        ct, _ = aes256_encrypt(key, plaintext)
        assert ct != plaintext

    def test_roundtrip(self):
        key = self._key()
        plaintext = b"dance event data"
        ct, nonce = aes256_encrypt(key, plaintext)
        assert aes256_decrypt(key, ct, nonce) == plaintext

    def test_roundtrip_with_aad(self):
        key = self._key()
        plaintext = b"protected payload"
        aad = b"authenticated context"
        ct, nonce = aes256_encrypt(key, plaintext, aad=aad)
        assert aes256_decrypt(key, ct, nonce, aad=aad) == plaintext

    def test_wrong_key_raises(self):
        key = self._key()
        plaintext = b"secret"
        ct, nonce = aes256_encrypt(key, plaintext)
        with pytest.raises(ValueError, match="authentication tag mismatch"):
            aes256_decrypt(self._key(), ct, nonce)

    def test_tampered_ciphertext_raises(self):
        key = self._key()
        ct, nonce = aes256_encrypt(key, b"secret")
        tampered = bytes([ct[0] ^ 0xFF]) + ct[1:]
        with pytest.raises(ValueError):
            aes256_decrypt(key, tampered, nonce)

    def test_wrong_aad_raises(self):
        key = self._key()
        ct, nonce = aes256_encrypt(key, b"secret", aad=b"good")
        with pytest.raises(ValueError):
            aes256_decrypt(key, ct, nonce, aad=b"bad")

    def test_invalid_key_length_raises_on_encrypt(self):
        with pytest.raises(ValueError, match="32 bytes"):
            aes256_encrypt(b"short", b"data")

    def test_invalid_key_length_raises_on_decrypt(self):
        key = self._key()
        ct, nonce = aes256_encrypt(key, b"data")
        with pytest.raises(ValueError, match="32 bytes"):
            aes256_decrypt(b"short", ct, nonce)

    def test_each_encryption_uses_different_nonce(self):
        key = self._key()
        _, nonce1 = aes256_encrypt(key, b"same")
        _, nonce2 = aes256_encrypt(key, b"same")
        assert nonce1 != nonce2


# ── HMAC-SHA256 / HMAC-SHA512 ─────────────────────────────────────────────────


class TestHmac:
    def test_sha256_output_length(self):
        assert len(hmac_sha256(b"key", b"msg")) == 32

    def test_sha512_output_length(self):
        assert len(hmac_sha512(b"key", b"msg")) == 64

    def test_sha256_is_deterministic(self):
        assert hmac_sha256(b"key", b"msg") == hmac_sha256(b"key", b"msg")

    def test_sha512_is_deterministic(self):
        assert hmac_sha512(b"key", b"msg") == hmac_sha512(b"key", b"msg")

    def test_sha256_different_keys(self):
        assert hmac_sha256(b"key1", b"msg") != hmac_sha256(b"key2", b"msg")

    def test_sha512_different_messages(self):
        assert hmac_sha512(b"key", b"msg1") != hmac_sha512(b"key", b"msg2")

    def test_sha256_differs_from_sha512(self):
        tag256 = hmac_sha256(b"key", b"msg")
        tag512 = hmac_sha512(b"key", b"msg")
        assert tag256 != tag512[:32]

    def test_verify_sha256_valid(self):
        key, msg = b"secret", b"hello"
        tag = hmac_sha256(key, msg)
        assert hmac_verify(key, msg, tag) is True

    def test_verify_sha512_valid(self):
        key, msg = b"secret", b"hello"
        tag = hmac_sha512(key, msg)
        assert hmac_verify(key, msg, tag, use_sha512=True) is True

    def test_verify_rejects_wrong_tag(self):
        key, msg = b"secret", b"hello"
        bad_tag = bytes(32)
        assert hmac_verify(key, msg, bad_tag) is False

    def test_verify_rejects_tampered_message(self):
        key = b"secret"
        tag = hmac_sha256(key, b"original")
        assert hmac_verify(key, b"tampered", tag) is False


# ── Hybrid encryption (X25519 + Kyber-1024 + AES-256-GCM) ────────────────────


class TestHybridEncryption:
    def test_generate_hybrid_keypair(self):
        kp = generate_hybrid_keypair()
        assert isinstance(kp.x25519, X25519KeyPair)
        assert isinstance(kp.kyber, KyberKeyPair)

    def test_hybrid_encrypt_returns_encrypted_message(self):
        kp = generate_hybrid_keypair()
        msg = hybrid_encrypt(kp, b"hello dance world")
        assert isinstance(msg, EncryptedMessage)
        assert len(msg.nonce) == 12
        assert len(msg.x25519_public) == 32
        assert len(msg.kyber_ciphertext) == 1568

    def test_hybrid_roundtrip(self):
        kp = generate_hybrid_keypair()
        plaintext = b"Copenhagen dance event"
        encrypted = hybrid_encrypt(kp, plaintext)
        assert hybrid_decrypt(kp, encrypted) == plaintext

    def test_hybrid_roundtrip_empty_plaintext(self):
        kp = generate_hybrid_keypair()
        encrypted = hybrid_encrypt(kp, b"")
        assert hybrid_decrypt(kp, encrypted) == b""

    def test_hybrid_roundtrip_large_payload(self):
        kp = generate_hybrid_keypair()
        plaintext = b"x" * 100_000
        encrypted = hybrid_encrypt(kp, plaintext)
        assert hybrid_decrypt(kp, encrypted) == plaintext

    def test_each_encryption_produces_different_ciphertext(self):
        kp = generate_hybrid_keypair()
        plaintext = b"same message"
        enc1 = hybrid_encrypt(kp, plaintext)
        enc2 = hybrid_encrypt(kp, plaintext)
        assert enc1.ciphertext != enc2.ciphertext
        assert enc1.x25519_public != enc2.x25519_public

    def test_wrong_keypair_raises(self):
        kp1 = generate_hybrid_keypair()
        kp2 = generate_hybrid_keypair()
        encrypted = hybrid_encrypt(kp1, b"secret")
        with pytest.raises(ValueError):
            hybrid_decrypt(kp2, encrypted)

    def test_tampered_ciphertext_raises(self):
        kp = generate_hybrid_keypair()
        encrypted = hybrid_encrypt(kp, b"secret")
        tampered = EncryptedMessage(
            ciphertext=bytes([encrypted.ciphertext[0] ^ 0xFF])
            + encrypted.ciphertext[1:],
            nonce=encrypted.nonce,
            x25519_public=encrypted.x25519_public,
            kyber_ciphertext=encrypted.kyber_ciphertext,
        )
        with pytest.raises(ValueError):
            hybrid_decrypt(kp, tampered)
