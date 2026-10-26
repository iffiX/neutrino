"""The public half of this client's static key, by X25519 (RFC 7748).

The transport does every handshake with the private half and the hub learns
the public half from it. The one place the client names its public half
itself is the move of a binding a 0.5 client kept, which tells the hub the
key over the legacy listener before any handshake.
"""

from neutrino_client.constants import CLIENT_TRANSPORT_SECRET_BYTES

# The field's prime, the curve's constant, and the base point's u.
X25519_PRIME = 2**255 - 19
X25519_A24 = 121665
X25519_BASE_U = 9


def public_key_of(private_key: str) -> str:
    """The public half of a static private key.

    Args:
        private_key: 32 bytes as 64 hex characters.

    Returns:
        X25519 of the clamped scalar and the base point, as 64 lowercase
        hex characters.

    Raises:
        ValueError: When the key is not 32 bytes of hex.
    """
    scalar = bytes.fromhex(private_key)
    if len(scalar) != CLIENT_TRANSPORT_SECRET_BYTES:
        raise ValueError("a static private key is 32 bytes")
    return _ladder(_clamped(scalar), X25519_BASE_U).to_bytes(32, "little").hex()


def _clamped(scalar: bytes) -> int:
    """The scalar as RFC 7748 clamps it."""
    clamped = bytearray(scalar)
    clamped[0] &= 248
    clamped[31] &= 127
    clamped[31] |= 64
    return int.from_bytes(bytes(clamped), "little")


def _ladder(scalar: int, u: int) -> int:
    """The Montgomery ladder of RFC 7748, section 5."""
    p = X25519_PRIME
    x1, x2, z2, x3, z3 = u, 1, 0, u, 1
    swap = 0
    for bit in range(254, -1, -1):
        current = (scalar >> bit) & 1
        swap ^= current
        if swap:
            x2, x3 = x3, x2
            z2, z3 = z3, z2
        swap = current
        a = (x2 + z2) % p
        aa = a * a % p
        b = (x2 - z2) % p
        bb = b * b % p
        e = (aa - bb) % p
        c = (x3 + z3) % p
        d = (x3 - z3) % p
        da = d * a % p
        cb = c * b % p
        x3 = (da + cb) ** 2 % p
        z3 = x1 * (da - cb) ** 2 % p
        x2 = aa * bb % p
        z2 = e * (aa + X25519_A24 * e) % p
    if swap:
        x2, x3 = x3, x2
        z2, z3 = z3, z2
    return x2 * pow(z2, p - 2, p) % p
