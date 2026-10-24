"""NaCl's ``crypto_secretbox_open_easy``: XSalsa20-Poly1305 under one key.

RustDesk seals the secrets in its settings files this way: the 16-byte tag,
then the ciphertext. Salsa20, HSalsa20 and Poly1305 are written here, since
the agent carries no dependencies.

Pure: bytes in, bytes out.
"""

import hmac
import struct

SECRETBOX_KEY_BYTES = 32
SECRETBOX_NONCE_BYTES = 24
SECRETBOX_TAG_BYTES = 16
# "expand 32-byte k", the Salsa20 constant, as four little-endian words.
SECRETBOX_SIGMA = (0x61707865, 0x3320646E, 0x79622D32, 0x6B206574)
SECRETBOX_MASK = 0xFFFFFFFF
SECRETBOX_POLY1305_PRIME = (1 << 130) - 5
SECRETBOX_POLY1305_CLAMP = 0x0FFFFFFC0FFFFFFC0FFFFFFC0FFFFFFF


def secretbox_open(sealed: bytes, nonce: bytes, key: bytes) -> bytes:
    """Open what ``crypto_secretbox_easy`` sealed.

    Args:
        sealed: The tag, then the ciphertext.
        nonce: The 24 bytes it was sealed with.
        key: The 32-byte key.

    Returns:
        The message.

    Raises:
        ValueError: If the key is not 32 bytes, the nonce not 24, the input
            is shorter than a tag, or the tag does not verify.
    """
    if len(key) != SECRETBOX_KEY_BYTES or len(nonce) != SECRETBOX_NONCE_BYTES:
        raise ValueError("a secretbox key is 32 bytes and its nonce 24")
    if len(sealed) < SECRETBOX_TAG_BYTES:
        raise ValueError("the sealed text is shorter than a tag")
    tag = sealed[:SECRETBOX_TAG_BYTES]
    ciphertext = sealed[SECRETBOX_TAG_BYTES:]
    stream = _xsalsa20_stream(key, nonce, 32 + len(ciphertext))
    if not hmac.compare_digest(_poly1305(stream[:32], ciphertext), tag):
        raise ValueError("the tag does not verify")
    return _xor(ciphertext, stream[32:])


def _xsalsa20_stream(key: bytes, nonce: bytes, length: int) -> bytes:
    """XSalsa20's key stream: Salsa20 under HSalsa20's subkey."""
    subkey = _hsalsa20(key, nonce[:16])
    blocks = []
    for counter in range((length + 63) // 64):
        state = _state(subkey, nonce[16:24] + struct.pack("<Q", counter))
        mixed = _rounds(state)
        blocks.append(
            struct.pack(
                "<16I", *((a + b) & SECRETBOX_MASK for a, b in zip(mixed, state))
            )
        )
    return b"".join(blocks)[:length]


def _hsalsa20(key: bytes, block: bytes) -> bytes:
    """HSalsa20: words 0, 5, 10, 15, 6, 7, 8 and 9 of the rounds' output."""
    words = _rounds(_state(key, block))
    return struct.pack("<8I", *(words[index] for index in (0, 5, 10, 15, 6, 7, 8, 9)))


def _state(key: bytes, block: bytes) -> list:
    """Salsa20's sixteen input words: the constant, the key and 16 bytes."""
    k = struct.unpack("<8I", key)
    n = struct.unpack("<4I", block)
    return [
        SECRETBOX_SIGMA[0],
        k[0],
        k[1],
        k[2],
        k[3],
        SECRETBOX_SIGMA[1],
        n[0],
        n[1],
        n[2],
        n[3],
        SECRETBOX_SIGMA[2],
        k[4],
        k[5],
        k[6],
        k[7],
        SECRETBOX_SIGMA[3],
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
    value &= SECRETBOX_MASK
    return ((value << count) | (value >> (32 - count))) & SECRETBOX_MASK


def _poly1305(key: bytes, message: bytes) -> bytes:
    """Poly1305's tag of a message under a one-time key."""
    r = int.from_bytes(key[:16], "little") & SECRETBOX_POLY1305_CLAMP
    s = int.from_bytes(key[16:32], "little")
    accumulator = 0
    for start in range(0, len(message), 16):
        block = message[start : start + 16] + b"\x01"
        accumulator = (
            (accumulator + int.from_bytes(block, "little")) * r
        ) % SECRETBOX_POLY1305_PRIME
    return ((accumulator + s) & ((1 << 128) - 1)).to_bytes(16, "little")


def _xor(data: bytes, stream: bytes) -> bytes:
    """Two byte strings of one length, combined."""
    return bytes(a ^ b for a, b in zip(data, stream))
