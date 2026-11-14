"""The gateway's providers generated from each machine's Ollama.

What these pin: a followed machine whose ``/api/tags`` lists a model is a
provider at its forward's address with Ollama's own names, and the list is
stored under the state root; the same name on two machines is in both; a
machine taken out at once, with no read, and when it lists no model; a
follow at a new forward port writing the new address; a failed read keeping
the provider; a follow at the same address reading nothing; the 30-second
read finding a model pulled on the machine and taking out a stored provider
no report followed; a new control connection keeping every provider and
following none; a refresh of a machine it does not follow reading
nothing; and the thread settling a follow by itself.
"""

import json
import time

import pytest

from neutrino_hub.modules.devices.ollama_gateway import OllamaGatewayProviderTable
from tests.conftest import unlock_vault
from tests.modules.devices.ollama_server import FakeOllama

QWEN = {"name": "qwen2.5:0.5b", "size": 397821319, "details": {}}
SMOLLM = {"name": "smollm2:135m", "size": 270898672, "details": {}}
CLOSED = "127.0.0.1:9"


@pytest.fixture
def state(monkeypatch, tmp_path):
    unlock_vault(monkeypatch, tmp_path)
    return tmp_path / "state"


@pytest.fixture
def ollama():
    server = FakeOllama().start()
    yield server
    server.stop()


@pytest.fixture
def second():
    server = FakeOllama().start()
    yield server
    server.stop()


class Changes:
    """The table's ``on_change``, counting its calls."""

    def __init__(self):
        self.count = 0

    def __call__(self):
        self.count += 1


def _stored(state) -> list:
    path = state / "cliproxyapi" / "ollama_providers.json"
    return json.loads(path.read_text(encoding="utf-8"))["providers"]


def _tags_reads(server) -> int:
    return sum(1 for _, path, _ in server.requests if path == "/api/tags")


def test_a_followed_machine_with_a_model_is_a_provider(state, ollama):
    ollama.models = [QWEN]
    changes = Changes()
    table = OllamaGatewayProviderTable(on_change=changes)
    table.follow("dev", ollama.address)

    assert table.settle() is True

    expected = [
        {"device_id": "dev", "address": ollama.address, "models": ["qwen2.5:0.5b"]}
    ]
    assert table.providers() == expected
    assert _stored(state) == expected
    assert changes.count == 1
    assert table.settle() is False
    assert changes.count == 1


def test_the_same_name_on_two_machines_is_in_both(state, ollama, second):
    ollama.models = [QWEN]
    second.models = [QWEN, SMOLLM]
    table = OllamaGatewayProviderTable(on_change=Changes())
    table.follow("a", ollama.address)
    table.follow("b", second.address)
    table.settle()

    assert [(held["device_id"], held["models"]) for held in table.providers()] == [
        ("a", ["qwen2.5:0.5b"]),
        ("b", ["qwen2.5:0.5b", "smollm2:135m"]),
    ]


def test_a_machine_that_lists_no_model_is_no_provider(state, ollama):
    table = OllamaGatewayProviderTable(on_change=Changes())
    table.follow("dev", ollama.address)
    table.settle()
    assert table.providers() == []

    ollama.models = [QWEN]
    table.refresh("dev")
    table.settle()
    assert [held["models"] for held in table.providers()] == [["qwen2.5:0.5b"]]

    ollama.models = []
    table.refresh("dev")
    table.settle()
    assert table.providers() == []
    assert _stored(state) == []


def test_a_dropped_machine_leaves_at_once_with_no_read(state, ollama):
    ollama.models = [QWEN]
    changes = Changes()
    table = OllamaGatewayProviderTable(on_change=changes)
    table.follow("dev", ollama.address)
    table.settle()
    reads = _tags_reads(ollama)

    table.drop("dev")
    assert table.settle() is True

    assert table.providers() == []
    assert _stored(state) == []
    assert _tags_reads(ollama) == reads
    assert changes.count == 2


def test_a_follow_at_a_new_port_writes_the_new_address(state, ollama, second):
    ollama.models = [QWEN]
    second.models = [QWEN]
    table = OllamaGatewayProviderTable(on_change=Changes())
    table.follow("dev", ollama.address)
    table.settle()

    table.follow("dev", second.address)
    table.settle()

    assert table.providers() == [
        {"device_id": "dev", "address": second.address, "models": ["qwen2.5:0.5b"]}
    ]
    assert _tags_reads(second) == 1


def test_a_failed_read_keeps_the_provider_at_the_forwards_address(state, ollama):
    ollama.models = [QWEN]
    table = OllamaGatewayProviderTable(on_change=Changes())
    table.follow("dev", ollama.address)
    table.settle()

    table.follow("dev", CLOSED)
    table.settle()

    assert table.providers() == [
        {"device_id": "dev", "address": CLOSED, "models": ["qwen2.5:0.5b"]}
    ]


def test_a_follow_at_the_same_address_reads_nothing(state, ollama):
    ollama.models = [QWEN]
    table = OllamaGatewayProviderTable(on_change=Changes())
    table.follow("dev", ollama.address)
    table.settle()

    table.follow("dev", ollama.address)
    assert table.settle() is False
    assert _tags_reads(ollama) == 1


def test_the_periodic_read_finds_a_model_pulled_on_the_machine(state, ollama):
    ollama.models = [QWEN]
    table = OllamaGatewayProviderTable(on_change=Changes())
    table.follow("dev", ollama.address)
    table.settle()

    ollama.models = [QWEN, SMOLLM]
    assert table.settle() is False
    assert table.settle(is_tick=True) is True

    assert table.providers()[0]["models"] == ["qwen2.5:0.5b", "smollm2:135m"]


def test_the_periodic_read_takes_out_a_stored_provider_no_report_followed(
    state, ollama
):
    (state / "cliproxyapi").mkdir(parents=True)
    (state / "cliproxyapi" / "ollama_providers.json").write_text(
        json.dumps(
            {
                "providers": [
                    {"device_id": "gone", "address": CLOSED, "models": ["a:1"]},
                    {"device_id": "dev", "address": CLOSED, "models": ["a:1"]},
                ]
            }
        )
    )
    ollama.models = [QWEN]
    table = OllamaGatewayProviderTable(on_change=Changes())
    assert [held["device_id"] for held in table.providers()] == ["dev", "gone"]

    table.follow("dev", ollama.address)
    table.settle()
    assert [held["device_id"] for held in table.providers()] == ["dev", "gone"]
    assert table.providers()[0]["address"] == ollama.address

    table.settle(is_tick=True)
    assert [held["device_id"] for held in table.providers()] == ["dev"]
    assert [held["device_id"] for held in _stored(state)] == ["dev"]


def test_a_new_control_connection_keeps_every_provider_and_follows_none(state, ollama):
    ollama.models = [QWEN]
    table = OllamaGatewayProviderTable(on_change=Changes())
    table.follow("dev", ollama.address)
    table.settle()

    table.forget_all()
    assert table.settle() is False
    assert [held["device_id"] for held in table.providers()] == ["dev"]

    table.follow("dev", ollama.address)
    table.settle()
    assert _tags_reads(ollama) == 2
    table.forget_all()
    table.settle(is_tick=True)
    assert table.providers() == []


def test_a_refresh_of_a_machine_not_followed_reads_nothing(state, ollama):
    ollama.models = [QWEN]
    table = OllamaGatewayProviderTable(on_change=Changes())
    table.refresh("dev")

    assert table.settle() is False
    assert _tags_reads(ollama) == 0


def test_the_thread_settles_a_follow_by_itself(state, ollama):
    ollama.models = [QWEN]
    table = OllamaGatewayProviderTable(on_change=Changes())
    table.start()
    try:
        table.follow("dev", ollama.address)
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline and not table.providers():
            time.sleep(0.02)
        assert [held["device_id"] for held in table.providers()] == ["dev"]
    finally:
        table.stop()
