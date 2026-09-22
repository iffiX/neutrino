"""One desired state per device: what the hub wants a machine to host.

``config/devices/<id>/`` holds ``modules.json``, each module's ``want`` and
whether the machine has settled it, one file per module with its
configuration, and ``rdp.json``, which seals the machine's seat password;
``<id>`` is the device's id. Composing a device's state gathers those with
the install recipe resolved for its platform and the parts the hub knows
about the machine, the address it sits at and the networks its shares
answer, under one hash the agent compares against. The document is the
``state`` frame's sections: ``modules``, one entry
``{want, config, install, uninstall}`` per module ``modules.json`` names
and has not settled, and ``desktop`` with the seat password.

A module the state does not mention is left as it is, and the agent
reports it all the same. A module the person uninstalled is mentioned
``absent`` until the agent reports it absent, at which point the report
path settles it: the state stops naming it, so the hub holds no standing
claim over software it took off, while the row keeps saying what the
person asked for.

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
from neutrino_hub.modules.channel.constants import CHANNEL_MODULE_WANTS
from neutrino_hub.modules.devices.catalog import resolved_modules
from neutrino_hub.modules.devices.constants import (
    DEVICE_GITEA_SECRET_NAMES,
    DEVICE_GITEA_SECRETS_FILE,
    DEVICE_MODULES_FILE,
    DEVICE_PACKAGES_DIR_NAME,
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
        """What one device is asked for, module by module.

        Args:
            key: The device key.

        Returns:
            Module name to ``{"want", "is_settled"}``, for the modules
            ``modules.json`` names and no other.
        """
        try:
            stored = read_config(self._path(key, DEVICE_MODULES_FILE))
        except (FileNotFoundError, ValueError):
            stored = {}
        held = stored.get("modules") if isinstance(stored, dict) else {}
        held = held if isinstance(held, dict) else {}
        modules = {}
        for name, entry in held.items():
            entry = entry if isinstance(entry, dict) else {}
            want = str(entry.get("want", "") or "")
            if want in CHANNEL_MODULE_WANTS:
                modules[str(name)] = {
                    "want": want,
                    "is_settled": bool(entry.get("is_settled", False)),
                }
        return modules

    def set_want(self, key: str, module: str, want: str) -> None:
        """Write what one device is to make of one module.

        A press asks again, so the module is unsettled: the state names it
        until the machine reports the want true.

        Args:
            key: The device key.
            module: The module name.
            want: ``absent``, ``installed``, ``stopped`` or ``running``.

        Raises:
            ValueError: For a ``want`` outside those four.
        """
        if want not in CHANNEL_MODULE_WANTS:
            raise ValueError(f"unknown want {want!r}")
        with CONFIG_WRITE_LOCK:
            modules = self.modules(key)
            modules[module] = {"want": want, "is_settled": False}
            write_config(self._path(key, DEVICE_MODULES_FILE), {"modules": modules})

    def want_of(self, key: str, module: str) -> str:
        """What one device is asked for on one module.

        Args:
            key: The device key.
            module: The module name.

        Returns:
            The ``want``, empty for a module the file does not name.
        """
        return self.modules(key).get(module, {}).get("want", "")

    def settle_want(self, key: str, module: str) -> bool:
        """Note that one device has made one module's ``want`` true.

        The row goes on saying what the person asked for; the state stops
        naming the module, so nothing the machine hosts afterwards is
        moved by a want it already satisfied.

        Args:
            key: The device key.
            module: The module name.

        Returns:
            True when the file named the module unsettled and now names it
            settled.
        """
        with CONFIG_WRITE_LOCK:
            modules = self.modules(key)
            entry = modules.get(module)
            if entry is None or entry["is_settled"]:
                return False
            modules[module] = {"want": entry["want"], "is_settled": True}
            write_config(self._path(key, DEVICE_MODULES_FILE), {"modules": modules})
        return True

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

    def has_gitea_secrets(self, key: str) -> bool:
        """Whether one device's Gitea secrets are stored, making none.

        Args:
            key: The device key.

        Returns:
            True when the secrets file names every secret.
        """
        try:
            held = read_config(self._path(key, DEVICE_GITEA_SECRETS_FILE))
        except (FileNotFoundError, ValueError):
            return False
        return all(held.get(name) for name in DEVICE_GITEA_SECRET_NAMES)

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
        urls: "list | tuple" = (),
    ) -> tuple:
        """One device's whole desired state and its hash.

        Every module ``modules.json`` names and has not settled is sent with
        its ``want``; one it does not name, and one the machine has already
        settled, is left out, so the agent leaves it as it is.

        Args:
            key: The device key.
            platform: The tuple the agent reported.
            address: Where the device is, for the URLs it derives.
            allowed_subnets: The networks its shares answer.
            urls: Every address the hub answers the channel on.

        Returns:
            ``(desired, hash)``, the document being
            ``{modules, desktop, urls}``.
        """
        resolved = resolved_modules(platform)
        modules = {}
        for name, entry in self.modules(key).items():
            if entry["is_settled"]:
                continue
            config = self.read(key, name)
            if name == "samba":
                config["allowed_subnets"] = list(allowed_subnets)
            elif name == "gitea":
                config["address"] = address
                config["secrets"] = self.gitea_secrets(key)
            modules[name] = {
                "want": entry["want"],
                "config": config,
                **_recipes(resolved.get(name) or {}),
            }
        desired = {
            "modules": modules,
            "desktop": {"seat_password": self.seat_password(key)},
            "urls": [str(url) for url in urls],
        }
        return desired, state_hash(desired)

    def forget(self, key: str) -> None:
        """Delete everything stored for one device.

        Args:
            key: The device key.
        """
        with CONFIG_WRITE_LOCK:
            shutil.rmtree(self._directory(key), ignore_errors=True)

    def forget_orphans(self, stored_ids) -> list:
        """Delete every device directory no stored id names.

        Args:
            stored_ids: The ids ``devices.json`` holds.

        Returns:
            The names removed, in order.
        """
        root = UTILS_CONFIG_DIR / DEVICES_DIR_NAME
        removed = []
        with CONFIG_WRITE_LOCK:
            if not root.is_dir():
                return removed
            for path in sorted(root.iterdir()):
                if not path.is_dir() or path.name == DEVICE_PACKAGES_DIR_NAME:
                    continue
                if path.name in stored_ids:
                    continue
                shutil.rmtree(path, ignore_errors=True)
                removed.append(path.name)
        return removed

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
        return UTILS_CONFIG_DIR / DEVICES_DIR_NAME / key

    def _path(self, key: str, name: str) -> str:
        return f"{DEVICES_DIR_NAME}/{key}/{name}"


def _recipes(resolved: dict) -> dict:
    """The install and uninstall recipes of one module resolved for a platform.

    Args:
        resolved: The module as :func:`resolved_modules` answers it.

    Returns:
        ``{"install", "uninstall"}``, the branch's own blocks; both empty
        where the manifest offers the platform nothing.
    """
    entry = resolved.get("entry")
    if not isinstance(entry, dict):
        return {"install": {}, "uninstall": {}}
    install = {name: value for name, value in entry.items() if name != "uninstall"}
    install["kind"] = str(resolved.get("kind", "") or "")
    return {"install": install, "uninstall": dict(entry.get("uninstall") or {})}


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
