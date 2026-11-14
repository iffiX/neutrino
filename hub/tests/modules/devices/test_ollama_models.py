"""A machine's Ollama models through Ollama's own API, and the hub's pulls.

What these pin: a model name the pull form takes and the ones it refuses;
the pulled models joined with the ones in memory; the client's calls over
real HTTP, a missing model a ``KeyError`` and an error line of a pull a
``ConnectionError`` with Ollama's words; the queue running one pull at a time
per machine in the order asked, its progress summed over every layer, a
further pull waiting behind the running one, a cancel ending the running
pull by closing its connection or taking a waiting one off, and a failed
pull kept with ``ollama_pull_failed`` until it is taken off.
"""

import threading
import time

import pytest

from neutrino_hub.modules.devices.ollama_models import (
    OllamaApiClient,
    OllamaPullQueue,
    is_model_name,
    model_rows,
    pull_progress,
)
from tests.modules.devices.ollama_server import FakeOllama

PULL = [
    {"status": "pulling manifest"},
    {"status": "pulling a", "digest": "sha256:a", "total": 1000},
    {"status": "pulling a", "digest": "sha256:a", "total": 1000, "completed": 600},
    {"status": "pulling b", "digest": "sha256:b", "total": 200, "completed": 200},
    {"status": "verifying sha256 digest"},
    {"status": "success"},
]


@pytest.fixture
def ollama():
    server = FakeOllama().start()
    yield server
    server.stop()


def _until(predicate, timeout=10.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.02)
    return False


def test_a_model_name_is_one_ollama_takes():
    for name in (
        "qwen2.5:0.5b",
        "llama3.2",
        "hf.co/unsloth/SmolLM2-135M-Instruct-GGUF:Q4_K_M",
        "modelscope.cn/unsloth/SmolLM2-135M-Instruct-GGUF:Q4_K_M",
    ):
        assert is_model_name(name), name
    for name in ("", " qwen", "-x", "a b", "a;b", "a/../b", "x" * 201):
        assert not is_model_name(name), name


def test_the_pulled_models_are_joined_with_the_ones_in_memory():
    tags = {
        "models": [
            {
                "name": "qwen2.5:0.5b",
                "size": 397821319,
                "modified_at": "2026-11-14T08:00:00Z",
                "details": {
                    "parameter_size": "494.03M",
                    "quantization_level": "Q4_K_M",
                },
            },
            {"name": "a:1", "size": 10},
        ]
    }
    ps = {"models": [{"name": "qwen2.5:0.5b", "size": 486000000, "size_vram": 0}]}
    rows = model_rows(tags, ps)
    assert [row["name"] for row in rows] == ["a:1", "qwen2.5:0.5b"]
    assert rows[1] == {
        "name": "qwen2.5:0.5b",
        "parameter_size": "494.03M",
        "quantization": "Q4_K_M",
        "size_bytes": 397821319,
        "modified_at": "2026-11-14T08:00:00Z",
        "is_loaded": True,
        "memory_bytes": 486000000,
        "vram_bytes": 0,
    }
    assert rows[0]["is_loaded"] is False


def test_a_pull_s_progress_sums_every_layer():
    assert pull_progress({}) == (0, 0)
    assert pull_progress({"a": (600, 1000), "b": (200, 200)}) == (800, 1200)


def test_the_client_lists_removes_and_unloads_over_http(ollama):
    ollama.models = [{"name": "qwen2.5:0.5b", "size": 1}]
    ollama.loaded = [{"name": "qwen2.5:0.5b", "size": 2, "size_vram": 0}]
    client = OllamaApiClient(ollama.address)
    assert client.tags()["models"][0]["name"] == "qwen2.5:0.5b"
    assert client.ps()["models"][0]["size"] == 2
    client.unload("qwen2.5:0.5b")
    assert (
        "POST",
        "/api/generate",
        {"model": "qwen2.5:0.5b", "keep_alive": 0, "stream": False},
    ) in ollama.requests
    client.delete("qwen2.5:0.5b")
    assert ollama.models == []
    with pytest.raises(KeyError):
        client.delete("qwen2.5:0.5b")


def test_a_client_that_reaches_nothing_raises_connection_error():
    with pytest.raises(ConnectionError):
        OllamaApiClient("127.0.0.1:9", timeout_s=1).tags()


def test_a_pull_streams_its_lines_and_an_error_line_fails_it(ollama):
    ollama.pull_lines["qwen2.5:0.5b"] = PULL
    seen = []
    OllamaApiClient(ollama.address).pull("qwen2.5:0.5b", on_line=seen.append)
    assert seen[-1] == {"status": "success"}
    with pytest.raises(ConnectionError) as failed:
        OllamaApiClient(ollama.address).pull("nothing:1", on_line=seen.append)
    assert "file does not exist" in str(failed.value)


def test_the_queue_runs_one_pull_at_a_time_in_order(ollama):
    ollama.pull_lines["a:1"] = PULL
    ollama.pull_lines["b:1"] = PULL
    ollama.gate.clear()
    queue = OllamaPullQueue(address_of=lambda device: ollama.address)
    queue.add("dev", "a:1")
    queue.add("dev", "b:1")
    queue.add("dev", "a:1")
    assert _until(lambda: queue.pulls("dev")[0]["state"] == "running")
    assert [(pull["name"], pull["state"]) for pull in queue.pulls("dev")] == [
        ("a:1", "running"),
        ("b:1", "queued"),
    ]
    assert queue.is_busy("dev") is True
    ollama.gate.set()
    assert _until(lambda: queue.pulls("dev") == [])
    pulls = [
        body["model"] for method, path, body in ollama.requests if path == "/api/pull"
    ]
    assert pulls == ["a:1", "b:1"]
    assert queue.is_busy("dev") is False


def test_a_running_pull_keeps_its_progress_and_a_cancel_ends_it(ollama):
    ollama.pull_lines["a:1"] = PULL
    ollama.gate.clear()
    ticks = iter(range(0, 10**6))
    queue = OllamaPullQueue(
        address_of=lambda device: ollama.address, clock=lambda: next(ticks)
    )
    queue.add("dev", "a:1")
    queue.add("dev", "b:1")
    assert _until(lambda: queue.pulls("dev")[0]["state"] == "running")
    assert queue.cancel("dev", "b:1") is True
    assert [pull["name"] for pull in queue.pulls("dev")] == ["a:1"]
    assert queue.cancel("dev", "a:1") is True
    assert queue.pulls("dev") == []
    assert queue.cancel("dev", "a:1") is False
    ollama.gate.set()
    time.sleep(0.2)
    assert queue.pulls("dev") == []
    assert not any(model["name"] == "a:1" for model in ollama.models)


def test_the_progress_is_the_sum_of_the_layers(ollama):
    lines = PULL[:3]
    ollama.pull_lines["a:1"] = lines + [{"status": "x"}] * 3
    progress = []
    done = threading.Event()
    queue = OllamaPullQueue(address_of=lambda device: ollama.address)

    original = queue._run

    def watched(device_id, pull):
        original(device_id, pull)
        progress.append((pull.completed_bytes, pull.total_bytes))
        done.set()

    queue._run = watched
    queue.add("dev", "a:1")
    assert done.wait(10)
    assert progress == [(600, 1000)]


def test_a_failed_pull_stays_with_its_code_until_taken_off(ollama):
    queue = OllamaPullQueue(address_of=lambda device: ollama.address)
    queue.add("dev", "nothing:1")
    assert _until(lambda: queue.pulls("dev")[0]["state"] == "failed")
    failed = queue.pulls("dev")[0]
    assert failed["code"] == "ollama_pull_failed"
    assert failed["params"]["name"] == "nothing:1"
    assert "file does not exist" in failed["params"]["detail"]
    assert queue.is_busy("dev") is False
    assert queue.cancel("dev", "nothing:1") is True
    assert queue.pulls("dev") == []


def test_a_machine_that_cannot_be_reached_fails_its_pull():
    def unreachable(device):
        raise ConnectionError("agent_offline")

    queue = OllamaPullQueue(address_of=unreachable)
    queue.add("dev", "a:1")
    assert _until(lambda: queue.pulls("dev")[0]["state"] == "failed")
    assert queue.pulls("dev")[0]["params"]["detail"] == "agent_offline"
