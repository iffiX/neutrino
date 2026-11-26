"""Each machine's Ollama models with their trained and Modelfile lengths, stored for the context lengths.

The hub reads ``/api/show`` for each model ``/api/tags`` lists under a
digest it has not read, on the thread of the ``/api/tags`` reads, and keeps
every machine whose Ollama module is installed, offline machines among
them, from the first read that lists a model until a read no longer lists
it, the module's uninstall or the machine's removal (hub_components/ai.md,
"An Ollama name's length").

The parsing and the pool are pure; the store is a file under the state root.
"""

import json

from neutrino_hub.modules.ai.context_lengths import AiOllamaPoolMachine
from neutrino_hub.modules.cliproxyapi.constants import (
    CLIPROXYAPI_OLLAMA_LENGTHS_RELATIVE,
)
from neutrino_hub.modules.devices.constants import DEVICE_OLLAMA_MODULE
from neutrino_hub.modules.channel.constants import CHANNEL_MODULE_STATE_ABSENT
from neutrino_hub.utils import constants
from neutrino_hub.utils.json_file import write_generated

# The parameter of a Modelfile that sets the window a model loads at.
MODELFILE_CONTEXT_PARAMETER = "num_ctx"
# The capability of a model that answers a chat request.
COMPLETION_CAPABILITY = "completion"


def tag_digests(tags: dict) -> dict:
    """The names ``/api/tags`` lists, each with its digest. Pure.

    Args:
        tags: ``/api/tags``'s answer.

    Returns:
        Each model's ``name``, else its ``model``, to its ``digest``, empty
        where it names none.
    """
    found = {}
    for model in tags.get("models") or []:
        if not isinstance(model, dict):
            continue
        name = str(model.get("name", "") or model.get("model", ""))
        if name:
            found[name] = str(model.get("digest", "") or "")
    return found


def shown_lengths(answer: dict) -> dict:
    """A model's trained length and its Modelfile's length, from ``/api/show``. Pure.

    Args:
        answer: ``/api/show``'s answer.

    Returns:
        ``{trained_context_length, modelfile_context_length}``: the
        ``<architecture>.context_length`` of ``model_info``,
        ``<architecture>`` being its ``general.architecture``, and the
        ``num_ctx`` line of ``parameters``, each 0 where it names none.
    """
    info = answer.get("model_info")
    info = info if isinstance(info, dict) else {}
    architecture = info.get("general.architecture")
    trained = info.get(f"{architecture}.context_length") if architecture else None
    modelfile = 0
    parameters = answer.get("parameters")
    for line in parameters.splitlines() if isinstance(parameters, str) else []:
        words = line.split()
        if len(words) == 2 and words[0] == MODELFILE_CONTEXT_PARAMETER:
            modelfile = _count(words[1])
    return {
        "trained_context_length": _count(trained),
        "modelfile_context_length": modelfile,
    }


def is_completion_model(answer: dict) -> bool:
    """Whether a model answers a chat request, from ``/api/show``. Pure.

    Args:
        answer: ``/api/show``'s answer.

    Returns:
        False when ``capabilities`` is a list without ``completion``, as for
        an embedding model; True otherwise.
    """
    capabilities = answer.get("capabilities")
    return not isinstance(capabilities, list) or COMPLETION_CAPABILITY in capabilities


def read_ollama_lengths() -> dict:
    """Each machine's stored Ollama models.

    Returns:
        Device id to model name to ``{digest, trained_context_length,
        modelfile_context_length, is_completion}``, ``is_completion`` left
        out where the file names none; empty when none is stored or the file
        does not read.
    """
    try:
        held = json.loads(_lengths_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    machines = held.get("machines") if isinstance(held, dict) else None
    found = {}
    for machine in machines if isinstance(machines, list) else []:
        if not isinstance(machine, dict):
            continue
        device_id = machine.get("device_id")
        models = machine.get("models")
        if not isinstance(device_id, str) or not device_id:
            continue
        if not isinstance(models, dict):
            continue
        found[device_id] = {
            str(name): _stored_model(model)
            for name, model in models.items()
            if isinstance(model, dict)
        }
    return found


def _stored_model(model: dict) -> dict:
    """One stored model as the file holds it, ``is_completion`` kept only where it is a bool."""
    held = {
        "digest": str(model.get("digest", "") or ""),
        "trained_context_length": _count(model.get("trained_context_length")),
        "modelfile_context_length": _count(model.get("modelfile_context_length")),
    }
    if isinstance(model.get("is_completion"), bool):
        held["is_completion"] = model["is_completion"]
    return held


def write_ollama_lengths(machines: dict) -> None:
    """Store each machine's Ollama models.

    Args:
        machines: Device id to model name to ``{digest,
            trained_context_length, modelfile_context_length,
            is_completion}``.

    Raises:
        OSError: If the state file cannot be written.
    """
    document = {
        "machines": [
            {"device_id": device_id, "models": machines[device_id]}
            for device_id in sorted(machines)
            if machines[device_id]
        ]
    }
    write_generated(_lengths_path(), json.dumps(document) + "\n", mode=0o600)


def pool_machines(
    stored: dict, providers: list, *, names: dict, settings: dict, wants: dict
) -> list:
    """Every machine whose Ollama module is installed, with the models it holds. Pure.

    Args:
        stored: :func:`read_ollama_lengths`'s answer; a model whose
            ``is_completion`` is false is left out.
        providers: The generated providers, ``{device_id, address,
            models}`` each; a model one lists that the store does not hold
            counts with the setting alone.
        names: Device id to what the hub calls the machine, for every
            stored device; a machine not among them is left out.
        settings: Device id to its Ollama ``context_length`` setting.
        wants: Device id to the Ollama module's ``want``; a machine whose
            module is not named, or is named ``absent``, is left out.

    Returns:
        :class:`AiOllamaPoolMachine` each.
    """
    models: dict = {}
    for device_id, held in stored.items():
        models[device_id] = {
            name: dict(model)
            for name, model in held.items()
            if model.get("is_completion", True)
        }
    for provider in providers:
        held = models.setdefault(provider["device_id"], {})
        for name in provider.get("models") or []:
            held.setdefault(name, {})
    machines = []
    for device_id, held in models.items():
        want = wants.get(device_id, "")
        if device_id not in names or not want or want == CHANNEL_MODULE_STATE_ABSENT:
            continue
        if not held:
            continue
        machines.append(
            AiOllamaPoolMachine(
                device_id=device_id,
                name=names[device_id] or device_id,
                setting=int(settings.get(device_id, 0) or 0),
                models=held,
            )
        )
    return machines


def ollama_wants(store, device_ids) -> dict:
    """Each device's Ollama ``want``, as its ``modules.json`` names it.

    Args:
        store: The :class:`DesiredStateStore`.
        device_ids: The devices.

    Returns:
        Device id to the ``want``, empty for a device whose file does not
        name the module.
    """
    return {key: store.want_of(key, DEVICE_OLLAMA_MODULE) for key in device_ids}


def _lengths_path():
    # Resolved per call, against the state root as it is right now.
    return constants.UTILS_STATE_ROOT / CLIPROXYAPI_OLLAMA_LENGTHS_RELATIVE


def _count(value) -> int:
    """A token count as an int, 0 for anything that is not a positive one."""
    if isinstance(value, bool):
        return 0
    try:
        number = int(value)
    except (TypeError, ValueError):
        return 0
    return number if number > 0 else 0
