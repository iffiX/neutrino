"""The SSH key the hub makes for one account on one machine.

One Ed25519 pair per enabled account and machine (agent/modules/ssh_server.md,
"Keys"): the private half is sealed in ``config/devices/<id>/ssh_server.json``
and handed to a client through the ``service`` frame, the public half is
the instance's one authorized key. Both halves are in OpenSSH form.
"""

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ed25519

from neutrino_hub.modules.devices.constants import DEVICE_SSH_SERVER_KEY_COMMENT


def generate_private_key() -> str:
    """A fresh Ed25519 private key.

    Returns:
        The key in OpenSSH form, as a client writes it under ``~/.ssh/neutrino/``.
    """
    key = ed25519.Ed25519PrivateKey.generate()
    return key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.OpenSSH,
        serialization.NoEncryption(),
    ).decode("ascii")


def public_key_of(private_key: str, *, comment: str = "") -> str:
    """The public half of one private key, as an authorized key line.

    Args:
        private_key: The private key in OpenSSH form.
        comment: What follows the key on the line; the hub's own word when
            empty.

    Returns:
        ``ssh-ed25519 <base64> <comment>``.

    Raises:
        ValueError: When the text is not an OpenSSH private key.
    """
    try:
        key = serialization.load_ssh_private_key(private_key.encode("ascii"), None)
    except (ValueError, TypeError, UnicodeEncodeError) as error:
        raise ValueError("not an OpenSSH private key") from error
    line = key.public_key().public_bytes(
        serialization.Encoding.OpenSSH, serialization.PublicFormat.OpenSSH
    )
    return f"{line.decode('ascii')} {comment or DEVICE_SSH_SERVER_KEY_COMMENT}"
