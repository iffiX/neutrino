"""One desired state per device: what the hub wants a machine to host.

``config/devices/<dir>/`` holds ``modules.json``, which modules are on, one
file per module with its configuration, and ``rdp.json``, which seals the
machine's seat password; ``<dir>`` is the device key with ``:`` written
``-``. Composing a device's desired state gathers those
with the catalog resolved for its platform and the parts the hub knows
about the machine, the address it sits at and the networks its shares
answer, under one hash the agent compares against.

Reads take no lock; every write goes through ``write_config`` under the one
config lock, re-reading inside it.
"""

import base64
import hashlib
import json
import secrets
import shutil
import string

from neutrino_hub.modules.credentials.vault import (
    seal_bytes,
    unseal_bytes,
)
from neutrino_hub.modules.devices.catalog import resolved_modules
from neutrino_hub.modules.devices.constants import (
    DEVICE_GITEA_SECRET_NAMES,
    DEVICE_GITEA_SECRETS_FILE,
    DEVICE_MODULE_NAMES,
    DEVICE_MODULES_FILE,
    DEVICE_RDP_FILE,
    DEVICE_RDP_SEAT_PASSWORD_AAD,
    DEVICE_RDP_SEAT_PASSWORD_CHARS,
)
from neutrino_hub.utils.constants import UTILS_CONFIG_DIR
from neutrino_hub.utils.json_file import (
    CONFIG_WRITE_LOCK,
    read_config,
    write_config,
)

DEVICES_DIR_NAME = "devices"


def device_dir(key: str) -> str:
    """The directory name one device's files live under.

    Args:
        key: The device key, ``aa:bb:cc:dd:ee:ff`` or ``id:<machine-id>``.

    Returns:
        The key, lowercased, with every ``:`` written ``-``.
    """
    return (key or "").lower().replace(":", "-")


def state_hash(desired: dict) -> str:
    """The hash both sides compare a desired state by.

    Args:
        desired: The composed state.

    Returns:
        The SHA-256 of its canonical JSON form.
    """
    serialized = json.dumps(desired, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


class DesiredStateStore:
    """Reads and writes the per-device module files under ``config/``."""

    def read(self, key: str, module: str) -> dict:
        """One module's stored configuration for one device.

        Args:
            key: The device key.
            module: The module name.

        Returns:
            The configuration, empty when the file does not exist.
        """
        try:
            return read_config(self._path(key, f"{module}.json"))
        except (FileNotFoundError, ValueError):
            return {}

    def write(self, key: str, module: str, config: dict) -> None:
        """Store one module's configuration for one device.

        Args:
            key: The device key.
            module: The module name.
            config: The configuration, whole.
        """
        with CONFIG_WRITE_LOCK:
            write_config(self._path(key, f"{module}.json"), dict(config))

    def modules(self, key: str) -> dict:
        """Which modules one device has on.

        Args:
            key: The device key.

        Returns:
            Module name to ``{"is_enabled"}``, every hosted module present.
        """
        try:
            stored = read_config(self._path(key, DEVICE_MODULES_FILE))
        except (FileNotFoundError, ValueError):
            stored = {}
        held = stored.get("modules") if isinstance(stored, dict) else {}
        held = held if isinstance(held, dict) else {}
        return {
            name: {"is_enabled": bool((held.get(name) or {}).get("is_enabled"))}
            for name in DEVICE_MODULE_NAMES
        }

    def set_enabled(self, key: str, module: str, is_enabled: bool) -> None:
        """Switch one module on or off for one device.

        Args:
            key: The device key.
            module: The module name.
            is_enabled: Whether the device should host it.
        """
        with CONFIG_WRITE_LOCK:
            modules = self.modules(key)
            modules[module] = {"is_enabled": bool(is_enabled)}
            write_config(self._path(key, DEVICE_MODULES_FILE), {"modules": modules})

    def is_enabled(self, key: str, module: str) -> bool:
        """Whether one device hosts one module."""
        return self.modules(key)[module]["is_enabled"]

    def gitea_secrets(self, key: str) -> dict:
        """The machine secrets one device's Gitea signs with, made once.

        Args:
            key: The device key.

        Returns:
            Every named secret.
        """
        with CONFIG_WRITE_LOCK:
            try:
                held = read_config(self._path(key, DEVICE_GITEA_SECRETS_FILE))
            except (FileNotFoundError, ValueError):
                held = {}
            missing = [name for name in DEVICE_GITEA_SECRET_NAMES if not held.get(name)]
            for name in missing:
                held[name] = _generate_secret(name)
            if missing:
                write_config(self._path(key, DEVICE_GITEA_SECRETS_FILE), held)
        return {name: str(held[name]) for name in DEVICE_GITEA_SECRET_NAMES}

    def seat_password(self, key: str) -> str:
        """The seat password ``rdp.json`` seals, opened for the machine.

        Args:
            key: The device key.

        Returns:
            The password, empty when the device has none, when the vault is
            locked, or when the seal does not open under this box's data
            key.
        """
        sealed = self._sealed_seat_password(key)
        if not sealed:
            return ""
        try:
            return unseal_bytes(sealed, DEVICE_RDP_SEAT_PASSWORD_AAD).decode()
        except ValueError:
            return ""

    def ensure_seat_password(self, key: str) -> bool:
        """Give one device a seat password the first time it needs one.

        Args:
            key: The device key.

        Returns:
            True when a password was generated and stored. A device that
            already has one keeps it, and a locked vault has nothing to seal
            with, which leaves the device for the next report.
        """
        with CONFIG_WRITE_LOCK:
            if self._sealed_seat_password(key):
                return False
            try:
                self._write_seat_password(key)
            except ValueError:
                return False
        return True

    def reset_seat_password(self, key: str) -> None:
        """Replace one device's seat password with a fresh one.

        Args:
            key: The device key.

        Raises:
            VaultLockedError: If there is no data key to seal it under.
        """
        with CONFIG_WRITE_LOCK:
            self._write_seat_password(key)

    def compose(
        self,
        key: str,
        platform: dict,
        *,
        address: str = "",
        allowed_subnets: "list | tuple" = (),
    ) -> tuple:
        """One device's whole desired state and its hash.

        Args:
            key: The device key.
            platform: The tuple the agent reported.
            address: Where the device is, for the URLs it derives.
            allowed_subnets: The networks its shares answer.

        Returns:
            ``(desired, hash)``.
        """
        modules = {}
        for name, switch in self.modules(key).items():
            config = self.read(key, name)
            if name == "samba":
                config["allowed_subnets"] = list(allowed_subnets)
            elif name == "gitea":
                config["address"] = address
                config["secrets"] = self.gitea_secrets(key)
            modules[name] = {"is_enabled": switch["is_enabled"], "config": config}
        desired = {
            "modules": modules,
            "rdp": {"seat_password": self.seat_password(key)},
            "catalog": {"modules": resolved_modules(platform)},
        }
        return desired, state_hash(desired)

    def forget(self, key: str) -> None:
        """Delete everything stored for one device.

        Args:
            key: The device key.
        """
        with CONFIG_WRITE_LOCK:
            shutil.rmtree(self._directory(key), ignore_errors=True)

    def _write_seat_password(self, key: str) -> None:
        """Seal a fresh seat password into the device's ``rdp.json``."""
        sealed = seal_bytes(
            _generate_seat_password().encode(), DEVICE_RDP_SEAT_PASSWORD_AAD
        )
        write_config(self._path(key, DEVICE_RDP_FILE), {"seat_password_sealed": sealed})

    def _sealed_seat_password(self, key: str) -> dict:
        """The seal ``rdp.json`` holds, empty when the file holds none."""
        try:
            held = read_config(self._path(key, DEVICE_RDP_FILE))
        except (FileNotFoundError, ValueError):
            return {}
        sealed = held.get("seat_password_sealed")
        return sealed if isinstance(sealed, dict) else {}

    def _directory(self, key: str):
        return UTILS_CONFIG_DIR / DEVICES_DIR_NAME / device_dir(key)

    def _path(self, key: str, name: str) -> str:
        return f"{DEVICES_DIR_NAME}/{device_dir(key)}/{name}"


def _generate_seat_password() -> str:
    """One seat password: letters and digits, long enough to stand alone."""
    alphabet = string.ascii_letters + string.digits
    return "".join(
        secrets.choice(alphabet) for _ in range(DEVICE_RDP_SEAT_PASSWORD_CHARS)
    )


def _generate_secret(name: str) -> str:
    """One machine secret in the form Gitea's own generator produces."""
    if name in ("JWT_SECRET", "LFS_JWT_SECRET"):
        return base64.urlsafe_b64encode(secrets.token_bytes(32)).decode().rstrip("=")
    if name == "INTERNAL_TOKEN":
        return secrets.token_urlsafe(48)
    return secrets.token_hex(32)
