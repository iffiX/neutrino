"""The agent's static key: an X25519 private key, kept as 64 lowercase hex characters.

The transport does every handshake with the key, and this side makes it.
"""

import secrets

KEY_BYTES = 32


def make_private_key() -> str:
    """A new static private key.

    Returns:
        32 random bytes as 64 lowercase hex characters.
    """
    return secrets.token_hex(KEY_BYTES)
