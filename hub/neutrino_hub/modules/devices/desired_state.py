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
and has not settled, ``desktop`` with the seat password, and ``ai_tools``,
the machine's AI tools setting from ``ai_tools.json`` with where its tools
reach the gateway and the device's key, for the accounts the instances of
the programs run as an account name.

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
import hmac
import json
import secrets
import shutil
import string
import time

from neutrino_hub.edition import EDITION
from neutrino_hub.exceptions import VaultLockedError
from neutrino_hub.modules.credentials.vault import (
    SecretVault,
    seal_bytes,
    unseal_bytes,
)
from neutrino_hub.modules.channel.constants import (
    CHANNEL_MODULE_STATE_ABSENT,
    CHANNEL_MODULE_STATE_RUNNING,
    CHANNEL_MODULE_STATE_STOPPED,
    CHANNEL_MODULE_WANTS,
)
from neutrino_hub.modules.clients.ai_keys import device_gateway
from neutrino_hub.modules.devices.ai_tools import (
    clean_tool_configs,
    resolved_tool_configs,
)
from neutrino_hub.modules.devices.catalog import resolved_modules
from neutrino_hub.modules.devices.manifests import (
    load_module_manifests,
    load_tool_manifests,
)
from neutrino_hub.modules.devices.constants import (
    DEVICE_AI_SWITCHER_NAME,
    DEVICE_AGENT_MODULES,
    DEVICE_AI_TOOLS_NAME,
    DEVICE_REMOTE_DESKTOP_MODULE,
    DEVICE_TERMINAL_ACCOUNT_OS,
    DEVICE_TERMINAL_MODULE,
    DEVICE_RETRY_MARK_KEY,
    DEVICE_CLOUDCLI_NPM_REGISTRIES,
    DEVICE_FORWARDER_TOKEN_EXPIRY_BYTES,
    DEVICE_FORWARDER_TOKEN_LIFETIME_S,
    DEVICE_FORWARDER_TOKEN_NONCE_BYTES,
    DEVICE_GITEA_SECRET_NAMES,
    DEVICE_GITEA_SECRETS_FILE,
    DEVICE_INSTANCE_LOGIN_KEY,
    DEVICE_MODULES_FILE,
    DEVICE_PACKAGES_DIR_NAME,
    DEVICE_PODMAN_MACHINE_KEY,
    DEVICE_PODMAN_MACHINE_OS,
    DEVICE_RDP_FILE,
    DEVICE_RDP_SEAT_PASSWORD_AAD,
    DEVICE_RDP_SEAT_PASSWORD_CHARS,
)
from neutrino_hub.modules.devices.module_table import (
    DeviceModuleRow,
    account_program_names,
    module_row,
)
from neutrino_hub.utils.constants import UTILS_CONFIG_DIR
from neutrino_hub.utils.json_file import (
    CONFIG_WRITE_LOCK,
    read_config,
    write_config,
)

DEVICES_DIR_NAME = "devices"
# The system whose instances start as their account only with its password.
VSCODE_PASSWORD_OS = "windows"
# A manifest naming this is an npm install: the state carries the registry
# of the hub's edition and the environment the manifest names for it.
NPM_ENVIRONMENT_KEY = "npm_environment"


def state_hash(desired: dict) -> str:
    """The hash both sides compare a desired state by.

    Args:
        desired: The composed state.

    Returns:
        The SHA-256 of its canonical JSON form.
    """
    serialized = json.dumps(desired, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def instances_agent_config(
    row: DeviceModuleRow, stored: dict, platform: dict, *, edition: str = EDITION
) -> dict:
    """What the agent is sent for a program run as a person's account.

    Args:
        row: The module's row in the description table.
        stored: The module's file: the instances, each with its sealed
            fields and, where the row names one, the login it runs as.
        platform: The tuple the agent reported; only a Windows machine is
            sent a password.
        edition: The hub's edition, whose npm registry a module installed
            by npm is sent.

    Returns:
        The row's ``config_head``, then for a module whose manifest names
        ``npm_environment`` the ``npm_registry`` and ``npm_environment`` of
        the edition, then ``instances``, each ``{account, port}`` with every
        sealed field opened under its opened key and, on Windows, the
        ``password`` of the instance's login.
    """
    config = dict(row.config_head)
    manifest = load_module_manifests().get(row.name) or {}
    if NPM_ENVIRONMENT_KEY in manifest:
        config["npm_registry"] = DEVICE_CLOUDCLI_NPM_REGISTRIES[edition]
        config[NPM_ENVIRONMENT_KEY] = dict(
            (manifest.get(NPM_ENVIRONMENT_KEY) or {}).get(edition, {})
        )
    is_windows = platform.get("os") == VSCODE_PASSWORD_OS
    instances = []
    for instance in stored.get("instances") or []:
        if not isinstance(instance, dict):
            continue
        sent = {
            "account": str(instance.get("account", "") or ""),
            "port": instance.get("port", 0),
        }
        for sealed in row.sealed_fields:
            sent[sealed.opened_key] = _unsealed_text(
                instance.get(sealed.key), sealed.aad
            )
        if row.is_login_named:
            login_id = str(instance.get(DEVICE_INSTANCE_LOGIN_KEY, "") or "")
            if is_windows and login_id:
                sent["password"] = _login_password(login_id)
        instances.append(sent)
    config["instances"] = instances
    return config


def podman_agent_config(stored: dict, platform: dict) -> dict:
    """What the agent is sent for the Containers module.

    Args:
        stored: ``podman.json``: the containers, the mirrors and the Run
            settings, ``machine``, with the login its account signs in with.
        platform: The tuple the agent reported; only a Windows or macOS
            machine is sent ``machine``, and only a Windows one a password.

    Returns:
        The file's fields as stored, ``machine`` left out on Linux and on a
        machine that reported no system; on Windows and macOS ``machine``
        is ``{account, cpus, memory_gib, disk_gib}``, with the ``password``
        of its login on Windows.
    """
    config = {
        key: value for key, value in stored.items() if key != DEVICE_PODMAN_MACHINE_KEY
    }
    machine = stored.get(DEVICE_PODMAN_MACHINE_KEY)
    os_name = platform.get("os")
    if os_name not in DEVICE_PODMAN_MACHINE_OS or not isinstance(machine, dict):
        return config
    sent = {
        "account": str(machine.get("account", "") or ""),
        "cpus": machine.get("cpus", 0),
        "memory_gib": machine.get("memory_gib", 0),
        "disk_gib": machine.get("disk_gib", 0),
    }
    login_id = str(machine.get(DEVICE_INSTANCE_LOGIN_KEY, "") or "")
    if os_name == VSCODE_PASSWORD_OS and login_id:
        sent["password"] = _login_password(login_id)
    config[DEVICE_PODMAN_MACHINE_KEY] = sent
    return config


def ai_tools_agent_config(
    stored: dict,
    accounts: list,
    platform: dict,
    gateway: dict,
    models: list,
    switcher_version: str = "",
    *,
    is_forwarded: bool = True,
) -> dict:
    """What the agent is sent for the machine's AI tools.

    Args:
        stored: The setting, as :meth:`DesiredStateStore.ai_tools` reads it.
        accounts: ``(account, login_id)`` of each account the setting acts
            on, as :meth:`DesiredStateStore.ai_tool_accounts` gives them.
        platform: The tuple the agent reported; only a Windows machine is
            sent a password.
        gateway: ``{gateway_url, gateway_key}``: where the device's tools
            reach the gateway, and the device's own key.
        models: The names the gateway serves now.
        switcher_version: The cc-switch version the hub's manifest pins.
        is_forwarded: Whether the agent opens its AI gateway forward: true on
            a managed machine, false on the hub's own.

    Returns:
        ``{is_enabled: false, cc_switch_version}`` while the setting is off,
        the gateway serves no model, or the device has no key for it, the
        version left out when none is given; else
        ``{is_enabled, is_forwarded, base_url, api_key, tool_configs,
        accounts: [{account, password}], cc_switch_version}``, every Claude
        slot filled with the first served model where none was chosen and
        ``password`` sent to a Windows machine alone.
    """
    base_url = str(gateway.get("gateway_url", "") or "")
    api_key = str(gateway.get("gateway_key", "") or "")
    if not stored.get("is_enabled") or not models or not base_url or not api_key:
        off = {"is_enabled": False}
        if switcher_version:
            off["cc_switch_version"] = switcher_version
        return off
    is_windows = platform.get("os") == VSCODE_PASSWORD_OS
    sent_accounts = []
    for account, login_id in accounts:
        sent = {"account": account}
        if is_windows and login_id:
            sent["password"] = _login_password(login_id)
        sent_accounts.append(sent)
    return {
        "is_enabled": True,
        "is_forwarded": is_forwarded,
        "base_url": base_url,
        "api_key": api_key,
        "tool_configs": resolved_tool_configs(
            stored.get("tool_configs") or {}, str(models[0])
        ),
        "accounts": sent_accounts,
        "cc_switch_version": switcher_version,
    }


def terminal_agent_config(stored: dict, platform: dict) -> dict:
    """What the agent is sent for the Terminal module.

    Args:
        stored: ``terminal.json``, empty when the device has none.
        platform: The tuple the agent reported; a Windows machine is sent
            no account.

    Returns:
        ``{account, shell_path}``, both empty for the default.
    """
    is_account_sent = (
        not platform.get("os") or platform.get("os") in DEVICE_TERMINAL_ACCOUNT_OS
    )
    return {
        "account": (str(stored.get("account", "") or "") if is_account_sent else ""),
        "shell_path": str(stored.get("shell_path", "") or ""),
    }


def forwarder_token(secret: str, *, expiry: int, nonce: bytes) -> str:
    """One token a CloudCLI or code-server instance's forwarder takes once.

    Args:
        secret: The instance's token secret.
        expiry: When it stops working, in seconds since the epoch.
        nonce: Random bytes, as many as a token carries.

    Returns:
        ``base64url(expiry || nonce || HMAC-SHA256(secret, expiry || nonce))``
        without padding.
    """
    body = int(expiry).to_bytes(DEVICE_FORWARDER_TOKEN_EXPIRY_BYTES, "big") + nonce
    mac = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).digest()
    return base64.urlsafe_b64encode(body + mac).rstrip(b"=").decode("ascii")


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

    def drop_want(self, key: str, module: str) -> bool:
        """Forget what one device was asked for on one module.

        The state stops naming the module, and the module's saved
        configuration stays where it is.

        Args:
            key: The device key.
            module: The module name.

        Returns:
            True when the file named the module.

        Raises:
            OSError: When the file cannot be written.
        """
        with CONFIG_WRITE_LOCK:
            modules = self.modules(key)
            if modules.pop(module, None) is None:
                return False
            write_config(self._path(key, DEVICE_MODULES_FILE), {"modules": modules})
        return True

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

    def sealed_instance_field(
        self, key: str, module: str, account: str, field: str
    ) -> dict:
        """One instance's sealed field, made the first time it is asked for.

        Args:
            key: The device key.
            module: The module, a program run as a person's account.
            account: The account the instance runs as.
            field: The key the seal is stored under, one the module's row
                names.

        Returns:
            The seal the module's file holds for that account's instance, or
            a fresh one to store with it.

        Raises:
            KeyError: For a module the table does not hold, or a field its
                row does not seal.
            VaultLockedError: If there is no data key to seal a fresh one
                under.
        """
        sealed = module_row(module).sealed_field(field)
        for instance in self.read(key, module).get("instances") or []:
            if not isinstance(instance, dict) or instance.get("account") != account:
                continue
            held = instance.get(field)
            if isinstance(held, dict) and held:
                return dict(held)
        return seal_bytes(
            secrets.token_urlsafe(sealed.secret_bytes).encode(), sealed.aad
        )

    def instance_token(
        self, key: str, module: str, account: str, *, now: "float | None" = None
    ) -> str:
        """The token a client opens one instance with, as the row says.

        Args:
            key: The device key.
            module: The module, a program run as a person's account.
            account: The account the instance runs as.
            now: Seconds since the epoch; None is the clock.

        Returns:
            For a row whose token is minted, a fresh token from the
            instance's secret, its expiry 60 seconds ahead; otherwise the
            opened value of the row's token field. Empty when the device has
            no such instance, when the vault is locked, or when the seal
            does not open under this box's data key.

        Raises:
            KeyError: For a module the table does not hold, or one that
                hands no token.
        """
        row = module_row(module)
        sealed = row.sealed_field(row.token_field)
        for instance in self.read(key, module).get("instances") or []:
            if not isinstance(instance, dict) or instance.get("account") != account:
                continue
            opened = _unsealed_text(instance.get(sealed.key), sealed.aad)
            if not opened or not row.is_token_minted:
                return opened
            return _fresh_token(opened, now)
        return ""

    def ai_tools(self, key: str) -> dict:
        """One device's AI tools setting.

        Args:
            key: The device key.

        Returns:
            ``{is_enabled, tool_configs}``, off and empty when the device has
            none, the choices cleaned as the client cleans them.
        """
        stored = self.read(key, DEVICE_AI_TOOLS_NAME)
        return {
            "is_enabled": stored.get("is_enabled") is True,
            "tool_configs": clean_tool_configs(stored.get("tool_configs") or {}),
        }

    def set_ai_tools(
        self,
        key: str,
        *,
        is_enabled: "bool | None" = None,
        tool_configs: "dict | None" = None,
    ) -> dict:
        """Write one device's AI tools setting.

        Args:
            key: The device key.
            is_enabled: Whether the machine's tools use the gateway; None
                keeps the stored value.
            tool_configs: The tool choices; None keeps the stored ones.

        Returns:
            The setting as written.
        """
        held = self.ai_tools(key)
        if is_enabled is not None:
            held["is_enabled"] = bool(is_enabled)
        if tool_configs is not None:
            held["tool_configs"] = clean_tool_configs(tool_configs)
        self.write(key, DEVICE_AI_TOOLS_NAME, held)
        return held

    def ai_tool_accounts(self, key: str) -> list:
        """The accounts one device's AI tools setting acts on.

        Args:
            key: The device key.

        Returns:
            ``(account, login_id, modules)`` for every account with an
            instance in the configuration of a program run as an account
            whose module is asked for and not withdrawn, sorted by account;
            ``login_id`` the first instance's in the table's order, empty
            where none names one, and ``modules`` the modules it has an
            instance in.
        """
        wanted = self.modules(key)
        found: dict = {}
        for module in account_program_names():
            entry = wanted.get(module)
            if entry is None or entry["want"] == CHANNEL_MODULE_STATE_ABSENT:
                continue
            for instance in self.read(key, module).get("instances") or []:
                if not isinstance(instance, dict):
                    continue
                account = str(instance.get("account", "") or "")
                if not account:
                    continue
                login_id, modules = found.get(account, ("", []))
                if module not in modules:
                    modules = [*modules, module]
                login_id = login_id or str(
                    instance.get(DEVICE_INSTANCE_LOGIN_KEY, "") or ""
                )
                found[account] = (login_id, modules)
        return [
            (account, found[account][0], found[account][1]) for account in sorted(found)
        ]

    def remote_desktop(self, key: str) -> dict:
        """One device's Remote desktop switch.

        Args:
            key: The device key.

        Returns:
            ``{is_enabled}``, off when the device has no file.
        """
        stored = self.read(key, DEVICE_REMOTE_DESKTOP_MODULE)
        return {"is_enabled": stored.get("is_enabled") is True}

    def has_remote_desktop(self, key: str) -> bool:
        """Whether the device's Remote desktop switch was ever written."""
        return bool(self.read(key, DEVICE_REMOTE_DESKTOP_MODULE))

    def set_remote_desktop(self, key: str, is_enabled: bool) -> dict:
        """Write one device's Remote desktop switch.

        Args:
            key: The device key.
            is_enabled: Whether the desktop is shared.

        Returns:
            The switch as written.
        """
        held = {"is_enabled": bool(is_enabled)}
        self.write(key, DEVICE_REMOTE_DESKTOP_MODULE, held)
        return held

    def agent_module_want(self, key: str, name: str) -> str:
        """The ``want`` the state sends for a module the agent carries.

        Args:
            key: The device key.
            name: ``terminal`` or ``remote_desktop``.

        Returns:
            ``running`` for the Terminal module and for a Remote desktop
            switched on, ``stopped`` for one switched off.
        """
        if name == DEVICE_REMOTE_DESKTOP_MODULE and not (
            self.remote_desktop(key)["is_enabled"]
        ):
            return CHANNEL_MODULE_STATE_STOPPED
        return CHANNEL_MODULE_STATE_RUNNING

    def is_ai_tools_enabled(self, key: str) -> bool:
        """Whether one device's AI tools setting is on."""
        return self.ai_tools(key)["is_enabled"]

    def agent_config(
        self,
        key: str,
        name: str,
        stored: dict,
        platform: dict,
        *,
        address: str = "",
        allowed_subnets: "list | tuple" = (),
    ) -> dict:
        """One module's configuration as the agent receives it.

        The one place a module's section is composed from its file: the
        state pushed and the configuration a panel's apply sends to be
        checked both come from here, so the check sees what the machine
        will be given.

        Args:
            key: The device key.
            name: The module.
            stored: What the module's file holds, or is about to hold.
            platform: The tuple the agent reported.
            address: Where the device is, for the URLs it derives.
            allowed_subnets: The networks its shares answer.

        Returns:
            The configuration: Samba with the networks its shares answer,
            Gitea with its address and the secrets it signs with, Containers
            as :func:`podman_agent_config` composes it, and a program run as
            an account with its sealed fields and logins opened, as its row
            says.

        Raises:
            VaultLockedError: When a sealed token or login cannot be opened.
        """
        config = dict(stored)
        if name == "samba":
            config["allowed_subnets"] = list(allowed_subnets)
        elif name == "gitea":
            config["address"] = address
            config["secrets"] = self.gitea_secrets(key)
        elif name == "podman":
            config = podman_agent_config(config, platform)
        elif name in account_program_names():
            config = instances_agent_config(module_row(name), config, platform)
        elif name == DEVICE_TERMINAL_MODULE:
            config = terminal_agent_config(config, platform)
        return config

    def compose(
        self,
        key: str,
        platform: dict,
        *,
        address: str = "",
        allowed_subnets: "list | tuple" = (),
        urls: "list | tuple" = (),
        is_hub_machine: bool = False,
        ai_models: "list | tuple" = (),
        retry_marks: "dict | None" = None,
    ) -> tuple:
        """One device's whole desired state and its hash.

        Every module ``modules.json`` names and has not settled is sent with
        its ``want``; one it does not name, and one the machine has already
        settled, is left out, so the agent leaves it as it is. The two
        modules the agent carries, ``terminal`` and ``remote_desktop``, are
        always sent, composed from their own files with no recipe.

        Args:
            key: The device key.
            platform: The tuple the agent reported.
            address: Where the device is, for the URLs it derives.
            allowed_subnets: The networks its shares answer.
            urls: Every address the hub answers the channel on.
            is_hub_machine: Whether the device is the hub's own machine,
                whose AI tools reach the gateway itself rather than its
                agent's forward.
            ai_models: The names the gateway serves now; none sends the AI
                tools setting as off.
            retry_marks: Module name, or ``ai_tools``, to the mark the last
                press on it after a failure left; each goes into its entry
                as ``retry_mark``, the AI tools' only while they are on.

        Returns:
            ``(desired, hash)``, the document being
            ``{modules, desktop, urls, ai_tools}``.
        """
        resolved = resolved_modules(platform)
        marks = dict(retry_marks or {})
        modules = {}
        for name, entry in self.modules(key).items():
            if entry["is_settled"]:
                continue
            config = self.agent_config(
                key,
                name,
                self.read(key, name),
                platform,
                address=address,
                allowed_subnets=allowed_subnets,
            )
            modules[name] = {
                "want": entry["want"],
                "config": config,
                **_recipes(resolved.get(name) or {}),
            }
            if marks.get(name):
                modules[name][DEVICE_RETRY_MARK_KEY] = marks[name]
        modules[DEVICE_TERMINAL_MODULE] = {
            "want": self.agent_module_want(key, DEVICE_TERMINAL_MODULE),
            "config": self.agent_config(
                key,
                DEVICE_TERMINAL_MODULE,
                self.read(key, DEVICE_TERMINAL_MODULE),
                platform,
            ),
        }
        modules[DEVICE_REMOTE_DESKTOP_MODULE] = {
            "want": self.agent_module_want(key, DEVICE_REMOTE_DESKTOP_MODULE),
            "config": self.remote_desktop(key),
        }
        for name in DEVICE_AGENT_MODULES:
            if marks.get(name):
                modules[name][DEVICE_RETRY_MARK_KEY] = marks[name]
        desired = {
            "modules": modules,
            "desktop": {"seat_password": self.seat_password(key)},
            "urls": [str(url) for url in urls],
            "ai_tools": ai_tools_agent_config(
                self.ai_tools(key),
                [entry[:2] for entry in self.ai_tool_accounts(key)],
                platform,
                device_gateway(key, is_hub_machine=is_hub_machine),
                list(ai_models),
                str(
                    load_tool_manifests()
                    .get(DEVICE_AI_SWITCHER_NAME, {})
                    .get("version", "")
                    or ""
                ),
                is_forwarded=not is_hub_machine,
            ),
        }
        if marks.get(DEVICE_AI_TOOLS_NAME):
            desired["ai_tools"][DEVICE_RETRY_MARK_KEY] = marks[DEVICE_AI_TOOLS_NAME]
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
        ``{"install", "uninstall"}``, the branch's own blocks, the
        components of an entry that lists them reduced to their name,
        package kind, directory and digest; both empty where the manifest
        offers the platform nothing.
    """
    entry = resolved.get("entry")
    if not isinstance(entry, dict):
        return {"install": {}, "uninstall": {}}
    install = {
        name: value
        for name, value in entry.items()
        if name not in ("uninstall", "components")
    }
    install["kind"] = str(resolved.get("kind", "") or "")
    if "components" in resolved:
        install["components"] = [
            dict(component) for component in resolved["components"]
        ]
    return {"install": install, "uninstall": dict(entry.get("uninstall") or {})}


def _fresh_token(secret: str, now: "float | None") -> str:
    """A token minted from an instance's secret, its expiry 60 seconds ahead."""
    moment = time.time() if now is None else now
    return forwarder_token(
        secret,
        expiry=int(moment) + DEVICE_FORWARDER_TOKEN_LIFETIME_S,
        nonce=secrets.token_bytes(DEVICE_FORWARDER_TOKEN_NONCE_BYTES),
    )


def _unsealed_text(sealed, aad: bytes) -> str:
    """A sealed string opened, empty when there is none or it does not open."""
    if not isinstance(sealed, dict) or not sealed:
        return ""
    try:
        return unseal_bytes(sealed, aad).decode()
    except ValueError:
        return ""


def _login_password(login_id: str) -> str:
    """A vault login's password, empty when it is gone or the vault is locked."""
    try:
        return str(SecretVault().open(login_id).get("password", "") or "")
    except (VaultLockedError, ValueError):
        return ""


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
