"""The gateway's model catalog, read over its management API and stored.

The hub reads each channel a source has, and the names the gateway serves
through each signed-in account, and stores the last read under the state
root, where every context length computation reads it (hub_components/ai.md,
"A cloud name's length"). A read that fails keeps the stored read.

Not pure: calls the running gateway and writes the stored read.
"""

import json
import logging

from neutrino_hub.exceptions import AiAccountRefusedError
from neutrino_hub.modules.ai.constants import (
    AI_ACCOUNT_CHANNELS,
    AI_PROVIDER_KIND_CHANNELS,
)
from neutrino_hub.modules.ai.registry import AiProviderRegistry
from neutrino_hub.modules.cliproxyapi.accounts import CliproxyApiAccountClient
from neutrino_hub.modules.cliproxyapi.constants import (
    CLIPROXYAPI_MODEL_CATALOG_RELATIVE,
)
from neutrino_hub.utils import constants
from neutrino_hub.utils.json_file import write_generated

LOGGER = logging.getLogger(__name__)


def catalog_entry(entry: dict) -> "dict | None":
    """One catalog entry's id, window and longest answer.

    Args:
        entry: The entry as the gateway keeps it.

    Returns:
        ``{id, context_length, output_limit}``: the window its
        ``context_length``, else its ``inputTokenLimit``, and the longest
        answer its ``max_completion_tokens``, else its ``outputTokenLimit``,
        each 0 where it names none; None for an entry with no id.
    """
    model = str(entry.get("id", "") or "")
    if not model:
        return None
    return {
        "id": model,
        "context_length": _count(entry.get("context_length"))
        or _count(entry.get("inputTokenLimit")),
        "output_limit": _count(entry.get("max_completion_tokens"))
        or _count(entry.get("outputTokenLimit")),
    }


def read_model_catalog() -> "dict | None":
    """The stored catalog read.

    Returns:
        ``{channels: {<channel>: [{id, context_length, output_limit}]},
        accounts: [{name, provider, models}]}``; None while none is stored
        or it does not read.
    """
    try:
        held = json.loads(_catalog_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(held, dict):
        return None
    channels = held.get("channels")
    accounts = held.get("accounts")
    return {
        "channels": channels if isinstance(channels, dict) else {},
        "accounts": accounts if isinstance(accounts, list) else [],
    }


def refresh_model_catalog(*, port: int, management_key: str) -> "bool | None":
    """Read the catalog from the gateway and store it when it changed.

    Args:
        port: Where the gateway listens.
        management_key: The key that unlocks the management API.

    Returns:
        Whether the stored read changed; None when a call failed or the
        read was not stored, which keeps the stored read as it was.
    """
    try:
        client = CliproxyApiAccountClient(port=port, management_key=management_key)
        accounts = [
            {
                "name": account.name,
                "provider": account.provider,
                "models": sorted(client.account_models(account.name)),
            }
            for account in client.list_accounts()
            if account.name
        ]
        channels = {}
        for channel in sorted(_channels_of(accounts)):
            entries = [
                catalog_entry(entry) for entry in client.model_definitions(channel)
            ]
            channels[channel] = [entry for entry in entries if entry is not None]
    except AiAccountRefusedError as error:
        LOGGER.info("the gateway's model catalog was not read: %s", error.code)
        return None
    read = {"channels": channels, "accounts": accounts}
    if read == read_model_catalog():
        return False
    try:
        write_generated(_catalog_path(), json.dumps(read) + "\n", mode=0o600)
    except OSError as error:
        LOGGER.warning("the gateway's model catalog was not stored: %s", error)
        return None
    return True


def _channels_of(accounts: list) -> set:
    """Each channel a signed-in account or a stored provider turned on with a key has."""
    channels = {
        AI_ACCOUNT_CHANNELS[str(account["provider"]).lower()]
        for account in accounts
        if str(account["provider"]).lower() in AI_ACCOUNT_CHANNELS
    }
    try:
        providers = AiProviderRegistry().list_records()
    except ValueError:
        providers = []
    for provider in providers:
        if provider.is_enabled and provider.secret_id:
            channel = AI_PROVIDER_KIND_CHANNELS.get(provider.kind)
            if channel:
                channels.add(channel)
    return channels


def _catalog_path():
    # Resolved per call, against the state root as it is right now.
    return constants.UTILS_STATE_ROOT / CLIPROXYAPI_MODEL_CATALOG_RELATIVE


def _count(value) -> int:
    """A token count as an int, 0 for anything that is not a positive one."""
    if isinstance(value, bool) or not isinstance(value, int):
        return 0
    return value if value > 0 else 0
