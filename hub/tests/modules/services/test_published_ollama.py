"""Ollama's entry is listed while its row reads present, whoever installed the server.

What these pin: an ``installed``, ``stopped`` or ``running`` row naming its
port gives the entry, healthy while the server answers, with or without a
``want`` of the hub's, a person's app among them; any other row, or one
naming no port, gives none.
"""

import pytest

from neutrino_hub.modules.devices.desired_state import DesiredStateStore
from neutrino_hub.modules.services.published import PublishedServiceCache


@pytest.fixture
def cache(tmp_path, monkeypatch):
    monkeypatch.setattr("neutrino_hub.utils.json_file.UTILS_CONFIG_DIR", tmp_path)
    return PublishedServiceCache(
        declared_probe=None,
        served_models=None,
        units=None,
        desired_states=DesiredStateStore(),
    )


def test_a_present_row_naming_its_port_gives_the_entry(cache):
    for state in ("installed", "stopped", "running"):
        status = {"state": state, "details": {"port": 11434, "is_running": True}}
        assert cache._hosted("d1", "ollama", status, {}) == {
            "port": 11434,
            "is_healthy": True,
        }
    found = {"state": "installed", "details": {"port": 11434, "found": "app"}}
    assert cache._hosted("d1", "ollama", found, {}) == {
        "port": 11434,
        "is_healthy": False,
    }


def test_any_other_row_gives_none(cache):
    for state in ("absent", "installing", "failed", "install_failed"):
        status = {"state": state, "details": {"port": 11434, "is_running": True}}
        assert cache._hosted("d1", "ollama", status, {}) is None
    assert (
        cache._hosted("d1", "ollama", {"state": "running", "details": {}}, {}) is None
    )
