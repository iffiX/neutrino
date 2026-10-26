"""What the SSH server module's tests share: one public key, its
fingerprint, and a private key file that names it."""

import base64
import struct

# A public key and the fingerprint ``ssh-keygen -lf`` printed for it.
PUBLIC_KEY = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIPbg3nX0Oi4lmPN3XHwV4yl1/aAMviQsLSIiP50dOkkz"  # scan: allow
PUBLIC_KEY_FINGERPRINT = (
    "SHA256:k4xI7N34jbzBM9eukqis2x6OkwzsQt59VHVOy0oEcqU"  # scan: allow
)


def ssh_string(data: bytes) -> bytes:
    """One SSH string: its length, then its bytes."""
    return struct.pack(">I", len(data)) + data


def private_key_text(public_line: str = PUBLIC_KEY) -> str:
    """An unencrypted OpenSSH private key file naming public_line, its private part filler."""
    blob = base64.b64decode(public_line.split()[1])
    body = (
        b"openssh-key-v1\x00"
        + ssh_string(b"none")
        + ssh_string(b"none")
        + ssh_string(b"")
        + struct.pack(">I", 1)
        + ssh_string(blob)
        + ssh_string(b"\x00" * 64)
    )
    encoded = base64.b64encode(body).decode("ascii")
    lines = [encoded[index : index + 70] for index in range(0, len(encoded), 70)]
    return "\n".join(
        [
            "-----BEGIN OPENSSH PRIVATE KEY-----",
            *lines,
            "-----END OPENSSH PRIVATE KEY-----",
            "",
        ]
    )
