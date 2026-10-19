"""NaCl's ``crypto_box``: X25519, HSalsa20 and XSalsa20-Poly1305.

OpenFrp's remote login hands the ``Authorization`` back sealed this way, as
Go's ``nacl/box`` seals it: the 24-byte nonce, then the 16-byte tag, then the
ciphertext. X25519 is ``cryptography``'s; Salsa20 and Poly1305 are written
here, since ``cryptography`` has no XSalsa20.

Pure: bytes in, bytes out.
"""

import hmac
import struct

from cryptography.hazmat.primitives.asymmetric.x25519 import (
    X25519PrivateKey,
    X25519PublicKey,
)

NACL_KEY_BYTES = 32
NACL_NONCE_BYTES = 24
NACL_TAG_BYTES = 16
# "expand 32-byte k", the Salsa20 constant, as four little-endian words.
NACL_SIGMA = (0x61707865, 0x3320646E, 0x79622D32, 0x6B206574)
NACL_MASK = 0xFFFFFFFF
NACL_POLY1305_PRIME = (1 << 130) - 5
NACL_POLY1305_CLAMP = 0x0FFFFFFC0FFFFFFC0FFFFFFC0FFFFFFF


def box_open(sealed: bytes, *, peer_public: bytes, own_private: bytes) -> bytes:
    """Open what the peer sealed to this key pair.

    Args:
        sealed: The nonce, the tag and the ciphertext, in that order.
        peer_public: The sender's X25519 public key.
        own_private: This side's X25519 private key.

    Returns:
        The message.

    Raises:
        ValueError: If a key is not 32 bytes, the input is shorter than a
            nonce and a tag, or the tag does not verify.
    """
    if len(sealed) < NACL_NONCE_BYTES + NACL_TAG_BYTES:
        raise ValueError("the sealed text is shorter than a nonce and a tag")
    key = box_key(peer_public=peer_public, own_private=own_private)
    nonce = sealed[:NACL_NONCE_BYTES]
    tag = sealed[NACL_NONCE_BYTES : NACL_NONCE_BYTES + NACL_TAG_BYTES]
    ciphertext = sealed[NACL_NONCE_BYTES + NACL_TAG_BYTES :]
    stream = _xsalsa20_stream(key, nonce, 32 + len(ciphertext))
    if not hmac.compare_digest(_poly1305(stream[:32], ciphertext), tag):
        raise ValueError("the tag does not verify")
    return _xor(ciphertext, stream[32:])


def box_seal(
    message: bytes, nonce: bytes, *, peer_public: bytes, own_private: bytes
) -> bytes:
    """Seal a message to the peer, as Go's ``box.Seal(nonce, ...)`` does.

    Args:
        message: What to seal.
        nonce: 24 bytes, never used twice with the same pair of keys.
        peer_public: The recipient's X25519 public key.
        own_private: This side's X25519 private key.

    Returns:
        The nonce, the tag and the ciphertext, in that order.

    Raises:
        ValueError: If a key is not 32 bytes or the nonce not 24.
    """
    if len(nonce) != NACL_NONCE_BYTES:
        raise ValueError("the nonce is not 24 bytes")
    key = box_key(peer_public=peer_public, own_private=own_private)
    stream = _xsalsa20_stream(key, nonce, 32 + len(message))
    ciphertext = _xor(message, stream[32:])
    return nonce + _poly1305(stream[:32], ciphertext) + ciphertext


def box_key(*, peer_public: bytes, own_private: bytes) -> bytes:
    """The key two parties share, ``crypto_box_beforenm``.

    Args:
        peer_public: The other side's X25519 public key.
        own_private: This side's X25519 private key.

    Returns:
        HSalsa20 of the X25519 shared secret and sixteen zero bytes.

    Raises:
        ValueError: If a key is not 32 bytes.
    """
    if len(peer_public) != NACL_KEY_BYTES or len(own_private) != NACL_KEY_BYTES:
        raise ValueError("an X25519 key is 32 bytes")
    shared = X25519PrivateKey.from_private_bytes(own_private).exchange(
        X25519PublicKey.from_public_bytes(peer_public)
    )
    return hsalsa20(shared, bytes(16))


def hsalsa20(key: bytes, block: bytes) -> bytes:
    """HSalsa20: 32 bytes from a key and a 16-byte input.

    Args:
        key: 32 bytes.
        block: 16 bytes.

    Returns:
        Words 0, 5, 10, 15, 6, 7, 8 and 9 of the rounds' output.
    """
    words = _rounds(_state(key, block))
    return struct.pack("<8I", *(words[index] for index in (0, 5, 10, 15, 6, 7, 8, 9)))


def _xsalsa20_stream(key: bytes, nonce: bytes, length: int) -> bytes:
    """XSalsa20's key stream: Salsa20 under HSalsa20's subkey."""
    subkey = hsalsa20(key, nonce[:16])
    blocks = []
    for counter in range((length + 63) // 64):
        state = _state(subkey, nonce[16:24] + struct.pack("<Q", counter))
        mixed = _rounds(state)
        blocks.append(
            struct.pack("<16I", *((a + b) & NACL_MASK for a, b in zip(mixed, state)))
        )
    return b"".join(blocks)[:length]


def _state(key: bytes, block: bytes) -> list:
    """Salsa20's sixteen input words: the constant, the key and 16 bytes."""
    k = struct.unpack("<8I", key)
    n = struct.unpack("<4I", block)
    return [
        NACL_SIGMA[0],
        k[0],
        k[1],
        k[2],
        k[3],
        NACL_SIGMA[1],
        n[0],
        n[1],
        n[2],
        n[3],
        NACL_SIGMA[2],
        k[4],
        k[5],
        k[6],
        k[7],
        NACL_SIGMA[3],
    ]


def _rounds(state: list) -> list:
    """Salsa20's twenty rounds, without the final addition."""
    x = list(state)
    for _ in range(10):
        for a, b, c, d in (
            (0, 4, 8, 12),
            (5, 9, 13, 1),
            (10, 14, 2, 6),
            (15, 3, 7, 11),
            (0, 1, 2, 3),
            (5, 6, 7, 4),
            (10, 11, 8, 9),
            (15, 12, 13, 14),
        ):
            x[b] ^= _rotated(x[a] + x[d], 7)
            x[c] ^= _rotated(x[b] + x[a], 9)
            x[d] ^= _rotated(x[c] + x[b], 13)
            x[a] ^= _rotated(x[d] + x[c], 18)
    return x


def _rotated(value: int, count: int) -> int:
    """A 32-bit word rotated left."""
    value &= NACL_MASK
    return ((value << count) | (value >> (32 - count))) & NACL_MASK


def _poly1305(key: bytes, message: bytes) -> bytes:
    """Poly1305's tag of a message under a one-time key."""
    r = int.from_bytes(key[:16], "little") & NACL_POLY1305_CLAMP
    s = int.from_bytes(key[16:32], "little")
    accumulator = 0
    for start in range(0, len(message), 16):
        block = message[start : start + 16] + b"\x01"
        accumulator = (
            (accumulator + int.from_bytes(block, "little")) * r
        ) % NACL_POLY1305_PRIME
    return ((accumulator + s) & ((1 << 128) - 1)).to_bytes(16, "little")


def _xor(data: bytes, stream: bytes) -> bytes:
    """Two byte strings of one length, combined."""
    return bytes(a ^ b for a, b in zip(data, stream))
