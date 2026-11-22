"""The Ollama block: the module's row, its models through the hub's forward, and its pulls.

What these pin: the view lists no model while the machine reports the
server not running or the machine is offline, and the models with their
total size through Ollama's API while it runs, and says
``ollama_unreachable`` when the call fails; a pull is refused for a name
Ollama does not take and for a machine whose server does not run, and is
otherwise queued and shown; a cancel of no such pull answers 404; a remove
of a model the machine does not have answers 404, and a remove and an
unload change what the next view lists. The settings: the view's defaults
while none are stored and the machine's resources from its last report;
``set`` storing them beside ``kept_models`` after the agent checked them
without ``kept_models``, and refusing a value outside the choices. A load
keeps a pulled model's name and starts its load, refuses a name the
machine does not hold, and an unload and a remove take the name off.
"""

import time

import pytest

from neutrino_hub.modules.devices.ollama_models import OllamaPullQueue
from neutrino_hub.web.routers.agent import module as device_modules
from neutrino_hub.web.routers.agent import module_ollama
from tests.modules.devices.ollama_server import FakeOllama
from tests.web.module_api_box import DEVICE, OFFLINE, module_box

BASE = "/api/agent/module/ollama"
MODEL = {
    "name": "qwen2.5:0.5b",
    "size": 397821319,
    "modified_at": "2026-11-14T08:00:00Z",
    "details": {"parameter_size": "494.03M", "quantization_level": "Q4_K_M"},
}


@pytest.fixture
def api(monkeypatch, tmp_path):
    server = FakeOllama().start()
    client, runtime = module_box(
        monkeypatch, tmp_path, [device_modules.router, module_ollama.router]
    )
    runtime.ollama_address = lambda device_id: server.address
    runtime.ollama_pulls = OllamaPullQueue(address_of=runtime.ollama_address)
    with client:
        yield client, runtime, server
    server.stop()


def view(client, device=DEVICE) -> dict:
    return client.get(BASE, params={"device_id": device}).json()


def test_no_model_is_listed_while_the_server_does_not_run(api):
    client, runtime, server = api
    server.models = [MODEL]
    runtime.report(DEVICE, "ollama", state="stopped", is_running=False, port=11434)
    held = view(client)
    assert (held["state"], held["is_running"], held["models"]) == ("stopped", False, [])
    runtime.report(OFFLINE, "ollama", state="running", is_running=True, port=11434)
    assert view(client, OFFLINE)["models"] == []


def test_the_models_and_their_total_are_listed_while_it_runs(api):
    client, runtime, server = api
    server.models = [MODEL, dict(MODEL, name="a:1", size=3)]
    server.loaded = [{"name": "a:1", "size": 7, "size_vram": 2}]
    runtime.report(
        DEVICE,
        "ollama",
        state="running",
        is_running=True,
        port=11434,
        version="0.40.16",
    )
    held = view(client)
    assert held["is_running"] is True
    assert held["version"] == "0.40.16"
    assert [model["name"] for model in held["models"]] == ["a:1", "qwen2.5:0.5b"]
    assert held["total_bytes"] == 397821322
    assert held["models"][0]["is_loaded"] is True
    assert held["models"][0]["vram_bytes"] == 2
    assert held["code"] == ""


def test_a_call_that_does_not_reach_ollama_says_so(api):
    client, runtime, server = api
    runtime.ollama_address = lambda device_id: "127.0.0.1:9"
    runtime.report(DEVICE, "ollama", state="running", is_running=True, port=11434)
    held = view(client)
    assert held["code"] == "ollama_unreachable"
    assert held["models"] == []


def test_a_pull_is_refused_for_a_bad_name_and_a_server_that_does_not_run(api):
    client, runtime, server = api
    runtime.report(DEVICE, "ollama", state="stopped", is_running=False, port=11434)
    answer = client.post(f"{BASE}/model/add", json={"device_id": DEVICE, "name": "a b"})
    assert answer.status_code == 400
    assert answer.json()["detail"]["code"] == "ollama_model_name_invalid"
    answer = client.post(f"{BASE}/model/add", json={"device_id": DEVICE, "name": "a:1"})
    assert answer.status_code == 409
    assert answer.json()["detail"]["code"] == "ollama_not_running"
    answer = client.post(
        f"{BASE}/model/add", json={"device_id": OFFLINE, "name": "a:1"}
    )
    assert answer.json()["detail"]["code"] == "agent_offline"


def test_a_pull_is_queued_and_shown_until_it_lands(api):
    client, runtime, server = api
    server.pull_lines["qwen2.5:0.5b"] = [
        {"status": "pulling manifest"},
        {"status": "pulling a", "digest": "sha256:a", "total": 100, "completed": 100},
        {"status": "success"},
    ]
    server.gate.clear()
    runtime.report(DEVICE, "ollama", state="running", is_running=True, port=11434)
    answer = client.post(
        f"{BASE}/model/add", json={"device_id": DEVICE, "name": "qwen2.5:0.5b"}
    )
    assert answer.status_code == 200
    assert [pull["name"] for pull in answer.json()["pulls"]] == ["qwen2.5:0.5b"]
    server.gate.set()
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline and view(client)["pulls"]:
        time.sleep(0.05)
    held = view(client)
    assert held["pulls"] == []
    assert [model["name"] for model in held["models"]] == ["qwen2.5:0.5b"]


def test_a_cancel_of_no_such_pull_answers_404(api):
    client, runtime, server = api
    runtime.report(DEVICE, "ollama", state="running", is_running=True, port=11434)
    answer = client.post(
        f"{BASE}/pull/remove", json={"device_id": DEVICE, "name": "a:1"}
    )
    assert answer.status_code == 404
    assert answer.json()["detail"]["code"] == "ollama_pull_unknown"


def test_a_remove_and_an_unload_change_the_next_view(api):
    client, runtime, server = api
    server.models = [MODEL]
    server.loaded = [{"name": "qwen2.5:0.5b", "size": 7, "size_vram": 0}]
    runtime.report(DEVICE, "ollama", state="running", is_running=True, port=11434)
    answer = client.post(
        f"{BASE}/loaded/remove", json={"device_id": DEVICE, "name": "qwen2.5:0.5b"}
    )
    assert answer.json()["models"][0]["is_loaded"] is False
    answer = client.post(
        f"{BASE}/model/remove", json={"device_id": DEVICE, "name": "qwen2.5:0.5b"}
    )
    assert answer.status_code == 200
    assert answer.json()["models"] == []
    answer = client.post(
        f"{BASE}/model/remove", json={"device_id": DEVICE, "name": "qwen2.5:0.5b"}
    )
    assert answer.status_code == 404
    assert answer.json()["detail"]["code"] == "ollama_model_unknown"


def test_a_remove_reads_the_machines_models_again_for_the_gateway(api):
    client, runtime, server = api
    server.models = [MODEL]
    runtime.report(DEVICE, "ollama", state="running", is_running=True, port=11434)
    client.post(
        f"{BASE}/model/remove", json={"device_id": DEVICE, "name": "qwen2.5:0.5b"}
    )
    assert runtime.ollama_gateway.refreshed == [DEVICE]


def _stored(runtime) -> dict:
    return runtime.desired_states.read(DEVICE, "ollama")


def test_the_view_carries_the_default_settings_and_the_machine_s_resources(api):
    client, runtime, server = api
    runtime.report(DEVICE, "ollama", state="running", is_running=True, port=11434)
    held = view(client)
    assert (held["keep_alive"], held["gpus"]) == ("30m", None)
    assert held["resources"] == {
        "gpus": [],
        "memory_used_mb": None,
        "memory_total_mb": None,
    }
    gpu = {"vendor": "nvidia", "name": "RTX 4090", "memory_used_mb": 2048}
    runtime.device_metrics[DEVICE] = {
        "memory_percent": 25.0,
        "memory_total_mb": 16000,
        "gpus": [dict(gpu, memory_total_mb=24564)],
    }
    resources = view(client)["resources"]
    assert (resources["memory_used_mb"], resources["memory_total_mb"]) == (4000, 16000)
    assert resources["gpus"][0]["name"] == "RTX 4090"
    assert resources["gpus"][0]["memory_total_mb"] == 24564


def test_set_stores_the_settings_beside_the_kept_models(api):
    client, runtime, server = api
    runtime.desired_states.write(DEVICE, "ollama", {"kept_models": ["a:1"]})
    runtime.report(DEVICE, "ollama", state="running", is_running=True, port=11434)
    gpus = [
        {"vendor": "nvidia", "is_used": True},
        {"vendor": "nvidia", "is_used": False},
    ]
    answer = client.post(
        f"{BASE}/set", json={"device_id": DEVICE, "keep_alive": "1h", "gpus": gpus}
    )
    assert answer.status_code == 200
    assert (answer.json()["keep_alive"], answer.json()["gpus"]) == ("1h", gpus)
    assert _stored(runtime) == {
        "kept_models": ["a:1"],
        "keep_alive": "1h",
        "gpus": gpus,
    }
    assert runtime.agent_sessions.validations[-1][2] == {
        "keep_alive": "1h",
        "gpus": gpus,
    }
    assert runtime.agent_sessions.pushes
    answer = client.post(
        f"{BASE}/set", json={"device_id": DEVICE, "keep_alive": "-1", "gpus": None}
    )
    assert answer.status_code == 200
    assert _stored(runtime) == {"kept_models": ["a:1"], "keep_alive": "-1"}
    assert runtime.agent_sessions.validations[-1][2] == {"keep_alive": "-1"}


def test_set_refuses_a_value_outside_the_choices(api):
    client, runtime, server = api
    for body in (
        {"keep_alive": "2h"},
        {"keep_alive": "30m", "gpus": [{"vendor": "nvidia"}]},
    ):
        answer = client.post(f"{BASE}/set", json={"device_id": DEVICE, **body})
        assert answer.status_code == 422
    answer = client.post(f"{BASE}/set", json={"device_id": OFFLINE, "keep_alive": "5m"})
    assert answer.json()["detail"]["code"] == "agent_offline"
    assert _stored(runtime) == {}


def test_a_load_keeps_a_pulled_model_and_starts_its_load(api):
    client, runtime, server = api
    server.models = [MODEL]
    runtime.report(DEVICE, "ollama", state="running", is_running=True, port=11434)
    runtime.ollama_kept.in_flight[DEVICE] = {"qwen2.5:0.5b"}
    answer = client.post(
        f"{BASE}/loaded/add", json={"device_id": DEVICE, "name": "qwen2.5:0.5b"}
    )
    assert answer.status_code == 200
    assert answer.json()["models"][0]["is_loading"] is True
    assert _stored(runtime) == {"kept_models": ["qwen2.5:0.5b"]}
    assert runtime.ollama_kept.loads == [(DEVICE, server.address, "qwen2.5:0.5b")]
    assert runtime.agent_sessions.pushes == []
    answer = client.post(
        f"{BASE}/loaded/add", json={"device_id": DEVICE, "name": "x:1"}
    )
    assert answer.status_code == 404
    assert answer.json()["detail"]["code"] == "ollama_model_unknown"
    runtime.report(DEVICE, "ollama", state="stopped", is_running=False, port=11434)
    answer = client.post(
        f"{BASE}/loaded/add", json={"device_id": DEVICE, "name": "qwen2.5:0.5b"}
    )
    assert answer.json()["detail"]["code"] == "ollama_not_running"


def test_an_unload_and_a_remove_take_the_name_off(api):
    client, runtime, server = api
    server.models = [MODEL, dict(MODEL, name="a:1")]
    runtime.desired_states.write(
        DEVICE, "ollama", {"keep_alive": "5m", "kept_models": ["qwen2.5:0.5b", "a:1"]}
    )
    runtime.report(DEVICE, "ollama", state="running", is_running=True, port=11434)
    client.post(f"{BASE}/loaded/remove", json={"device_id": DEVICE, "name": "a:1"})
    assert _stored(runtime) == {"keep_alive": "5m", "kept_models": ["qwen2.5:0.5b"]}
    client.post(
        f"{BASE}/model/remove", json={"device_id": DEVICE, "name": "qwen2.5:0.5b"}
    )
    assert _stored(runtime) == {"keep_alive": "5m", "kept_models": []}
