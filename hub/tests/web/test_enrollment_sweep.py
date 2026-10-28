"""The sweep removes the client rows whose link expired before anybody
joined, and tells the Clients page once when it removed any."""

import pytest

from neutrino_hub.modules.clients.registry import ClientRegistry
from neutrino_hub.web.enrollment_sweep import PanelEnrollmentSweeper


class Events:
    def __init__(self):
        self.published: list = []

    def publish(self, event_type, key="", data=None):
        self.published.append(event_type)


@pytest.fixture
def config(tmp_path, monkeypatch):
    monkeypatch.setattr("neutrino_hub.utils.json_file.UTILS_CONFIG_DIR", tmp_path)
    return tmp_path


def test_a_sweep_removes_the_expired_waiting_rows_and_says_so(config):
    registry = ClientRegistry()
    expired = registry.create("expired", link_expires_at=100.0)
    open_link = registry.create("open", link_expires_at=300.0)
    events = Events()
    sweeper = PanelEnrollmentSweeper(events=events)

    assert sweeper.sweep_once(now=200.0) == [expired]
    assert sweeper.sweep_once(now=200.0) == []

    assert [client.id for client in ClientRegistry().all()] == [open_link]
    assert events.published == ["clients"]
