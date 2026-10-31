"""An Ed25519 public key made from its seed, RFC 8032's key generation.

RustDesk's key pair is NaCl's ``crypto_sign``: the secret key is the seed, then
the public key. The arithmetic is written here, since the agent carries no
dependencies. Nothing here signs.

Pure: bytes in, bytes out.
"""

import hashlib

ED25519_SEED_BYTES = 32
# The prime of the field, the curve's constant, and the base point.
ED25519_PRIME = (1 << 255) - 19
ED25519_D = -121665 * pow(121666, ED25519_PRIME - 2, ED25519_PRIME) % ED25519_PRIME
ED25519_BASE_X = (
    15112221349535400772501151409588531511454012693041857206046113283949847762202
)
ED25519_BASE_Y = (
    46316835694926478169428394003475163141307993866256225615783033603165251855960
)


def public_key(seed: bytes) -> bytes:
    """The public key of one seed.

    Args:
        seed: The 32 bytes of the secret key.

    Returns:
        The 32 bytes of the public key.

    Raises:
        ValueError: If the seed is not 32 bytes.
    """
    if len(seed) != ED25519_SEED_BYTES:
        raise ValueError("an Ed25519 seed is 32 bytes")
    digest = hashlib.sha512(seed).digest()
    scalar = int.from_bytes(digest[:32], "little")
    scalar &= (1 << 254) - 8
    scalar |= 1 << 254
    base = (
        ED25519_BASE_X,
        ED25519_BASE_Y,
        1,
        ED25519_BASE_X * ED25519_BASE_Y % ED25519_PRIME,
    )
    return _compressed(_multiplied(scalar, base))


def _added(left: tuple, right: tuple) -> tuple:
    """The sum of two points in extended coordinates."""
    prime = ED25519_PRIME
    a = (left[1] - left[0]) * (right[1] - right[0]) % prime
    b = (left[1] + left[0]) * (right[1] + right[0]) % prime
    c = 2 * left[3] * right[3] * ED25519_D % prime
    d = 2 * left[2] * right[2] % prime
    e, f, g, h = b - a, d - c, d + c, b + a
    return (e * f % prime, g * h % prime, f * g % prime, e * h % prime)


def _multiplied(scalar: int, point: tuple) -> tuple:
    """A point added to itself ``scalar`` times, from the curve's neutral point."""
    total = (0, 1, 1, 0)
    while scalar > 0:
        if scalar & 1:
            total = _added(total, point)
        point = _added(point, point)
        scalar >>= 1
    return total


def _compressed(point: tuple) -> bytes:
    """A point as 32 bytes: its y, and the low bit of its x in the top bit."""
    inverse = pow(point[2], ED25519_PRIME - 2, ED25519_PRIME)
    x = point[0] * inverse % ED25519_PRIME
    y = point[1] * inverse % ED25519_PRIME
    return (y | ((x & 1) << 255)).to_bytes(32, "little")
