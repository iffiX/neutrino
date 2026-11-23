"""Each served name's context length, against hub_components/ai.md, "Each model's context length".

What these pin: a source's numbers from the table, else the stored catalog
read, else 200000; an account's from its row's numbers through an account;
an alias by its upstream name; a name matched whole and without case; the
smallest over the sources; a set length replacing the window alone; an
Ollama name's the smallest over its pool of the setting and the trained
length, the Modelfile's ``num_ctx`` in place of the machine's setting and the
setting alone for a model not read; a name a cloud source also serves taking
the smaller of the two with no set length applied; and
``data/context_lengths.json`` holding exactly the rows of the page's table.
"""

import json
import re
from pathlib import Path

from neutrino_hub.modules.ai import context_lengths
from neutrino_hub.modules.ai.context_lengths import (
    AiContextLengthResolver,
    AiOllamaPoolMachine,
    is_context_length_input,
    load_known_models,
    one_number,
    one_numbers,
    read_set_lengths,
    write_set_lengths,
)
from neutrino_hub.modules.ai.registry import AiProviderRecord

HUB_DIR = Path(__file__).resolve().parents[3]
AI_PAGE = HUB_DIR.parent / "skills/core-code-author/design/hub_components/ai.md"

TABLE = [
    {
        "names": ["claude-opus-4-6", "claude-sonnet-4-6"],
        "context_length": 1000000,
        "input_limit": 0,
        "output_limit": 128000,
        "account": {
            "context_length": 200000,
            "input_limit": 0,
            "output_limit": 64000,
        },
    },
    {
        "names": ["gpt-6.2-astra"],
        "context_length": 1050000,
        "input_limit": 922000,
        "output_limit": 128000,
        "account": {
            "context_length": 272000,
            "input_limit": 0,
            "output_limit": 128000,
        },
    },
    {
        "names": ["qwen4-max"],
        "context_length": 1000000,
        "input_limit": 983616,
        "output_limit": 131072,
    },
]

CATALOG = {
    "channels": {
        "claude": [
            {"id": "claude-new-model", "context_length": 400000, "output_limit": 9000}
        ],
        "codex": [
            {"id": "gpt-6.2-astra", "context_length": 272000, "output_limit": 128000},
            {"id": "gpt-wide", "context_length": 0, "output_limit": 5000},
        ],
    },
    "accounts": [
        {
            "name": "claude-person.json",
            "provider": "claude",
            "models": ["claude-opus-4-6", "claude-new-model", "claude-unknown"],
        },
        {"name": "codex-person.json", "provider": "codex", "models": ["gpt-6.2-astra"]},
    ],
}


def provider(
    name: str, kind: str, models=(), provider_id: str = ""
) -> AiProviderRecord:
    return AiProviderRecord(
        id=provider_id or name,
        name=name,
        kind=kind,
        secret_id="token-1",
        models=[dict(entry) for entry in models],
    )


def resolver(**overrides) -> AiContextLengthResolver:
    arguments = {
        "known_models": TABLE,
        "catalog": CATALOG,
        "providers": [],
        "set_lengths": {},
        "ollama_machines": [],
        "ollama_names": set(),
    }
    arguments.update(overrides)
    return AiContextLengthResolver(**arguments)


def length(context=0, prompt=0, answer=0) -> dict:
    return {"context_length": context, "input_limit": prompt, "output_limit": answer}


# --- a cloud name's sources ---


def test_an_account_takes_its_row_s_numbers_through_an_account():
    lengths = resolver().lengths(["claude-opus-4-6", "gpt-6.2-astra"])

    assert lengths["claude-opus-4-6"] == length(200000, 0, 64000)
    assert lengths["gpt-6.2-astra"] == length(272000, 0, 128000)


def test_a_provider_takes_its_row_s_own_numbers():
    found = resolver(
        catalog={"channels": {}, "accounts": []},
        providers=[provider("relay", "openai", [{"name": "gpt-6.2-astra"}])],
    ).lengths(["gpt-6.2-astra"])

    assert found["gpt-6.2-astra"] == length(1050000, 922000, 128000)


def test_a_name_the_table_lacks_takes_the_catalog_s_window_then_200000():
    found = resolver().lengths(["claude-new-model", "claude-unknown"])

    assert found["claude-new-model"] == length(400000, 0, 9000)
    assert found["claude-unknown"] == length(200000, 0, 0)


def test_a_catalog_entry_with_no_window_falls_back_to_200000():
    found = resolver(
        catalog={"channels": CATALOG["channels"], "accounts": []},
        providers=[provider("relay", "openai")],
    ).lengths(["gpt-wide"])

    assert found["gpt-wide"] == length(200000, 0, 0)


def test_an_alias_takes_the_length_of_its_upstream_name():
    found = resolver(
        providers=[
            provider("relay", "custom", [{"name": "QWEN4-MAX", "alias": "my-qwen"}])
        ],
    ).lengths(["my-qwen"])

    assert found["my-qwen"] == length(1000000, 983616, 131072)


def test_a_name_is_matched_whole_and_without_case():
    found = resolver(
        catalog={
            "channels": {},
            "accounts": [
                {"name": "a.json", "provider": "claude", "models": ["CLAUDE-OPUS-4-6"]}
            ],
        }
    ).lengths(["Claude-Opus-4-6", "claude-opus-4"])

    assert found["Claude-Opus-4-6"] == length(200000, 0, 64000)
    assert found["claude-opus-4"] == length(200000, 0, 0)


def test_a_name_an_account_and_a_provider_serve_takes_the_smallest_of_each_number():
    found = resolver(
        providers=[provider("relay", "openai", [{"name": "gpt-6.2-astra"}])],
    ).lengths(["gpt-6.2-astra"])

    assert found["gpt-6.2-astra"] == length(272000, 922000, 128000)


def test_a_provider_with_no_list_serves_its_channel_and_a_custom_one_none():
    view = resolver(
        catalog={"channels": CATALOG["channels"], "accounts": []},
        providers=[provider("api", "openai"), provider("relay", "custom")],
    ).view(["gpt-6.2-astra"])

    assert view["cloud"][0]["sources"] == [
        {"origin": "provider", "id": "api", "name": "api"}
    ]


def test_without_a_stored_read_a_name_takes_its_row_s_smallest_or_200000():
    found = resolver(catalog=None).lengths(["claude-opus-4-6", "gpt-6.2-astra", "x"])

    assert found["claude-opus-4-6"] == length(200000, 0, 64000)
    assert found["gpt-6.2-astra"] == length(272000, 922000, 128000)
    assert found["x"] == length(200000, 0, 0)


def test_a_set_length_replaces_the_window_alone():
    found = resolver(set_lengths={"gpt-6.2-astra": 500000}).lengths(["gpt-6.2-astra"])

    assert found["gpt-6.2-astra"] == length(500000, 0, 128000)


def test_the_cloud_view_names_its_sources_its_set_length_and_its_default():
    view = resolver(
        providers=[provider("relay", "openai", [{"name": "gpt-6.2-astra"}], "p1")],
        set_lengths={"gpt-6.2-astra": 500000},
    ).view(["gpt-6.2-astra", "claude-opus-4-6"])

    assert view["cloud"] == [
        {
            "model": "claude-opus-4-6",
            "sources": [
                {"origin": "account", "id": "claude-person.json", "name": "claude"}
            ],
            "context_length": None,
            "default_context_length": 200000,
        },
        {
            "model": "gpt-6.2-astra",
            "sources": [
                {"origin": "account", "id": "codex-person.json", "name": "codex"},
                {"origin": "provider", "id": "p1", "name": "relay"},
            ],
            "context_length": 500000,
            "default_context_length": 272000,
        },
    ]


# --- an Ollama name's pool ---


def machine(device_id, setting, models) -> AiOllamaPoolMachine:
    return AiOllamaPoolMachine(
        device_id=device_id, name=device_id, setting=setting, models=models
    )


def shown(trained=0, modelfile=0) -> dict:
    return {
        "digest": "d",
        "trained_context_length": trained,
        "modelfile_context_length": modelfile,
    }


def test_an_ollama_name_takes_the_smallest_over_its_pool_of_setting_and_trained():
    found = resolver(
        ollama_machines=[
            machine("a", 65536, {"qwen": shown(trained=32768)}),
            machine("b", 16384, {"qwen": shown(trained=32768)}),
            machine("c", 4096, {"other": shown(trained=8192)}),
        ],
        ollama_names={"qwen"},
    ).lengths(["qwen"])

    assert found["qwen"] == length(16384)


def test_a_modelfile_num_ctx_takes_the_machine_s_setting_s_place():
    found = resolver(
        ollama_machines=[machine("a", 65536, {"qwen-8k": shown(32768, 8192)})],
        ollama_names={"qwen-8k"},
    ).lengths(["qwen-8k"])

    assert found["qwen-8k"] == length(8192)


def test_a_model_not_read_counts_with_its_setting_alone():
    found = resolver(
        ollama_machines=[machine("a", 65536, {"qwen": {}})],
        ollama_names={"qwen"},
    ).lengths(["qwen"])

    assert found["qwen"] == length(65536)


def test_a_name_a_cloud_source_also_serves_takes_the_smaller_and_no_set_length():
    found = resolver(
        ollama_machines=[machine("a", 65536, {"gpt-6.2-astra": shown(trained=32768)})],
        ollama_names={"gpt-6.2-astra"},
        set_lengths={"gpt-6.2-astra": 4096},
    ).lengths(["gpt-6.2-astra"])

    assert found["gpt-6.2-astra"] == length(32768, 0, 128000)


def test_the_ollama_view_names_each_machine_its_sources_and_the_cloud_default():
    view = resolver(
        ollama_machines=[
            AiOllamaPoolMachine(
                device_id="b",
                name="beta",
                setting=16384,
                models={"gpt-6.2-astra": {}},
            ),
            AiOllamaPoolMachine(
                device_id="a",
                name="alpha",
                setting=65536,
                models={"gpt-6.2-astra": shown(32768, 8192)},
            ),
        ],
        ollama_names={"gpt-6.2-astra"},
    ).view(["gpt-6.2-astra"])

    assert view == {
        "cloud": [],
        "ollama": [
            {
                "model": "gpt-6.2-astra",
                "machines": [
                    {
                        "device_id": "a",
                        "name": "alpha",
                        "setting_context_length": 8192,
                        "trained_context_length": 32768,
                    },
                    {
                        "device_id": "b",
                        "name": "beta",
                        "setting_context_length": 16384,
                        "trained_context_length": 0,
                    },
                ],
                "sources": [
                    {"origin": "account", "id": "codex-person.json", "name": "codex"}
                ],
                "cloud_context_length": 272000,
                "context_length": 8192,
            }
        ],
    }


# --- the one number, the files ---


def test_the_one_number_is_the_window_or_a_smaller_longest_prompt():
    assert one_number(length(1050000, 922000, 128000)) == 922000
    assert one_number(length(272000, 0, 128000)) == 272000
    assert one_numbers(["a", "b", "c"], {"a": length(5000), "c": length(0)}) == {
        "a": 5000
    }


def test_set_lengths_are_stored_by_name_and_read_back(monkeypatch, tmp_path):
    monkeypatch.setattr("neutrino_hub.utils.json_file.UTILS_CONFIG_DIR", tmp_path)

    assert read_set_lengths() == {}
    write_set_lengths({"b": 5000, "a": 4096})

    assert json.loads((tmp_path / "ai/context_lengths.json").read_text()) == {
        "lengths": {"a": 4096, "b": 5000}
    }
    assert read_set_lengths() == {"a": 4096, "b": 5000}


def test_the_files_the_lengths_come_from_are_named():
    assert is_context_length_input("ai/providers.json")
    assert is_context_length_input("ai/context_lengths.json")
    assert is_context_length_input("devices/dev-1/ollama.json")
    assert is_context_length_input("devices/dev-1/modules.json")
    assert not is_context_length_input("devices/dev-1/siyuan.json")
    assert not is_context_length_input("cliproxyapi/cliproxyapi.json")


def test_the_shipped_table_holds_exactly_the_rows_of_the_page():
    page = AI_PAGE.read_text(encoding="utf-8")
    section = page.split("### The table of known models", 1)[1]
    section = section.split("### An Ollama name", 1)[0]
    rows = []
    for line in section.splitlines():
        if not line.startswith("| `"):
            continue
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        row = {
            "names": re.findall(r"`([^`]+)`", cells[0]),
            "context_length": int(cells[1] or 0),
            "input_limit": int(cells[2] or 0),
            "output_limit": int(cells[3] or 0),
        }
        if cells[4]:
            window, answer = re.fullmatch(r"(\d+), output (\d+)", cells[4]).groups()
            row["account"] = {
                "context_length": int(window),
                "input_limit": 0,
                "output_limit": int(answer),
            }
        rows.append(row)

    context_lengths._KNOWN_MODELS.clear()
    assert load_known_models() == rows
    assert len(rows) == 34
