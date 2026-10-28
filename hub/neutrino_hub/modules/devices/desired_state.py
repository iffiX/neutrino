"""One desired state per device: what the hub wants a machine to host.

``config/devices/<id>/`` holds ``modules.json``, each module's ``want``, the
version the machine chose and whether the machine has settled the want, one
file per module with its configuration, ``accounts.json`` with the machine's
available accounts, and ``rdp.json``, which seals the machine's seat
password; ``<id>`` is the device's id. Composing a device's state gathers
those with the install recipe resolved for its platform and the parts the
hub knows about the machine, the address it sits at and the networks its
shares answer, under one hash the agent compares against. The document is
the ``state`` frame's sections: ``modules``, one entry ``{want, config,
install}`` per module ``modules.json`` names and has not settled, and one
for each of the three modules the agent carries, ``desktop`` with the seat
password, ``urls``, ``ai_tools``, the available accounts whose switch is on
with where their tools reach the gateway and the device's key, and
``source_sets``.

A module of the account layer runs one instance per enabled account: its
file holds the enabled accounts with the secrets the hub generated for each,
and the state carries them opened beside what each account's row says
(protocol.md, "The account layer in the state").

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
from neutrino_hub.modules.clients.ai_keys import device_gateway, gateway_port
from neutrino_hub.modules.devices.ai_tools import resolved_tool_configs
from neutrino_hub.modules.devices.catalog import resolved_modules
from neutrino_hub.modules.devices.manifests import (
    entry_artifacts,
    load_tool_manifests,
    resolve_platform_entry,
)
from neutrino_hub.modules.devices.constants import (
    DEVICE_SAMBA_SHARES_KEY,
    DEVICE_ACCOUNTS_NAME,
    DEVICE_AI_SWITCHER_NAME,
    DEVICE_AGENT_MODULES,
    DEVICE_AI_TOOLS_NAME,
    DEVICE_DISABLED_ACCOUNTS_KEY,
    DEVICE_ENABLED_ACCOUNTS_KEY,
    DEVICE_PASSWORD_OS,
    DEVICE_REMOTE_DESKTOP_MODULE,
    DEVICE_SAMBA_MODULE,
    DEVICE_SAMBA_USER_CHARS_MAX,
    DEVICE_SAMBA_USER_PREFIX,
    DEVICE_SAMBA_USER_CUT_OS,
    DEVICE_SSH_SERVER_MODULE,
    DEVICE_TERMINAL_MODULE,
    DEVICE_RETRY_MARK_KEY,
    DEVICE_FORWARDER_TOKEN_EXPIRY_BYTES,
    DEVICE_FORWARDER_TOKEN_LIFETIME_S,
    DEVICE_FORWARDER_TOKEN_NONCE_BYTES,
    DEVICE_CONFIG_DIR_NAME,
    DEVICE_GITEA_MODULE,
    DEVICE_GITEA_SECRET_NAMES,
    DEVICE_GITEA_SECRETS_FILE,
    DEVICE_HERMES_WEBUI_MODULE,
    DEVICE_INSTANCE_LOGIN_KEY,
    DEVICE_MODULES_FILE,
    DEVICE_PACKAGES_DIR_NAME,
    DEVICE_HUB_CONTAINERS_KEY,
    DEVICE_PODMAN_MACHINE_KEY,
    DEVICE_PODMAN_MACHINE_OS,
    DEVICE_PODMAN_MODULE,
    DEVICE_SOURCE_SETS_KEY,
    DEVICE_RDP_FILE,
    DEVICE_RDP_SEAT_PASSWORD_AAD,
    DEVICE_RDP_SEAT_PASSWORD_CHARS,
)
from neutrino_hub.modules.devices import hermes_webui
from neutrino_hub.modules.devices.accounts import DeviceAccount
from neutrino_hub.modules.devices.hub_containers import compose_hub_containers
from neutrino_hub.modules.devices.module_releases import ModuleReleaseStore
from neutrino_hub.modules.devices.source_sets import state_source_sets
from neutrino_hub.modules.devices.ssh_account_keys import (
    generate_private_key,
    public_key_of,
)
from neutrino_hub.modules.devices.module_table import (
    SEALED_KIND_SSH_KEY,
    DeviceModuleRow,
    account_layer_rows,
    gateway_module_names,
    module_row,
)
from neutrino_hub.modules.services.apps import (
    app_slugs,
    cookie_name,
    entry_id,
    local_name,
    slug,
)
from neutrino_hub.modules.services.constants import (
    SERVICES_ENTRY_SSH,
    SERVICES_ENTRY_WEB,
    SERVICES_GITEA_ID,
    SERVICES_GITEA_TITLE,
    SERVICES_HERMES_WEBUI_ID,
    SERVICES_HERMES_WEBUI_TITLE,
    SERVICES_MACHINE_SLUG_FALLBACK,
    SERVICES_SSH_SERVER_ID,
    SERVICES_SSH_SERVER_TITLE,
)
from neutrino_hub.modules.services.apps import local_port
from neutrino_hub.utils.constants import UTILS_CONFIG_DIR
from neutrino_hub.utils.json_file import (
    CONFIG_WRITE_LOCK,
    read_config,
    write_config,
)

DEVICES_DIR_NAME = DEVICE_CONFIG_DIR_NAME


def state_hash(desired: dict) -> str:
    """The hash both sides compare a desired state by.

    Args:
        desired: The composed state.

    Returns:
        The SHA-256 of its canonical JSON form.
    """
    serialized = json.dumps(desired, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def smb_user(account: str, platform: dict) -> str:
    """The SMB user of one enabled account of the file share.

    Args:
        account: The account.
        platform: The tuple the agent reported.

    Returns:
        ``neutrino-<account>``, cut to 20 characters on Windows.
    """
    user = f"{DEVICE_SAMBA_USER_PREFIX}{account}"
    if platform.get("os") in DEVICE_SAMBA_USER_CUT_OS:
        return user[:DEVICE_SAMBA_USER_CHARS_MAX]
    return user


def instance_app_id(module: str, device_id: str, account: str) -> str:
    """The id of the app one instance of an account-layer module is."""
    return f"{module}_{device_id}_{account}"


def machine_apps(store: "DesiredStateStore", key: str) -> dict:
    """Every app the hub composes for one machine, by id, with its title.

    The set the local names are told apart in: each enabled account's
    instance of a program run as an account, Gitea, the SSH server, Hermes
    WebUI and the containers the Containers module declares.

    Args:
        store: The per-device store.
        key: The device.

    Returns:
        App id to its title.
    """
    titles = {
        f"{SERVICES_GITEA_ID}_{key}": SERVICES_GITEA_TITLE,
        f"{SERVICES_SSH_SERVER_ID}_{key}": SERVICES_SSH_SERVER_TITLE,
        f"{SERVICES_HERMES_WEBUI_ID}_{key}": SERVICES_HERMES_WEBUI_TITLE,
    }
    for row in account_layer_rows():
        if not row.entry_title or "{account}" not in row.entry_title:
            continue
        for account in store.enabled_accounts(key, row.name):
            titles[instance_app_id(row.name, key, account)] = row.entry_title.format(
                account=account
            )
    for container in store.read(key, DEVICE_PODMAN_MODULE).get("containers") or []:
        if isinstance(container, dict) and container.get("name"):
            name = str(container["name"])
            titles[f"{DEVICE_PODMAN_MODULE}_{key}_{name}"] = name
    return titles


def account_layer_agent_config(
    row: DeviceModuleRow,
    stored: dict,
    available: list,
    platform: dict,
    *,
    device_id: str = "",
    account_details: "dict | None" = None,
    machine_slug: str = SERVICES_MACHINE_SLUG_FALLBACK,
    app_slug_of: "dict | None" = None,
) -> dict:
    """What the agent is sent for one account-layer module.

    Args:
        row: The module's row in the description table.
        stored: The module's file: the enabled accounts, each with the
            fields the row seals.
        available: The machine's available accounts, :class:`DeviceAccount`
            each; an enabled account that is not among them is left out.
        platform: The tuple the agent reported; only a Windows machine is
            sent a password.
        device_id: The device, for the ids of the instances' apps.
        account_details: Account to ``{home, shell}`` as the machine last
            reported, which fills an empty share path.
        machine_slug: The slug of the machine's name, for the local names.
        app_slug_of: App id to its slug, as :func:`machine_apps` and
            :func:`app_slugs` give them; None slugs each title alone.

    Returns:
        The Terminal module's ``{accounts: [{account, shell_path,
        password}]}``; the file share's ``{shares, users, passwords}``; the
        others' ``{...config_head, instances: [{account, <opened fields>,
        password, local_name, cookie_name}]}``, the last two on a module
        with a forwarder and ``password`` on a Windows machine alone.
    """
    is_windows = platform.get("os") == DEVICE_PASSWORD_OS
    by_name = {account.account: account for account in available}
    details = account_details or {}
    enabled = [
        record
        for record in stored.get(DEVICE_ENABLED_ACCOUNTS_KEY) or []
        if isinstance(record, dict) and str(record.get("account", "") or "") in by_name
    ]
    if row.name == DEVICE_TERMINAL_MODULE:
        return {
            DEVICE_ENABLED_ACCOUNTS_KEY: [
                _with_password(
                    {
                        "account": record["account"],
                        "shell_path": by_name[record["account"]].shell_path,
                    },
                    by_name[record["account"]],
                    is_windows,
                )
                for record in enabled
            ]
        }
    if row.name == DEVICE_SAMBA_MODULE:
        return _samba_config(row, enabled, by_name, platform, details, stored)
    config = dict(row.config_head)
    instances = []
    for record in enabled:
        account = str(record["account"])
        sent = {"account": account}
        for sealed in row.sealed_fields:
            opened = _unsealed_text(record.get(sealed.key), sealed.aad)
            if sealed.kind == SEALED_KIND_SSH_KEY:
                opened = _public_key(opened)
            sent[sealed.opened_key] = opened
        if row.name == DEVICE_SSH_SERVER_MODULE:
            sent["shell_path"] = by_name[account].shell_path
        if row.is_login_named:
            _with_password(sent, by_name[account], is_windows)
        if row.has_forwarder:
            app_id = instance_app_id(row.name, device_id, account)
            made = (app_slug_of or {}).get(app_id) or slug(
                row.entry_title.format(account=account)
            )
            sent["local_name"] = local_name(made, machine_slug)
            sent["cookie_name"] = cookie_name(entry_id(app_id, SERVICES_ENTRY_WEB))
        instances.append(sent)
    config["instances"] = instances
    return config


def _samba_config(
    row: DeviceModuleRow,
    enabled: list,
    by_name: dict,
    platform: dict,
    details: dict,
    stored: "dict | None" = None,
) -> dict:
    """The file share's section: one share and one user per enabled account,
    the share's files written as the account, then the shares the file names
    itself, each open to the enabled accounts' users it names, by the SMB
    user's name or by the account's. An enabled account with no share path
    whose home the machine has not reported is left out."""
    sealed = row.sealed_fields[0]
    shares = []
    users = []
    passwords = {}
    user_of_account = {}
    for record in enabled:
        account = str(record["account"])
        user = smb_user(account, platform)
        path = by_name[account].share_path or str(
            (details.get(account) or {}).get("home", "") or ""
        )
        if not path:
            continue
        shares.append(
            {
                "name": account,
                "path": path,
                "comment": "",
                "is_read_only": False,
                "valid_users": [user],
                "force_user": account,
            }
        )
        users.append(user)
        user_of_account[account] = user
        passwords[user] = _unsealed_text(record.get(sealed.key), sealed.aad)
    for share in (stored or {}).get(DEVICE_SAMBA_SHARES_KEY) or []:
        if not isinstance(share, dict) or not share.get("name"):
            continue
        valid_users = []
        for named in share.get("valid_users") or []:
            user = user_of_account.get(str(named), str(named))
            if user in users and user not in valid_users:
                valid_users.append(user)
        shares.append(
            {
                "name": str(share["name"]),
                "path": str(share.get("path", "") or ""),
                "comment": str(share.get("comment", "") or ""),
                "is_read_only": bool(share.get("is_read_only", False)),
                "valid_users": valid_users,
            }
        )
    return {"shares": shares, "users": users, "passwords": passwords}


def _with_password(sent: dict, account: DeviceAccount, is_windows: bool) -> dict:
    """Add the account's login password on a Windows machine."""
    if is_windows and account.login_id:
        sent["password"] = _login_password(account.login_id)
    return sent


def _public_key(private_key: str) -> str:
    """The authorized key line of a sealed private key, empty when it does not read."""
    if not private_key:
        return ""
    try:
        return public_key_of(private_key)
    except ValueError:
        return ""


def podman_agent_config(stored: dict, platform: dict, available: list) -> dict:
    """What the agent is sent for the Containers module.

    Args:
        stored: ``podman.json``: the containers, the mirrors and the Run
            settings, ``machine``, naming an available account.
        platform: The tuple the agent reported; only a Windows or macOS
            machine is sent ``machine``, and only a Windows one a password.
        available: The machine's available accounts, whose login a Windows
            machine's ``machine`` signs in with.

    Returns:
        The file's fields as stored, ``machine`` left out on Linux and on a
        machine that reported no system; on Windows and macOS ``machine``
        is ``{account, cpus, memory_gib, disk_gib}``, with the ``password``
        of the account's login on Windows.
    """
    config = {
        key: value for key, value in stored.items() if key != DEVICE_PODMAN_MACHINE_KEY
    }
    machine = stored.get(DEVICE_PODMAN_MACHINE_KEY)
    os_name = platform.get("os")
    if os_name not in DEVICE_PODMAN_MACHINE_OS or not isinstance(machine, dict):
        return config
    account = str(machine.get("account", "") or "")
    sent = {
        "account": account,
        "cpus": machine.get("cpus", 0),
        "memory_gib": machine.get("memory_gib", 0),
        "disk_gib": machine.get("disk_gib", 0),
    }
    row = next((held for held in available if held.account == account), None)
    if os_name == DEVICE_PASSWORD_OS and row is not None and row.login_id:
        sent["password"] = _login_password(row.login_id)
    config[DEVICE_PODMAN_MACHINE_KEY] = sent
    return config


def ai_tools_agent_config(
    accounts: list,
    platform: dict,
    gateway: dict,
    models: list,
    switcher_version: str = "",
    *,
    switcher_artifact: "dict | None" = None,
    is_hub_machine: bool = False,
    is_gateway_module: bool = False,
    listen_port: int = 0,
) -> dict:
    """What the agent is sent for the machine's AI tools.

    Args:
        accounts: The available accounts whose switch is on,
            :class:`DeviceAccount` each.
        platform: The tuple the agent reported; only a Windows machine is
            sent a password.
        gateway: ``{gateway_url, gateway_key}``: where the device's tools
            reach the gateway, and the device's own key.
        models: The names the gateway serves now.
        switcher_version: The cc-switch version the hub's manifest pins.
        switcher_artifact: Its artifact for the machine's platform, ``{name,
            kind, digest}``; None where the manifest names none.
        is_hub_machine: Whether the device is the hub's own machine, whose
            agent opens no forward.
        is_gateway_module: Whether a container module that uses the gateway
            is installed on the device.
        listen_port: The gateway's own port, which the hub's own machine
            relays to its containers while such a module is installed there.

    Returns:
        ``{is_enabled: false, is_forwarded, gateway_port,
        cc_switch_version, cc_switch_artifact}`` while no account's switch
        is on, the gateway serves no model, or the device has no key for
        it, the version and the artifact each left out when none is given;
        else ``{is_enabled, is_forwarded, gateway_port, base_url, api_key,
        accounts: [{account, password, tool_configs}], cc_switch_version,
        cc_switch_artifact}``, every Claude slot filled with the first
        served model where none was chosen and ``password`` sent to a
        Windows machine alone.
    """
    base_url = str(gateway.get("gateway_url", "") or "")
    api_key = str(gateway.get("gateway_key", "") or "")
    is_on = bool(accounts and models and base_url and api_key)
    forward = {
        "is_forwarded": not is_hub_machine and (is_on or is_gateway_module),
        "gateway_port": listen_port if is_hub_machine and is_gateway_module else 0,
    }
    if not is_on:
        off = {"is_enabled": False, **forward}
        if switcher_version:
            off["cc_switch_version"] = switcher_version
        if switcher_artifact:
            off["cc_switch_artifact"] = dict(switcher_artifact)
        return off
    is_windows = platform.get("os") == DEVICE_PASSWORD_OS
    sent_accounts = []
    for account in accounts:
        sent = _with_password({"account": account.account}, account, is_windows)
        sent["tool_configs"] = resolved_tool_configs(
            account.tool_configs, str(models[0])
        )
        sent_accounts.append(sent)
    section = {
        "is_enabled": True,
        **forward,
        "base_url": base_url,
        "api_key": api_key,
        "accounts": sent_accounts,
        "cc_switch_version": switcher_version,
    }
    if switcher_artifact:
        section["cc_switch_artifact"] = dict(switcher_artifact)
    return section


def switcher_artifact(manifest: dict, platform: dict) -> "dict | None":
    """The cc-switch artifact one machine's agent asks the package stream for.

    Args:
        manifest: ``cc_switch.json``, empty when the hub holds none.
        platform: The tuple the agent reported.

    Returns:
        ``{name, kind, digest}`` of the entry's one artifact, or None where
        the manifest names no entry for the platform.
    """
    _, entry = resolve_platform_entry(manifest, platform)
    for artifact in entry_artifacts(manifest, entry):
        return {key: artifact[key] for key in ("name", "kind", "digest")}
    return None


def forwarder_token(secret: str, *, expiry: int, nonce: bytes) -> str:
    """One token a forwarder in front of an instance takes once.

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
            Module name to ``{"want", "is_settled", "version"}``, for the
            modules ``modules.json`` names and no other; ``version`` is the
            machine's choice, empty while it follows the tested one.
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
                    "version": str(entry.get("version", "") or ""),
                }
        return modules

    def named_versions(self) -> dict:
        """Module to the versions some stored machine chose for it.

        Returns:
            Module name to the set of ``version`` values the devices'
            ``modules.json`` files name, empty strings left out.
        """
        versions: dict = {}
        root = UTILS_CONFIG_DIR / DEVICES_DIR_NAME
        if not root.is_dir():
            return versions
        for directory in sorted(root.iterdir()):
            if not directory.is_dir() or directory.name == DEVICE_PACKAGES_DIR_NAME:
                continue
            for name, entry in self.modules(directory.name).items():
                if entry.get("version"):
                    versions.setdefault(name, set()).add(entry["version"])
        return versions

    def named_modules(self) -> set:
        """Every module some device's ``modules.json`` still names.

        Returns:
            The module names some device names with a ``want`` other than a
            settled ``absent``.
        """
        root = UTILS_CONFIG_DIR / DEVICES_DIR_NAME
        named: set = set()
        if not root.is_dir():
            return named
        for path in sorted(root.iterdir()):
            if not path.is_dir() or path.name == DEVICE_PACKAGES_DIR_NAME:
                continue
            for name, entry in self.modules(path.name).items():
                if not entry["is_settled"]:
                    named.add(name)
        return named

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
            held = modules.get(module) or {}
            modules[module] = {
                "want": want,
                "is_settled": False,
                "version": held.get("version", ""),
            }
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

    def version_of(self, key: str, module: str) -> str:
        """The version one device chose for one module.

        Args:
            key: The device key.
            module: The module name.

        Returns:
            The chosen version, empty while the machine follows the tested
            one or the file does not name the module.
        """
        return self.modules(key).get(module, {}).get("version", "")

    def set_version(self, key: str, module: str, version: str) -> None:
        """Write the version one device is to run one module at.

        Args:
            key: The device key.
            module: The module name.
            version: The version; empty follows the tested one.
        """
        with CONFIG_WRITE_LOCK:
            modules = self.modules(key)
            held = modules.get(module) or {
                "want": CHANNEL_MODULE_STATE_RUNNING,
                "is_settled": False,
            }
            modules[module] = {
                "want": held["want"],
                "is_settled": held.get("is_settled", False),
                "version": str(version or ""),
            }
            write_config(self._path(key, DEVICE_MODULES_FILE), {"modules": modules})

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
            modules[module] = {**entry, "is_settled": True}
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

    def available_accounts(self, key: str) -> list:
        """One device's available accounts, in the order they were added.

        Args:
            key: The device key.

        Returns:
            The :class:`DeviceAccount` rows of ``accounts.json``.
        """
        rows = self.read(key, DEVICE_ACCOUNTS_NAME).get(DEVICE_ENABLED_ACCOUNTS_KEY)
        return [
            DeviceAccount.from_dict(row)
            for row in (rows if isinstance(rows, list) else [])
            if isinstance(row, dict) and row.get("account")
        ]

    def enabled_accounts(self, key: str, module: str) -> list:
        """The accounts one account-layer module enables on one device.

        Args:
            key: The device key.
            module: The module.

        Returns:
            The account names in the order they were enabled, available
            ones alone.
        """
        available = {account.account for account in self.available_accounts(key)}
        return [
            str(record["account"])
            for record in self.read(key, module).get(DEVICE_ENABLED_ACCOUNTS_KEY) or []
            if isinstance(record, dict) and str(record.get("account", "") or "")
            if str(record["account"]) in available
        ]

    def set_enabled_accounts(self, key: str, module: str, accounts: list) -> dict:
        """Replace the accounts one account-layer module enables on one device.

        A newly enabled account gets each field the row seals, made once; an
        account disabled keeps its record under ``disabled``, so enabling it
        again gives it the same secrets.

        Args:
            key: The device key.
            module: The module.
            accounts: The enabled accounts' names, in the order checked.

        Returns:
            The module's file as written.

        Raises:
            KeyError: For a module the table does not hold.
            VaultLockedError: If a secret has to be made and the vault is
                locked.
            OSError: When the file cannot be written.
        """
        row = module_row(module)
        with CONFIG_WRITE_LOCK:
            held = self.read(key, module)
            kept = {
                str(record["account"]): dict(record)
                for name in (DEVICE_ENABLED_ACCOUNTS_KEY, DEVICE_DISABLED_ACCOUNTS_KEY)
                for record in held.get(name) or []
                if isinstance(record, dict) and record.get("account")
            }
            enabled = []
            for account in accounts:
                record = kept.pop(account, None) or {"account": account}
                for sealed in row.sealed_fields:
                    if not (
                        isinstance(record.get(sealed.key), dict) and record[sealed.key]
                    ):
                        record[sealed.key] = _fresh_seal(sealed)
                enabled.append(record)
            written = {
                name: value
                for name, value in held.items()
                if name
                not in (DEVICE_ENABLED_ACCOUNTS_KEY, DEVICE_DISABLED_ACCOUNTS_KEY)
            }
            written[DEVICE_ENABLED_ACCOUNTS_KEY] = enabled
            disabled = [record for record in kept.values() if row.sealed_fields]
            if disabled:
                written[DEVICE_DISABLED_ACCOUNTS_KEY] = disabled
            write_config(self._path(key, row.config_file), written)
        return written

    def forget_account(self, key: str, account: str) -> list:
        """Take one account out of every account-layer module on one device.

        Args:
            key: The device key.
            account: The account removed from the available accounts.

        Returns:
            The modules that enabled it.

        Raises:
            OSError: When a file cannot be written.
        """
        was_enabled = []
        with CONFIG_WRITE_LOCK:
            for row in account_layer_rows():
                held = self.read(key, row.name)
                if not held:
                    continue
                enabled = [
                    record
                    for record in held.get(DEVICE_ENABLED_ACCOUNTS_KEY) or []
                    if isinstance(record, dict) and record.get("account")
                ]
                disabled = [
                    record
                    for record in held.get(DEVICE_DISABLED_ACCOUNTS_KEY) or []
                    if isinstance(record, dict) and record.get("account")
                ]
                if not any(
                    record["account"] == account for record in enabled + disabled
                ):
                    continue
                if any(record["account"] == account for record in enabled):
                    was_enabled.append(row.name)
                written = {
                    name: value
                    for name, value in held.items()
                    if name
                    not in (DEVICE_ENABLED_ACCOUNTS_KEY, DEVICE_DISABLED_ACCOUNTS_KEY)
                }
                written[DEVICE_ENABLED_ACCOUNTS_KEY] = [
                    record for record in enabled if record["account"] != account
                ]
                left = [record for record in disabled if record["account"] != account]
                if left:
                    written[DEVICE_DISABLED_ACCOUNTS_KEY] = left
                write_config(self._path(key, row.config_file), written)
        return was_enabled

    def account_secret(self, key: str, module: str, account: str, field: str) -> str:
        """One enabled account's sealed field, opened.

        Args:
            key: The device key.
            module: The account-layer module.
            account: The account.
            field: The key the seal is stored under, one the module's row
                names.

        Returns:
            The opened value; empty when the module does not enable the
            account, when the vault is locked, or when the seal does not
            open under this box's data key.

        Raises:
            KeyError: For a module the table does not hold, or a field its
                row does not seal.
        """
        sealed = module_row(module).sealed_field(field)
        for record in self.read(key, module).get(DEVICE_ENABLED_ACCOUNTS_KEY) or []:
            if isinstance(record, dict) and record.get("account") == account:
                return _unsealed_text(record.get(sealed.key), sealed.aad)
        return ""

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
            opened value of the row's token field. Empty when the module
            does not enable the account, when the vault is locked, or when
            the seal does not open under this box's data key.

        Raises:
            KeyError: For a module the table does not hold, or one that
                hands no token.
        """
        row = module_row(module)
        opened = self.account_secret(key, module, account, row.token_field)
        if not opened or not row.is_token_minted:
            return opened
        return _fresh_token(opened, now)

    def module_token(self, key: str, module: str, *, now: "float | None" = None) -> str:
        """A fresh token a client opens a container module's page with.

        Args:
            key: The device key.
            module: The container module, whose row names the sealed field
                its file holds the token secret under.
            now: Seconds since the epoch; None is the clock.

        Returns:
            A token minted from the module's secret, its expiry 60 seconds
            ahead; empty when the file holds no secret, when the vault is
            locked, or when the seal does not open under this box's data
            key.

        Raises:
            KeyError: For a module the table does not hold, or one that
                hands no token.
        """
        row = module_row(module)
        sealed = row.sealed_field(row.token_field)
        opened = _unsealed_text(self.read(key, module).get(sealed.key), sealed.aad)
        return _fresh_token(opened, now) if opened else ""

    def ai_tool_accounts(self, key: str) -> list:
        """The available accounts whose AI tools use the gateway.

        Args:
            key: The device key.

        Returns:
            The :class:`DeviceAccount` rows whose switch is on, in the
            file's order.
        """
        return [
            account
            for account in self.available_accounts(key)
            if account.is_ai_tools_enabled
        ]

    def is_ai_tools_enabled(self, key: str) -> bool:
        """Whether any available account of one device has its AI tools switch on."""
        return bool(self.ai_tool_accounts(key))

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
            name: ``terminal``, ``remote_desktop`` or ``ssh_server``.

        Returns:
            ``running`` for the Terminal module, for a Remote desktop
            switched on and for an SSH server with an enabled account;
            ``stopped`` for the other two otherwise.
        """
        if name == DEVICE_REMOTE_DESKTOP_MODULE and not (
            self.remote_desktop(key)["is_enabled"]
        ):
            return CHANNEL_MODULE_STATE_STOPPED
        if name == DEVICE_SSH_SERVER_MODULE and not self.enabled_accounts(key, name):
            return CHANNEL_MODULE_STATE_STOPPED
        return CHANNEL_MODULE_STATE_RUNNING

    def has_gateway_module(self, key: str) -> bool:
        """Whether a container module that uses the AI gateway is installed on one device.

        Args:
            key: The device key.

        Returns:
            True while ``modules.json`` names such a module with a ``want``
            other than ``absent``.
        """
        modules = self.modules(key)
        return any(
            modules[name]["want"] != CHANNEL_MODULE_STATE_ABSENT
            for name in gateway_module_names()
            if name in modules
        )

    def agent_config(
        self,
        key: str,
        name: str,
        stored: dict,
        platform: dict,
        *,
        address: str = "",
        is_hub_machine: bool = False,
        account_details: "dict | None" = None,
        machine_slug: str = SERVICES_MACHINE_SLUG_FALLBACK,
        app_slug_of: "dict | None" = None,
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
            is_hub_machine: Whether the device is the hub's own machine, which
                a container module's composition may read.
            account_details: Account to ``{home, shell}`` as the machine last
                reported.
            machine_slug: The slug of the machine's name, for local names.
            app_slug_of: App id to its slug for this machine; None slugs each
                title alone.

        Returns:
            The configuration: an account-layer module as
            :func:`account_layer_agent_config` composes it, the file share
            with the networks its shares answer, Gitea with its address, the
            secrets it signs with and its SSH entry's local port, Containers
            as :func:`podman_agent_config` composes it with the hub
            containers of the machine's container modules, and Hermes WebUI
            with its secrets opened and its names.

        Raises:
            VaultLockedError: When a sealed token or login cannot be opened.
        """
        config = dict(stored)
        available = self.available_accounts(key)
        if name in [row.name for row in account_layer_rows()]:
            config = account_layer_agent_config(
                module_row(name),
                config,
                available,
                platform,
                device_id=key,
                account_details=account_details,
                machine_slug=machine_slug,
                app_slug_of=app_slug_of,
            )
        elif name == DEVICE_GITEA_MODULE:
            config["address"] = address
            config["secrets"] = self.gitea_secrets(key)
            config["ssh_port"] = local_port(
                entry_id(f"{SERVICES_GITEA_ID}_{key}", SERVICES_ENTRY_SSH)
            )
        elif name == DEVICE_PODMAN_MODULE:
            config = podman_agent_config(config, platform, available)
            config[DEVICE_HUB_CONTAINERS_KEY] = compose_hub_containers(
                self, key, platform, is_hub_machine=is_hub_machine
            )
        elif name == DEVICE_HERMES_WEBUI_MODULE:
            app_id = f"{SERVICES_HERMES_WEBUI_ID}_{key}"
            made = (app_slug_of or {}).get(app_id) or slug(SERVICES_HERMES_WEBUI_TITLE)
            config = hermes_webui.agent_config(
                config, key, local_name=local_name(made, machine_slug)
            )
        return config

    def compose(
        self,
        key: str,
        platform: dict,
        *,
        address: str = "",
        urls: "list | tuple" = (),
        is_hub_machine: bool = False,
        ai_models: "list | tuple" = (),
        retry_marks: "dict | None" = None,
        account_details: "dict | None" = None,
        machine_slug: str = SERVICES_MACHINE_SLUG_FALLBACK,
        releases: "ModuleReleaseStore | None" = None,
    ) -> tuple:
        """One device's whole desired state and its hash.

        Every module ``modules.json`` names and has not settled is sent with
        its ``want`` and the recipe of the version the machine chose; one it
        does not name, and one the machine has already settled, is left out,
        so the agent leaves it as it is. The three modules the agent
        carries, ``terminal``, ``remote_desktop`` and ``ssh_server``, are
        always sent, composed from their own files, with the ``agent``
        recipe their manifests name.

        Args:
            key: The device key.
            platform: The tuple the agent reported.
            address: Where the device is, for the URLs it derives.
            urls: Every address the hub answers the channel on.
            is_hub_machine: Whether the device is the hub's own machine,
                whose AI tools reach the gateway itself rather than its
                agent's forward.
            ai_models: The names the gateway serves now; none sends the AI
                tools setting as off.
            retry_marks: Module name, or ``ai_tools``, to the mark the last
                press on it after a failure left; each goes into its entry
                as ``retry_mark``, the AI tools' only while they are on.
            account_details: Account to ``{home, shell}`` as the machine last
                reported.
            machine_slug: The slug of the machine's name, for local names.
            releases: The publishers' feeds as last read; None sends every
                module its tested recipe.

        Returns:
            ``(desired, hash)``, the document being
            ``{modules, desktop, urls, ai_tools, source_sets}``,
            ``source_sets`` holding each set the modules' recipes name.
        """
        resolved = resolved_modules(platform)
        marks = dict(retry_marks or {})
        slugs = app_slugs(machine_apps(self, key))
        shared = {
            "address": address,
            "is_hub_machine": is_hub_machine,
            "account_details": account_details,
            "machine_slug": machine_slug,
            "app_slug_of": slugs,
        }
        modules = {}
        for name, entry in self.modules(key).items():
            if entry["is_settled"] or name in DEVICE_AGENT_MODULES:
                continue
            recipe = dict((resolved.get(name) or {}).get("recipe") or {})
            if entry["version"] and releases is not None and recipe:
                chosen = releases.recipe(name, platform, entry["version"])
                recipe = chosen if chosen else recipe
            modules[name] = {
                "want": entry["want"],
                "config": self.agent_config(
                    key, name, self.read(key, name), platform, **shared
                ),
                "install": recipe,
            }
            if marks.get(name):
                modules[name][DEVICE_RETRY_MARK_KEY] = marks[name]
        for name in DEVICE_AGENT_MODULES:
            modules[name] = {
                "want": self.agent_module_want(key, name),
                "config": (
                    self.remote_desktop(key)
                    if name == DEVICE_REMOTE_DESKTOP_MODULE
                    else self.agent_config(
                        key, name, self.read(key, name), platform, **shared
                    )
                ),
            }
            recipe = (resolved.get(name) or {}).get("recipe")
            if recipe:
                modules[name]["install"] = dict(recipe)
            if marks.get(name):
                modules[name][DEVICE_RETRY_MARK_KEY] = marks[name]
        switcher = load_tool_manifests().get(DEVICE_AI_SWITCHER_NAME, {})
        is_gateway_module = self.has_gateway_module(key)
        desired = {
            "modules": modules,
            "desktop": {"seat_password": self.seat_password(key)},
            "urls": [str(url) for url in urls],
            "ai_tools": ai_tools_agent_config(
                self.ai_tool_accounts(key),
                platform,
                device_gateway(key, is_hub_machine=is_hub_machine),
                list(ai_models),
                str(switcher.get("version", "") or ""),
                switcher_artifact=switcher_artifact(switcher, platform),
                is_hub_machine=is_hub_machine,
                is_gateway_module=is_gateway_module,
                listen_port=(
                    gateway_port() if is_hub_machine and is_gateway_module else 0
                ),
            ),
        }
        if marks.get(DEVICE_AI_TOOLS_NAME):
            desired["ai_tools"][DEVICE_RETRY_MARK_KEY] = marks[DEVICE_AI_TOOLS_NAME]
        desired[DEVICE_SOURCE_SETS_KEY] = state_source_sets(modules)
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

    def directory_of(self, key: str):
        """One device's directory under ``config/``, whether or not it exists."""
        return self._directory(key)

    def _directory(self, key: str):
        return UTILS_CONFIG_DIR / DEVICES_DIR_NAME / key

    def _path(self, key: str, name: str) -> str:
        return f"{DEVICES_DIR_NAME}/{key}/{name}"


def _fresh_seal(sealed) -> dict:
    """A fresh value for one sealed field, sealed under the vault's data key.

    Raises:
        VaultLockedError: If there is no data key to seal it under.
    """
    if sealed.kind == SEALED_KIND_SSH_KEY:
        value = generate_private_key()
    else:
        value = secrets.token_urlsafe(sealed.secret_bytes)
    return seal_bytes(value.encode(), sealed.aad)


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
