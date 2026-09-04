"""The key that unlocks the AI gateway's management API.

Generated on the box, never typed by anybody: the panel is the management API's
only caller, so the key is machine state rather than a user-facing credential.
It lives like the agent channel's private key — sealed under the vault's data
key beside the module's config, so a backup carries it protected, with the
working copy in the state root for the applier and the usage collector to
read. It is deliberately not a vault record: deleting credentials on the
Credentials page must never be able to switch the metering off.
"""

import json
import os
import uuid
from pathlib import Path

from neutrino_hub.modules.cliproxyapi.constants import (
    CLIPROXYAPI_MANAGEMENT_KEY_AAD,
    CLIPROXYAPI_MANAGEMENT_KEY_RELATIVE,
    CLIPROXYAPI_MANAGEMENT_SEALED_KEY_RELATIVE,
)
from neutrino_hub.modules.credentials.vault import (
    VaultError,
    seal_bytes,
    unseal_bytes,
)
from neutrino_hub.utils import constants, json_file


def ensure_management_key(*, sealed_key_path: Path | None = None) -> bool:
    """Generate and seal the key once; an existing sealed key is left alone.

    Regenerating would invalidate the hash the running gateway holds until
    the next apply, so the key is written only when it is not there.

    Args:
        sealed_key_path: Where the sealed key lives; None resolves it under
            this instance's config directory.

    Returns:
        True when a key was generated.

    Raises:
        VaultLockedError: If a key is needed and there is no data key to
            seal it under.
    """
    sealed_key_path = sealed_key_path or _sealed_key_path()
    if sealed_key_path.is_file():
        return False
    key = uuid.uuid4().hex + uuid.uuid4().hex
    sealed = seal_bytes(key.encode(), CLIPROXYAPI_MANAGEMENT_KEY_AAD)
    sealed_key_path.parent.mkdir(parents=True, exist_ok=True)
    _write_private(sealed_key_path, json.dumps(sealed, indent=2).encode())
    return True


def write_working_key(
    *,
    sealed_key_path: Path | None = None,
    working_key_path: Path | None = None,
) -> Path:
    """Unseal the key into the state file the panel reads it from.

    Args:
        sealed_key_path: The sealed key in ``config/``; None resolves it.
        working_key_path: The state file to write, mode 0600; None resolves
            it under the state root.

    Returns:
        The state file's path.

    Raises:
        VaultLockedError: If there is no data key on this box.
        VaultError: If the sealed key is missing, malformed, or does not
            decrypt.
        OSError: If the state file cannot be written.
    """
    sealed_key_path = sealed_key_path or _sealed_key_path()
    working_key_path = working_key_path or _working_key_path()
    sealed = json.loads(sealed_key_path.read_text(encoding="utf-8"))
    key = unseal_bytes(sealed, CLIPROXYAPI_MANAGEMENT_KEY_AAD)
    working_key_path.parent.mkdir(parents=True, exist_ok=True)
    _write_private(working_key_path, key)
    return working_key_path


def read_management_key(*, working_key_path: Path | None = None) -> str:
    """Read the working copy.

    Args:
        working_key_path: The state file; None resolves it.

    Returns:
        The key, or empty when the working copy is not there or unreadable.
    """
    working_key_path = working_key_path or _working_key_path()
    try:
        return working_key_path.read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def resolve_management_key() -> str:
    """The key for a render, generating and unsealing on first need.

    Returns:
        The key, or empty when the vault cannot open one — the render then
        leaves the management API off rather than failing the apply.
    """
    key = read_management_key()
    if key:
        return key
    try:
        ensure_management_key()
        write_working_key()
    except (VaultError, OSError, ValueError):
        return ""
    return read_management_key()


def _sealed_key_path() -> Path:
    # Resolved per call, against the config directory as it is right now.
    return json_file.UTILS_CONFIG_DIR / CLIPROXYAPI_MANAGEMENT_SEALED_KEY_RELATIVE


def _working_key_path() -> Path:
    # Resolved per call, against the state root as it is right now.
    return constants.UTILS_STATE_ROOT / CLIPROXYAPI_MANAGEMENT_KEY_RELATIVE


def _write_private(path: Path, data: bytes) -> None:
    """Write the file readable by root alone, from its first byte on disk."""
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(descriptor, "wb") as stream:
        stream.write(data)
    os.chmod(path, 0o600)
