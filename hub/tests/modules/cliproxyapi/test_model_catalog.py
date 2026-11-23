"""The gateway's model catalog, read over its management API and stored.

What these pin: each entry's window from ``context_length`` else
``inputTokenLimit`` and its longest answer from ``max_completion_tokens``
else ``outputTokenLimit``; the channels read being those a signed-in account
or a stored provider turned on with a key has; each account's names read for
its token file; the read stored under the state root and read back; an
unchanged read writing nothing; and a read that fails keeping the stored one.
"""

import json

import pytest

from neutrino_hub.exceptions import AiAccountRefusedError
from neutrino_hub.modules.cliproxyapi import model_catalog
from neutrino_hub.modules.cliproxyapi.accounts import CliproxyApiAccount
from neutrino_hub.modules.cliproxyapi.model_catalog import (
    catalog_entry,
    read_model_catalog,
    refresh_model_catalog,
)
from neutrino_hub.modules.ai.registry import AiProviderRecord
from tests.conftest import unlock_vault


def account(name: str, provider: str) -> CliproxyApiAccount:
    return CliproxyApiAccount(
        name=name,
        auth_index="",
        provider=provider,
        label="",
        email="",
        account_type="",
        status="active",
        status_message="",
        is_disabled=False,
        is_unavailable=False,
        failed_count=0,
        success_count=0,
        created_at="",
        updated_at="",
    )


class FakeClient:
    """The management API as the catalog reader calls it."""

    accounts: list = []
    definitions: dict = {}
    account_names: dict = {}
    calls: list = []
    failing: str = ""

    def __init__(self, *, port, management_key):
        del port, management_key

    def list_accounts(self):
        FakeClient.calls.append(("accounts",))
        return list(FakeClient.accounts)

    def account_models(self, name):
        FakeClient.calls.append(("models", name))
        return list(FakeClient.account_names.get(name, []))

    def model_definitions(self, channel):
        FakeClient.calls.append(("definitions", channel))
        if channel == FakeClient.failing:
            raise AiAccountRefusedError("gateway_unreachable")
        return list(FakeClient.definitions.get(channel, []))


@pytest.fixture
def gateway(monkeypatch, tmp_path):
    unlock_vault(monkeypatch, tmp_path)
    FakeClient.accounts = [account("claude-person.json", "claude")]
    FakeClient.definitions = {
        "claude": [
            {
                "id": "claude-opus-5-5",
                "context_length": 1000000,
                "max_completion_tokens": 128000,
            }
        ],
        "gemini": [
            {
                "id": "gemini-4-neon",
                "inputTokenLimit": 1048576,
                "outputTokenLimit": 65536,
            }
        ],
        "codex": [{"id": "gpt-6.2-astra", "context_length": 272000}],
    }
    FakeClient.account_names = {"claude-person.json": ["claude-opus-5-5", "x"]}
    FakeClient.calls = []
    FakeClient.failing = ""
    monkeypatch.setattr(model_catalog, "CliproxyApiAccountClient", FakeClient)
    providers = [
        AiProviderRecord(id="p1", name="g", kind="gemini", secret_id="t1"),
        AiProviderRecord(id="p2", name="o", kind="openai", secret_id=None),
        AiProviderRecord(id="p3", name="c", kind="custom", secret_id="t2"),
    ]
    monkeypatch.setattr(
        model_catalog,
        "AiProviderRegistry",
        lambda: type("Registry", (), {"list_records": lambda self: providers})(),
    )
    return tmp_path / "state"


def test_an_entry_takes_its_window_and_its_longest_answer():
    assert catalog_entry(
        {"id": "a", "context_length": 200000, "max_completion_tokens": 64000}
    ) == {"id": "a", "context_length": 200000, "output_limit": 64000}
    assert catalog_entry(
        {"id": "b", "inputTokenLimit": 1048576, "outputTokenLimit": 65536}
    ) == {"id": "b", "context_length": 1048576, "output_limit": 65536}
    assert catalog_entry({"id": "c"}) == {
        "id": "c",
        "context_length": 0,
        "output_limit": 0,
    }
    assert catalog_entry({"context_length": 5}) is None


def test_a_read_takes_each_source_s_channel_and_each_account_s_names(gateway):
    assert read_model_catalog() is None

    assert refresh_model_catalog(port=8317, management_key="k") is True

    stored = json.loads((gateway / "cliproxyapi/model_catalog.json").read_text())
    assert stored == {
        "channels": {
            "claude": [
                {
                    "id": "claude-opus-5-5",
                    "context_length": 1000000,
                    "output_limit": 128000,
                }
            ],
            "gemini": [
                {
                    "id": "gemini-4-neon",
                    "context_length": 1048576,
                    "output_limit": 65536,
                }
            ],
        },
        "accounts": [
            {
                "name": "claude-person.json",
                "provider": "claude",
                "models": ["claude-opus-5-5", "x"],
            }
        ],
    }
    assert read_model_catalog() == stored
    assert ("definitions", "codex") not in FakeClient.calls


def test_an_unchanged_read_writes_nothing(gateway):
    refresh_model_catalog(port=8317, management_key="k")
    path = gateway / "cliproxyapi/model_catalog.json"
    path.write_text(path.read_text() + "\n")
    before = path.read_text()

    assert refresh_model_catalog(port=8317, management_key="k") is False
    assert path.read_text() == before


def test_a_read_that_fails_keeps_the_stored_read(gateway):
    refresh_model_catalog(port=8317, management_key="k")
    before = read_model_catalog()
    FakeClient.account_names = {"claude-person.json": ["claude-opus-5-5"]}
    FakeClient.failing = "gemini"

    assert refresh_model_catalog(port=8317, management_key="k") is None
    assert read_model_catalog() == before
