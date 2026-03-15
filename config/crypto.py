"""Cryptographic primitives for the Pleskal application.

Provides industry-standard algorithms:

- Curve25519 (X25519): Classical elliptic-curve Diffie-Hellman key exchange
- Kyber-1024: Post-quantum key encapsulation (NIST ML-KEM-1024 / FIPS 203)
- AES-256-GCM: Authenticated symmetric encryption
- HMAC-SHA256/512: Message authentication codes

The hybrid encryption scheme combines X25519 + Kyber-1024 for both classical
and post-quantum security, following NIST recommendations for hybrid PQC
(post-quantum cryptography) deployments.
"""

import os
from dataclasses import dataclass

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives import hmac as _hmac
from cryptography.hazmat.primitives.asymmetric.x25519 import (
    X25519PrivateKey,
    X25519PublicKey,
)
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from cryptography.hazmat.primitives.serialization import (
    Encoding,
    NoEncryption,
    PrivateFormat,
    PublicFormat,
)
from kyber_py.kyber import Kyber1024

# ── Key-pair dataclasses ───────────────────────────────────────────────────────


@dataclass
class X25519KeyPair:
    """An X25519 (Curve25519) private/public key pair."""

    private_key: X25519PrivateKey
    public_key: X25519PublicKey

    def private_bytes(self) -> bytes:
        """Serialise the private key as raw 32 bytes."""
        return self.private_key.private_bytes(
            Encoding.Raw, PrivateFormat.Raw, NoEncryption()
        )

    def public_bytes(self) -> bytes:
        """Serialise the public key as raw 32 bytes."""
        return self.public_key.public_bytes(Encoding.Raw, PublicFormat.Raw)


@dataclass
class KyberKeyPair:
    """A Kyber-1024 (ML-KEM-1024) public/secret key pair."""

    public_key: bytes  # 1568 bytes
    secret_key: bytes  # 3168 bytes


@dataclass
class HybridKeyPair:
    """Combined X25519 + Kyber-1024 key pair used for hybrid encryption."""

    x25519: X25519KeyPair
    kyber: KyberKeyPair


@dataclass
class EncryptedMessage:
    """All data required to decrypt a message produced by :func:`hybrid_encrypt`."""

    ciphertext: bytes  # AES-256-GCM encrypted payload (includes 16-byte auth tag)
    nonce: bytes  # AES-256-GCM nonce (12 bytes)
    x25519_public: bytes  # Ephemeral X25519 public key (32 bytes)
    kyber_ciphertext: bytes  # Kyber-1024 encapsulated key (1568 bytes)


# ── X25519 (Curve25519) ────────────────────────────────────────────────────────


def generate_x25519_keypair() -> X25519KeyPair:
    """Generate a fresh X25519 (Curve25519) key pair."""
    private = X25519PrivateKey.generate()
    return X25519KeyPair(private_key=private, public_key=private.public_key())


def x25519_shared_secret(
    private_key: X25519PrivateKey, peer_public_key: X25519PublicKey
) -> bytes:
    """Perform X25519 Diffie-Hellman key exchange.

    Returns a 32-byte shared secret.  Both parties must derive a key from this
    value (e.g. via HKDF) before using it for encryption.
    """
    return private_key.exchange(peer_public_key)


# ── Kyber-1024 (ML-KEM-1024) ──────────────────────────────────────────────────


def generate_kyber_keypair() -> KyberKeyPair:
    """Generate a Kyber-1024 key pair.

    Public key is 1568 bytes; secret key is 3168 bytes.
    """
    pk, sk = Kyber1024.keygen()
    return KyberKeyPair(public_key=pk, secret_key=sk)


def kyber_encapsulate(public_key: bytes) -> tuple[bytes, bytes]:
    """Encapsulate a shared secret using Kyber-1024.

    Returns ``(shared_secret, ciphertext)``.  The caller sends *ciphertext* to
    the key holder, who calls :func:`kyber_decapsulate` to recover the same
    *shared_secret*.
    """
    shared_secret, ciphertext = Kyber1024.encaps(public_key)
    return shared_secret, ciphertext


def kyber_decapsulate(secret_key: bytes, ciphertext: bytes) -> bytes:
    """Decapsulate a Kyber-1024 ciphertext, recovering the shared secret."""
    return Kyber1024.decaps(secret_key, ciphertext)


# ── AES-256-GCM ───────────────────────────────────────────────────────────────

_AES_KEY_BYTES = 32
_AES_NONCE_BYTES = 12


def aes256_encrypt(
    key: bytes,
    plaintext: bytes,
    aad: bytes | None = None,
) -> tuple[bytes, bytes]:
    """Encrypt *plaintext* with AES-256-GCM.

    Returns ``(ciphertext, nonce)``.  The ciphertext already includes the
    16-byte authentication tag appended by GCM.  *aad* is optional additional
    authenticated data that is covered by the tag but not encrypted.

    Raises :class:`ValueError` if *key* is not exactly 32 bytes.
    """
    if len(key) != _AES_KEY_BYTES:
        raise ValueError(f"AES-256 key must be exactly {_AES_KEY_BYTES} bytes")
    nonce = os.urandom(_AES_NONCE_BYTES)
    ciphertext = AESGCM(key).encrypt(nonce, plaintext, aad)
    return ciphertext, nonce


def aes256_decrypt(
    key: bytes,
    ciphertext: bytes,
    nonce: bytes,
    aad: bytes | None = None,
) -> bytes:
    """Decrypt an AES-256-GCM *ciphertext*.

    Raises :class:`ValueError` on key mismatch or authentication-tag failure.
    """
    if len(key) != _AES_KEY_BYTES:
        raise ValueError(f"AES-256 key must be exactly {_AES_KEY_BYTES} bytes")
    try:
        return AESGCM(key).decrypt(nonce, ciphertext, aad)
    except Exception as exc:
        raise ValueError("Decryption failed: authentication tag mismatch") from exc


# ── HMAC-SHA256 / HMAC-SHA512 ─────────────────────────────────────────────────


def hmac_sha256(key: bytes, message: bytes) -> bytes:
    """Compute HMAC-SHA256 of *message* under *key*. Returns 32 bytes."""
    h = _hmac.HMAC(key, hashes.SHA256())
    h.update(message)
    return h.finalize()


def hmac_sha512(key: bytes, message: bytes) -> bytes:
    """Compute HMAC-SHA512 of *message* under *key*. Returns 64 bytes."""
    h = _hmac.HMAC(key, hashes.SHA512())
    h.update(message)
    return h.finalize()


def hmac_verify(
    key: bytes, message: bytes, tag: bytes, *, use_sha512: bool = False
) -> bool:
    """Constant-time HMAC verification.

    Returns ``True`` if *tag* matches the HMAC of *message* under *key*,
    ``False`` otherwise.  Uses SHA-512 when *use_sha512* is ``True``.
    """
    h = _hmac.HMAC(key, hashes.SHA512() if use_sha512 else hashes.SHA256())
    h.update(message)
    try:
        h.verify(tag)
        return True
    except InvalidSignature:
        return False


# ── Hybrid encryption (X25519 + Kyber-1024 + AES-256-GCM) ────────────────────

_HKDF_INFO = b"pleskal-hybrid-v1"
_HKDF_KEY_BYTES = 32


def _derive_aes_key(x25519_secret: bytes, kyber_secret: bytes) -> bytes:
    """Combine X25519 and Kyber-1024 secrets into a single AES-256 key via HKDF-SHA256."""
    hkdf = HKDF(
        algorithm=hashes.SHA256(),
        length=_HKDF_KEY_BYTES,
        salt=None,
        info=_HKDF_INFO,
    )
    return hkdf.derive(x25519_secret + kyber_secret)


def generate_hybrid_keypair() -> HybridKeyPair:
    """Generate a combined X25519 + Kyber-1024 key pair for hybrid encryption."""
    return HybridKeyPair(
        x25519=generate_x25519_keypair(),
        kyber=generate_kyber_keypair(),
    )


def hybrid_encrypt(recipient: HybridKeyPair, plaintext: bytes) -> EncryptedMessage:
    """Encrypt *plaintext* for *recipient* using hybrid post-quantum encryption.

    Key exchange protocol:
    1. Generate an ephemeral X25519 key pair.
    2. Perform X25519 DH between the ephemeral private key and the recipient's
       X25519 public key to obtain a classical shared secret.
    3. Encapsulate a Kyber-1024 shared secret using the recipient's Kyber
       public key to obtain a post-quantum shared secret.
    4. Derive a 256-bit AES key from both secrets via HKDF-SHA256.
    5. Encrypt *plaintext* with AES-256-GCM.

    The returned :class:`EncryptedMessage` bundles the ephemeral public key,
    the Kyber ciphertext, and the AES ciphertext + nonce so the recipient can
    call :func:`hybrid_decrypt`.
    """
    # Step 1 & 2: ephemeral X25519
    ephemeral = generate_x25519_keypair()
    x25519_secret = x25519_shared_secret(
        ephemeral.private_key, recipient.x25519.public_key
    )

    # Step 3: Kyber-1024 encapsulation
    kyber_secret, kyber_ct = kyber_encapsulate(recipient.kyber.public_key)

    # Step 4: key derivation
    aes_key = _derive_aes_key(x25519_secret, kyber_secret)

    # Step 5: AES-256-GCM encryption
    ciphertext, nonce = aes256_encrypt(aes_key, plaintext)

    return EncryptedMessage(
        ciphertext=ciphertext,
        nonce=nonce,
        x25519_public=ephemeral.public_bytes(),
        kyber_ciphertext=kyber_ct,
    )


def hybrid_decrypt(recipient: HybridKeyPair, message: EncryptedMessage) -> bytes:
    """Decrypt a message produced by :func:`hybrid_encrypt`.

    Raises :class:`ValueError` on authentication failure.
    """
    # Reconstruct ephemeral X25519 public key
    ephemeral_pub = X25519PublicKey.from_public_bytes(message.x25519_public)

    # X25519 shared secret
    x25519_secret = x25519_shared_secret(recipient.x25519.private_key, ephemeral_pub)

    # Kyber-1024 decapsulation
    kyber_secret = kyber_decapsulate(
        recipient.kyber.secret_key, message.kyber_ciphertext
    )

    # Derive symmetric key and decrypt
    aes_key = _derive_aes_key(x25519_secret, kyber_secret)
    return aes256_decrypt(aes_key, message.ciphertext, message.nonce)
