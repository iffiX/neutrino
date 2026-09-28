"""What the runtime does when an agent's channel opens or ends.

The devices page is told, the published list is recomposed, and every
client is handed its state, whose terminals list each machine's presence,
so a client's dots follow the machines at once rather than at its next
report.
"""

import threading

from neutrino_hub.modules.channel.constants import CHANNEL_ROLE_CLIENT
from neutrino_hub.web import panel_runtime as runtime_module
from neutrino_hub.web.constants import WEB_EVENT_DEVICES
from neutrino_hub.web.panel_runtime import PanelRuntime


class RecordingEvents:
    def __init__(self):
        self.published = []

    def publish(self, event_type, key="", data=None):
        self.published.append(event_type)


class CountingServices:
    def __init__(self):
        self.refreshes = 0

    def schedule_refresh(self) -> None:
        self.refreshes += 1


def test_an_agent_coming_or_going_pushes_every_client_its_state(monkeypatch):
    pushed = []
    done = threading.Event()

    def push_states(runtime, role):
        pushed.append((runtime, role, threading.current_thread().name))
        done.set()

    monkeypatch.setattr(runtime_module.channel_state, "push_states", push_states)
    panel = object.__new__(PanelRuntime)
    panel.events = RecordingEvents()
    panel.published_services = CountingServices()

    panel._publish_devices()

    assert done.wait(timeout=5)
    assert pushed == [(panel, CHANNEL_ROLE_CLIENT, "client_state_push")]
    assert panel.events.published == [WEB_EVENT_DEVICES]
    assert panel.published_services.refreshes == 1
