"""Each served model's context length, for the AI tools and the apps that use the gateway.

A cloud name's length is the one a person set, else its default: for each of
the three numbers the smallest its sources give, a source's numbers coming
from the table of known models, else the gateway's catalog, else 200000. An
Ollama name's window is the smallest over its pool, each machine giving the
smaller of the model's setting and its trained length, and the smaller of
that and the cloud default where an account or a stored provider serves the
name too (hub_components/ai.md, "Each model's context length").

The resolver is pure. The table and the set lengths are read by the
functions here.
"""

import json
import operator
from dataclasses import dataclass, field

from neutrino_hub.modules.ai.constants import (
    AI_ACCOUNT_CHANNELS,
    AI_CONTEXT_LENGTH_FALLBACK,
    AI_CONTEXT_LENGTHS_PATH,
    AI_CONTEXT_ORIGIN_ACCOUNT,
    AI_CONTEXT_ORIGIN_PROVIDER,
    AI_KNOWN_MODELS_PATH,
    AI_PROVIDER_KIND_CHANNELS,
    AI_PROVIDERS_PATH,
)
from neutrino_hub.modules.devices.constants import (
    DEVICE_CONFIG_DIR_NAME,
    DEVICE_MODULES_FILE,
    DEVICE_OLLAMA_MODULE,
)
from neutrino_hub.utils.json_file import read_config, write_config

LENGTH_KEYS = ("context_length", "input_limit", "output_limit")

# The table as read at its first use, by path.
_KNOWN_MODELS: dict = {}


def load_known_models(path=AI_KNOWN_MODELS_PATH) -> list:
    """The table of known models, read once per path.

    Args:
        path: The table's file.

    Returns:
        ``{names, context_length, input_limit, output_limit}`` per row,
        with ``account`` beside them on a row whose numbers through a login
        differ.

    Raises:
        OSError: If the file cannot be read.
        ValueError: If it is not the table's JSON.
    """
    key = str(path)
    if key not in _KNOWN_MODELS:
        with open(path, encoding="utf-8") as stream:
            held = json.load(stream)
        rows = held.get("models") if isinstance(held, dict) else None
        if not isinstance(rows, list):
            raise ValueError(f"{path} holds no models")
        _KNOWN_MODELS[key] = [row for row in rows if isinstance(row, dict)]
    return _KNOWN_MODELS[key]


def read_set_lengths() -> dict:
    """The lengths a person set, by served name.

    Returns:
        Name to tokens; empty while the file is absent, does not read, or
        holds none.
    """
    try:
        held = read_config(AI_CONTEXT_LENGTHS_PATH)
    except (FileNotFoundError, ValueError):
        return {}
    lengths = held.get("lengths") if isinstance(held, dict) else None
    if not isinstance(lengths, dict):
        return {}
    return {
        str(name): value
        for name, value in lengths.items()
        if isinstance(value, int) and not isinstance(value, bool) and value > 0
    }


def write_set_lengths(lengths: dict) -> None:
    """Store the lengths a person set.

    Args:
        lengths: Name to tokens.
    """
    write_config(AI_CONTEXT_LENGTHS_PATH, {"lengths": dict(sorted(lengths.items()))})


def is_context_length_input(relative_path: str) -> bool:
    """Whether a file under ``config/`` is one the context lengths come from.

    Args:
        relative_path: The file, below ``config/``.

    Returns:
        True for the stored providers, the set lengths, and a machine's
        Ollama settings or its module wants.
    """
    path = relative_path.replace("\\", "/")
    if path in (AI_PROVIDERS_PATH, AI_CONTEXT_LENGTHS_PATH):
        return True
    parts = path.split("/")
    return (
        len(parts) == 3
        and parts[0] == DEVICE_CONFIG_DIR_NAME
        and parts[2] in (f"{DEVICE_OLLAMA_MODULE}.json", DEVICE_MODULES_FILE)
    )


def one_number(length: dict) -> int:
    """A model's one number: its window, or its longest prompt where that is smaller.

    Args:
        length: ``{context_length, input_limit, output_limit}``.

    Returns:
        ``context_length``, or ``input_limit`` when it is smaller and not 0.
    """
    window = int(length.get("context_length", 0) or 0)
    prompt = int(length.get("input_limit", 0) or 0)
    if prompt and (not window or prompt < window):
        return prompt
    return window


def one_numbers(models, lengths: "dict | None") -> dict:
    """Each name's one number, for an app that takes one number per model.

    Args:
        models: The names.
        lengths: Name to ``{context_length, input_limit, output_limit}``;
            None names none.

    Returns:
        Each name that has a length to its :func:`one_number`.
    """
    held = lengths or {}
    found = {}
    for name in models:
        number = one_number(held[name]) if name in held else 0
        if number:
            found[str(name)] = number
    return found


def _length(context_length=0, input_limit=0, output_limit=0) -> dict:
    """One length's three numbers."""
    return {
        "context_length": int(context_length or 0),
        "input_limit": int(input_limit or 0),
        "output_limit": int(output_limit or 0),
    }


def _smallest(lengths: list) -> dict:
    """For each of the three numbers the smallest the lengths give, 0 counting as none."""
    found = {}
    for key in LENGTH_KEYS:
        numbers = [length[key] for length in lengths if length.get(key)]
        found[key] = min(numbers) if numbers else 0
    return found


@dataclass
class AiOllamaPoolMachine:
    """A machine whose Ollama module is installed, as the context lengths count it.

    Attributes:
        device_id: The machine.
        name: What the hub calls it.
        setting: Its Ollama module's ``context_length`` setting.
        models: Each model its Ollama holds, to ``{trained_context_length,
            modelfile_context_length}``, each 0 where the hub read none.
    """

    device_id: str
    name: str
    setting: int
    models: dict = field(default_factory=dict)

    def model_setting(self, model: str) -> int:
        """The setting one model loads at here: its Modelfile's ``num_ctx``, else the machine's."""
        held = self.models.get(model) or {}
        return int(held.get("modelfile_context_length", 0) or 0) or self.setting

    def model_trained(self, model: str) -> int:
        """One model's trained length, 0 where none was read."""
        return int((self.models.get(model) or {}).get("trained_context_length", 0) or 0)

    def model_window(self, model: str) -> int:
        """The smaller of one model's setting and its trained length."""
        setting = self.model_setting(model)
        trained = self.model_trained(model)
        return min(setting, trained) if trained else setting


class AiContextLengthResolver:
    """Resolves the context length of each name the gateway serves."""

    def __init__(
        self,
        *,
        known_models: list,
        catalog: "dict | None",
        providers: list,
        set_lengths: dict,
        ollama_machines: list,
        ollama_names,
    ):
        """
        Args:
            known_models: The table's rows, as :func:`load_known_models`
                gives them.
            catalog: The stored catalog read, ``{channels: {<channel>:
                [{id, context_length, output_limit}]}, accounts: [{name,
                provider, models}]}``; None while none is stored.
            providers: The stored providers turned on with a key,
                :class:`AiProviderRecord` each.
            set_lengths: The lengths a person set, by served name.
            ollama_machines: Every machine whose Ollama module is installed,
                :class:`AiOllamaPoolMachine` each.
            ollama_names: The names a generated Ollama provider lists.
        """
        self._known = {}
        for row in known_models:
            for name in row.get("names") or []:
                self._known[str(name).lower()] = row
        self._catalog = catalog
        self._channels = {}
        for channel, entries in ((catalog or {}).get("channels") or {}).items():
            self._channels[channel] = {
                str(entry.get("id", "")).lower(): entry
                for entry in entries or []
                if isinstance(entry, dict)
            }
        self._accounts = sorted(
            [
                account
                for account in (catalog or {}).get("accounts") or []
                if isinstance(account, dict)
            ],
            key=_account_order,
        )
        self._providers = sorted(providers, key=operator.attrgetter("name", "id"))
        self._set_lengths = dict(set_lengths)
        self._machines = sorted(
            ollama_machines, key=operator.attrgetter("name", "device_id")
        )
        self._ollama_names = {str(name) for name in ollama_names}

    def lengths(self, served) -> dict:
        """Every served name's length.

        Args:
            served: The served list.

        Returns:
            Name to ``{context_length, input_limit, output_limit}``; a name
            with no window is left out.
        """
        found = {}
        for name in served:
            if name in self._ollama_names:
                length = self._ollama_length(name)
            else:
                length = self._cloud_length(name)
            if length["context_length"]:
                found[name] = length
        return found

    def view(self, served) -> dict:
        """Every served name's length with where it comes from.

        Args:
            served: The served list.

        Returns:
            ``{cloud, ollama}`` as ``GET /api/hub/ai/context`` answers,
            each by name.
        """
        cloud = []
        ollama = []
        for name in sorted(served):
            sources = self._sources(name)
            if name in self._ollama_names:
                default = self._cloud_default(name, sources) if sources else None
                ollama.append(
                    {
                        "model": name,
                        "machines": [
                            {
                                "device_id": machine.device_id,
                                "name": machine.name,
                                "setting_context_length": machine.model_setting(name),
                                "trained_context_length": machine.model_trained(name),
                            }
                            for machine in self._pool(name)
                        ],
                        "sources": [source.view() for source in sources],
                        "cloud_context_length": (
                            default["context_length"] if default else 0
                        ),
                        "context_length": self._ollama_length(name)["context_length"],
                    }
                )
                continue
            cloud.append(
                {
                    "model": name,
                    "sources": [source.view() for source in sources],
                    "context_length": self._set_lengths.get(name),
                    "default_context_length": self._cloud_default(name, sources)[
                        "context_length"
                    ],
                }
            )
        return {"cloud": cloud, "ollama": ollama}

    def _cloud_length(self, name: str) -> dict:
        """A cloud name's length: its default, the window replaced by a set length."""
        length = self._cloud_default(name, self._sources(name))
        if name in self._set_lengths:
            length = dict(length, context_length=self._set_lengths[name])
        return length

    def _ollama_length(self, name: str) -> dict:
        """An Ollama name's length: its pool's window, made smaller by a cloud source's numbers."""
        windows = [machine.model_window(name) for machine in self._pool(name)]
        pooled = [_length(min(windows))] if windows else []
        sources = self._sources(name)
        if sources:
            pooled.append(self._cloud_default(name, sources))
        return _smallest(pooled)

    def _pool(self, name: str) -> list:
        """Every machine whose Ollama holds a model, by name."""
        return [machine for machine in self._machines if name in machine.models]

    def _cloud_default(self, name: str, sources: list) -> dict:
        """The default of a name: the smallest its sources give, or its table row's smallest without them."""
        if self._catalog is None or not sources:
            row = self._known.get(name.lower())
            if row is None:
                return _length(AI_CONTEXT_LENGTH_FALLBACK)
            return _smallest([_row_length(row), _row_length(row, is_account=True)])
        return _smallest([self._source_length(source) for source in sources])

    def _source_length(self, source: "AiContextSource") -> dict:
        """One source's numbers: the table's, else the catalog's, else the fallback."""
        row = self._known.get(source.upstream.lower())
        if row is not None:
            return _row_length(
                row, is_account=source.origin == AI_CONTEXT_ORIGIN_ACCOUNT
            )
        entry = self._channels.get(source.channel, {}).get(source.upstream.lower())
        if entry and int(entry.get("context_length", 0) or 0) > 0:
            return _length(entry["context_length"], 0, entry.get("output_limit", 0))
        return _length(AI_CONTEXT_LENGTH_FALLBACK)

    def _sources(self, name: str) -> list:
        """The accounts and then the stored providers that serve a name."""
        lowered = name.lower()
        sources = []
        for account in self._accounts:
            models = {str(model).lower() for model in account.get("models") or []}
            if lowered not in models:
                continue
            provider = str(account.get("provider", "") or "")
            sources.append(
                AiContextSource(
                    origin=AI_CONTEXT_ORIGIN_ACCOUNT,
                    id=str(account.get("name", "")),
                    name=provider,
                    upstream=name,
                    channel=AI_ACCOUNT_CHANNELS.get(provider.lower(), ""),
                )
            )
        for provider in self._providers:
            upstream = self._provider_upstream(provider, lowered)
            if upstream:
                sources.append(
                    AiContextSource(
                        origin=AI_CONTEXT_ORIGIN_PROVIDER,
                        id=provider.id,
                        name=provider.name,
                        upstream=upstream,
                        channel=AI_PROVIDER_KIND_CHANNELS.get(provider.kind, ""),
                    )
                )
        return sources

    def _provider_upstream(self, provider, lowered: str) -> str:
        """The upstream name a provider serves a name as, empty when it serves none."""
        entries = [
            entry
            for entry in provider.models or []
            if isinstance(entry, dict) and str(entry.get("name", "")).strip()
        ]
        if entries:
            for entry in entries:
                upstream = str(entry["name"]).strip()
                alias = str(entry.get("alias", "") or "").strip() or upstream
                if alias.lower() == lowered:
                    return upstream
            return ""
        channel = AI_PROVIDER_KIND_CHANNELS.get(provider.kind, "")
        entry = self._channels.get(channel, {}).get(lowered) if channel else None
        return str(entry.get("id", "")) if entry else ""


@dataclass(frozen=True)
class AiContextSource:
    """An account or a stored provider that serves a name.

    Attributes:
        origin: ``account`` or ``provider``.
        id: The account's token file, or the provider's id.
        name: The account's login, as the gateway names its provider, or
            the provider's name.
        upstream: The name the source serves it as upstream.
        channel: The catalog channel the source reads, empty for none.
    """

    origin: str
    id: str
    name: str
    upstream: str
    channel: str

    def view(self) -> dict:
        """The source as the context view names it."""
        return {"origin": self.origin, "id": self.id, "name": self.name}


def _row_length(row: dict, *, is_account: bool = False) -> dict:
    """A table row's numbers, through a login where the row names them."""
    held = row.get("account") if is_account else None
    source = held if isinstance(held, dict) else row
    return _length(
        source.get("context_length", 0),
        source.get("input_limit", 0),
        source.get("output_limit", 0),
    )


def _account_order(account: dict) -> str:
    """An account's place among a name's sources: by its token file."""
    return str(account.get("name", ""))
