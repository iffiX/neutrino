"""A machine's Ollama models through Ollama's own API, and the hub's pulls.

What these pin: a model name the pull form takes and the ones it refuses;
the pulled models joined with the ones in memory, those listed first, each
in memory with the context length ``/api/ps`` names, and a model being
loaded marked; the client's calls over real HTTP, a load with
``keep_alive`` -1, a missing model a ``KeyError`` and an error line of a pull a
``ConnectionError`` with Ollama's words; the queue running one pull at a time
per machine in the order asked, its progress summed over every layer, a
further pull waiting behind the running one, a cancel ending the running
pull by closing its connection or taking a waiting one off, and a failed
pull kept with ``ollama_pull_failed`` until it is taken off; a cancel while
the pull reads the size line of a chunk raising nothing out of the worker,
the queue running on after it.
"""

import logging
import sys
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


def _threads(name):
    return [thread for thread in threading.enumerate() if thread.name == name]


def _waits_for_a_chunk(name):
    """Whether a thread of the name is reading the size line of the next chunk."""
    frames = sys._current_frames()
    for thread in _threads(name):
        frame = frames.get(thread.ident)
        while frame is not None:
            if frame.f_code.co_name == "_read_next_chunk_size":
                return True
            frame = frame.f_back
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
    ps = {
        "models": [
            {
                "name": "qwen2.5:0.5b",
                "size": 486000000,
                "size_vram": 0,
                "context_length": 32768,
            }
        ]
    }
    rows = model_rows(tags, ps)
    assert [row["name"] for row in rows] == ["qwen2.5:0.5b", "a:1"]
    assert rows[0] == {
        "name": "qwen2.5:0.5b",
        "parameter_size": "494.03M",
        "quantization": "Q4_K_M",
        "size_bytes": 397821319,
        "modified_at": "2026-11-14T08:00:00Z",
        "is_loaded": True,
        "is_loading": False,
        "memory_bytes": 486000000,
        "vram_bytes": 0,
        "context_length": 32768,
    }
    assert rows[1]["is_loaded"] is False
    assert rows[1]["is_loading"] is False
    assert rows[1]["context_length"] == 0


def test_the_models_in_memory_come_first_and_a_load_in_flight_is_marked():
    tags = {"models": [{"name": name} for name in ("c:1", "a:1", "b:1", "d:1")]}
    ps = {"models": [{"name": "d:1"}, {"model": "b:1"}]}
    rows = model_rows(tags, ps, loading={"a:1", "b:1"})
    assert [row["name"] for row in rows] == ["b:1", "d:1", "a:1", "c:1"]
    assert [row["is_loading"] for row in rows] == [False, False, True, False]


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
    client.keep("qwen2.5:0.5b")
    assert (
        "POST",
        "/api/generate",
        {"model": "qwen2.5:0.5b", "keep_alive": -1, "stream": False},
    ) in ollama.requests
    assert [model["name"] for model in ollama.loaded] == ["qwen2.5:0.5b"]
    client.delete("qwen2.5:0.5b")
    assert ollama.models == []
    with pytest.raises(KeyError):
        client.delete("qwen2.5:0.5b")
    with pytest.raises(KeyError):
        client.keep("qwen2.5:0.5b")


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


def test_a_cancel_while_the_pull_waits_for_a_chunk_leaves_the_queue_running(
    ollama, monkeypatch, caplog
):
    escaped = []
    monkeypatch.setattr(threading, "excepthook", escaped.append)
    ollama.pull_lines["a:1"] = [PULL[2], PULL[-1]]
    ollama.pull_lines["b:1"] = [PULL[-1]]
    ollama.gate.clear()
    queue = OllamaPullQueue(address_of=lambda device: ollama.address)
    queue.add("cut", "a:1")
    assert _until(lambda: queue.pulls("cut")[0]["total_bytes"] == 1000)
    assert _until(lambda: _waits_for_a_chunk("ollama_pull_cut"))
    assert queue.cancel("cut", "a:1") is True
    for worker in _threads("ollama_pull_cut"):
        worker.join(10)
    assert _threads("ollama_pull_cut") == []
    assert escaped == []
    assert [
        record for record in caplog.records if record.levelno >= logging.ERROR
    ] == []
    assert queue.pulls("cut") == []
    queue.add("cut", "b:1")
    assert _until(lambda: any(model["name"] == "b:1" for model in ollama.models))
    assert _until(lambda: queue.pulls("cut") == [])


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


def test_a_pull_that_lands_reads_the_machine_again(ollama):
    ollama.pull_lines["a:1"] = PULL
    landed: list = []
    queue = OllamaPullQueue(
        address_of=lambda device: ollama.address, on_pulled=landed.append
    )
    queue.add("dev", "a:1")
    queue.add("dev", "nothing:1")
    assert _until(lambda: [pull["state"] for pull in queue.pulls("dev")] == ["failed"])
    assert landed == ["dev"]
