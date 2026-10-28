"""The SiYuan module's configuration: which accounts run it, and the gateway they call.

Each instance is one account's SiYuan kernel behind the agent's forwarder,
on a port the agent takes and keeps in the instance's record. The hub sends
each instance's token secret, which signs the one-time tokens a client opens
the instance with; its access code, the kernel's own login; its key to the
AI gateway; the app's local name the forwarder accepts as a ``Host``; and
the forwarder's cookie name. Beside the instances it sends the gateway's
address on the machine and the models the gateway serves. On Windows an
instance also carries the account's password, from the login the hub holds
for it.

Pure: parsing, validation, and the kernel's settings with the module's
provider written in.
"""

# PEP 604 unions below are annotations only; this keeps them lazy so the
# agent still imports on the Python 3.9 that older Raspbian ships.
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field

from neutrino_agent.exceptions import ModuleApplyError
from neutrino_agent.modules.siyuan.constants import (
    SIYUAN_GATEWAY_PATH,
    SIYUAN_ID_HEX_CHARS,
    SIYUAN_ID_STAMP,
    SIYUAN_MODEL_SEED_PREFIX,
    SIYUAN_PROVIDER_PROTOCOL,
    SIYUAN_PROVIDER_SEED,
    SIYUAN_PROVIDER_TIMEOUT_S,
)

# An account name that survives a unit name, a launchd label, a task name
# and a command line.
ACCOUNT_PATTERN = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_.-]{0,63}\Z")


def siyuan_id(seed: str) -> str:
    """An id of SiYuan's own form for one of the module's entries in the kernel's settings.

    Args:
        seed: What the entry is: ``neutrino`` for the provider,
            ``neutrino/<name>`` for a model.

    Returns:
        ``20000101000000-`` and the first seven hex characters of the
        seed's SHA-256.
    """
    digest = hashlib.sha256(seed.encode("utf-8")).hexdigest()
    return SIYUAN_ID_STAMP + digest[:SIYUAN_ID_HEX_CHARS]


def provider_id() -> str:
    """The id of the module's provider in the kernel's settings."""
    return siyuan_id(SIYUAN_PROVIDER_SEED)


def model_id(name: str) -> str:
    """The id of one model of the module's provider.

    Args:
        name: The model's name, as the gateway serves it.

    Returns:
        The id.
    """
    return siyuan_id(SIYUAN_MODEL_SEED_PREFIX + name)


def settings_digest(gateway_key: str, gateway_url: str, models: list) -> str:
    """What the kernel's settings were last written from, as one value.

    Args:
        gateway_key: The instance's key to the gateway.
        gateway_url: The gateway's address on the machine.
        models: The model names.

    Returns:
        The SHA-256, in hex, of the three as JSON.
    """
    material = json.dumps([gateway_key, gateway_url, list(models)])
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def with_module_settings(
    conf: dict, *, gateway_key: str, gateway_url: str, models: list
) -> dict:
    """The kernel's settings with the module's provider and its own settings written in.

    The module's provider, found by its fixed id, is replaced whole or
    added after the person's own; with no key or no address it is taken
    out. The agent's and the editor's model point at the provider's first
    model only while they name no model the settings hold. The kernel's
    background download of new installers is turned off.

    Args:
        conf: The kernel's ``conf.json``, parsed.
        gateway_key: The instance's key to the gateway, written as it is.
        gateway_url: The gateway's address on the machine; ``/v1`` follows
            it in the provider's address.
        models: The names the gateway serves, one model each.

    Returns:
        A new settings document; ``conf`` is left as it was.
    """
    settings = json.loads(json.dumps(conf))
    ai = settings.get("ai")
    if not isinstance(ai, dict):
        ai = {}
        settings["ai"] = ai
    held = ai.get("providers")
    providers = [
        entry
        for entry in (held if isinstance(held, list) else [])
        if not (isinstance(entry, dict) and entry.get("id") == provider_id())
    ]
    if gateway_key and gateway_url:
        providers.append(
            {
                "id": provider_id(),
                "enabled": True,
                "apiKey": gateway_key,
                "baseURL": gateway_url.rstrip("/") + SIYUAN_GATEWAY_PATH,
                "protocol": SIYUAN_PROVIDER_PROTOCOL,
                "requestTimeout": SIYUAN_PROVIDER_TIMEOUT_S,
                "models": [
                    {"id": model_id(name), "enabled": True, "name": name}
                    for name in models
                ],
            }
        )
    ai["providers"] = providers
    known = {
        str(model.get("id", ""))
        for provider in providers
        if isinstance(provider, dict)
        for model in provider.get("models") or []
        if isinstance(model, dict)
    }
    if gateway_key and gateway_url and models:
        first = model_id(models[0])
        for use in ("agent", "editing"):
            held_use = ai.get(use)
            if not isinstance(held_use, dict):
                held_use = {}
                ai[use] = held_use
            if str(held_use.get("modelId", "") or "") not in known:
                held_use["modelId"] = first
    system = settings.get("system")
    if not isinstance(system, dict):
        system = {}
        settings["system"] = system
    system["downloadInstallPkg"] = False
    return settings


@dataclass
class SiyuanInstance:
    """One account's SiYuan.

    Attributes:
        account: The account it runs as.
        secret: The secret a token for this instance is signed with.
        access_code: The kernel's access code.
        gateway_key: The instance's key to the AI gateway.
        password: The account's password; Windows only.
        local_name: Its app's local name, a ``Host`` the forwarder accepts.
        cookie_name: The name the browser keeps the kernel's login under.
        port: The port the forwarder listens on, which the agent took; 0 in
            an instance the state names, which names none.
    """

    account: str
    secret: str = ""
    access_code: str = ""
    gateway_key: str = ""
    password: str = ""
    local_name: str = ""
    cookie_name: str = ""
    port: int = 0

    @classmethod
    def from_dict(cls, data: dict) -> "SiyuanInstance":
        try:
            port = int(data.get("port", 0))
        except (TypeError, ValueError):
            port = 0
        return cls(
            account=str(data.get("account", "") or ""),
            secret=str(data.get("secret", "") or ""),
            access_code=str(data.get("access_code", "") or ""),
            gateway_key=str(data.get("gateway_key", "") or ""),
            password=str(data.get("password", "") or ""),
            local_name=str(data.get("local_name", "") or ""),
            cookie_name=str(data.get("cookie_name", "") or ""),
            port=port,
        )


@dataclass
class SiyuanConfig:
    """Everything the module's desired configuration holds.

    Attributes:
        instances: One kernel per account.
        gateway_url: Where the gateway is reached on this machine.
        models: The names the gateway serves.
    """

    instances: list = field(default_factory=list)
    gateway_url: str = ""
    models: list = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict) -> "SiyuanConfig":
        instances = data.get("instances")
        models = data.get("models")
        return cls(
            instances=[
                SiyuanInstance.from_dict(entry)
                for entry in (instances if isinstance(instances, list) else [])
                if isinstance(entry, dict)
            ],
            gateway_url=str(data.get("gateway_url", "") or ""),
            models=[
                str(name)
                for name in (models if isinstance(models, list) else [])
                if isinstance(name, str) and name
            ],
        )

    def validate(self, *, os_name: str = "linux") -> None:
        """Check the configuration holds together.

        Args:
            os_name: The system the instances run on; on ``windows`` every
                instance needs its account's password.

        Raises:
            ModuleApplyError: ``account_invalid``, ``account_duplicate`` or
                ``secret_missing``, naming the first problem found, and on
                Windows ``credential_missing`` for an instance with no
                password.
        """
        accounts: set = set()
        for instance in self.instances:
            if not ACCOUNT_PATTERN.match(instance.account):
                raise ModuleApplyError("account_invalid", {"account": instance.account})
            if instance.account.lower() in accounts:
                raise ModuleApplyError(
                    "account_duplicate", {"account": instance.account}
                )
            accounts.add(instance.account.lower())
            if not instance.secret or not instance.access_code:
                raise ModuleApplyError("secret_missing", {"account": instance.account})
            if os_name == "windows" and not instance.password:
                raise ModuleApplyError(
                    "credential_missing", {"account": instance.account}
                )
