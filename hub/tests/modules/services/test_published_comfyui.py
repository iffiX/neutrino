"""ComfyUI's page is listed while the device reports the module running at its forwarder's port.

What these pin: a ``running`` row naming the forwarder's port gives the
entry while the hub asks the module to run or to stop; a row in any other
state, one naming no port, and a module the hub asks nothing of give none.
"""

import pytest

from neutrino_hub.modules.devices.desired_state import DesiredStateStore
from neutrino_hub.modules.services.published import PublishedServiceCache


@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.setattr("neutrino_hub.utils.json_file.UTILS_CONFIG_DIR", tmp_path)
    monkeypatch.setattr(
        "neutrino_hub.modules.devices.desired_state.UTILS_CONFIG_DIR", tmp_path
    )
    return DesiredStateStore()


def hosted(store, status: dict):
    cache = PublishedServiceCache(
        declared_probe=None,
        served_models=None,
        units=None,
        desired_states=store,
    )
    return cache._hosted("d1", "comfyui", status, {})


def test_a_running_row_naming_its_port_gives_the_entry(store):
    store.set_want("d1", "comfyui", "running")
    status = {"state": "running", "details": {"port": 8188, "is_running": True}}

    assert hosted(store, status) == {"port": 8188, "is_healthy": True}


def test_any_other_row_or_no_want_gives_none(store):
    store.set_want("d1", "comfyui", "running")
    for state in ("installed", "stopped", "installing", "failed", "absent"):
        status = {"state": state, "details": {"port": 8188}}
        assert hosted(store, status) is None, state
    assert hosted(store, {"state": "running", "details": {}}) is None
    store.set_want("d1", "comfyui", "absent")
    assert hosted(store, {"state": "running", "details": {"port": 8188}}) is None
