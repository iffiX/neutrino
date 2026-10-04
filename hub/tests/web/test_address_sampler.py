"""The address sampler: the runtime converges only when the set moved.

The first sample is not itself news, a set equal to the last says nothing,
and a set that moved runs the converge step once, which hands both roles
their state. A sample whose overlay devices or network resolvers moved has
converged already. Every sample hands the set to the panel's certificate,
which is issued again when its names moved.
"""

from neutrino_hub.web import address_sampler as sampler_module
from neutrino_hub.web.address_sampler import PanelAddressSampler


class StubRuntime:
    """Only what the sampler reaches for."""

    def __init__(self):
        self.urls = ["https://192.168.100.1:8443"]
        self.calls: list = []
        self.is_device_moved = False
        self.is_resolver_moved = False

    def follow_overlay_devices(self) -> bool:
        self.calls.append("follow")
        return self.is_device_moved

    def follow_network_resolvers(self) -> bool:
        self.calls.append("resolvers")
        return self.is_resolver_moved

    def check_overlay_routes(self) -> list:
        self.calls.append("routes")
        return []

    def converge_network_blocking(self, only=None) -> str:
        self.calls.append("converge")
        return "applied"


def sampler(monkeypatch) -> tuple:
    runtime = StubRuntime()
    monkeypatch.setattr(sampler_module, "channel_urls", lambda given: list(given.urls))
    monkeypatch.setattr(
        sampler_module.panel_tls,
        "follow_addresses",
        lambda urls: runtime.calls.append(("certificate", list(urls))),
    )
    return PanelAddressSampler(runtime=runtime), runtime


def test_the_first_sample_is_not_itself_news(monkeypatch):
    watcher, runtime = sampler(monkeypatch)

    assert watcher.sample_once() is False
    assert "converge" not in runtime.calls


def test_a_set_that_did_not_move_converges_nothing(monkeypatch):
    watcher, runtime = sampler(monkeypatch)
    watcher.sample_once()

    assert watcher.sample_once() is False
    assert "converge" not in runtime.calls


def test_a_set_that_moved_converges_once(monkeypatch):
    watcher, runtime = sampler(monkeypatch)
    watcher.sample_once()

    runtime.urls = ["https://192.168.100.1:8443", "https://100.64.0.1:8443"]

    assert watcher.sample_once() is True
    assert runtime.calls.count("converge") == 1
    assert watcher.sample_once() is False
    assert runtime.calls.count("converge") == 1


def test_a_device_that_moved_is_not_converged_on_twice(monkeypatch):
    watcher, runtime = sampler(monkeypatch)
    watcher.sample_once()
    runtime.is_device_moved = True

    runtime.urls = ["https://192.168.100.1:8443", "https://10.126.126.1:8443"]

    assert watcher.sample_once() is True
    assert "converge" not in runtime.calls


def test_each_sample_follows_the_overlay_devices_before_reading(monkeypatch):
    """A console bringing its network up moves the firewall first, so the set
    read after it names the overlay's address."""
    watcher, runtime = sampler(monkeypatch)
    monkeypatch.setattr(
        sampler_module,
        "channel_urls",
        lambda given: given.calls.append("urls") or list(given.urls),
    )

    watcher.sample_once()

    assert runtime.calls == [
        "follow",
        "resolvers",
        "routes",
        "urls",
        ("certificate", runtime.urls),
    ]


def test_a_sample_whose_overlay_devices_moved_reads_no_resolvers(monkeypatch):
    """That converge recorded the resolvers it read already."""
    watcher, runtime = sampler(monkeypatch)
    runtime.is_device_moved = True

    watcher.sample_once()

    assert "resolvers" not in runtime.calls


def test_resolvers_that_moved_are_not_converged_on_twice(monkeypatch):
    """A lease naming new resolvers converges once, in the follow step."""
    watcher, runtime = sampler(monkeypatch)
    watcher.sample_once()
    runtime.is_resolver_moved = True

    runtime.urls = ["https://192.168.100.1:8443", "https://10.126.126.1:8443"]

    assert watcher.sample_once() is True
    assert "converge" not in runtime.calls


def test_every_sample_checks_the_overlays_routes(monkeypatch):
    """A route the console hands EasyTier arrives with no write on this box,
    so it is read every half minute."""
    watcher, runtime = sampler(monkeypatch)

    watcher.sample_once()
    watcher.sample_once()

    assert runtime.calls.count("routes") == 2


def test_every_sample_hands_the_set_to_the_panel_certificate(monkeypatch):
    watcher, runtime = sampler(monkeypatch)

    watcher.sample_once()
    watcher.sample_once()

    assert runtime.calls.count(("certificate", runtime.urls)) == 2
