"""The models a person loaded, loaded again on each machine whose Ollama lost them.

What these pin: a kept model ``/api/ps`` does not list is loaded with
``keep_alive`` -1 when the machine is first followed and at a periodic
check; one in memory and one not kept are left alone; a machine that keeps
no model is not read; a model has at most one load at a time, and the view
names it loading until it ends; a failed load is tried again only after the
retry time or at a press; a load that ends after its name was taken off
unloads the model; a machine dropped, or a new control connection, is not
checked again until it is followed.
"""

import time

import pytest

from neutrino_hub.modules.devices.ollama_kept_models import OllamaKeptModelController
from tests.modules.devices.ollama_server import FakeOllama

DEVICE = "dev-1"


@pytest.fixture
def ollama():
    server = FakeOllama().start()
    server.models = [{"name": "a:1"}, {"name": "b:1"}]
    yield server
    server.stop()


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


def _until(predicate, timeout=10.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.02)
    return False


def _controller(kept, clock=None):
    return OllamaKeptModelController(
        kept_of=lambda device_id: list(kept.get(device_id, [])),
        clock=clock or Clock(),
    )


def _loads(server):
    return [
        body["model"]
        for method, path, body in server.requests
        if path == "/api/generate" and body.get("keep_alive") == -1
    ]


def test_a_kept_model_out_of_memory_is_loaded_at_the_first_follow(ollama):
    kept = {DEVICE: ["a:1"]}
    controller = _controller(kept)
    controller.follow(DEVICE, ollama.address)
    assert controller.settle() == {DEVICE: ["a:1"]}
    assert _until(lambda: [m["name"] for m in ollama.loaded] == ["a:1"])
    assert _loads(ollama) == ["a:1"]
    assert controller.settle() == {}


def test_a_periodic_check_loads_what_a_restart_lost_and_leaves_the_rest(ollama):
    kept = {DEVICE: ["a:1"]}
    controller = _controller(kept)
    ollama.loaded = [{"name": "a:1"}, {"name": "b:1"}]
    controller.follow(DEVICE, ollama.address)
    assert controller.settle() == {DEVICE: []}
    ollama.loaded = []
    assert controller.settle(is_tick=True) == {DEVICE: ["a:1"]}
    assert _until(lambda: [m["name"] for m in ollama.loaded] == ["a:1"])
    assert _loads(ollama) == ["a:1"]


def test_a_machine_that_keeps_no_model_is_not_read(ollama):
    controller = _controller({})
    controller.follow(DEVICE, ollama.address)
    assert controller.settle(is_tick=True) == {}
    assert ollama.requests == []


def test_one_load_at_a_time_and_the_view_names_it_loading(ollama):
    kept = {DEVICE: ["a:1"]}
    controller = _controller(kept)
    ollama.load_gate.clear()
    controller.follow(DEVICE, ollama.address)
    controller.settle()
    assert controller.loading(DEVICE) == {"a:1"}
    assert controller.settle(is_tick=True) == {DEVICE: []}
    controller.load(DEVICE, ollama.address, "a:1")
    ollama.load_gate.set()
    assert _until(lambda: controller.loading(DEVICE) == set())
    assert _loads(ollama) == ["a:1"]


def test_a_failed_load_waits_for_the_retry_time_or_a_press(ollama):
    kept = {DEVICE: ["b:1"]}
    clock = Clock()
    controller = _controller(kept, clock)
    ollama.failing_loads.add("b:1")
    controller.follow(DEVICE, ollama.address)
    controller.settle()
    assert _until(lambda: controller.loading(DEVICE) == set())
    clock.now += 299
    assert controller.settle(is_tick=True) == {DEVICE: []}
    clock.now += 2
    assert controller.settle(is_tick=True) == {DEVICE: ["b:1"]}
    assert _until(lambda: controller.loading(DEVICE) == set())
    controller.load(DEVICE, ollama.address, "b:1")
    assert _until(lambda: _loads(ollama) == ["b:1", "b:1", "b:1"])


def test_a_load_that_ends_after_its_name_was_taken_off_unloads_it(ollama):
    kept = {DEVICE: ["a:1"]}
    controller = _controller(kept)
    ollama.load_gate.clear()
    controller.load(DEVICE, ollama.address, "a:1")
    kept[DEVICE] = []
    ollama.load_gate.set()
    assert _until(lambda: controller.loading(DEVICE) == set())
    assert _until(
        lambda: (
            "POST",
            "/api/generate",
            {"model": "a:1", "keep_alive": 0, "stream": False},
        )
        in ollama.requests
    )
    assert ollama.loaded == []


def test_a_dropped_machine_and_a_new_control_connection_are_not_checked(ollama):
    kept = {DEVICE: ["a:1"], "dev-2": ["a:1"]}
    controller = _controller(kept)
    controller.follow(DEVICE, ollama.address)
    controller.follow("dev-2", ollama.address)
    controller.drop(DEVICE)
    assert set(controller.settle()) == {"dev-2"}
    controller.forget_all()
    assert controller.settle(is_tick=True) == {}
    controller.follow("dev-2", "")
    assert controller.settle(is_tick=True) == {}


def test_the_thread_settles_at_a_follow(ollama):
    kept = {DEVICE: ["a:1"]}
    controller = OllamaKeptModelController(
        kept_of=lambda device_id: list(kept.get(device_id, [])), period_s=3600
    )
    controller.start()
    try:
        controller.follow(DEVICE, ollama.address)
        assert _until(lambda: [m["name"] for m in ollama.loaded] == ["a:1"])
    finally:
        controller.stop()
