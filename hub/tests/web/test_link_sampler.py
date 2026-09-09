"""The link sampler: the panel is told only when the wires moved.

A carrier, a lease and a radio all change with nobody writing anything, so
this is the only thing that would tell an open panel. What is pinned is that
the first sample is not itself news, that a reading equal to the last one
says nothing, and that any part of it moving does.
"""

from neutrino_hub.modules.router.link_status import LinkStatus
from neutrino_hub.web.constants import WEB_EVENT_LINKS
from neutrino_hub.web.link_sampler import PanelLinkSampler


class StubLinkStatus:
    """The live reader, answering from what the test set."""

    def __init__(self, links, gateway):
        self.links = links
        self.gateway = gateway

    def all_links(self) -> list:
        return list(self.links)

    def default_gateway(self):
        return self.gateway


class RecordingEvents:
    """The bus, remembering what was published on it."""

    def __init__(self):
        self.published: list = []

    def publish(self, event_type: str, key: str = "", data=None) -> None:
        self.published.append((event_type, key, data))


class StubRuntime:
    """Only what the sampler reaches for."""

    def __init__(self, status: StubLinkStatus):
        self.events = RecordingEvents()
        self.status = status

    def link_status(self) -> StubLinkStatus:
        return self.status


def wired(name: str, *, is_up: bool = True, address: str = "192.168.100.1/24"):
    return LinkStatus(name=name, is_present=True, is_up=is_up, ipv4_address=address)


def sampler(links, gateway="192.168.1.1"):
    runtime = StubRuntime(StubLinkStatus(links, gateway))
    return PanelLinkSampler(runtime=runtime), runtime


def test_the_first_sample_is_not_itself_news():
    watcher, runtime = sampler([wired("enp1s0")])

    assert watcher.sample_once() is False
    assert runtime.events.published == []


def test_a_reading_that_did_not_move_says_nothing():
    watcher, runtime = sampler([wired("enp1s0")])
    watcher.sample_once()

    assert watcher.sample_once() is False
    assert runtime.events.published == []


def test_a_cable_pulled_out_says_the_links_moved():
    links = [wired("enp1s0")]
    watcher, runtime = sampler(links)
    watcher.sample_once()

    links[0] = wired("enp1s0", is_up=False)

    assert watcher.sample_once() is True
    assert runtime.events.published == [(WEB_EVENT_LINKS, "", None)]


def test_a_renewed_lease_says_the_links_moved():
    links = [wired("enp2s0", address="10.0.0.5/24")]
    watcher, runtime = sampler(links)
    watcher.sample_once()

    links[0] = wired("enp2s0", address="10.0.0.6/24")
    watcher.sample_once()

    assert runtime.events.published == [(WEB_EVENT_LINKS, "", None)]


def test_a_new_default_gateway_says_the_links_moved():
    watcher, runtime = sampler([wired("enp1s0")])
    watcher.sample_once()

    runtime.status.gateway = "10.0.0.1"
    watcher.sample_once()

    assert runtime.events.published == [(WEB_EVENT_LINKS, "", None)]
