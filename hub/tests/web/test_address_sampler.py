"""The address sampler: both roles are pushed only when the set moved.

The first sample is not itself news, a set equal to the last says nothing,
and a set that moved pushes the clients and then the agents.
"""

from neutrino_hub.modules.channel.constants import (
    CHANNEL_ROLE_AGENT,
    CHANNEL_ROLE_CLIENT,
)
from neutrino_hub.web import address_sampler as sampler_module
from neutrino_hub.web.address_sampler import PanelAddressSampler


class StubRuntime:
    """Only what the sampler reaches for."""

    def __init__(self):
        self.urls = ["https://192.168.100.1:8443"]


def sampler(monkeypatch) -> tuple:
    runtime = StubRuntime()
    pushed: list = []
    monkeypatch.setattr(sampler_module, "channel_urls", lambda given: list(given.urls))
    monkeypatch.setattr(
        sampler_module.channel_state,
        "push_states",
        lambda given, role: pushed.append(role),
    )
    return PanelAddressSampler(runtime=runtime), runtime, pushed


def test_the_first_sample_is_not_itself_news(monkeypatch):
    watcher, _, pushed = sampler(monkeypatch)

    assert watcher.sample_once() is False
    assert pushed == []


def test_a_set_that_did_not_move_pushes_nothing(monkeypatch):
    watcher, _, pushed = sampler(monkeypatch)
    watcher.sample_once()

    assert watcher.sample_once() is False
    assert pushed == []


def test_a_set_that_moved_pushes_both_roles_once(monkeypatch):
    watcher, runtime, pushed = sampler(monkeypatch)
    watcher.sample_once()

    runtime.urls = ["https://192.168.100.1:8443", "https://100.64.0.1:8443"]

    assert watcher.sample_once() is True
    assert pushed == [CHANNEL_ROLE_CLIENT, CHANNEL_ROLE_AGENT]
    assert watcher.sample_once() is False
    assert pushed == [CHANNEL_ROLE_CLIENT, CHANNEL_ROLE_AGENT]
