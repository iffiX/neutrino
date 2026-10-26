"""OpenSSH key forms: a public key line, its fingerprint, and the public
half a private key file names.

Pure: parsing of text alone.
"""

# PEP 604 unions below are annotations only; this keeps them lazy so the
# agent still imports on the Python 3.9 that older Raspbian ships.
from __future__ import annotations

import base64
import binascii
import hashlib
import struct

# What every OpenSSH private key file's body starts with.
PRIVATE_KEY_MAGIC = b"openssh-key-v1\x00"
PRIVATE_KEY_BEGIN = "-----BEGIN OPENSSH PRIVATE KEY-----"
PRIVATE_KEY_END = "-----END OPENSSH PRIVATE KEY-----"


def public_key_blob(line: str) -> bytes:
    """The key blob of one authorized_keys line.

    Args:
        line: ``<type> <base64>`` and an optional comment.

    Returns:
        The decoded blob.

    Raises:
        ValueError: When the line names no key, its base64 does not decode,
            or the blob's own type is not the line's.
    """
    fields = line.strip().split()
    if len(fields) < 2:
        raise ValueError("a public key line is a type and a key")
    try:
        blob = base64.b64decode(fields[1], validate=True)
    except (binascii.Error, ValueError):
        raise ValueError("the key is not base64") from None
    if _read_string(blob, 0)[0] != fields[0].encode("ascii", "replace"):
        raise ValueError("the key's type is not the line's")
    return blob


def is_public_key(line: str) -> bool:
    """Whether a line is one OpenSSH public key.

    Args:
        line: The text.

    Returns:
        True when :func:`public_key_blob` reads it.
    """
    try:
        public_key_blob(line)
    except ValueError:
        return False
    return True


def fingerprint(line: str) -> str:
    """A public key's fingerprint as OpenSSH prints it.

    Args:
        line: The public key line.

    Returns:
        ``SHA256:`` and the digest of the blob in base64 without padding.

    Raises:
        ValueError: When the line is not a public key.
    """
    digest = hashlib.sha256(public_key_blob(line)).digest()
    return "SHA256:" + base64.b64encode(digest).decode("ascii").rstrip("=")


def public_line_of_private(text: str) -> str:
    """The public half an unencrypted OpenSSH private key file names.

    Args:
        text: The file's text.

    Returns:
        ``<type> <base64>``, the first key the file holds.

    Raises:
        ValueError: When the text is not an OpenSSH private key.
    """
    lines = [line.strip() for line in text.strip().splitlines()]
    if len(lines) < 3 or lines[0] != PRIVATE_KEY_BEGIN or lines[-1] != PRIVATE_KEY_END:
        raise ValueError("not an OpenSSH private key")
    try:
        body = base64.b64decode("".join(lines[1:-1]), validate=True)
    except (binascii.Error, ValueError):
        raise ValueError("the private key is not base64") from None
    if not body.startswith(PRIVATE_KEY_MAGIC):
        raise ValueError("not an OpenSSH private key")
    offset = len(PRIVATE_KEY_MAGIC)
    for _skipped in ("cipher", "kdf", "kdf options"):
        _value, offset = _read_string(body, offset)
    if offset + 4 > len(body) or struct.unpack(">I", body[offset : offset + 4])[0] < 1:
        raise ValueError("the private key holds no key")
    blob, _offset = _read_string(body, offset + 4)
    key_type = _read_string(blob, 0)[0].decode("ascii", "replace")
    return f"{key_type} {base64.b64encode(blob).decode('ascii')}"


def _read_string(data: bytes, offset: int) -> tuple:
    """One SSH string at offset: its bytes and the offset after it."""
    if offset + 4 > len(data):
        raise ValueError("the key ends early")
    (length,) = struct.unpack(">I", data[offset : offset + 4])
    end = offset + 4 + length
    if end > len(data):
        raise ValueError("the key ends early")
    return data[offset + 4 : end], end
