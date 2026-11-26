"""Each machine's Ollama models with their lengths, as the context lengths count them.

What these pin: ``/api/tags``'s digests; ``/api/show``'s trained length from
``<architecture>.context_length`` and its Modelfile's ``num_ctx``, each 0
where the answer names none; the stored list read back; and the pool:
every machine whose Ollama module is installed, offline machines among
them, a model a generated provider lists counting with the setting alone,
and a machine whose module is uninstalled or that the hub no longer stores
left out.
"""

from neutrino_hub.modules.devices.ollama_lengths import (
    is_completion_model,
    pool_machines,
    read_ollama_lengths,
    shown_lengths,
    tag_digests,
    write_ollama_lengths,
)
from tests.conftest import unlock_vault


def test_tags_give_each_name_its_digest():
    assert tag_digests(
        {"models": [{"name": "a", "digest": "d1"}, {"model": "b"}, "x", {}]}
    ) == {"a": "d1", "b": ""}


def test_show_gives_the_trained_length_and_the_modelfile_s_num_ctx():
    assert shown_lengths(
        {
            "parameters": 'num_ctx                        8192\nstop "<|im_end|>"',
            "model_info": {
                "general.architecture": "llama",
                "llama.context_length": 131072,
                "qwen2.context_length": 5,
            },
        }
    ) == {"trained_context_length": 131072, "modelfile_context_length": 8192}
    assert shown_lengths({"model_info": {"general.architecture": "llama"}}) == {
        "trained_context_length": 0,
        "modelfile_context_length": 0,
    }
    assert shown_lengths({}) == {
        "trained_context_length": 0,
        "modelfile_context_length": 0,
    }


def test_show_s_capabilities_say_whether_a_model_answers_a_chat():
    assert is_completion_model({"capabilities": ["completion", "tools"]}) is True
    assert is_completion_model({"capabilities": ["embedding"]}) is False
    assert is_completion_model({"capabilities": []}) is False
    assert is_completion_model({}) is True


def test_the_stored_lengths_are_read_back(monkeypatch, tmp_path):
    unlock_vault(monkeypatch, tmp_path)
    assert read_ollama_lengths() == {}
    held = {
        "dev": {
            "m": {
                "digest": "d",
                "trained_context_length": 32768,
                "modelfile_context_length": 0,
                "is_completion": False,
            },
            "older": {
                "digest": "e",
                "trained_context_length": 0,
                "modelfile_context_length": 0,
            },
        },
        "gone": {},
    }

    write_ollama_lengths(held)

    assert read_ollama_lengths() == {"dev": held["dev"]}


def test_the_pool_holds_every_machine_whose_module_is_installed():
    stored = {
        "online": {"m": {"trained_context_length": 32768}},
        "offline": {"m": {"trained_context_length": 32768}},
        "uninstalled": {"m": {}},
        "removed": {"m": {}},
    }
    providers = [{"device_id": "online", "address": "a:1", "models": ["m", "new"]}]

    machines = pool_machines(
        stored,
        providers,
        names={"online": "One", "offline": "", "uninstalled": "U"},
        settings={"online": 65536, "offline": 16384},
        wants={"online": "running", "offline": "running", "uninstalled": "absent"},
    )

    by_id = {machine.device_id: machine for machine in machines}
    assert sorted(by_id) == ["offline", "online"]
    assert by_id["online"].name == "One"
    assert by_id["offline"].name == "offline"
    assert by_id["online"].models["new"] == {}
    assert by_id["online"].model_window("new") == 65536
    assert by_id["offline"].model_window("m") == 16384


def test_an_embedding_model_is_in_no_pool():
    stored = {
        "dev": {
            "m": {"trained_context_length": 32768, "is_completion": True},
            "embed": {"trained_context_length": 512, "is_completion": False},
        }
    }

    machines = pool_machines(
        stored, [], names={"dev": "Dev"}, settings={}, wants={"dev": "running"}
    )

    assert sorted(machines[0].models) == ["m"]
