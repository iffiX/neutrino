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
the machine's AI tools setting from ``ai_tools.json`` with the gateway's
address and the device's key, for the accounts the VS Code, CloudCLI and
code-server instances name.

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
    CHANNEL_MODULE_WANTS,
)
from neutrino_hub.modules.clients.ai_keys import device_gateway
from neutrino_hub.modules.devices.ai_tools import (
    clean_tool_configs,
    resolved_tool_configs,
)
from neutrino_hub.modules.devices.catalog import resolved_modules
from neutrino_hub.modules.devices.manifests import load_module_manifests
from neutrino_hub.modules.devices.constants import (
    DEVICE_AI_TOOL_MODULES,
    DEVICE_AI_TOOLS_NAME,
    DEVICE_RETRY_MARK_KEY,
    DEVICE_CLOUDCLI_LOGIN_KEY,
    DEVICE_CLOUDCLI_MODULE,
    DEVICE_CLOUDCLI_NPM_REGISTRIES,
    DEVICE_CLOUDCLI_PASSWORD_AAD,
    DEVICE_CLOUDCLI_PASSWORD_KEY,
    DEVICE_CLOUDCLI_SECRET_AAD,
    DEVICE_CLOUDCLI_SECRET_BYTES,
    DEVICE_CLOUDCLI_SECRET_KEY,
    DEVICE_CODE_SERVER_MODULE,
    DEVICE_CODE_SERVER_SECRET_AAD,
    DEVICE_CODE_SERVER_SECRET_BYTES,
    DEVICE_CODE_SERVER_SECRET_KEY,
    DEVICE_FORWARDER_TOKEN_EXPIRY_BYTES,
    DEVICE_FORWARDER_TOKEN_LIFETIME_S,
    DEVICE_FORWARDER_TOKEN_NONCE_BYTES,
    DEVICE_GITEA_SECRET_NAMES,
    DEVICE_GITEA_SECRETS_FILE,
    DEVICE_MODULES_FILE,
    DEVICE_PACKAGES_DIR_NAME,
    DEVICE_RDP_FILE,
    DEVICE_RDP_SEAT_PASSWORD_AAD,
    DEVICE_RDP_SEAT_PASSWORD_CHARS,
    DEVICE_VSCODE_LOGIN_KEY,
    DEVICE_VSCODE_MODULE,
    DEVICE_VSCODE_TOKEN_AAD,
    DEVICE_VSCODE_TOKEN_KEY,
)
from neutrino_hub.utils.constants import UTILS_CONFIG_DIR
from neutrino_hub.utils.json_file import (
    CONFIG_WRITE_LOCK,
    read_config,
    write_config,
)

DEVICES_DIR_NAME = "devices"
# How many random bytes a VS Code connection token is made of.
VSCODE_TOKEN_BYTES = 24
# The system whose instances start as their account only with its password.
VSCODE_PASSWORD_OS = "windows"


def state_hash(desired: dict) -> str:
    """The hash both sides compare a desired state by.

    Args:
        desired: The composed state.

    Returns:
        The SHA-256 of its canonical JSON form.
    """
    serialized = json.dumps(desired, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def vscode_agent_config(stored: dict, platform: dict) -> dict:
    """What the agent is sent for VS Code.

    Args:
        stored: The module's file: the instances, each with its sealed token
            and the login it runs as.
        platform: The tuple the agent reported; only a Windows machine is
            sent a password.

    Returns:
        ``{address, instances: [{account, port, token, password}]}``, the
        address empty so the instances listen on every address, the token
        opened and the password taken from the instance's login.
    """
    is_windows = platform.get("os") == VSCODE_PASSWORD_OS
    instances = []
    for instance in stored.get("instances") or []:
        if not isinstance(instance, dict):
            continue
        sent = {
            "account": str(instance.get("account", "") or ""),
            "port": instance.get("port", 0),
            "token": _unsealed_text(
                instance.get(DEVICE_VSCODE_TOKEN_KEY), DEVICE_VSCODE_TOKEN_AAD
            ),
        }
        login_id = str(instance.get(DEVICE_VSCODE_LOGIN_KEY, "") or "")
        if is_windows and login_id:
            sent["password"] = _login_password(login_id)
        instances.append(sent)
    return {"address": "", "instances": instances}


def cloudcli_agent_config(
    stored: dict, platform: dict, *, edition: str = EDITION
) -> dict:
    """What the agent is sent for CloudCLI.

    Args:
        stored: The module's file: the instances, each with its two sealed
            secrets and the login it runs as.
        platform: The tuple the agent reported; only a Windows machine is
            sent a password.
        edition: The hub's edition, whose npm registry the agent installs
            CloudCLI from.

    Returns:
        ``{npm_registry, npm_environment, instances: [{account, port,
        web_password, token_secret, password}]}``,
        ``npm_environment`` being what the manifest names for the edition,
        both secrets opened and the password taken from the instance's
        login.
    """
    is_windows = platform.get("os") == VSCODE_PASSWORD_OS
    instances = []
    for instance in stored.get("instances") or []:
        if not isinstance(instance, dict):
            continue
        sent = {
            "account": str(instance.get("account", "") or ""),
            "port": instance.get("port", 0),
            "web_password": _unsealed_text(
                instance.get(DEVICE_CLOUDCLI_PASSWORD_KEY),
                DEVICE_CLOUDCLI_PASSWORD_AAD,
            ),
            "token_secret": _unsealed_text(
                instance.get(DEVICE_CLOUDCLI_SECRET_KEY), DEVICE_CLOUDCLI_SECRET_AAD
            ),
        }
        login_id = str(instance.get(DEVICE_CLOUDCLI_LOGIN_KEY, "") or "")
        if is_windows and login_id:
            sent["password"] = _login_password(login_id)
        instances.append(sent)
    return {
        "npm_registry": DEVICE_CLOUDCLI_NPM_REGISTRIES[edition],
        "npm_environment": dict(
            (load_module_manifests().get(DEVICE_CLOUDCLI_MODULE) or {})
            .get("npm_environment", {})
            .get(edition, {})
        ),
        "instances": instances,
    }


def ai_tools_agent_config(
    stored: dict, accounts: list, platform: dict, gateway: dict, models: list
) -> dict:
    """What the agent is sent for the machine's AI tools.

    Args:
        stored: The setting, as :meth:`DesiredStateStore.ai_tools` reads it.
        accounts: ``(account, login_id)`` of each account the setting acts
            on, as :meth:`DesiredStateStore.ai_tool_accounts` gives them.
        platform: The tuple the agent reported; only a Windows machine is
            sent a password.
        gateway: ``{gateway_url, gateway_key}``: the gateway as the device
            reaches it, and the device's own key.
        models: The names the gateway serves now.

    Returns:
        ``{is_enabled: false}`` while the setting is off, the gateway serves
        no model, or the device has no key or no address for it; else
        ``{is_enabled, base_url, api_key, tool_configs, accounts: [{account,
        password}]}``, every Claude slot filled with the first served model
        where none was chosen and ``password`` sent to a Windows machine
        alone.
    """
    base_url = str(gateway.get("gateway_url", "") or "")
    api_key = str(gateway.get("gateway_key", "") or "")
    if not stored.get("is_enabled") or not models or not base_url or not api_key:
        return {"is_enabled": False}
    is_windows = platform.get("os") == VSCODE_PASSWORD_OS
    sent_accounts = []
    for account, login_id in accounts:
        sent = {"account": account}
        if is_windows and login_id:
            sent["password"] = _login_password(login_id)
        sent_accounts.append(sent)
    return {
        "is_enabled": True,
        "base_url": base_url,
        "api_key": api_key,
        "tool_configs": resolved_tool_configs(
            stored.get("tool_configs") or {}, str(models[0])
        ),
        "accounts": sent_accounts,
    }


def code_server_agent_config(stored: dict) -> dict:
    """What the agent is sent for code-server.

    Args:
        stored: The module's file: the instances, each with its sealed
            token secret.

    Returns:
        ``{instances: [{account, port, secret}]}``, each secret opened.
    """
    instances = []
    for instance in stored.get("instances") or []:
        if not isinstance(instance, dict):
            continue
        instances.append(
            {
                "account": str(instance.get("account", "") or ""),
                "port": instance.get("port", 0),
                "secret": _unsealed_text(
                    instance.get(DEVICE_CODE_SERVER_SECRET_KEY),
                    DEVICE_CODE_SERVER_SECRET_AAD,
                ),
            }
        )
    return {"instances": instances}


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

    def vscode_token(self, key: str, account: str) -> str:
        """The connection token one VS Code instance answers to.

        Args:
            key: The device key.
            account: The account the instance runs as.

        Returns:
            The token, empty when the device has no such instance, when the
            vault is locked, or when the seal does not open under this box's
            data key.
        """
        for instance in self.read(key, DEVICE_VSCODE_MODULE).get("instances") or []:
            if isinstance(instance, dict) and instance.get("account") == account:
                return _unsealed_text(
                    instance.get(DEVICE_VSCODE_TOKEN_KEY), DEVICE_VSCODE_TOKEN_AAD
                )
        return ""

    def sealed_vscode_token(self, key: str, account: str) -> dict:
        """One instance's token seal, made the first time it is asked for.

        Args:
            key: The device key.
            account: The account the instance runs as.

        Returns:
            The seal ``vscode.json`` holds for that account's instance, or a
            fresh one to store with it.

        Raises:
            VaultLockedError: If there is no data key to seal a fresh one
                under.
        """
        for instance in self.read(key, DEVICE_VSCODE_MODULE).get("instances") or []:
            if not isinstance(instance, dict) or instance.get("account") != account:
                continue
            held = instance.get(DEVICE_VSCODE_TOKEN_KEY)
            if isinstance(held, dict) and held:
                return dict(held)
        return seal_bytes(
            secrets.token_urlsafe(VSCODE_TOKEN_BYTES).encode(),
            DEVICE_VSCODE_TOKEN_AAD,
        )

    def sealed_cloudcli_secret(self, key: str, account: str, field: str) -> dict:
        """One CloudCLI instance's password or token secret, made the first time.

        Args:
            key: The device key.
            account: The account the instance runs as.
            field: ``web_password_sealed`` or ``token_secret_sealed``.

        Returns:
            The seal ``cloudcli.json`` holds for that account's instance, or
            a fresh one to store with it.

        Raises:
            KeyError: For a field that is neither.
            VaultLockedError: If there is no data key to seal a fresh one
                under.
        """
        aad = {
            DEVICE_CLOUDCLI_PASSWORD_KEY: DEVICE_CLOUDCLI_PASSWORD_AAD,
            DEVICE_CLOUDCLI_SECRET_KEY: DEVICE_CLOUDCLI_SECRET_AAD,
        }[field]
        for instance in self.read(key, DEVICE_CLOUDCLI_MODULE).get("instances") or []:
            if not isinstance(instance, dict) or instance.get("account") != account:
                continue
            held = instance.get(field)
            if isinstance(held, dict) and held:
                return dict(held)
        return seal_bytes(
            secrets.token_urlsafe(DEVICE_CLOUDCLI_SECRET_BYTES).encode(), aad
        )

    def cloudcli_token(
        self, key: str, account: str, *, now: "float | None" = None
    ) -> str:
        """A fresh token for one CloudCLI instance, good for one open.

        Args:
            key: The device key.
            account: The account the instance runs as.
            now: Seconds since the epoch; None is the clock.

        Returns:
            The token, its expiry 60 seconds ahead; empty when the device
            has no such instance, when the vault is locked, or when the
            secret does not open under this box's data key.
        """
        for instance in self.read(key, DEVICE_CLOUDCLI_MODULE).get("instances") or []:
            if not isinstance(instance, dict) or instance.get("account") != account:
                continue
            secret = _unsealed_text(
                instance.get(DEVICE_CLOUDCLI_SECRET_KEY), DEVICE_CLOUDCLI_SECRET_AAD
            )
            if not secret:
                return ""
            return _fresh_token(secret, now)
        return ""

    def sealed_code_server_secret(self, key: str, account: str) -> dict:
        """One code-server instance's token secret, made the first time.

        Args:
            key: The device key.
            account: The account the instance runs as.

        Returns:
            The seal ``code_server.json`` holds for that account's instance,
            or a fresh one to store with it.

        Raises:
            VaultLockedError: If there is no data key to seal a fresh one
                under.
        """
        for instance in (
            self.read(key, DEVICE_CODE_SERVER_MODULE).get("instances") or []
        ):
            if not isinstance(instance, dict) or instance.get("account") != account:
                continue
            held = instance.get(DEVICE_CODE_SERVER_SECRET_KEY)
            if isinstance(held, dict) and held:
                return dict(held)
        return seal_bytes(
            secrets.token_urlsafe(DEVICE_CODE_SERVER_SECRET_BYTES).encode(),
            DEVICE_CODE_SERVER_SECRET_AAD,
        )

    def code_server_token(
        self, key: str, account: str, *, now: "float | None" = None
    ) -> str:
        """A fresh token for one code-server instance, good for one open.

        Args:
            key: The device key.
            account: The account the instance runs as.
            now: Seconds since the epoch; None is the clock.

        Returns:
            The token, its expiry 60 seconds ahead; empty when the device
            has no such instance, when the vault is locked, or when the
            secret does not open under this box's data key.
        """
        for instance in (
            self.read(key, DEVICE_CODE_SERVER_MODULE).get("instances") or []
        ):
            if not isinstance(instance, dict) or instance.get("account") != account:
                continue
            secret = _unsealed_text(
                instance.get(DEVICE_CODE_SERVER_SECRET_KEY),
                DEVICE_CODE_SERVER_SECRET_AAD,
            )
            if not secret:
                return ""
            return _fresh_token(secret, now)
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
            instance in a VS Code, CloudCLI or code-server configuration
            whose module is asked for and not withdrawn, sorted by account;
            ``login_id`` the first instance's in that module order, empty
            where none names one, and ``modules`` the modules it has an
            instance in.
        """
        wanted = self.modules(key)
        found: dict = {}
        for module in DEVICE_AI_TOOL_MODULES:
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
                login_id = login_id or str(instance.get("login_id", "") or "")
                found[account] = (login_id, modules)
        return [
            (account, found[account][0], found[account][1]) for account in sorted(found)
        ]

    def is_ai_tools_enabled(self, key: str) -> bool:
        """Whether one device's AI tools setting is on."""
        return self.ai_tools(key)["is_enabled"]

    def compose(
        self,
        key: str,
        platform: dict,
        *,
        address: str = "",
        allowed_subnets: "list | tuple" = (),
        urls: "list | tuple" = (),
        hub_address: str = "",
        ai_models: "list | tuple" = (),
        retry_marks: "dict | None" = None,
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
            hub_address: The hub's own address on the device's network, for
                the AI gateway the machine's tools reach.
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
            config = self.read(key, name)
            if name == "samba":
                config["allowed_subnets"] = list(allowed_subnets)
            elif name == "gitea":
                config["address"] = address
                config["secrets"] = self.gitea_secrets(key)
            elif name == DEVICE_VSCODE_MODULE:
                config = vscode_agent_config(config, platform)
            elif name == DEVICE_CODE_SERVER_MODULE:
                config = code_server_agent_config(config)
            elif name == DEVICE_CLOUDCLI_MODULE:
                config = cloudcli_agent_config(config, platform)
            modules[name] = {
                "want": entry["want"],
                "config": config,
                **_recipes(resolved.get(name) or {}),
            }
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
                device_gateway(key, hub_address),
                list(ai_models),
            ),
        }
        if desired["ai_tools"]["is_enabled"] and marks.get(DEVICE_AI_TOOLS_NAME):
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
        ``{"install", "uninstall"}``, the branch's own blocks; both empty
        where the manifest offers the platform nothing.
    """
    entry = resolved.get("entry")
    if not isinstance(entry, dict):
        return {"install": {}, "uninstall": {}}
    install = {name: value for name, value in entry.items() if name != "uninstall"}
    install["kind"] = str(resolved.get("kind", "") or "")
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
