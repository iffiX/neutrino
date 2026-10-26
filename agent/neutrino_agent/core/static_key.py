"""The agent's static key: an X25519 pair, kept as 64 lowercase hex characters.

The transport does every handshake with the private key; this side makes
the key and, for a binding that predates it, works out its public half to
hand the hub once. The curve's arithmetic is RFC 7748's, in pure Python. Pure
but for the random bytes a new key takes.
"""

import secrets

# The field's prime, 2^255 - 19, and the curve constant (A - 2) / 4.
FIELD_PRIME = 2**255 - 19
CURVE_A24 = 121665
# The u-coordinate of the base point.
BASE_POINT_U = 9
KEY_BYTES = 32


def make_private_key() -> str:
    """A new static private key.

    Returns:
        32 random bytes as 64 lowercase hex characters.
    """
    return secrets.token_hex(KEY_BYTES)


def public_key_of(private_key: str) -> str:
    """The public half of a static private key.

    Args:
        private_key: 64 hex characters.

    Returns:
        X25519 of the key and the base point, 64 lowercase hex characters.

    Raises:
        ValueError: When the key is not 64 hex characters.
    """
    return x25519(bytes.fromhex(_checked(private_key)), _encode_u(BASE_POINT_U)).hex()


def x25519(scalar: bytes, u: bytes) -> bytes:
    """RFC 7748's X25519 function.

    Args:
        scalar: The 32-byte scalar, clamped here.
        u: The 32-byte little-endian u-coordinate.

    Returns:
        The 32-byte result.

    Raises:
        ValueError: When either argument is not 32 bytes.
    """
    if len(scalar) != KEY_BYTES or len(u) != KEY_BYTES:
        raise ValueError("X25519 takes 32-byte inputs")
    clamped = bytearray(scalar)
    clamped[0] &= 248
    clamped[31] &= 127
    clamped[31] |= 64
    k = int.from_bytes(clamped, "little")
    x_1 = int.from_bytes(u, "little") & ((1 << 255) - 1)
    x_2, z_2, x_3, z_3 = 1, 0, x_1, 1
    swap = 0
    for t in reversed(range(255)):
        k_t = (k >> t) & 1
        swap ^= k_t
        if swap:
            x_2, x_3 = x_3, x_2
            z_2, z_3 = z_3, z_2
        swap = k_t
        a = (x_2 + z_2) % FIELD_PRIME
        aa = a * a % FIELD_PRIME
        b = (x_2 - z_2) % FIELD_PRIME
        bb = b * b % FIELD_PRIME
        e = (aa - bb) % FIELD_PRIME
        c = (x_3 + z_3) % FIELD_PRIME
        d = (x_3 - z_3) % FIELD_PRIME
        da = d * a % FIELD_PRIME
        cb = c * b % FIELD_PRIME
        x_3 = (da + cb) ** 2 % FIELD_PRIME
        z_3 = x_1 * (da - cb) ** 2 % FIELD_PRIME
        x_2 = aa * bb % FIELD_PRIME
        z_2 = e * (aa + CURVE_A24 * e) % FIELD_PRIME
    if swap:
        x_2, x_3 = x_3, x_2
        z_2, z_3 = z_3, z_2
    result = x_2 * pow(z_2, FIELD_PRIME - 2, FIELD_PRIME) % FIELD_PRIME
    return _encode_u(result)


def _encode_u(value: int) -> bytes:
    return value.to_bytes(KEY_BYTES, "little")


def _checked(key: str) -> str:
    text = str(key).strip().lower()
    if len(text) != 2 * KEY_BYTES or any(c not in "0123456789abcdef" for c in text):
        raise ValueError("a key is 64 hex characters")
    return text
