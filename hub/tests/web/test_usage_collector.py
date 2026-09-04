"""The usage collector: what one poll pops, maps, and folds into the store."""

import json

import pytest

from neutrino_hub.modules.cliproxyapi.config import (
    CliproxyApiClientKey,
    CliproxyApiConfig,
)
from neutrino_hub.modules.cliproxyapi.constants import CLIPROXYAPI_CLIENT_KEY_AAD
from neutrino_hub.modules.cliproxyapi.usage_store import CliproxyApiUsageStore
from neutrino_hub.modules.credentials.vault import seal_bytes
from neutrino_hub.web import usage_collector as collector_module
from neutrino_hub.web.usage_collector import PanelUsageCollector
from tests.conftest import unlock_vault

# One success and one failure, as CLIProxyAPI 7.2.146's usage-queue answers
# them, trimmed to the fields the pipeline reads.
QUEUE_ANSWER = [
    {
        "timestamp": "2026-09-04T06:16:24.186798+08:00",
        "api_key": "client-key-one",
        "source": "sk-upstream",
        "provider": "openai-compatible-relay",
        "failed": False,
        "token_breakdown": {
            "input": {
                "total_tokens": 120,
                "cache_read_tokens": 40,
                "cache_write_tokens": 0,
            },
            "output": {"total_tokens": 30},
        },
    },
    {
        "timestamp": "2026-09-04T06:17:07.520137+08:00",
        "api_key": "client-key-one",
        "source": "sk-upstream",
        "provider": "openai-compatible-relay",
        "failed": True,
        "token_breakdown": {
            "input": {
                "total_tokens": 0,
                "cache_read_tokens": 0,
                "cache_write_tokens": 0,
            },
            "output": {"total_tokens": 0},
        },
    },
]


class FakeResponse:
    def __init__(self, payload, *, status_code=200):
        self._payload = payload
        self.is_success = status_code == 200

    def json(self):
        return self._payload


class FakeRegistry:
    def __init__(self):
        pass

    def list_records(self):
        record = type("Record", (), {"id": "p1", "is_enabled": True, "secret_id": "s1"})
        return [record()]

    def open_api_key(self, record):
        return "sk-upstream"


@pytest.fixture
def collector(monkeypatch, tmp_path):
    unlock_vault(monkeypatch, tmp_path)
    config = CliproxyApiConfig(
        listen_port=18317,
        client_keys=[
            CliproxyApiClientKey(
                id="k1",
                name="laptop",
                key_sealed=seal_bytes(b"client-key-one", CLIPROXYAPI_CLIENT_KEY_AAD),
            )
        ],
    )
    monkeypatch.setattr(collector_module, "load_config", lambda: config)
    monkeypatch.setattr(collector_module, "read_management_key", lambda: "mk-test")
    monkeypatch.setattr(collector_module, "AiProviderRegistry", FakeRegistry)
    return PanelUsageCollector(
        store=CliproxyApiUsageStore(path=tmp_path / "usage.json")
    )


def test_a_poll_pops_maps_and_folds(collector, monkeypatch, tmp_path):
    seen = {}

    def fake_get(url, *, params, headers, timeout):
        seen["url"] = url
        seen["params"] = params
        seen["headers"] = headers
        return FakeResponse(QUEUE_ANSWER)

    monkeypatch.setattr(collector_module.httpx, "get", fake_get)
    assert collector.poll_once() == 2
    assert seen["url"] == "http://127.0.0.1:18317/v0/management/usage-queue"
    assert seen["headers"] == {"authorization": "Bearer mk-test"}
    assert seen["params"] == {"count": 1000}

    data = json.loads((tmp_path / "usage.json").read_text())
    cell = data["cells"]["k1|p1"]
    day = cell["days"]["2026-09-03"]
    assert day["requests"] == 2
    assert day["failed"] == 1
    assert day["input_tokens"] == 120
    assert data["keys"]["k1"]["name"] == "laptop"


def test_a_missing_key_or_a_dead_gateway_is_a_quiet_zero(collector, monkeypatch):
    def refuse(*args, **kwargs):
        raise collector_module.httpx.ConnectError("down")

    monkeypatch.setattr(collector_module.httpx, "get", refuse)
    assert collector.poll_once() == 0

    monkeypatch.setattr(collector_module, "read_management_key", lambda: "")
    assert collector.poll_once() == 0


def test_a_locked_vault_folds_nothing(collector, monkeypatch, tmp_path):
    """No data key means no key map, and a record folded onto no key is worse."""
    monkeypatch.setattr(
        collector_module.httpx, "get", lambda *a, **k: FakeResponse(QUEUE_ANSWER)
    )
    monkeypatch.setattr(
        "neutrino_hub.utils.constants.UTILS_STATE_ROOT", tmp_path / "locked"
    )
    assert collector.poll_once() == 0
    assert not (tmp_path / "usage.json").exists()


def test_a_refusal_and_junk_bodies_fold_nothing(collector, monkeypatch):
    monkeypatch.setattr(
        collector_module.httpx,
        "get",
        lambda *a, **k: FakeResponse({"detail": "no"}, status_code=401),
    )
    assert collector.poll_once() == 0
    monkeypatch.setattr(
        collector_module.httpx, "get", lambda *a, **k: FakeResponse("not a list")
    )
    assert collector.poll_once() == 0
