"""The YAML renderer: provider buckets, aliases, and what gets left out."""

import yaml

from neutrino_hub.modules.cliproxyapi.config import CliproxyApiConfig
from neutrino_hub.modules.cliproxyapi.renderer import CliproxyApiConfigRenderer
from neutrino_hub.modules.ai.registry import AiProviderRecord


def _provider(**overrides) -> AiProviderRecord:
    base = dict(
        id="p1",
        name="Anthropic direct",
        kind="anthropic",
        base_url="",
        secret_id="s1",
        is_enabled=True,
        models=[],
        created_at="2026-01-01T00:00:00+00:00",
    )
    base.update(overrides)
    return AiProviderRecord(**base)


def _render(providers, api_keys, management_key: str = "") -> dict:
    text = CliproxyApiConfigRenderer(
        config=CliproxyApiConfig(listen_port=8317),
        providers=providers,
        api_keys=api_keys,
        client_keys=["client-key-1"],
        management_key=management_key,
    ).render()
    return yaml.safe_load(text)


def test_kinds_land_in_their_blocks():
    document = _render(
        [
            _provider(),
            _provider(id="p2", kind="openai"),
            _provider(id="p3", kind="gemini"),
            _provider(
                id="p4",
                kind="custom",
                name="My Relay",
                base_url="https://relay.example/v1",
            ),
        ],
        {"p1": "sk-x", "p2": "sk-o", "p3": "AI-g", "p4": "rk"},
    )
    assert document["claude-api-key"][0]["api-key"] == "sk-x"
    assert document["codex-api-key"][0]["api-key"] == "sk-o"
    assert document["gemini-api-key"][0]["api-key"] == "AI-g"
    compat = document["openai-compatibility"][0]
    assert compat["name"] == "my-relay"
    assert compat["api-key-entries"] == [{"api-key": "rk"}]
    assert document["api-keys"] == ["client-key-1"]
    assert document["port"] == 8317


def test_disabled_and_keyless_providers_are_left_out():
    document = _render(
        [
            _provider(is_enabled=False),
            _provider(id="p2"),
            _provider(id="p3"),
        ],
        {"p1": "sk-x", "p2": ""},
    )
    assert "claude-api-key" not in document


def test_model_aliases_render_with_alias_defaulting_to_name():
    document = _render(
        [
            _provider(
                models=[
                    {"name": "claude-fable-5", "alias": "fast"},
                    {"name": "claude-opus-5"},
                    {"name": "   "},
                ]
            )
        ],
        {"p1": "sk-x"},
    )
    models = document["claude-api-key"][0]["models"]
    assert models == [
        {"name": "claude-fable-5", "alias": "fast"},
        {"name": "claude-opus-5", "alias": "claude-opus-5"},
    ]


def test_base_url_is_omitted_when_empty():
    document = _render([_provider()], {"p1": "sk-x"})
    assert "base-url" not in document["claude-api-key"][0]


def test_a_management_key_turns_metering_on():
    document = _render([], {}, management_key="mk-1")
    assert document["usage-statistics-enabled"] is True
    assert document["remote-management"] == {
        "allow-remote": False,
        "disable-control-panel": True,
        "secret-key": "mk-1",
    }


def test_no_management_key_leaves_the_management_api_off():
    document = _render([], {})
    assert "remote-management" not in document
    assert "usage-statistics-enabled" not in document


def test_provider_blocks_follow_the_given_order():
    document = _render(
        [
            _provider(id="p2", kind="custom", name="Second", base_url="https://b/v1"),
            _provider(id="p1", kind="custom", name="First", base_url="https://a/v1"),
        ],
        {"p1": "k1", "p2": "k2"},
    )
    names = [entry["name"] for entry in document["openai-compatibility"]]
    assert names == ["second", "first"]
